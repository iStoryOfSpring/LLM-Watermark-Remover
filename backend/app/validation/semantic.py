from __future__ import annotations

import math
import re
from collections import Counter
from difflib import SequenceMatcher


_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z]+|\d+(?:\.\d+)?")


class SurfaceSimilarityFallback:
    """Diagnostic-only surface similarity; never represents semantic proof."""

    mode = "surface-similarity-diagnostic-only"

    @staticmethod
    def _vector(text: str) -> Counter[str]:
        tokens = _TOKEN_RE.findall(text)
        features = list(tokens)
        features.extend(
            f"{tokens[index]}{tokens[index + 1]}"
            for index in range(len(tokens) - 1)
        )
        return Counter(features)

    @classmethod
    def score(cls, original: str, rewritten: str) -> float:
        if original == rewritten:
            return 1.0
        left = cls._vector(original)
        right = cls._vector(rewritten)
        if not left or not right:
            return 0.0
        dot = sum(left[key] * right.get(key, 0) for key in left)
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        if not left_norm or not right_norm:
            return 0.0
        cosine = dot / (left_norm * right_norm)
        sequence = SequenceMatcher(None, original, rewritten, autojunk=False).ratio()
        return max(cosine, sequence)
