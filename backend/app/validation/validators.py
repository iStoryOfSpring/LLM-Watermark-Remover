from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from backend.app.core.models import (
    Action,
    Candidate,
    DecisionEnvelope,
    LayoutSensitivity,
    Patch,
    RejectedProposal,
    SentenceDecisionEnvelope,
    SentenceContext,
)
from backend.app.protection.engine import ProtectedSpanEngine
from backend.app.validation.semantic import SemanticValidator


_SENSITIVE_TOKEN_RE = re.compile(
    r"https?://[^\s，。；！？]+|www\.[^\s，。；！？]+|"
    r"\d{2,4}年(?:\d{1,2}月(?:\d{1,2}日)?)?|\d+(?:\.\d+)?\s*%|"
    r"\d+(?:\.\d+)?\s*(?:万|亿|元|万元|亿元|人|件|个|次|年|月|日|吨|公里|km|kg|GB|TB)"
)
_LOGIC_SAFETY_WORDS = {
    "不", "未", "无", "没有", "并非", "尚未", "不得", "不能",
    "必须", "禁止", "可能", "或许", "一定", "应当", "应该",
    "因此", "所以", "由于", "导致", "造成", "但是", "然而", "同时",
    "唯一", "全部", "部分", "主要", "显著", "相关",
}


@dataclass
class ValidationOutcome:
    patches: list[Patch] = field(default_factory=list)
    rejected: list[RejectedProposal] = field(default_factory=list)
    kept: int = 0


@dataclass
class SentenceValidationOutcome:
    patches: list[Patch] = field(default_factory=list)
    rejected: list[RejectedProposal] = field(default_factory=list)
    kept: int = 0


