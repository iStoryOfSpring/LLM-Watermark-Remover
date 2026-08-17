from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class SemanticBackendError(RuntimeError):
    """Base error for local semantic model failures."""


class SemanticBackendUnavailable(SemanticBackendError):
    """Raised when required local model assets cannot be used."""


class SemanticBackendConfigurationError(SemanticBackendError):
    """Raised when model metadata is unsafe or ambiguous."""


class NLIScores(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entailment: float
    neutral: float
    contradiction: float


class SemanticEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    embedding_similarity: float | None = None

    forward_entailment: float | None = None
    forward_neutral: float | None = None
    forward_contradiction: float | None = None

    reverse_entailment: float | None = None
    reverse_neutral: float | None = None
    reverse_contradiction: float | None = None

    passed: bool
    reason: str
    backend: str


class EmbeddingBackend(Protocol):
    @property
    def name(self) -> str:
        ...

    def available(self) -> bool:
        ...

    def score(self, original: str, rewritten: str) -> float:
        ...

    def score_batch(self, pairs: list[tuple[str, str]]) -> list[float]:
        ...

    def status(self) -> dict[str, str]:
        ...


class NLIBackend(Protocol):
    @property
    def name(self) -> str:
        ...

    def available(self) -> bool:
        ...

    def infer(self, premise: str, hypothesis: str) -> NLIScores:
        ...

    def infer_batch(self, pairs: list[tuple[str, str]]) -> list[NLIScores]:
        ...

    def status(self) -> dict[str, str]:
        ...
