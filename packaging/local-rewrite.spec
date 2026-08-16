from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


project_root = Path(SPEC).resolve().parents[1]


datas = []
binaries = []
hiddenimports = set(collect_submodules("backend.app"))
hiddenimports.update(
    {
        "tkinter",
        "tkinter.filedialog",
        "transformers.models.qwen3_5",
        "transformers.models.qwen3_5.configuration_qwen3_5",
        "transformers.models.qwen3_5.modeling_qwen3_5",
        "transformers.models.qwen3_5.modular_qwen3_5",
        "transformers.models.qwen3_5.tokenization_qwen3_5",
    }
)

for package_name in ("transformers", "safetensors", "tokenizers", "jieba"):
    datas.extend(collect_data_files(package_name, include_py_files=False))

for package_name in ("numpy", "safetensors", "tokenizers", "lxml"):
    binaries.extend(collect_dynamic_libs(package_name))

datas.extend(
    [
        (str(project_root / "backend" / "app" / "dictionaries" / "default_protected.json"), "backend/app/dictionaries"),
        (str(project_root / "backend" / "app" / "dictionaries" / "sources.md"), "backend/app/dictionaries"),
    ]
)


a = Analysis(
    [str(project_root / "backend" / "app" / "desktop.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(hiddenimports),
    hookspath=[str(project_root / "packaging" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "scipy",
        "pandas",
        "sklearn",
        "pytest",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LLMWatermarkRemoverBackend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LLMWatermarkRemoverBackend",
)
