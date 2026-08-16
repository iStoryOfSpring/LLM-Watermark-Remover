"""Keep only Transformers metadata and the Qwen family needed by the app."""

from PyInstaller.utils.hooks import copy_metadata


datas = copy_metadata("transformers")
hiddenimports = [
    "transformers.dependency_versions_check",
    "transformers.dependency_versions_table",
    "transformers.generation",
    "transformers.generation.utils",
    "transformers.modeling_layers",
    "transformers.models.auto",
    "transformers.models.auto.configuration_auto",
    "transformers.models.auto.modeling_auto",
    "transformers.models.auto.tokenization_auto",
    "transformers.models.qwen3_5",
    "transformers.models.qwen3_5.configuration_qwen3_5",
    "transformers.models.qwen3_5.modeling_qwen3_5",
    "transformers.models.qwen3_5.modular_qwen3_5",
    "transformers.models.qwen3_5.tokenization_qwen3_5",
    "transformers.processing_utils",
    "transformers.tokenization_utils_base",
]
