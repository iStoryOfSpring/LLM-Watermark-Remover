from __future__ import annotations

import json
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from backend.app.config import settings
from backend.app.core.models import AuditReport, DocumentFormat, RewriteResult, RewriteScope, RewriteSettings
from backend.app.nlp.analyzer import load_user_terms
from backend.app.service.rewrite_service import RewriteService
from backend.app.service.job_log import JobLogStore
from backend.app.service.native_save import NativeSaveUnavailable, save_with_native_dialog


class JobState(BaseModel):
    job_id: str
    state: str
    filename: str
    result: RewriteResult | None = None
    error: str | None = None


class TextRewriteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    rewrite_scope: RewriteScope = RewriteScope.LEXICAL
    strength: int = Field(default=2, ge=1, le=3)
    preserve_layout: bool = True
    layout_sensitivity: str = "STRICT"
    protect_terms: list[str] = Field(default_factory=list)
    user_terms: list[str] = Field(default_factory=list)


class ExportRequest(BaseModel):
    accepted_change_ids: list[str] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    accepted_change_ids: list[str] = Field(default_factory=list)


class JobManager:
    def __init__(self, service: RewriteService | None = None):
        self.service = service or RewriteService()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rewrite-job")
        self.jobs: dict[str, JobState] = {}
        self._lock = threading.Lock()
        self.log = JobLogStore(settings.job_root / "jobs.sqlite3")

    def submit_file(self, source_path: Path, filename: str, rewrite_settings: RewriteSettings) -> str:
        job_id = str(uuid.uuid4())
        record = JobState(job_id=job_id, state="queued", filename=filename)
        with self._lock:
            self.jobs[job_id] = record
        self.log.upsert(job_id, filename, "queued")
        self.executor.submit(self._run, job_id, source_path, rewrite_settings)
        return job_id

    def _run(self, job_id: str, source_path: Path, rewrite_settings: RewriteSettings) -> None:
        with self._lock:
            record = self.jobs.get(job_id)
            if record is None:
                return
            self.jobs[job_id] = record.model_copy(update={"state": "running"})
            filename = record.filename
        self.log.upsert(job_id, filename, "running")
        try:
            result = self.service.rewrite_file(
                source_path,
                job_id=job_id,
                rewrite_settings=rewrite_settings,
                job_dir=settings.job_root / job_id,
            )
            state = "completed" if result.success else "failed"
            with self._lock:
                self.jobs[job_id] = self.jobs[job_id].model_copy(
                    update={"state": state, "result": result}
                )
            self.log.upsert(job_id, filename, state, result=result)
        except Exception as exc:
            with self._lock:
                self.jobs[job_id] = self.jobs[job_id].model_copy(
                    update={"state": "failed", "error": str(exc)}
                )
            self.log.upsert(job_id, filename, "failed", error=str(exc))

    def delete(self, job_id: str) -> None:
        with self._lock:
            record = self.jobs.get(job_id)
            if record is not None and record.state in {"queued", "running"}:
                raise RuntimeError("任务仍在处理中，完成后才能删除。")

        row = self.log.get(job_id)
        job_dir = settings.job_root / job_id
        if row is None and not job_dir.exists():
            raise KeyError(job_id)
        root = settings.job_root.resolve()
        resolved_job_dir = job_dir.resolve()
        if resolved_job_dir.parent != root or resolved_job_dir == root:
            raise ValueError("拒绝删除工作目录之外的路径。")
        if resolved_job_dir.exists():
            shutil.rmtree(resolved_job_dir)
        self.log.delete(job_id)
        with self._lock:
            self.jobs.pop(job_id, None)
        self.service.forget_job(job_id)

    def get(self, job_id: str) -> JobState:
        with self._lock:
            record = self.jobs.get(job_id)
        if record is None:
            row = self.log.get(job_id)
            if row is not None:
                audit_path = Path(row["audit_file"]) if row.get("audit_file") else None
                audit = None
                if audit_path and audit_path.exists():
                    audit = AuditReport.model_validate(
                        json.loads(audit_path.read_text(encoding="utf-8"))
                    )
                result = None
                if audit is not None:
                    result = RewriteResult(
                        success=row["state"] == "completed" or bool(row.get("output_file")),
                        job_id=job_id,
                        document_id=audit.document_id,
                        format=DocumentFormat(audit.format),
                        output_file=row.get("output_file"),
                        audit_file=row.get("audit_file"),
                        audit=audit,
                    )
                record = JobState(
                    job_id=job_id,
                    state=row["state"],
                    filename=row["filename"],
                    result=result,
                    error=row.get("error"),
                )
                with self._lock:
                    self.jobs[job_id] = record
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return record

    def sync_audit(self, job_id: str, audit: AuditReport) -> None:
        with self._lock:
            record = self.jobs.get(job_id)
            if record is None or record.result is None:
                return
            result = record.result.model_copy(update={"audit": audit})
            self.jobs[job_id] = record.model_copy(update={"result": result})
            filename = record.filename
        self.log.set_review(job_id, [patch.change_id for patch in audit.changes if patch.accepted])
        self.log.upsert(job_id, filename, record.state, result=result)


