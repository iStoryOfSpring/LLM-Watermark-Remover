from __future__ import annotations

from backend.app.semantic.base import NLIScores
from backend.app.semantic.validator import SemanticEquivalenceValidator


class FakeEmbeddingBackend:
    name = "fake-embedding"

    def __init__(self, score: float = 0.95, *, is_available: bool = True):
        self.value = score
        self.is_available = is_available
        self.calls: list[list[tuple[str, str]]] = []

    def available(self) -> bool:
        return self.is_available

    def score(self, original: str, rewritten: str) -> float:
        self.calls.append([(original, rewritten)])
        return self.value

    def score_batch(self, pairs: list[tuple[str, str]]) -> list[float]:
        self.calls.append(pairs)
        return [self.value] * len(pairs)

    def status(self) -> dict[str, str]:
        return {
            "model": self.name,
            "state": "available" if self.is_available else "unavailable",
        }


class FakeNLIBackend:
    name = "fake-nli"

    def __init__(
        self,
        scores: list[NLIScores] | None = None,
        *,
        is_available: bool = True,
        error: Exception | None = None,
    ):
        safe = NLIScores(entailment=0.96, neutral=0.03, contradiction=0.01)
        self.scores = scores or [safe, safe]
        self.is_available = is_available
        self.error = error
        self.calls: list[list[tuple[str, str]]] = []

    def available(self) -> bool:
        return self.is_available

    def infer(self, premise: str, hypothesis: str) -> NLIScores:
        return self.infer_batch([(premise, hypothesis)])[0]

    def infer_batch(self, pairs: list[tuple[str, str]]) -> list[NLIScores]:
        self.calls.append(pairs)
        if self.error is not None:
            raise self.error
        return self.scores[: len(pairs)]

    def status(self) -> dict[str, str]:
        return {
            "model": self.name,
            "state": "available" if self.is_available else "unavailable",
        }


def fake_semantic_validator(
    embedding: FakeEmbeddingBackend | None = None,
    nli: FakeNLIBackend | None = None,
) -> SemanticEquivalenceValidator:
    return SemanticEquivalenceValidator(
        embedding or FakeEmbeddingBackend(),
        nli or FakeNLIBackend(),
        timeout_seconds=None,
    )
