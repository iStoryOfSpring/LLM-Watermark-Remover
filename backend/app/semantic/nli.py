from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

from backend.app.semantic.base import (
    NLIScores,
    SemanticBackendConfigurationError,
    SemanticBackendUnavailable,
)
from backend.app.semantic.cache import LRUCache, pair_cache_key


_EXPECTED_LABELS = {"CONTRADICTION", "NEUTRAL", "ENTAILMENT"}


class ErlangshenNLIBackend:
    """Local three-way Chinese NLI classifier with verified label metadata."""

    def __init__(
        self,
        model_path: Path,
        *,
        device: str = "cpu",
        batch_size: int = 16,
        cache_size: int = 4096,
    ):
        self.model_path = Path(model_path)
        self.device = device
        self.batch_size = max(1, batch_size)
        self._cache: LRUCache[NLIScores] = LRUCache(cache_size)
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._label_indices: dict[str, int] | None = None
        self._load_error: str | None = None
        self._load_lock = RLock()
        self._inference_lock = RLock()

    @property
    def name(self) -> str:
        return "Erlangshen-RoBERTa-110M-NLI"

    @staticmethod
    def _resolve_label_indices(id2label: dict[Any, Any]) -> dict[str, int]:
        resolved: dict[str, int] = {}
        for raw_index, raw_label in id2label.items():
            label = str(raw_label).strip().upper()
            if label in _EXPECTED_LABELS:
                resolved[label] = int(raw_index)
        if set(resolved) != _EXPECTED_LABELS or len(set(resolved.values())) != 3:
            raise SemanticBackendConfigurationError(
                "NLI id2label must identify CONTRADICTION, NEUTRAL, and ENTAILMENT"
            )
        return resolved

    def _asset_problem(self) -> str | None:
        if not self.model_path.is_dir():
            return f"NLI model directory not found: {self.model_path}"
        config_path = self.model_path / "config.json"
        if not config_path.is_file():
            return "NLI config.json is missing"
        if not any(
            (self.model_path / filename).is_file()
            for filename in ("model.safetensors", "pytorch_model.bin")
        ):
            return "NLI model weights are missing"
        if not any(
            (self.model_path / filename).is_file()
            for filename in ("tokenizer.json", "vocab.txt")
        ):
            return "NLI tokenizer assets are missing"
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self._resolve_label_indices(payload.get("id2label", {}))
        except (
            OSError,
            json.JSONDecodeError,
            ValueError,
            TypeError,
            SemanticBackendConfigurationError,
        ) as exc:
            return f"NLI label configuration is invalid: {exc}"
        return None

    def available(self) -> bool:
        return self._asset_problem() is None and self._load_error is None

    def status(self) -> dict[str, str]:
        problem = self._load_error or self._asset_problem()
        state = "unavailable" if problem else "ready" if self._model is not None else "available"
        payload = {
            "model": self.name,
            "state": state,
            "device": self.device,
            "model_path": str(self.model_path),
        }
        if problem:
            payload["reason"] = problem
        return payload

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return
        with self._load_lock:
            if self._model is not None and self._tokenizer is not None:
                return
            problem = self._asset_problem()
            if problem:
                self._load_error = problem
                raise SemanticBackendUnavailable(problem)
            try:
                from transformers import AutoModelForSequenceClassification, AutoTokenizer

                tokenizer = AutoTokenizer.from_pretrained(
                    self.model_path,
                    local_files_only=True,
                    trust_remote_code=False,
                )
                model = AutoModelForSequenceClassification.from_pretrained(
                    self.model_path,
                    local_files_only=True,
                    trust_remote_code=False,
                )
                label_indices = self._resolve_label_indices(model.config.id2label)
                model.eval()
                model.to(self.device)
            except Exception as exc:
                self._load_error = f"NLI model load failed: {exc}"
                raise SemanticBackendUnavailable(self._load_error) from exc
            self._tokenizer = tokenizer
            self._model = model
            self._label_indices = label_indices

    def infer(self, premise: str, hypothesis: str) -> NLIScores:
        return self.infer_batch([(premise, hypothesis)])[0]

    def infer_batch(self, pairs: list[tuple[str, str]]) -> list[NLIScores]:
        if not pairs:
            return []
        results: list[NLIScores | None] = [None] * len(pairs)
        missing_indices: list[int] = []
        for index, (premise, hypothesis) in enumerate(pairs):
            cached = self._cache.get(pair_cache_key(premise, hypothesis))
            if cached is None:
                missing_indices.append(index)
            else:
                results[index] = cached

        if missing_indices:
            self._ensure_loaded()
            import torch

            assert self._tokenizer is not None
            assert self._model is not None
            assert self._label_indices is not None
            with self._inference_lock, torch.inference_mode():
                for start in range(0, len(missing_indices), self.batch_size):
                    indices = missing_indices[start : start + self.batch_size]
                    batch_pairs = [pairs[index] for index in indices]
                    encoded = self._tokenizer(
                        [pair[0] for pair in batch_pairs],
                        [pair[1] for pair in batch_pairs],
                        padding=True,
                        truncation=True,
                        max_length=512,
                        return_tensors="pt",
                    )
                    encoded = {key: value.to(self.device) for key, value in encoded.items()}
                    probabilities = torch.softmax(self._model(**encoded).logits, dim=-1).detach().cpu()
                    for index, row in zip(indices, probabilities, strict=True):
                        scores = NLIScores(
                            contradiction=float(row[self._label_indices["CONTRADICTION"]].item()),
                            neutral=float(row[self._label_indices["NEUTRAL"]].item()),
                            entailment=float(row[self._label_indices["ENTAILMENT"]].item()),
                        )
                        premise, hypothesis = pairs[index]
                        self._cache.put(pair_cache_key(premise, hypothesis), scores)
                        results[index] = scores

        if any(result is None for result in results):
            raise SemanticBackendUnavailable("NLI inference returned incomplete results")
        return [result for result in results if result is not None]
