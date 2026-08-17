from __future__ import annotations

import hashlib
from collections import OrderedDict
from threading import RLock
from typing import Generic, TypeVar


T = TypeVar("T")


def text_cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pair_cache_key(premise: str, hypothesis: str) -> str:
    return hashlib.sha256(
        premise.encode("utf-8") + b"\0" + hypothesis.encode("utf-8")
    ).hexdigest()


class LRUCache(Generic[T]):
    """Small thread-safe in-process LRU used for immutable inference results."""

    def __init__(self, max_size: int = 4096):
        if max_size < 1:
            raise ValueError("max_size must be positive")
        self.max_size = max_size
        self._values: OrderedDict[str, T] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> T | None:
        with self._lock:
            value = self._values.get(key)
            if value is not None:
                self._values.move_to_end(key)
            return value

    def put(self, key: str, value: T) -> None:
        with self._lock:
            self._values[key] = value
            self._values.move_to_end(key)
            while len(self._values) > self.max_size:
                self._values.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)
