from __future__ import annotations

import math
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z]+|\d+(?:\.\d+)?")


class SemanticValidator:
    """Sentence-level and paragraph-level semantic gate.

    A local embedding model can be plugged into this class later. Until one is
    bundled, the deterministic character/word n-gram score is still a gate:
    low similarity rejects a patch, never accepts it.
    """

    def __init__(
        self,
        threshold: float = 0.86,
        paragraph_threshold: float = 0.88,
        model_path: Path | None = None,
        tokenizer_path: Path | None = None,
        allow_fallback: bool = True,
    ):
        self.threshold = threshold
        self.paragraph_threshold = paragraph_threshold
        self.encoder: OnnxEmbeddingEncoder | None = None
        self.mode = "deterministic-ngram-fallback"
        if model_path and model_path.exists():
            try:
                self.encoder = OnnxEmbeddingEncoder(model_path, tokenizer_path or model_path.parent)
                self.mode = "onnx-embedding"
            except Exception as exc:
                if not allow_fallback:
                    self.mode = f"unavailable: {exc}"
        elif not allow_fallback:
            self.mode = "unavailable: embedding model not found"

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

    def validate(self, original: str, rewritten: str, paragraph: bool = False) -> tuple[bool, float, str]:
        if self.encoder is not None:
            score = self.encoder.score(original, rewritten)
        elif self.mode.startswith("unavailable"):
            return False, 0.0, self.mode
        else:
            score = self.score(original, rewritten)
        threshold = self.paragraph_threshold if paragraph else self.threshold
        if score < threshold:
            return False, score, f"semantic similarity {score:.3f} < {threshold:.3f}"
        return True, score, f"semantic similarity {score:.3f}"


class OnnxEmbeddingEncoder:
    """Optional local sentence encoder for the packaged semantic gate.

    The model is intentionally discovered only when an ONNX file exists. It
    expects the common input_ids/attention_mask interface and mean-pools the
    first sequence output. Missing optional runtime/model assets never make a
    normal development install fail to start.
    """

    def __init__(self, model_path: Path, tokenizer_path: Path):
        import onnxruntime as ort
        from transformers import AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.input_names = {item.name for item in self.session.get_inputs()}

    def encode(self, text: str):
        import numpy as np

        encoded = self.tokenizer(
            text,
            return_tensors="np",
            truncation=True,
            max_length=512,
            padding=True,
        )
        feeds: dict[str, Any] = {
            key: value.astype(np.int64)
            for key, value in encoded.items()
            if key in self.input_names
        }
        outputs = self.session.run(None, feeds)
        values = outputs[0]
        if values.ndim == 3:
            mask = encoded.get("attention_mask", np.ones(values.shape[:2], dtype=np.float32))
            pooled = (values * mask[..., None]).sum(axis=1) / np.maximum(mask.sum(axis=1, keepdims=True), 1)
            values = pooled
        vector = values[0].astype(np.float64)
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def score(self, original: str, rewritten: str) -> float:
        import numpy as np

        left = self.encode(original)
        right = self.encode(rewritten)
        return float(np.dot(left, right))
