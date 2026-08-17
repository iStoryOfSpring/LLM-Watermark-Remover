from pathlib import Path

import pytest
import torch

from backend.app.semantic.cache import LRUCache, pair_cache_key, text_cache_key
from backend.app.semantic.embedding import BGEChineseEmbeddingBackend


def test_embedding_score_uses_dot_product_of_normalized_vectors(tmp_path: Path) -> None:
    backend = BGEChineseEmbeddingBackend(tmp_path)
    backend._vectors = lambda texts: [  # type: ignore[method-assign]
        torch.tensor([1.0, 0.0]),
        torch.tensor([0.8, 0.6]),
    ]

    assert backend.score("原文", "改写") == pytest.approx(0.8)


def test_embedding_backend_missing_assets_is_unavailable(tmp_path: Path) -> None:
    backend = BGEChineseEmbeddingBackend(tmp_path / "missing")

    assert backend.available() is False
    assert backend.status()["state"] == "unavailable"


def test_semantic_cache_keys_are_directional_and_lru_evicts() -> None:
    assert text_cache_key("甲") == text_cache_key("甲")
    assert pair_cache_key("甲", "乙") != pair_cache_key("乙", "甲")

    cache: LRUCache[int] = LRUCache(max_size=2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    cache.put("c", 3)

    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3
