from __future__ import annotations

from backend.app.core.models import ProtectedSpan


class ProtectedSpanEngine:
    """Merge overlapping protection findings with user terms winning all ties."""

    def merge(self, spans: list[ProtectedSpan]) -> list[ProtectedSpan]:
        selected: list[ProtectedSpan] = []
        ordered = sorted(
            (span for span in spans if span.end > span.start),
            key=lambda span: (-span.priority, -(span.end - span.start), span.start, span.end),
        )
        for span in ordered:
            overlaps = any(not (span.end <= current.start or span.start >= current.end) for current in selected)
            if not overlaps:
                selected.append(span)
        return sorted(selected, key=lambda span: (span.start, span.end))

    @staticmethod
    def intersects(start: int, end: int, spans: list[ProtectedSpan]) -> bool:
        return any(not (end <= span.start or start >= span.end) for span in spans)

    @staticmethod
    def protected_count(spans: list[ProtectedSpan]) -> int:
        return len(spans)

