"""Small macOS-focused torch hook for the text-only Qwen runtime."""

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


datas = collect_data_files(
    "torch",
    excludes=["**/*.h", "**/*.hpp", "**/*.cuh", "**/*.lib", "**/*.cpp", "**/*.pyi", "**/*.cmake"],
)
binaries = collect_dynamic_libs("torch")
hiddenimports = [
    "torch._C",
    "torch._VF",
    "torch._utils",
    "torch._utils_internal",
    "torch.amp",
    "torch.backends",
    "torch.backends.mps",
    "torch.cuda",
    "torch.nn",
    "torch.nn.functional",
    "torch.nn.modules",
    "torch.optim",
    "torch.serialization",
    "torch.utils",
    "torch.utils._pytree",
    "torch.utils.data",
    "torch.utils.dlpack",
]
