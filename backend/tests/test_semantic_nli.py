import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from backend.app.semantic.base import SemanticBackendConfigurationError
from backend.app.semantic.nli import ErlangshenNLIBackend


def test_nli_label_mapping_is_read_from_model_config() -> None:
    indices = ErlangshenNLIBackend._resolve_label_indices(
        {"0": "CONTRADICTION", "1": "NEUTRAL", "2": "ENTAILMENT"}
    )

    assert indices == {"CONTRADICTION": 0, "NEUTRAL": 1, "ENTAILMENT": 2}


def test_unknown_nli_labels_fail_closed() -> None:
    with pytest.raises(SemanticBackendConfigurationError):
        ErlangshenNLIBackend._resolve_label_indices(
            {0: "LABEL_0", 1: "LABEL_1", 2: "LABEL_2"}
        )


def test_nli_assets_with_unknown_labels_are_unavailable(tmp_path: Path) -> None:
    model_path = tmp_path / "nli"
    model_path.mkdir()
    (model_path / "config.json").write_text(
        json.dumps({"id2label": {"0": "LABEL_0", "1": "LABEL_1", "2": "LABEL_2"}}),
        encoding="utf-8",
    )
    (model_path / "pytorch_model.bin").write_bytes(b"placeholder")
    (model_path / "vocab.txt").write_text("[PAD]\n", encoding="utf-8")

    backend = ErlangshenNLIBackend(model_path)

    assert backend.available() is False
    assert "id2label" in backend.status()["reason"]


def test_nli_uses_tokenizer_pair_api_and_configured_label_indices(tmp_path: Path) -> None:
    calls: list[tuple[list[str], list[str]]] = []

    class Tokenizer:
        def __call__(self, premises, hypotheses, **kwargs):
            calls.append((premises, hypotheses))
            return {
                "input_ids": torch.ones((len(premises), 3), dtype=torch.long),
                "attention_mask": torch.ones((len(premises), 3), dtype=torch.long),
            }

    class Model:
        def __call__(self, **kwargs):
            return SimpleNamespace(logits=torch.tensor([[0.0, 1.0, 3.0]]))

    backend = ErlangshenNLIBackend(tmp_path)
    backend._tokenizer = Tokenizer()
    backend._model = Model()
    backend._label_indices = {
        "CONTRADICTION": 0,
        "NEUTRAL": 1,
        "ENTAILMENT": 2,
    }

    scores = backend.infer("原文", "改写")

    assert calls == [(["原文"], ["改写"])]
    assert scores.entailment > scores.neutral > scores.contradiction
    assert scores.entailment + scores.neutral + scores.contradiction == pytest.approx(1.0)

    cached = backend.infer("原文", "改写")
    assert cached == scores
    assert calls == [(["原文"], ["改写"])]
