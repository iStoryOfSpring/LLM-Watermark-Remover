import json
import os
from pathlib import Path

import pytest

from backend.app.config import settings
from backend.app.semantic.embedding import BGEChineseEmbeddingBackend
from backend.app.semantic.nli import ErlangshenNLIBackend
from backend.app.semantic.validator import SemanticEquivalenceValidator


pytestmark = pytest.mark.model


@pytest.mark.skipif(
    os.getenv("LOCAL_REWRITE_RUN_MODEL_TESTS") != "1",
    reason="set LOCAL_REWRITE_RUN_MODEL_TESTS=1 to run local model integration tests",
)
def test_local_models_score_curated_chinese_semantic_pairs() -> None:
    validator = SemanticEquivalenceValidator(
        BGEChineseEmbeddingBackend(settings.semantic_embedding_model_path),
        ErlangshenNLIBackend(settings.semantic_nli_model_path),
        embedding_threshold=settings.semantic_embedding_threshold,
        entailment_threshold=settings.semantic_nli_entailment_threshold,
        contradiction_ceiling=settings.semantic_nli_contradiction_ceiling,
        timeout_seconds=settings.model_timeout_seconds,
    )
    fixture = Path(__file__).parent / "fixtures" / "semantic_pairs_zh.jsonl"
    samples = [
        json.loads(line)
        for line in fixture.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(samples) == 50

    evidence = [
        validator.validate(sample["original"], sample["rewritten"])
        for sample in samples
    ]
    by_id = {
        sample["id"]: result
        for sample, result in zip(samples, evidence, strict=True)
    }
    # PR 1 is an integration gate, not threshold calibration. These are the
    # explicit acceptance cases from the design. Aggregate FAR is calibrated
    # separately before release rather than hidden by changing this test.
    required_rejections = {
        "negation_001",
        "modality_001",
        "quantity_001",
        "number_001",
        "causality_001",
        "causality_002",
        "strength_001",
        "strength_003",
    }
    assert all(not by_id[sample_id].passed for sample_id in required_rejections)
    assert by_id["equivalent_001"].passed is True
    assert by_id["equivalent_002"].passed is True
    assert all(result.embedding_similarity is not None for result in evidence)
