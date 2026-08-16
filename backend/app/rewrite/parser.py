from __future__ import annotations

import json

from pydantic import ValidationError

from backend.app.core.models import DecisionEnvelope, SentenceDecisionEnvelope


class ModelJsonError(ValueError):
    pass


def _extract_json_object(text: str) -> str:
    cleaned = text.strip()
    fence = chr(96) * 3
    if cleaned.startswith(fence):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith(fence):
            lines = lines[1:]
        if lines and lines[-1].strip() == fence:
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    if start < 0:
        raise ModelJsonError("模型输出未包含 JSON 对象。")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : index + 1]
    raise ModelJsonError("模型输出 JSON 括号不完整。")


def parse_decision_envelope(text: str) -> DecisionEnvelope:
    try:
        payload = json.loads(_extract_json_object(text))
        return DecisionEnvelope.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, ModelJsonError) as exc:
        raise ModelJsonError(f"模型 JSON 校验失败: {exc}") from exc


def parse_sentence_decision_envelope(text: str) -> SentenceDecisionEnvelope:
    try:
        payload = json.loads(_extract_json_object(text))
        return SentenceDecisionEnvelope.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, ModelJsonError) as exc:
        raise ModelJsonError(f"句子模型 JSON 校验失败: {exc}") from exc
