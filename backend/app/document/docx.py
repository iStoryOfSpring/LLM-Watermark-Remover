from __future__ import annotations

import copy
import hashlib
import re
import uuid
import zipfile
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape as xml_escape

from lxml import etree

from backend.app.core.hashing import sha256_bytes
from backend.app.core.models import (
    DocumentFormat,
    DocumentSnapshot,
    DocumentUnit,
    Location,
    Patch,
    TextMappingSegment,
)
from backend.app.document.base import DocumentAdapter


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
_TEXT_TAG_RE = re.compile(
    rb"(?P<open><(?:[A-Za-z_][\w.-]*:)?t\b[^>]*>)(?P<content>.*?)(?P<close></(?:[A-Za-z_][\w.-]*:)?t>)",
    re.DOTALL,
)


def _formatting_fingerprint(run: etree._Element | None) -> str:
    if run is None:
        return "none"
    run_properties = run.find("w:rPr", namespaces=NS)
    if run_properties is None:
        return "plain"
    canonical = etree.tostring(run_properties, method="c14n")
    return hashlib.sha1(canonical).hexdigest()[:12]


def _is_heading(paragraph: etree._Element) -> bool:
    style = paragraph.find("./w:pPr/w:pStyle", namespaces=NS)
    if style is None:
        return False
    value = style.get(f"{{{W_NS}}}val", "").lower()
    return value.startswith("heading") or value.startswith("title") or "标题" in value


def _is_unsupported_paragraph(paragraph: etree._Element) -> str | None:
    if paragraph.xpath(".//w:fldSimple | .//w:instrText", namespaces=NS):
        return "field_or_toc"
    if paragraph.xpath(
        ".//w:object | .//w:txbxContent | .//w:oMath | .//m:oMath",
        namespaces={
            "w": W_NS,
            "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
        },
    ):
        return "object_formula_or_textbox"
    if paragraph.xpath(".//w:commentReference | .//w:footnoteReference | .//w:endnoteReference", namespaces=NS):
        return "reference_or_comment"
    if paragraph.xpath(".//w:hyperlink", namespaces=NS):
        return "hyperlink"
    return None


def _iter_direct_body_paragraphs(root: etree._Element) -> Iterable[etree._Element]:
    body = root.find(".//w:body", namespaces=NS)
    if body is None:
        return []
    return body.findall("./w:p", namespaces=NS)


