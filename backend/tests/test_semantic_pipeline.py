import time

from backend.app.core.models import SentenceContext, SentenceDecisionEnvelope
from backend.app.semantic.base import NLIScores
from backend.app.semantic.validator import SemanticEquivalenceValidator
from backend.app.validation.validators import ProposalValidator
from backend.tests.fakes import FakeEmbeddingBackend, FakeNLIBackend


SAFE = NLIScores(entailment=0.96, neutral=0.03, contradiction=0.01)
UNSAFE = NLIScores(entailment=0.20, neutral=0.75, contradiction=0.05)
CONTRADICTORY = NLIScores(entailment=0.03, neutral=0.02, contradiction=0.95)


def _validator(embedding, nli) -> SemanticEquivalenceValidator:
    return SemanticEquivalenceValidator(embedding, nli, timeout_seconds=None)


def test_full_semantic_evidence_passes_only_when_both_directions_pass() -> None:
    embedding = FakeEmbeddingBackend(0.93)
    nli = FakeNLIBackend([SAFE, SAFE])

    evidence = _validator(embedding, nli).validate("能够完成", "可以完成")

    assert evidence.passed is True
    assert evidence.embedding_similarity == 0.93
    assert evidence.forward_entailment == SAFE.entailment
    assert evidence.reverse_entailment == SAFE.entailment
    assert nli.calls == [[("能够完成", "可以完成"), ("可以完成", "能够完成")]]


def test_low_embedding_score_rejects_before_nli() -> None:
    nli = FakeNLIBackend([SAFE, SAFE])

    evidence = _validator(FakeEmbeddingBackend(0.84), nli).validate(
        "部分用户同意", "全部用户同意"
    )

    assert evidence.passed is False
    assert "embedding similarity" in evidence.reason
    assert nli.calls == []


def test_reverse_entailment_failure_rejects_candidate() -> None:
    evidence = _validator(
        FakeEmbeddingBackend(0.97),
        FakeNLIBackend([SAFE, UNSAFE]),
    ).validate("该方法可能有效", "该方法有效")

    assert evidence.passed is False
    assert evidence.forward_entailment == SAFE.entailment
    assert evidence.reverse_entailment == UNSAFE.entailment


def test_contradiction_ceiling_rejects_candidate() -> None:
    evidence = _validator(
        FakeEmbeddingBackend(0.97),
        FakeNLIBackend([CONTRADICTORY, SAFE]),
    ).validate("结果没有提高", "结果提高了")

    assert evidence.passed is False
    assert evidence.forward_contradiction == CONTRADICTORY.contradiction


def test_missing_embedding_or_nli_backend_fails_closed() -> None:
    missing_embedding = _validator(
        FakeEmbeddingBackend(is_available=False), FakeNLIBackend()
    ).validate("甲", "乙")
    missing_nli = _validator(
        FakeEmbeddingBackend(), FakeNLIBackend(is_available=False)
    ).validate("甲", "乙")

    assert missing_embedding.passed is False
    assert "embedding backend unavailable" in missing_embedding.reason
    assert missing_nli.passed is False
    assert "NLI backend unavailable" in missing_nli.reason


def test_disabled_bidirectional_nli_or_unknown_fallback_policy_fails_closed() -> None:
    disabled = SemanticEquivalenceValidator(
        FakeEmbeddingBackend(),
        FakeNLIBackend(),
        timeout_seconds=None,
        require_bidirectional_nli=False,
    ).validate("甲", "乙")
    fallback = SemanticEquivalenceValidator(
        FakeEmbeddingBackend(),
        FakeNLIBackend(),
        timeout_seconds=None,
        fallback_policy="surface",
    ).validate("甲", "乙")

    assert disabled.passed is False
    assert "bidirectional NLI is disabled" in disabled.reason
    assert fallback.passed is False
    assert "unsupported semantic fallback policy" in fallback.reason


def test_nli_error_and_timeout_fail_closed_without_surface_fallback() -> None:
    for error in (RuntimeError("broken"), TimeoutError("slow")):
        evidence = _validator(
            FakeEmbeddingBackend(), FakeNLIBackend(error=error)
        ).validate("甲", "乙")
        assert evidence.passed is False
        assert "NLI inference failed" in evidence.reason
        assert evidence.backend == "fake-embedding+fake-nli"


def test_validator_enforces_inference_timeout() -> None:
    class SlowEmbedding(FakeEmbeddingBackend):
        def score(self, original: str, rewritten: str) -> float:
            time.sleep(0.05)
            return 0.99

    validator = SemanticEquivalenceValidator(
        SlowEmbedding(), FakeNLIBackend(), timeout_seconds=0.001
    )

    evidence = validator.validate("甲", "乙")

    assert evidence.passed is False
    assert "timed out" in evidence.reason


def test_deterministic_number_validation_runs_before_semantic_models() -> None:
    embedding = FakeEmbeddingBackend()
    validator = ProposalValidator(
        _validator(embedding, FakeNLIBackend())
    )
    context = SentenceContext(
        sentence_id="s1",
        unit_id="p1",
        text="共有100人参加实验。",
        start=0,
        end=10,
    )
    envelope = SentenceDecisionEnvelope(
        schema_version="1.1",
        task="sentence_rewrite",
        decisions=[
            {
                "id": "s1",
                "action": "replace",
                "replacement": "共有200人参加实验。",
            }
        ],
    )

    outcome = validator.validate_sentence(context, envelope)

    assert outcome.patches == []
    assert outcome.rejected[0].stage == "number_entity_validator"
    assert embedding.calls == []
