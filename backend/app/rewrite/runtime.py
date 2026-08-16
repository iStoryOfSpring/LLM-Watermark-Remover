from __future__ import annotations

import importlib.util
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from backend.app.config import settings
from backend.app.core.models import DecisionEnvelope, SentenceContext, SentenceDecisionEnvelope
from backend.app.rewrite.parser import (
    ModelJsonError,
    parse_decision_envelope,
    parse_sentence_decision_envelope,
)
from backend.app.rewrite.prompt import PromptBuilder


class ModelUnavailable(RuntimeError):
    pass


class ModelRuntime(ABC):
    @abstractmethod
    def status(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def propose(self, context: SentenceContext) -> DecisionEnvelope:
        raise NotImplementedError

    def propose_sentence(self, context: SentenceContext, layout_sensitivity="STRICT") -> SentenceDecisionEnvelope:
        raise ModelUnavailable("句子改写运行时不可用")


class NullRuntime(ModelRuntime):
    def __init__(self, reason: str):
        self.reason = reason

    def status(self) -> dict[str, Any]:
        return {"state": "unavailable", "backend": "none", "reason": self.reason}

    def propose(self, context: SentenceContext) -> DecisionEnvelope:
        raise ModelUnavailable(self.reason)


class QwenTransformersRuntime(ModelRuntime):
    """Lazy local Transformers runtime for the bundled Qwen3.5-2B weights."""

    def __init__(self, model_path: Path | None = None):
        self.model_path = model_path or settings.model_path
        self.prompt_builder = PromptBuilder()
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._lock = threading.Lock()
        self._load_error: str | None = None

    def status(self) -> dict[str, Any]:
        if not self.model_path.exists():
            return {
                "state": "unavailable",
                "backend": "transformers",
                "reason": f"model path not found: {self.model_path}",
            }
        if importlib.util.find_spec("torch") is None:
            return {
                "state": "unavailable",
                "backend": "transformers",
                "reason": "PyTorch is not installed; install a compatible local runtime before enabling Qwen.",
                "model_path": str(self.model_path),
            }
        if self._load_error:
            return {
                "state": "unavailable",
                "backend": "transformers",
                "reason": self._load_error,
                "model_path": str(self.model_path),
            }
        return {
            "state": "ready" if self._model is not None else "available",
            "backend": "transformers",
            "mode": "non-thinking",
            "model_path": str(self.model_path),
        }

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return
        if not self.model_path.exists():
            raise ModelUnavailable(f"model path not found: {self.model_path}")
        if importlib.util.find_spec("torch") is None:
            raise ModelUnavailable("PyTorch is not installed; model inference is unavailable.")
        with self._lock:
            if self._model is not None and self._tokenizer is not None:
                return
            try:
                # This product only sends text. AutoProcessor would eagerly
                # build Qwen's image/video processors and make torchvision a
                # hard dependency even though no visual input is ever used.
                from transformers import AutoModelForImageTextToText, AutoTokenizer

                self._tokenizer = AutoTokenizer.from_pretrained(
                    self.model_path,
                    local_files_only=True,
                    trust_remote_code=False,
                )
                load_kwargs: dict[str, Any] = {
                    "local_files_only": True,
                    "torch_dtype": "auto",
                    "trust_remote_code": False,
                }
                # device_map="auto" is useful when accelerate is installed,
                # but it must not make the default local CPU path unusable.
                if importlib.util.find_spec("accelerate") is not None:
                    load_kwargs["device_map"] = "auto"
                self._model = AutoModelForImageTextToText.from_pretrained(
                    self.model_path,
                    **load_kwargs,
                )
                if "device_map" not in load_kwargs:
                    import torch

                    if torch.cuda.is_available():
                        device = torch.device("cuda")
                    elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
                        device = torch.device("mps")
                    else:
                        device = torch.device("cpu")
                    self._model.to(device)
                self._model.eval()
            except Exception as exc:
                self._load_error = str(exc)
                raise ModelUnavailable(f"Qwen 本地模型加载失败: {exc}") from exc

    def propose(self, context: SentenceContext) -> DecisionEnvelope:
        return self._generate(self.prompt_builder.build(context), parse_decision_envelope)

    def propose_sentence(self, context: SentenceContext, layout_sensitivity="STRICT") -> SentenceDecisionEnvelope:
        return self._generate(
            self.prompt_builder.build_sentence(context, layout_sensitivity),
            parse_sentence_decision_envelope,
        )

    def _generate(self, messages, parser):
        self._ensure_loaded()
        assert self._tokenizer is not None
        assert self._model is not None
        try:
            encoded = self._tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
                chat_template_kwargs={"enable_thinking": False},
            )
            model_device = next(self._model.parameters()).device
            if hasattr(encoded, "to"):
                encoded = encoded.to(model_device)
            import torch

            with torch.inference_mode():
                output = self._model.generate(
                    **encoded,
                    max_new_tokens=96,
                    do_sample=False,
                    repetition_penalty=1.0,
                )
            input_length = encoded["input_ids"].shape[-1]
            generated = output[0][input_length:]
            decoded = self._tokenizer.decode(
                generated,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )
            return parser(decoded)
        except ModelJsonError:
            raise
        except ModelUnavailable:
            raise
        except Exception as exc:
            raise RuntimeError(f"Qwen 推理或 JSON 解析失败: {exc}") from exc


def build_runtime() -> ModelRuntime:
    if os.getenv("LOCAL_REWRITE_RUNTIME", "transformers").lower() == "openai-compatible":
        from backend.app.rewrite.native_runtime import OpenAICompatibleRuntime

        return OpenAICompatibleRuntime()
    return QwenTransformersRuntime(settings.model_path)