class ProposalValidator:
    def __init__(
        self,
        semantic: SemanticValidator | None = None,
        span_engine: ProtectedSpanEngine | None = None,
    ):
        self.semantic = semantic or SemanticValidator()
        self.span_engine = span_engine or ProtectedSpanEngine()

    @staticmethod
    def _reject(candidate: Candidate, replacement: str | None, reason: str, stage: str) -> RejectedProposal:
        return RejectedProposal(
            candidate_id=candidate.id,
            unit_id=candidate.unit_id,
            original=candidate.text,
            replacement=replacement,
            reason=reason,
            stage=stage,
        )

    @staticmethod
    def _max_delta(sensitivity: LayoutSensitivity) -> int:
        return {
            LayoutSensitivity.STRICT: 2,
            LayoutSensitivity.NORMAL: 4,
            LayoutSensitivity.LOOSE: 8,
        }[sensitivity]

    @staticmethod
    def _max_sentence_percent(sensitivity: LayoutSensitivity) -> int:
        return {
            LayoutSensitivity.STRICT: 10,
            LayoutSensitivity.NORMAL: 20,
            LayoutSensitivity.LOOSE: 30,
        }[sensitivity]

    def validate(
        self,
        context: SentenceContext,
        envelope: DecisionEnvelope,
        layout_sensitivity: LayoutSensitivity = LayoutSensitivity.STRICT,
        preserve_layout: bool = True,
    ) -> ValidationOutcome:
        outcome = ValidationOutcome()
        candidates = {candidate.id: candidate for candidate in context.candidates}
        decisions = {decision.id: decision for decision in envelope.decisions}
        if set(decisions) != set(candidates) or len(decisions) != len(envelope.decisions):
            outcome.kept = len(candidates)
            for candidate in candidates.values():
                outcome.rejected.append(
                    self._reject(candidate, None, "模型决策列表与候选集合不完全一致", "schema_validator")
                )
            return outcome

        for candidate in context.candidates:
            decision = decisions[candidate.id]
            if decision.action == Action.KEEP:
                outcome.kept += 1
                continue
            replacement = decision.replacement
            if replacement is None:
                outcome.rejected.append(
                    self._reject(candidate, None, "REPLACE 缺少 replacement", "schema_validator")
                )
                continue
            if context.text[candidate.start : candidate.end] != candidate.text:
                outcome.rejected.append(
                    self._reject(candidate, replacement, "candidate span 原文不匹配", "span_validator")
                )
                continue
            if replacement not in candidate.allowed_replacements:
                outcome.rejected.append(
                    self._reject(candidate, replacement, "replacement 不在候选允许集合内", "lexical_validator")
                )
                continue
            if not replacement or any(char in replacement for char in "\r\n"):
                outcome.rejected.append(
                    self._reject(candidate, replacement, "replacement 为空或包含换行", "span_validator")
                )
                continue
            if any(char in replacement for char in "。！？!?；;\n"):
                outcome.rejected.append(
                    self._reject(candidate, replacement, "replacement 试图改变句子结构", "structure_validator")
                )
                continue
            if preserve_layout and abs(len(replacement) - len(candidate.text)) > self._max_delta(layout_sensitivity):
                outcome.rejected.append(
                    self._reject(candidate, replacement, "长度变化超过版式敏感阈值", "layout_validator")
                )
                continue
            if self.span_engine.intersects(candidate.start, candidate.end, context.protected):
                outcome.rejected.append(
                    self._reject(candidate, replacement, "candidate 与 protected span 重叠", "protected_span_validator")
                )
                continue
            original_sensitive = _SENSITIVE_TOKEN_RE.findall(context.text)
            rewritten_sentence = (
                context.text[: candidate.start]
                + replacement
                + context.text[candidate.end :]
            )
            rewritten_sensitive = _SENSITIVE_TOKEN_RE.findall(rewritten_sentence)
            if original_sensitive != rewritten_sensitive:
                outcome.rejected.append(
                    self._reject(candidate, replacement, "数字、日期、单位或链接发生变化", "number_entity_validator")
                )
                continue
            protected_texts = [span.text for span in context.protected]
            if any(text not in rewritten_sentence for text in protected_texts):
                outcome.rejected.append(
                    self._reject(candidate, replacement, "受保护词未在改写句中完整保留", "protected_term_validator")
                )
                continue
            ok, score, semantic_reason = self.semantic.validate(context.text, rewritten_sentence)
            if not ok:
                outcome.rejected.append(
                    self._reject(candidate, replacement, semantic_reason, "semantic_validator")
                )
                continue
            outcome.patches.append(
                Patch(
                    change_id=f"change:{candidate.id}",
                    unit_id=candidate.unit_id,
                    sentence_id=candidate.sentence_id,
                    start=context.start + candidate.start,
                    end=context.start + candidate.end,
                    original=candidate.text,
                    replacement=replacement,
                    reason=decision.reason or candidate.reason,
                    similarity=score,
                    validation_trace=[
                        "schema:pass",
                        "span:pass",
                        "protected:pass",
                        "number_entity:pass",
                        "layout:pass",
                        "semantic:pass",
                    ],
                )
            )
        return outcome

    def validate_sentence(
        self,
        context: SentenceContext,
        envelope: SentenceDecisionEnvelope,
        layout_sensitivity: LayoutSensitivity = LayoutSensitivity.STRICT,
    ) -> SentenceValidationOutcome:
        outcome = SentenceValidationOutcome()
        decisions = {decision.id: decision for decision in envelope.decisions}
        if set(decisions) != {context.sentence_id} or len(envelope.decisions) != 1:
            outcome.kept = 1
            outcome.rejected.append(
                RejectedProposal(
                    candidate_id=context.sentence_id,
                    unit_id=context.unit_id,
                    original=context.text,
                    replacement=None,
                    reason="句子模型决策必须只对应当前一句",
                    stage="schema_validator",
                )
            )
            return outcome

        decision = decisions[context.sentence_id]
        if decision.action == Action.KEEP:
            outcome.kept = 1
            return outcome
        replacement = decision.replacement
        if not replacement:
            outcome.rejected.append(
                RejectedProposal(
                    candidate_id=context.sentence_id,
                    unit_id=context.unit_id,
                    original=context.text,
                    replacement=replacement,
                    reason="句子 REPLACE 缺少完整 replacement",
                    stage="schema_validator",
                )
            )
            return outcome
        if any(char in replacement for char in "\r\n"):
            outcome.rejected.append(
                RejectedProposal(
                    candidate_id=context.sentence_id,
                    unit_id=context.unit_id,
                    original=context.text,
                    replacement=replacement,
                    reason="句子 replacement 包含换行",
                    stage="structure_validator",
                )
            )
            return outcome

        sentence_parts = [part for part in re.split(r"(?<=[。！？!?；;])", replacement) if part.strip()]
        if len(sentence_parts) != 1:
            outcome.rejected.append(
                RejectedProposal(
                    candidate_id=context.sentence_id,
                    unit_id=context.unit_id,
                    original=context.text,
                    replacement=replacement,
                    reason="句子模式禁止拆句或合句",
                    stage="structure_validator",
                )
            )
            return outcome

        max_percent = self._max_sentence_percent(layout_sensitivity)
        length_delta = abs(len(replacement) - len(context.text)) / max(len(context.text), 1) * 100
        if length_delta > max_percent:
            outcome.rejected.append(
                RejectedProposal(
                    candidate_id=context.sentence_id,
                    unit_id=context.unit_id,
                    original=context.text,
                    replacement=replacement,
                    reason=f"句子长度变化 {length_delta:.1f}% 超过 {max_percent}% 阈值",
                    stage="layout_validator",
                )
            )
            return outcome

        original_sensitive = _SENSITIVE_TOKEN_RE.findall(context.text)
        rewritten_sensitive = _SENSITIVE_TOKEN_RE.findall(replacement)
        if original_sensitive != rewritten_sensitive:
            outcome.rejected.append(
                RejectedProposal(
                    candidate_id=context.sentence_id,
                    unit_id=context.unit_id,
                    original=context.text,
                    replacement=replacement,
                    reason="数字、日期、单位或链接发生变化",
                    stage="number_entity_validator",
                )
            )
            return outcome

        protected_texts = [span.text for span in context.protected]
        if any(replacement.count(text) != context.text.count(text) for text in protected_texts):
            outcome.rejected.append(
                RejectedProposal(
                    candidate_id=context.sentence_id,
                    unit_id=context.unit_id,
                    original=context.text,
                    replacement=replacement,
                    reason="受保护词未按原样完整保留",
                    stage="protected_span_validator",
                )
            )
            return outcome

        introduced_safety_words = [
            word for word in _LOGIC_SAFETY_WORDS
            if word in replacement and word not in context.text
        ]
        if introduced_safety_words:
            outcome.rejected.append(
                RejectedProposal(
                    candidate_id=context.sentence_id,
                    unit_id=context.unit_id,
                    original=context.text,
                    replacement=replacement,
                    reason=f"引入新的否定、情态或逻辑词：{'、'.join(sorted(introduced_safety_words))}",
                    stage="logic_validator",
                )
            )
            return outcome

        ok, score, semantic_reason = self.semantic.validate(context.text, replacement)
        if not ok:
            outcome.rejected.append(
                RejectedProposal(
                    candidate_id=context.sentence_id,
                    unit_id=context.unit_id,
                    original=context.text,
                    replacement=replacement,
                    reason=semantic_reason,
                    stage="semantic_validator",
                )
            )
            return outcome

        opcodes = SequenceMatcher(None, context.text, replacement, autojunk=False).get_opcodes()
        patches: list[Patch] = []
        for tag, start, end, replacement_start, replacement_end in opcodes:
            if tag == "equal":
                continue
            original = context.text[start:end]
            replacement_part = replacement[replacement_start:replacement_end]
            if self.span_engine.intersects(start, end, context.protected):
                outcome.rejected.append(
                    RejectedProposal(
                        candidate_id=context.sentence_id,
                        unit_id=context.unit_id,
                        original=original,
                        replacement=replacement_part,
                        reason="句子 diff 跨越 protected span",
                        stage="protected_span_validator",
                    )
                )
                return outcome
            patches.append(
                Patch(
                    change_id=f"sentence:{context.sentence_id}:{len(patches):03d}",
                    unit_id=context.unit_id,
                    sentence_id=context.sentence_id,
                    start=context.start + start,
                    end=context.start + end,
                    original=original,
                    replacement=replacement_part,
                    reason=decision.reason or "受约束句子改写",
                    kind="sentence",
                    source_sentence=context.text,
                    similarity=score,
                    validation_trace=[
                        "schema:pass",
                        "structure:pass",
                        "protected:pass",
                        "number_entity:pass",
                        "layout:pass",
                        "semantic:pass",
                    ],
                )
            )
        if not patches:
            outcome.kept = 1
            return outcome
        outcome.patches = patches
        return outcome


def _apply_local_patches(text: str, patches: list[Patch]) -> str:
    result = text
    for patch in sorted(patches, key=lambda item: item.start, reverse=True):
        if result[patch.start : patch.end] != patch.original:
            raise ValueError("paragraph patch 原文校验失败")
        result = result[: patch.start] + patch.replacement + result[patch.end :]
    return result


def validate_paragraph_semantics(
    original: str,
    patches: list[Patch],
    semantic: SemanticValidator,
) -> tuple[bool, float, str]:
    rewritten = _apply_local_patches(original, patches)
    return semantic.validate(original, rewritten, paragraph=True)