class DocxAdapter(DocumentAdapter):
    main_part = "word/document.xml"

    def _read_main_part(self, path: Path) -> tuple[bytes, etree._Element]:
        with zipfile.ZipFile(path, "r") as archive:
            try:
                xml_bytes = archive.read(self.main_part)
            except KeyError as exc:
                raise ValueError("DOCX 缺少 word/document.xml，无法安全处理。") from exc
        try:
            root = etree.fromstring(xml_bytes)
        except etree.XMLSyntaxError as exc:
            raise ValueError("DOCX 主文档 XML 无法解析，已按 Fail Closed 拒绝。") from exc
        return xml_bytes, root

    def load(self, path: Path) -> DocumentSnapshot:
        raw = path.read_bytes()
        _, root = self._read_main_part(path)
        paragraphs = list(_iter_direct_body_paragraphs(root))
        units: list[DocumentUnit] = []
        global_offset = 0
        all_text_nodes = root.xpath(".//w:t", namespaces=NS)
        node_key_by_id = {id(node): f"t:{index}" for index, node in enumerate(all_text_nodes)}
        run_key_by_id: dict[int, str] = {}
        run_counter = 0

        for node in all_text_nodes:
            parent_run = node.getparent()
            while parent_run is not None and etree.QName(parent_run).localname != "r":
                parent_run = parent_run.getparent()
            if parent_run is not None and id(parent_run) not in run_key_by_id:
                run_key_by_id[id(parent_run)] = f"r:{run_counter}"
                run_counter += 1

        for index, paragraph in enumerate(paragraphs):
            text_nodes = paragraph.xpath(".//w:t", namespaces=NS)
            paragraph_text = "".join(node.text or "" for node in text_nodes)
            mapping: list[TextMappingSegment] = []
            local_offset = 0
            for node in text_nodes:
                node_text = node.text or ""
                parent_run = node.getparent()
                while parent_run is not None and etree.QName(parent_run).localname != "r":
                    parent_run = parent_run.getparent()
                run_key = run_key_by_id.get(id(parent_run), f"r:unknown:{index}")
                mapping.append(
                    TextMappingSegment(
                        start=local_offset,
                        end=local_offset + len(node_text),
                        node_key=node_key_by_id[id(node)],
                        part=self.main_part,
                        run_key=run_key,
                        formatting_fingerprint=_formatting_fingerprint(parent_run),
                    )
                )
                local_offset += len(node_text)

            unsupported_reason = _is_unsupported_paragraph(paragraph)
            heading = _is_heading(paragraph)
            protection_reason = "title_or_heading" if heading else unsupported_reason
            editable = bool(text_nodes) and not protection_reason
            units.append(
                DocumentUnit(
                    unit_id=f"p_{index:04d}",
                    text=paragraph_text,
                    start_offset=global_offset,
                    end_offset=global_offset + len(paragraph_text),
                    location=Location(
                        part=self.main_part,
                        paragraph_index=index,
                        xml_node_keys=[segment.node_key for segment in mapping],
                        protected_reason=protection_reason,
                    ),
                    text_mapping=mapping,
                    editable=editable,
                    protection_reason=protection_reason,
                )
            )
            global_offset += len(paragraph_text) + 1

        return DocumentSnapshot(
            document_id=str(uuid.uuid4()),
            format=DocumentFormat.DOCX,
            source_path=str(path),
            source_hash=sha256_bytes(raw),
            source_size=len(raw),
            logical_text="\n".join(unit.text for unit in units),
            units=units,
            metadata={
                "main_part": self.main_part,
                "all_text_node_count": len(all_text_nodes),
                "editable_scope": "body_direct_paragraphs_only",
                "protected_region_count": len(root.xpath(".//w:tbl//w:p", namespaces=NS)),
            },
        )

    def _patch_main_xml(self, original_xml: bytes, snapshot: DocumentSnapshot, patches: list[Patch]) -> bytes:
        unit_by_id = {unit.unit_id: unit for unit in snapshot.units}
        node_updates: dict[str, list[tuple[int, int, str, str]]] = {}
        for patch in patches:
            unit = unit_by_id.get(patch.unit_id)
            if unit is None or not unit.editable:
                raise ValueError("DOCX patch 目标段落受保护或不存在。")
            matching = [
                segment
                for segment in unit.text_mapping
                if segment.start <= patch.start and patch.end <= segment.end
            ]
            if len(matching) != 1:
                raise ValueError("DOCX span 跨格式或跨文本节点，按 Fail Closed 拒绝。")
            segment = matching[0]
            node_updates.setdefault(segment.node_key, []).append(
                (
                    patch.start - segment.start,
                    patch.end - segment.start,
                    patch.original,
                    patch.replacement,
                )
            )

        for node_key in sorted(node_updates, key=lambda value: int(value.split(":", 1)[1]), reverse=True):
            node_index = int(node_key.split(":", 1)[1])
            matches = list(_TEXT_TAG_RE.finditer(original_xml))
            if node_index >= len(matches):
                raise ValueError("DOCX text node mapping 越界。")
            match = matches[node_index]
            raw_content = match.group("content")
            try:
                decoded_content = etree.fromstring(b"<root>" + raw_content + b"</root>").text or ""
            except etree.XMLSyntaxError as exc:
                raise ValueError("DOCX text node 内容无法解析。") from exc
            new_content = decoded_content
            for start, end, original, replacement in sorted(node_updates[node_key], reverse=True):
                if new_content[start:end] != original:
                    raise ValueError("DOCX patch 原文校验失败。")
                if original[:1].isspace() != replacement[:1].isspace() or original[-1:].isspace() != replacement[-1:].isspace():
                    raise ValueError("DOCX patch 会改变空白边界，拒绝以保护 xml:space。")
                new_content = new_content[:start] + replacement + new_content[end:]
            encoded = xml_escape(new_content, entities={"\"": "&quot;", "'": "&apos;"}).encode("utf-8")
            replacement_bytes = match.group("open") + encoded + match.group("close")
            original_xml = original_xml[: match.start()] + replacement_bytes + original_xml[match.end() :]
        return original_xml

    def write(self, snapshot: DocumentSnapshot, patches: list[Patch], output_path: Path) -> None:
        source_path = Path(snapshot.source_path)
        with zipfile.ZipFile(source_path, "r") as source_zip:
            entries = [(info, source_zip.read(info.filename)) for info in source_zip.infolist()]
        main_xml = next((data for info, data in entries if info.filename == self.main_part), None)
        if main_xml is None:
            raise ValueError("DOCX 缺少主文档 part。")
        patched_xml = self._patch_main_xml(main_xml, snapshot, patches)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w") as output_zip:
            for info, data in entries:
                new_info = copy.copy(info)
                if info.filename == self.main_part:
                    data = patched_xml
                output_zip.writestr(new_info, data)

    def validate_output(self, source_path: Path, output_path: Path, patches: list[Patch]) -> None:
        if not output_path.exists():
            raise ValueError("DOCX 输出文件不存在。")
        with zipfile.ZipFile(source_path, "r") as original_zip, zipfile.ZipFile(output_path, "r") as output_zip:
            original_names = original_zip.namelist()
            if original_names != output_zip.namelist():
                raise ValueError("DOCX package part 列表发生变化。")
            for name in original_names:
                if name != self.main_part and original_zip.read(name) != output_zip.read(name):
                    raise ValueError(f"DOCX 非允许 part 被修改: {name}")
            try:
                original_root = etree.fromstring(original_zip.read(self.main_part))
                output_root = etree.fromstring(output_zip.read(self.main_part))
            except etree.XMLSyntaxError as exc:
                raise ValueError("DOCX 输出 XML 无法解析。") from exc
            if _structure_signature(original_root) != _structure_signature(output_root):
                raise ValueError("DOCX 除允许文本节点外结构发生变化。")


def _structure_signature(root: etree._Element) -> bytes:
    cloned = copy.deepcopy(root)
    for node in cloned.xpath(".//w:t", namespaces=NS):
        node.text = "__TEXT__"
    return etree.tostring(cloned, method="c14n")
