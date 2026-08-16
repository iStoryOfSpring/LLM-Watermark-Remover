from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.core.models import Candidate, DocumentUnit, ProtectedSpan, SentenceContext
from backend.app.nlp.analyzer import LinguisticAnalyzer, SafeReplacement
from backend.app.protection.engine import ProtectedSpanEngine


@dataclass(frozen=True)
class Sentence:
    sentence_id: str
    start: int
    end: int
    text: str


class SentenceSplitter:
    _BOUNDARY = re.compile(r"(?<=[。！？!?；;])")

    def split(self, text: str) -> list[Sentence]:
        result: list[Sentence] = []
        start = 0
        for match in self._BOUNDARY.finditer(text):
            end = match.end()
            chunk = text[start:end]
            if chunk.strip():
                result.append(Sentence(f"s_{len(result):04d}", start, end, chunk))
            start = end
        if text[start:].strip():
            result.append(Sentence(f"s_{len(result):04d}", start, len(text), text[start:]))
        return result


class CandidateSelector:
    def __init__(
        self,
        analyzer: LinguisticAnalyzer,
        span_engine: ProtectedSpanEngine | None = None,
        splitter: SentenceSplitter | None = None,
    ):
        self.analyzer = analyzer
        self.span_engine = span_engine or ProtectedSpanEngine()
        self.splitter = splitter or SentenceSplitter()

    def select(
        self,
        unit: DocumentUnit,
        user_terms: list[str],
        strength: int,
    ) -> tuple[list[SentenceContext], list[ProtectedSpan]]:
        if not unit.editable:
            return [], [
                ProtectedSpan(
                    start=0,
                    end=len(unit.text),
                    text=unit.text,
                    type="TITLE" if unit.protection_reason == "title_or_heading" else "UNSUPPORTED",
                    reason=unit.protection_reason or "unsupported scope",
                    priority=100,
                    source="document_adapter",
                )
            ] if unit.text else []

        protected = self.span_engine.merge(self.analyzer.analyze_protected(unit.text, user_terms))
        contexts: list[SentenceContext] = []
        safe = sorted(self.analyzer.dictionary.safe_replacements, key=lambda item: len(item.text), reverse=True)
        sentences = self.splitter.split(unit.text)
        # The model needs more than one option to make a useful decision. The
        # final approved patch count is enforced separately in the service;
        # this is only an input budget for the per-sentence proposal.
        candidate_limit = {1: 4, 2: 8, 3: 12}.get(strength, 8)
        for index, sentence in enumerate(sentences):
            sentence_protected = [
                span.model_copy(update={"start": span.start - sentence.start, "end": span.end - sentence.start})
                for span in protected
                if span.start >= sentence.start and span.end <= sentence.end
            ]
            candidate_matches: list[tuple[int, int, SafeReplacement]] = []
            for replacement in safe:
                for match in re.finditer(re.escape(replacement.text), sentence.text):
                    start = match.start()
                    end = match.end()
                    if self.span_engine.intersects(start, end, sentence_protected):
                        continue
                    candidate_matches.append((start, end, replacement))
            candidates: list[Candidate] = []
            # Read in document order and never offer overlapping lexical
            # candidates to the model. This avoids the old dictionary-order
            # behaviour where the first one or two entries starved the rest
            # of a sentence.
            for start, end, replacement in sorted(
                candidate_matches,
                key=lambda item: (item[0], -(item[1] - item[0]), item[2].text),
            ):
                if any(not (end <= item.start or start >= item.end) for item in candidates):
                    continue
                pos = self.analyzer.pos_for(replacement.text)
                candidates.append(
                    Candidate(
                        id=f"{unit.unit_id}_{sentence.sentence_id}_c{len(candidates):03d}",
                        unit_id=unit.unit_id,
                        sentence_id=sentence.sentence_id,
                        text=replacement.text,
                        start=start,
                        end=end,
                        pos=pos if pos != "x" else replacement.pos,
                        allowed_replacements=list(replacement.replacements),
                        reason=replacement.reason,
                    )
                )
                if len(candidates) >= candidate_limit:
                    break
            previous_sentence = contexts[-1].text if contexts else ""
            next_sentence = ""
            if index + 1 < len(sentences):
                next_sentence = sentences[index + 1].text
            contexts.append(
                SentenceContext(
                    sentence_id=f"{unit.unit_id}:{sentence.sentence_id}",
                    unit_id=unit.unit_id,
                    text=sentence.text,
                    start=sentence.start,
                    end=sentence.end,
                    previous_sentence=previous_sentence,
                    next_sentence=next_sentence,
                    protected=sentence_protected,
                    candidates=candidates,
                )
            )
        return contexts, protected
