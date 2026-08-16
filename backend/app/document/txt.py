from __future__ import annotations

import re
import uuid
from pathlib import Path

from backend.app.core.hashing import sha256_bytes
from backend.app.core.models import (
    DocumentFormat,
    DocumentSnapshot,
    DocumentUnit,
    Location,
    Patch,
)
from backend.app.document.base import DocumentAdapter


_LINE_RE = re.compile(r".*?(?:\r\n|\n|\r|$)", re.DOTALL)


class TxtAdapter(DocumentAdapter):
    def load(self, path: Path) -> DocumentSnapshot:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("TXT 必须是 UTF-8 编码；无法安全解码，已按 Fail Closed 拒绝。") from exc

        units: list[DocumentUnit] = []
        paragraph_index = 0
        for match in _LINE_RE.finditer(text):
            raw_line = match.group(0)
            if not raw_line:
                continue
            line = raw_line.rstrip("\r\n")
            if not line and match.start() == len(text):
                continue
            units.append(
                DocumentUnit(
                    unit_id=f"p_{paragraph_index:04d}",
                    text=line,
                    start_offset=match.start(),
                    end_offset=match.start() + len(line),
                    location=Location(
                        part="text",
                        paragraph_index=paragraph_index,
                        xml_node_keys=[],
                    ),
                )
            )
            paragraph_index += 1

        return DocumentSnapshot(
            document_id=str(uuid.uuid4()),
            format=DocumentFormat.TXT,
            source_path=str(path),
            source_hash=sha256_bytes(raw),
            source_size=len(raw),
            logical_text=text,
            units=units,
            metadata={"encoding": "utf-8", "newline_preserved": True},
        )

    def write(self, snapshot: DocumentSnapshot, patches: list[Patch], output_path: Path) -> None:
        text = snapshot.logical_text
        unit_by_id = {unit.unit_id: unit for unit in snapshot.units}
        absolute_patches: list[tuple[int, int, str, str]] = []
        for patch in patches:
            unit = unit_by_id[patch.unit_id]
            absolute_patches.append(
                (
                    unit.start_offset + patch.start,
                    unit.start_offset + patch.end,
                    patch.original,
                    patch.replacement,
                )
            )
        for start, end, original, replacement in sorted(absolute_patches, reverse=True):
            if text[start:end] != original:
                raise ValueError("TXT patch 原文校验失败，拒绝写出。")
            text = text[:start] + replacement + text[end:]
        output_path.write_text(text, encoding="utf-8", newline="")

    def validate_output(self, source_path: Path, output_path: Path, patches: list[Patch]) -> None:
        if not output_path.exists():
            raise ValueError("TXT 输出文件不存在。")
        output = output_path.read_text(encoding="utf-8")
        if "\x00" in output:
            raise ValueError("TXT 输出包含非法 NUL 字符。")

