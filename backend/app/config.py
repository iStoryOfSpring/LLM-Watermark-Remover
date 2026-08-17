from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def resource_root() -> Path:
    """Return the read-only root containing bundled application resources."""

    configured_root = os.getenv("LOCAL_REWRITE_RESOURCE_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).resolve()
    return SOURCE_ROOT


def default_data_root() -> Path:
    """Return the writable per-user data root for the current platform."""

    configured_root = os.getenv("LOCAL_REWRITE_DATA_DIR")
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        return Path.home() / "Library" / "Application Support" / "LLM Watermark Remover"
    return resource_root() / "data"


RESOURCE_ROOT = resource_root()
DATA_ROOT = default_data_root()
PROJECT_ROOT = RESOURCE_ROOT  # Backwards-compatible alias used by integrations.
CONFIG_FILE = RESOURCE_ROOT / "config" / "default.json"
DEFAULT_MODEL_PATH = RESOURCE_ROOT / "model" / "Qwen3.5-2B"


def _config_value(key: str, default: Any) -> Any:
    try:
        payload = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return payload.get(key, default)
    except (OSError, json.JSONDecodeError):
        return default


def _path_setting(value: str | os.PathLike[str], root: Path = RESOURCE_ROOT) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, key: str, default: float) -> float:
    return float(os.getenv(name, str(_config_value(key, default))))


def _env_int(name: str, key: str, default: int) -> int:
    return int(os.getenv(name, str(_config_value(key, default))))


@dataclass(frozen=True)
class Settings:
    resource_root: Path = RESOURCE_ROOT
    project_root: Path = RESOURCE_ROOT
    data_root: Path = DATA_ROOT
    model_path: Path = _path_setting(
        os.getenv("LOCAL_REWRITE_MODEL_PATH", str(_config_value("model_path", DEFAULT_MODEL_PATH)))
    )
    semantic_embedding_model_path: Path = _path_setting(
        os.getenv(
            "LOCAL_REWRITE_SEMANTIC_EMBEDDING_MODEL_PATH",
            str(
                _config_value(
                    "semantic_embedding_model_path",
                    RESOURCE_ROOT / "model" / "bge-small-zh-v1.5",
                )
            ),
        )
    )
    semantic_nli_model_path: Path = _path_setting(
        os.getenv(
            "LOCAL_REWRITE_SEMANTIC_NLI_MODEL_PATH",
            str(
                _config_value(
                    "semantic_nli_model_path",
                    RESOURCE_ROOT / "model" / "Erlangshen-RoBERTa-110M-NLI",
                )
            ),
        )
    )
    semantic_device: str = os.getenv(
        "LOCAL_REWRITE_SEMANTIC_DEVICE",
        str(_config_value("semantic_device", "cpu")),
    )
    semantic_batch_size: int = _env_int(
        "LOCAL_REWRITE_SEMANTIC_BATCH_SIZE",
        "semantic_batch_size",
        16,
    )
    semantic_fallback_policy: str = os.getenv(
        "LOCAL_REWRITE_SEMANTIC_FALLBACK_POLICY",
        str(_config_value("semantic_fallback_policy", "reject")),
    )
    job_root: Path = DATA_ROOT / "jobs"
    dictionary_root: Path = DATA_ROOT / "user-dictionaries"
    log_root: Path = DATA_ROOT / "logs"
    host: str = os.getenv("LOCAL_REWRITE_HOST", str(_config_value("host", "127.0.0.1")))
    port: int = int(os.getenv("LOCAL_REWRITE_PORT", str(_config_value("port", 8000))))
    cors_origin: str = os.getenv(
        "LOCAL_REWRITE_CORS_ORIGIN",
        str(_config_value("cors_origin", "http://localhost:5173")),
    )
    load_model_on_startup: bool = _env_bool(
        "LOCAL_REWRITE_LOAD_MODEL_ON_STARTUP",
        bool(_config_value("load_model_on_startup", False)),
    )
    # Development defaults only. Release values must come from calibration data.
    semantic_embedding_threshold: float = _env_float(
        "LOCAL_REWRITE_SEMANTIC_EMBEDDING_THRESHOLD",
        "semantic_embedding_threshold",
        0.85,
    )
    semantic_nli_entailment_threshold: float = _env_float(
        "LOCAL_REWRITE_SEMANTIC_NLI_ENTAILMENT_THRESHOLD",
        "semantic_nli_entailment_threshold",
        0.70,
    )
    semantic_nli_contradiction_ceiling: float = _env_float(
        "LOCAL_REWRITE_SEMANTIC_NLI_CONTRADICTION_CEILING",
        "semantic_nli_contradiction_ceiling",
        0.10,
    )
    semantic_require_bidirectional_nli: bool = _env_bool(
        "LOCAL_REWRITE_SEMANTIC_REQUIRE_BIDIRECTIONAL_NLI",
        bool(_config_value("semantic_require_bidirectional_nli", True)),
    )
    model_timeout_seconds: float = _env_float("LOCAL_REWRITE_MODEL_TIMEOUT", "model_timeout_seconds", 180.0)


settings = Settings()
for _directory in (settings.data_root, settings.job_root, settings.dictionary_root, settings.log_root):
    _directory.mkdir(parents=True, exist_ok=True)
