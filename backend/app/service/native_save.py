from __future__ import annotations

import shutil
from pathlib import Path


class NativeSaveUnavailable(RuntimeError):
    """Raised when the local process cannot open a system save dialog."""


def save_with_native_dialog(
    source_path: Path,
    audit_path: Path,
    suggested_name: str,
) -> tuple[Path, Path]:
    """Save the current output and audit beside each other using the OS picker.

    The browser cannot reliably discover the parent directory of a selected
    file. The local FastAPI process can, so this is the preferred path for the
    desktop workflow. Import tkinter lazily so headless/API-only installs do
    not need a GUI toolkit at import time.
    """

    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # pragma: no cover - platform dependent
        raise NativeSaveUnavailable(f"系统保存对话框不可用: {exc}") from exc

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        target_name = filedialog.asksaveasfilename(
            title="保存受约束改写结果",
            initialfile=suggested_name,
            defaultextension=source_path.suffix,
            filetypes=[
                ("改写文档", f"*{source_path.suffix}"),
                ("所有文件", "*.*"),
            ],
        )
    except Exception as exc:  # pragma: no cover - platform dependent
        raise NativeSaveUnavailable(f"系统保存对话框调用失败: {exc}") from exc
    finally:
        if root is not None:
            root.destroy()

    if not target_name:
        raise NativeSaveUnavailable("用户取消保存。")

    output_target = Path(target_name).expanduser().resolve()
    output_target.parent.mkdir(parents=True, exist_ok=True)
    audit_target = output_target.with_name(f"{output_target.stem}_rewrite_audit.json")
    temporary_output = output_target.with_suffix(output_target.suffix + ".tmp")
    temporary_audit = audit_target.with_suffix(audit_target.suffix + ".tmp")
    try:
        shutil.copy2(source_path, temporary_output)
        shutil.copy2(audit_path, temporary_audit)
        temporary_output.replace(output_target)
        temporary_audit.replace(audit_target)
    except Exception:
        temporary_output.unlink(missing_ok=True)
        temporary_audit.unlink(missing_ok=True)
        raise
    return output_target, audit_target