service = RewriteService()
job_manager = JobManager(service)
router = APIRouter(prefix="/api")


def _parse_terms(value: str) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except json.JSONDecodeError:
        return [line.strip() for line in value.splitlines() if line.strip()]
    raise HTTPException(status_code=400, detail="user_terms 必须是 JSON 数组或逐行文本。")


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "local-rewrite-desk"}


@router.get("/model/status")
def model_status() -> dict[str, Any]:
    return service.model_status()


@router.get("/licenses/third-party", response_class=PlainTextResponse)
def third_party_licenses() -> str:
    """Expose the bundled attribution notice to the desktop About view."""

    notice_path = settings.resource_root / "LICENSES" / "THIRD_PARTY_NOTICES.md"
    if not notice_path.exists():
        raise HTTPException(status_code=404, detail="第三方许可证清单不存在。")
    return notice_path.read_text(encoding="utf-8")


@router.post("/dictionaries/parse")
async def parse_dictionary(file: UploadFile = File(...)) -> dict[str, Any]:
    filename = Path(file.filename or "dictionary.txt").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".txt", ".csv"}:
        raise HTTPException(status_code=400, detail="词典只支持 .txt 或 .csv。")
    temporary_dir = settings.job_root / "_dictionary_uploads"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = temporary_dir / f"{uuid.uuid4()}{suffix}"
    temporary_path.write_bytes(await file.read())
    try:
        terms = load_user_terms(temporary_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        temporary_path.unlink(missing_ok=True)
    return {"filename": filename, "terms": terms, "count": len(terms)}


@router.post("/rewrite")
async def rewrite_document(
    file: UploadFile = File(...),
    dictionary: UploadFile | None = File(default=None),
    strength: int = Form(default=2),
    rewrite_scope: str = Form(default="lexical"),
    preserve_layout: str = Form(default="true"),
    layout_sensitivity: str = Form(default="STRICT"),
    protect_terms: str = Form(default="[]"),
    user_terms: str = Form(default="[]"),
) -> dict[str, str]:
    if Path(file.filename or "").suffix.lower() not in {".txt", ".docx"}:
        raise HTTPException(status_code=400, detail="只支持 .txt 和 .docx 文件。")
    if strength not in {1, 2, 3}:
        raise HTTPException(status_code=400, detail="strength 必须是 1、2 或 3。")
    try:
        settings_payload = RewriteSettings(
            rewrite_scope=rewrite_scope,
            strength=strength,
            preserve_layout=_parse_bool(preserve_layout),
            layout_sensitivity=layout_sensitivity,
            protect_terms=_parse_terms(protect_terms),
            user_terms=_parse_terms(user_terms),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"改写设置无效: {exc}") from exc
    filename = Path(file.filename or "document.txt").name
    job_id = str(uuid.uuid4())
    job_dir = settings.job_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    source_path = job_dir / filename
    source_path.write_bytes(await file.read())
    if dictionary is not None:
        dictionary_name = Path(dictionary.filename or "dictionary.txt").name
        dictionary_path = job_dir / dictionary_name
        dictionary_path.write_bytes(await dictionary.read())
        try:
            imported_terms = load_user_terms(dictionary_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        settings_payload = settings_payload.model_copy(
            update={"user_terms": [*settings_payload.user_terms, *imported_terms]}
        )
    record = JobState(job_id=job_id, state="queued", filename=filename)
    with job_manager._lock:
        job_manager.jobs[job_id] = record
    job_manager.log.upsert(job_id, filename, "queued")
    job_manager.executor.submit(job_manager._run, job_id, source_path, settings_payload)
    return {"job_id": job_id, "state": "queued"}


@router.post("/rewrite/text")
def rewrite_text(request: TextRewriteRequest) -> dict[str, Any]:
    if len(request.text) > 2000:
        raise HTTPException(status_code=400, detail="直接粘贴文本最多支持 2000 字。")
    try:
        rewrite_settings = RewriteSettings(
            rewrite_scope=request.rewrite_scope,
            strength=request.strength,
            preserve_layout=request.preserve_layout,
            layout_sensitivity=request.layout_sensitivity,
            protect_terms=request.protect_terms,
            user_terms=request.user_terms,
        )
        result = service.rewrite_text(request.text, rewrite_settings)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    rewritten_text = request.text
    if result.output_file and Path(result.output_file).exists():
        rewritten_text = Path(result.output_file).read_text(encoding="utf-8")
    return {
        "success": result.success,
        "job_id": result.job_id,
        "rewritten_text": rewritten_text,
        "result": result.model_dump(mode="json"),
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> JobState:
    return job_manager.get(job_id)


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, Any]:
    try:
        job_manager.delete(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job_id": job_id, "deleted": True}


@router.get("/jobs")
def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    return job_manager.log.list_recent(limit)


@router.get("/jobs/{job_id}/audit")
def get_audit(job_id: str) -> Any:
    record = job_manager.get(job_id)
    if record.result is None:
        raise HTTPException(status_code=409, detail="job 尚未完成。")
    if record.result.audit_file and Path(record.result.audit_file).exists():
        return AuditReport.model_validate(
            json.loads(Path(record.result.audit_file).read_text(encoding="utf-8"))
        )
    return record.result.audit


@router.get("/jobs/{job_id}/preview")
def get_preview(job_id: str) -> dict[str, Any]:
    record = job_manager.get(job_id)
    if record.result is None:
        raise HTTPException(status_code=409, detail="job 尚未完成。")
    snapshot_path = settings.job_root / job_id / "snapshot.json"
    if not snapshot_path.exists():
        raise HTTPException(status_code=404, detail="逻辑文本快照不存在。")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    original = str(snapshot.get("logical_text", ""))
    rewritten = original
    audit = get_audit(job_id)
    accepted_patches = [item for item in audit.changes if item.accepted]
    for patch in sorted(accepted_patches, key=lambda item: item.document_start or 0, reverse=True):
        if patch.document_start is None or patch.document_end is None:
            continue
        if rewritten[patch.document_start:patch.document_end] != patch.original:
            raise HTTPException(status_code=500, detail="预览 patch 校验失败。")
        rewritten = rewritten[:patch.document_start] + patch.replacement + rewritten[patch.document_end:]
    paragraphs: list[dict[str, Any]] = []
    for unit in snapshot.get("units", []):
        unit_id = str(unit["unit_id"])
        unit_text = str(unit.get("text", ""))
        all_unit_patches = sorted(
            [item for item in audit.changes if item.unit_id == unit_id],
            key=lambda item: item.start,
        )
        unit_patches = [item for item in all_unit_patches if item.accepted]
        rewritten_unit = unit_text
        for patch in reversed(unit_patches):
            if rewritten_unit[patch.start:patch.end] != patch.original:
                raise HTTPException(status_code=500, detail="段落预览 patch 校验失败。")
            rewritten_unit = rewritten_unit[:patch.start] + patch.replacement + rewritten_unit[patch.end:]
        paragraphs.append(
            {
                "unit_id": unit_id,
                "text": unit_text,
                "rewritten_text": rewritten_unit,
                "changes": [patch.model_dump(mode="json") for patch in all_unit_patches],
            }
        )
    return {"original_text": original, "rewritten_text": rewritten, "paragraphs": paragraphs}


@router.put("/jobs/{job_id}/review")
def update_review(job_id: str, request: ReviewRequest) -> dict[str, Any]:
    record = job_manager.get(job_id)
    if record.result is None:
        raise HTTPException(status_code=409, detail="job 尚未完成。")
    try:
        audit = service.update_review(job_id, request.accepted_change_ids)
        job_manager.sync_audit(job_id, audit)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"审阅状态保存失败: {exc}") from exc
    return {"job_id": job_id, "audit": audit.model_dump(mode="json")}


@router.post("/jobs/{job_id}/export")
def export_job(job_id: str, request: ExportRequest) -> dict[str, str]:
    record = job_manager.get(job_id)
    if record.result is None:
        raise HTTPException(status_code=409, detail="job 尚未完成。")
    try:
        service.update_review(job_id, request.accepted_change_ids)
        output_path = service.export_selected(job_id, request.accepted_change_ids)
        audit = get_audit(job_id)
        job_manager.sync_audit(job_id, audit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"导出失败，原输出未被覆盖: {exc}") from exc
    return {
        "job_id": job_id,
        "output_file": str(output_path),
        "download_url": f"/api/jobs/{job_id}/download/output",
    }


@router.post("/jobs/{job_id}/export/native")
def export_native(job_id: str, request: ExportRequest) -> dict[str, str | bool]:
    record = job_manager.get(job_id)
    if record.result is None:
        raise HTTPException(status_code=409, detail="job 尚未完成。")
    try:
        service.update_review(job_id, request.accepted_change_ids)
        output_path = service.export_selected(job_id, request.accepted_change_ids)
        audit = get_audit(job_id)
        audit_path = Path(record.result.audit_file or settings.job_root / job_id / "audit.json")
        saved_output, saved_audit = save_with_native_dialog(
            output_path,
            audit_path,
            output_path.name,
        )
        job_manager.sync_audit(job_id, audit)
    except NativeSaveUnavailable as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"原生保存失败，原输出未被覆盖: {exc}") from exc
    return {
        "success": True,
        "job_id": job_id,
        "output_file": str(saved_output),
        "audit_file": str(saved_audit),
    }


@router.get("/jobs/{job_id}/download/output")
def download_output(job_id: str) -> FileResponse:
    record = job_manager.get(job_id)
    if record.result is None or not record.result.output_file:
        raise HTTPException(status_code=409, detail="输出文件尚未生成。")
    path = Path(record.result.output_file)
    if not path.exists():
        raise HTTPException(status_code=404, detail="输出文件不存在。")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.get("/jobs/{job_id}/download/audit")
def download_audit(job_id: str) -> FileResponse:
    record = job_manager.get(job_id)
    if record.result is None or not record.result.audit_file:
        raise HTTPException(status_code=409, detail="审计文件尚未生成。")
    path = Path(record.result.audit_file)
    if not path.exists():
        raise HTTPException(status_code=404, detail="审计文件不存在。")
    return FileResponse(path, filename=path.name, media_type="application/json")
