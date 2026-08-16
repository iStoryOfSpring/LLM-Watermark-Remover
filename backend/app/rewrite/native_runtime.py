from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from backend.app.core.models import DecisionEnvelope, SentenceContext, SentenceDecisionEnvelope
from backend.app.rewrite.parser import parse_decision_envelope, parse_sentence_decision_envelope
from backend.app.rewrite.prompt import PromptBuilder
from backend.app.rewrite.runtime import ModelRuntime, ModelUnavailable


class OpenAICompatibleRuntime(ModelRuntime):
    """Adapter for a local llama.cpp/vLLM/SGLang-style server.

    The endpoint must be local and is intentionally not enabled by default.
    It keeps the same prompt and non-thinking contract as the Transformers
    runtime so the rest of the pipeline remains unchanged.
    """

    def __init__(self, base_url: str | None = None, model_name: str | None = None):
        self.base_url = (base_url or os.getenv("LOCAL_REWRITE_NATIVE_URL", "")).rstrip("/")
        self.model_name = model_name or os.getenv("LOCAL_REWRITE_NATIVE_MODEL", "Qwen3.5-2B")
        self.timeout = float(os.getenv("LOCAL_REWRITE_NATIVE_TIMEOUT", "45"))
        self.prompt_builder = PromptBuilder()

    def status(self) -> dict[str, Any]:
        if not self.base_url:
            return {
                "state": "unavailable",
                "backend": "openai-compatible",
                "reason": "LOCAL_REWRITE_NATIVE_URL is not configured",
                "mode": "non-thinking",
            }
        return {
            "state": "available",
            "backend": "openai-compatible",
            "endpoint": self.base_url,
            "model": self.model_name,
            "mode": "non-thinking",
        }

    def propose(self, context: SentenceContext) -> DecisionEnvelope:
        return self._request(self.prompt_builder.build(context), parse_decision_envelope)

    def propose_sentence(self, context: SentenceContext, layout_sensitivity="STRICT") -> SentenceDecisionEnvelope:
        return self._request(
            self.prompt_builder.build_sentence(context, layout_sensitivity),
            parse_sentence_decision_envelope,
        )

    def _request(self, messages, parser):
        if not self.base_url:
            raise ModelUnavailable("native runtime endpoint is not configured")
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.0,
            "top_p": 1.0,
            "max_tokens": 128,
            "extra_body": {
                "top_k": 20,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        }
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ModelUnavailable(f"native runtime request failed: {exc}") from exc
        try:
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            return parser(str(content))
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelUnavailable("native runtime response missing choices[0].message.content") from exc
