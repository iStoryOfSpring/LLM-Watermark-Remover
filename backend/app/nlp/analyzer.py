from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

from backend.app.core.models import ProtectedSpan, SpanType


@dataclass(frozen=True)
class SafeReplacement:
    text: str
    pos: str
    replacements: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class DictionaryBundle:
    protected_terms: tuple[str, ...]
    risk_terms: dict[SpanType, tuple[str, ...]]
    safe_replacements: tuple[SafeReplacement, ...]
    sources: tuple[dict[str, str], ...]


def load_dictionary(path: Path | None = None) -> DictionaryBundle:
    source_path = path or Path(__file__).resolve().parents[1] / "dictionaries" / "default_protected.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    risk_terms = {
        SpanType[key]: tuple(values)
        for key, values in payload.get("risk_terms", {}).items()
        if key in SpanType.__members__
    }
    safe = tuple(
        SafeReplacement(
            text=item["text"],
            pos=item.get("pos", "x"),
            replacements=tuple(item.get("replacements", [])),
            reason=item.get("reason", "safe lexical substitution"),
        )
        for item in payload.get("safe_replacements", [])
    )
    return DictionaryBundle(
        protected_terms=tuple(payload.get("protected_terms", [])),
        risk_terms=risk_terms,
        safe_replacements=safe,
        sources=tuple(payload.get("sources", [])),
    )


def load_user_terms(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    if suffix == ".csv":
        terms: list[str] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.reader(handle):
                if not row:
                    continue
                value = row[0].strip()
                if value and not value.startswith("#"):
                    terms.append(value)
        return terms
    raise ValueError("用户词典只支持 .txt 或 .csv。")


class LinguisticAnalyzer:
    """A conservative analyzer replaceable by an ONNX NER implementation."""

    _URL = re.compile(r"https?://[^\s，。；！？]+|www\.[^\s，。；！？]+", re.IGNORECASE)
    _EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
    _DATE = re.compile(
        r"(?<!\w)(?:\d{2,4}年(?:\d{1,2}月(?:\d{1,2}日)?)?|\d{1,2}月\d{1,2}日|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})(?!\w)"
    )
    _PERCENTAGE = re.compile(r"(?<!\w)\d+(?:\.\d+)?\s*%(?!\w)")
    _NUMBER_UNIT = re.compile(
        r"(?<!\w)(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?\s*(?:万|亿|千|百|元|万元|亿元|人|件|个|次|年|月|日|吨|公里|km|kg|GB|TB)(?!\w)",
        re.IGNORECASE,
    )
    _NUMBER = re.compile(r"(?<!\w)\d+(?:\.\d+)?(?!\w)")
    _CODE = re.compile(r"\x60[^\x60]+\x60|(?<!\w)(?:[A-Za-z_][A-Za-z0-9_.-]*\([^)]*\))(?!\w)")
    _ORG = re.compile(r"[\u4e00-\u9fff]{2,16}(?:大学|学院|公司|集团|研究院|研究所|银行|医院|委员会|中心|实验室)")
    # Keep the lightweight NER conservative. A bare ``路`` suffix creates
    # false positives such as ``家长通常做路线`` and ``需要路线``; those
    # false positives used to lock ordinary prose before candidate selection.
    # Specific roads remain protectable through the built-in or user terms.
    _LOCATION = re.compile(
        r"[\u4e00-\u9fff]{2,8}(?:省|市|区|县|乡|镇|街道|村)(?![\u4e00-\u9fff])"
    )
    _LATIN_PROPER = re.compile(r"(?<!\w)(?:[A-Z][A-Za-z0-9.+-]{1,}|[A-Za-z]+(?:\s+[A-Za-z]+){1,3})(?!\w)")

    def __init__(self, dictionary: DictionaryBundle | None = None):
        self.dictionary = dictionary or load_dictionary()
        self.ner_available = True

    def _find_terms(
        self,
        text: str,
        terms: tuple[str, ...],
        span_type: SpanType,
        reason: str,
        priority: int,
        source: str,
    ) -> list[ProtectedSpan]:
        spans: list[ProtectedSpan] = []
        for term in sorted((term for term in terms if term), key=len, reverse=True):
            start = 0
            while True:
                index = text.find(term, start)
                if index < 0:
                    break
                spans.append(
                    ProtectedSpan(
                        start=index,
                        end=index + len(term),
                        text=term,
                        type=span_type,
                        reason=reason,
                        priority=priority,
                        source=source,
                    )
                )
                start = index + len(term)
        return spans

    def analyze_protected(self, text: str, user_terms: list[str] | None = None) -> list[ProtectedSpan]:
        spans: list[ProtectedSpan] = []
        user_terms = tuple(user_terms or [])
        spans.extend(self._find_terms(text, user_terms, SpanType.USER_TERM, "用户自定义词典", 100, "user"))
        spans.extend(
            self._find_terms(
                text,
                self.dictionary.protected_terms,
                SpanType.BUILTIN_TERM,
                "内置保护词典",
                80,
                "builtin",
            )
        )
        for span_type, terms in self.dictionary.risk_terms.items():
            spans.extend(self._find_terms(text, terms, span_type, "风险词保护", 75, "risk_lexicon"))

        regexes: list[tuple[re.Pattern[str], SpanType, str, int]] = [
            (self._URL, SpanType.URL, "URL", 90),
            (self._EMAIL, SpanType.EMAIL, "email", 90),
            (self._DATE, SpanType.DATE, "date", 90),
            (self._PERCENTAGE, SpanType.PERCENTAGE, "percentage", 90),
            (self._NUMBER_UNIT, SpanType.NUMBER_UNIT, "number_unit", 90),
            (self._CODE, SpanType.CODE, "code", 90),
            (self._NUMBER, SpanType.NUMBER, "number", 90),
        ]
        for pattern, span_type, reason, priority in regexes:
            spans.extend(
                ProtectedSpan(
                    start=match.start(),
                    end=match.end(),
                    text=match.group(0),
                    type=span_type,
                    reason=reason,
                    priority=priority,
                    source="regex",
                )
                for match in pattern.finditer(text)
            )

        if not self.ner_available:
            raise RuntimeError("NER analyzer unavailable")
        for pattern, reason in (
            (self._ORG, "organization heuristic"),
            (self._LOCATION, "location heuristic"),
            (self._LATIN_PROPER, "latin named-entity heuristic"),
        ):
            spans.extend(
                ProtectedSpan(
                    start=match.start(),
                    end=match.end(),
                    text=match.group(0),
                    type=SpanType.NAMED_ENTITY,
                    reason=reason,
                    priority=70,
                    source="lightweight_ner",
                )
                for match in pattern.finditer(text)
            )
        return spans

    def pos_for(self, word: str) -> str:
        try:
            import jieba.posseg as pseg

            words = list(pseg.cut(word))
            return words[0].flag if words else "x"
        except Exception:
            return "x"
