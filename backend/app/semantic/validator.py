from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Callable, TypeVar

from backend.app.semantic.base import (
    EmbeddingBackend,
    NLIBackend,
    SemanticEvidence,
)


T = TypeVar("T")


class SemanticEquivalenceValidator:
    """Fail-closed BGE plus bidirectional NLI equivalence gate."""

    def __init__(
        self,
        embedding: EmbeddingBackend,
        nli: NLIBackend,
        *,
        embedding_threshold: float = 0.85,
        entailment_threshold: float = 0.70,
        contradiction_ceiling: float = 0.10,
        timeout_seconds: float | None = 180.0,
        require_bidirectional_nli: bool = True,
        fallback_policy: str = "reject",
    ):
        self.embedding = embedding
        self.nli = nli
        self.embedding_threshold = embedding_threshold
        self.entailment_threshold = entailment_threshold
        self.contradiction_ceiling = contradiction_ceiling
        self.timeout_seconds = timeout_seconds
        self.require_bidirectional_nli = require_bidirectional_nli
        self.fallback_policy = fallback_policy

    @property
    def name(self) -> str:
        return f"{self.embedding.name}+{self.nli.name}"

    @property
    def mode(self) -> str:
        if not self.require_bidirectional_nli or self.fallback_policy != "reject":
            return "unavailable"
        if not self.embedding.available() or not self.nli.available():
            return "unavailable"
        return "full-bidirectional-nli"

    def status(self) -> dict[str, object]:
        return {
            "state": "available" if self.mode != "unavailable" else "unavailable",
            "mode": self.mode,
            "backend": self.name,
            "fallback_policy": self.fallback_policy,
            "development_defaults_not_calibrated": True,
        }

    def _run(self, operation: Callable[[], T], label: str) -> T:
        if self.timeout_seconds is None:
            return operation()
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"semantic-{label}")
        future = executor.submit(operation)
        try:
            result = future.result(timeout=self.timeout_seconds)
            executor.shutdown(wait=True)
            return result
        except FutureTimeout as exc:
            future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            raise TimeoutError(f"{label} inference timed out") from exc
        except Exception:
            executor.shutdown(wait=True)
            raise

    def validate(self, original: str, rewritten: str) -> SemanticEvidence:
        backend = self.name
        if not self.require_bidirectional_nli:
            return SemanticEvidence(
                passed=False,
                reason="bidirectional NLI is disabled; rejected by fail-closed policy",
                backend=backend,
            )
        if self.fallback_policy != "reject":
            return SemanticEvidence(
                passed=False,
                reason=(
                    f"unsupported semantic fallback policy {self.fallback_policy!r}; "
                    "rejected by fail-closed policy"
                ),
                backend=backend,
            )
        if not self.embedding.available():
            return SemanticEvidence(
                passed=False,
                reason="embedding backend unavailable; rejected by fail-closed policy",
                backend=backend,
            )
        if not self.nli.available():
            return SemanticEvidence(
                passed=False,
                reason="NLI backend unavailable; rejected by fail-closed policy",
                backend=backend,
            )
        try:
            similarity = self._run(
                lambda: self.embedding.score(original, rewritten),
                "embedding",
            )
        except Exception as exc:
            return SemanticEvidence(
                passed=False,
                reason=f"embedding inference failed; rejected by fail-closed policy: {exc}",
                backend=backend,
            )
        if similarity < self.embedding_threshold:
            return SemanticEvidence(
                embedding_similarity=similarity,
                passed=False,
                reason=(
                    f"embedding similarity {similarity:.3f} < "
                    f"development threshold {self.embedding_threshold:.3f}"
                ),
                backend=backend,
            )

        try:
            forward, reverse = self._run(
                lambda: self.nli.infer_batch(
                    [(original, rewritten), (rewritten, original)]
                ),
                "nli",
            )
        except Exception as exc:
            return SemanticEvidence(
                embedding_similarity=similarity,
                passed=False,
                reason=f"NLI inference failed; rejected by fail-closed policy: {exc}",
                backend=backend,
            )

        passed = (
            forward.entailment >= self.entailment_threshold
            and reverse.entailment >= self.entailment_threshold
            and forward.contradiction <= self.contradiction_ceiling
            and reverse.contradiction <= self.contradiction_ceiling
        )
        if passed:
            reason = (
                f"semantic equivalence passed: embedding={similarity:.3f}, "
                f"entailment={forward.entailment:.3f}/{reverse.entailment:.3f}"
            )
        else:
            reason = (
                "bidirectional NLI rejected candidate: "
                f"entailment={forward.entailment:.3f}/{reverse.entailment:.3f}, "
                f"contradiction={forward.contradiction:.3f}/{reverse.contradiction:.3f}"
            )
        return SemanticEvidence(
            embedding_similarity=similarity,
            forward_entailment=forward.entailment,
            forward_neutral=forward.neutral,
            forward_contradiction=forward.contradiction,
            reverse_entailment=reverse.entailment,
            reverse_neutral=reverse.neutral,
            reverse_contradiction=reverse.contradiction,
            passed=passed,
            reason=reason,
            backend=backend,
        )
