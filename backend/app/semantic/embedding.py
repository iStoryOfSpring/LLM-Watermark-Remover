from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from backend.app.semantic.base import SemanticBackendUnavailable
from backend.app.semantic.cache import LRUCache, text_cache_key


class BGEChineseEmbeddingBackend:
    """Local BGE encoder using CLS pooling and L2 normalization."""

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
        self._cache: LRUCache[Any] = LRUCache(cache_size)
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._load_error: str | None = None
        self._load_lock = RLock()
        self._inference_lock = RLock()

    @property
    def name(self) -> str:
        return "bge-small-zh-v1.5"

    def _asset_problem(self) -> str | None:
        if not self.model_path.is_dir():
            return f"embedding model directory not found: {self.model_path}"
        if not (self.model_path / "config.json").is_file():
            return "embedding config.json is missing"
        if not any(
            (self.model_path / filename).is_file()
            for filename in ("model.safetensors", "pytorch_model.bin")
        ):
            return "embedding model weights are missing"
        if not any(
            (self.model_path / filename).is_file()
            for filename in ("tokenizer.json", "vocab.txt")
        ):
            return "embedding tokenizer assets are missing"
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
                from transformers import AutoModel, AutoTokenizer

                tokenizer = AutoTokenizer.from_pretrained(
                    self.model_path,
                    local_files_only=True,
                    trust_remote_code=False,
                )
                model = AutoModel.from_pretrained(
                    self.model_path,
                    local_files_only=True,
                    trust_remote_code=False,
                )
                model.eval()
                model.to(self.device)
            except Exception as exc:
                self._load_error = f"embedding model load failed: {exc}"
                raise SemanticBackendUnavailable(self._load_error) from exc
            self._tokenizer = tokenizer
            self._model = model

    def _encode_missing(self, texts: list[str]) -> dict[str, Any]:
        self._ensure_loaded()
        import torch
        import torch.nn.functional as functional

        assert self._tokenizer is not None
        assert self._model is not None
        result: dict[str, Any] = {}
        with self._inference_lock, torch.inference_mode():
            for start in range(0, len(texts), self.batch_size):
                batch = texts[start : start + self.batch_size]
                encoded = self._tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt",
                )
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                outputs = self._model(**encoded)
                pooled = outputs.last_hidden_state[:, 0]
                normalized = functional.normalize(pooled, p=2, dim=1).detach().cpu()
                for text, vector in zip(batch, normalized, strict=True):
                    key = text_cache_key(text)
                    self._cache.put(key, vector)
                    result[key] = vector
        return result

    def _vectors(self, texts: list[str]) -> list[Any]:
        cached: dict[str, Any] = {}
        missing: list[str] = []
        seen_missing: set[str] = set()
        for text in texts:
            key = text_cache_key(text)
            vector = self._cache.get(key)
            if vector is not None:
                cached[key] = vector
            elif key not in seen_missing:
                seen_missing.add(key)
                missing.append(text)
        if missing:
            cached.update(self._encode_missing(missing))
        return [cached[text_cache_key(text)] for text in texts]

    def score(self, original: str, rewritten: str) -> float:
        return self.score_batch([(original, rewritten)])[0]

    def score_batch(self, pairs: list[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        vectors = self._vectors([text for pair in pairs for text in pair])
        return [
            float((vectors[index] * vectors[index + 1]).sum().item())
            for index in range(0, len(vectors), 2)
        ]
