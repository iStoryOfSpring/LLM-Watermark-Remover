from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any

from backend.app.config import settings
from backend.app.core.models import (
    AuditReport,
    DocumentFormat,
    DocumentSnapshot,
    Patch,
    RejectedProposal,
    RewriteScope,
    RewriteResult,
    RewriteSettings,
)
from backend.app.document.base import DocumentAdapter
from backend.app.document.docx import DocxAdapter
from backend.app.document.txt import TxtAdapter
from backend.app.nlp.analyzer import LinguisticAnalyzer
from backend.app.protection.engine import ProtectedSpanEngine
from backend.app.rewrite.candidates import CandidateSelector
from backend.app.rewrite.parser import ModelJsonError
from backend.app.rewrite.runtime import ModelRuntime, ModelUnavailable, build_runtime
from backend.app.semantic.embedding import BGEChineseEmbeddingBackend
from backend.app.semantic.nli import ErlangshenNLIBackend
from backend.app.semantic.validator import SemanticEquivalenceValidator
from backend.app.validation.validators import ProposalValidator, validate_paragraph_semantics


def adapter_for_path(path: Path) -> DocumentAdapter:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return TxtAdapter()
    if suffix == ".docx":
        return DocxAdapter()
    raise ValueError("只支持 .txt 和 .docx 文件。")


class RewriteService:
    def __init__(
        self,
        runtime: ModelRuntime | None = None,
        semantic: SemanticEquivalenceValidator | None = None,
    ):
        self.analyzer = LinguisticAnalyzer()
        self.span_engine = ProtectedSpanEngine()
        self.selector = CandidateSelector(self.analyzer, self.span_engine)
        self.semantic = semantic or SemanticEquivalenceValidator(
            BGEChineseEmbeddingBackend(
                settings.semantic_embedding_model_path,
                device=settings.semantic_device,
                batch_size=settings.semantic_batch_size,
            ),
            ErlangshenNLIBackend(
                settings.semantic_nli_model_path,
                device=settings.semantic_device,
                batch_size=settings.semantic_batch_size,
            ),
            embedding_threshold=settings.semantic_embedding_threshold,
            entailment_threshold=settings.semantic_nli_entailment_threshold,
            contradiction_ceiling=settings.semantic_nli_contradiction_ceiling,
            timeout_seconds=settings.model_timeout_seconds,
            require_bidirectional_nli=settings.semantic_require_bidirectional_nli,
            fallback_policy=settings.semantic_fallback_policy,
        )
        self.validator = ProposalValidator(self.semantic, self.span_engine)
        self.runtime = runtime or build_runtime()
        self._job_dirs: dict[str, Path] = {}

    def model_status(self) -> dict[str, Any]:
        runtime_status = self.runtime.status()
        return {
            **runtime_status,
            "rewrite": runtime_status,
            "embedding": self.semantic.embedding.status(),
            "nli": self.semantic.nli.status(),
            "semantic_validator": self.semantic.mode,
            "semantic_fallback_policy": self.semantic.fallback_policy,
            "semantic_thresholds": {
                "embedding": settings.semantic_embedding_threshold,
                "entailment": settings.semantic_nli_entailment_threshold,
                "contradiction_ceiling": settings.semantic_nli_contradiction_ceiling,
                "notice": "DEVELOPMENT DEFAULT - NOT CALIBRATED",
            },
            "source_scope": "body_direct_paragraphs_only_for_docx",
            "rewrite_granularity": "lexical_default_sentence_opt_in",
            "failure_policy": "fail_closed",
        }

    def _call_runtime(
        self,
        context,
        timeout_seconds: float,
        *,
        sentence: bool = False,
        layout_sensitivity: str = "STRICT",
    ):
        for attempt in range(2):
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rewrite-model")
            if sentence:
                future = executor.submit(
                    self.runtime.propose_sentence,
                    context,
                    layout_sensitivity,
                )
            else:
                future = executor.submit(self.runtime.propose, context)
            try:
                result = future.result(timeout=timeout_seconds)
                executor.shutdown(wait=True)
                return result
            except FutureTimeout as exc:
                future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                raise TimeoutError("模型推理超时，候选全部 KEEP。") from exc
            except ModelJsonError:
                executor.shutdown(wait=True)
                if attempt == 0:
                    continue
                raise
            except Exception:
                executor.shutdown(wait=True)
                raise
        raise ModelJsonError("模型 JSON 解析重试失败")

    def _plan(
        self,
        snapshot: DocumentSnapshot,
        job_id: str,
        rewrite_settings: RewriteSettings,
    ) -> tuple[list[Patch], list[RejectedProposal], int, int, list[str]]:
        patches: list[Patch] = []
        rejected: list[RejectedProposal] = []
        protected_count = int(snapshot.metadata.get("protected_region_count", 0))
        kept = 0
        warnings: list[str] = []
        user_terms = rewrite_settings.all_user_terms

        sentence_cap = {1: 1, 2: 1, 3: 2}[rewrite_settings.strength]
        lexical_cap = {1: 1, 2: 2, 3: 3}[rewrite_settings.strength]
        for unit in snapshot.units:
            try:
                contexts, protected = self.selector.select(
                    unit,
                    user_terms=user_terms,
                    strength=rewrite_settings.strength,
                )
            except Exception as exc:
                warnings.append(f"{unit.unit_id}: NLP 分析失败，整段 KEEP: {exc}")
                rejected.append(
                    RejectedProposal(
                        candidate_id=f"{unit.unit_id}:analysis",
                        unit_id=unit.unit_id,
                        original=unit.text,
                        replacement=None,
                        reason="NER/分析失败，按 Fail Closed 保留原文",
                        stage="analyzer",
                    )
                )
                continue
            protected_count += len(protected)
            sentence_proposals = 0
            for context in contexts:
                sentence_patch_added = False
                if (
                    rewrite_settings.rewrite_scope == RewriteScope.LEXICAL_AND_SENTENCE
                    and sentence_proposals < sentence_cap
                ):
                    try:
                        sentence_envelope = self._call_runtime(
                            context,
                            settings.model_timeout_seconds,
                            sentence=True,
                            layout_sensitivity=rewrite_settings.layout_sensitivity.value,
                        )
                        sentence_outcome = self.validator.validate_sentence(
                            context,
                            sentence_envelope,
                            layout_sensitivity=rewrite_settings.layout_sensitivity,
                        )
                        rejected.extend(sentence_outcome.rejected)
                        if sentence_outcome.patches:
                            patches.extend(sentence_outcome.patches)
                            sentence_proposals += 1
                            sentence_patch_added = True
                        elif not context.candidates:
                            kept += sentence_outcome.kept
                    except (ModelUnavailable, TimeoutError) as exc:
                        warnings.append(f"{context.sentence_id}: 句子模型不可用或超时，按 Fail Closed 保留原文: {exc}")
                    except Exception as exc:
                        rejected.append(
                            RejectedProposal(
                                candidate_id=context.sentence_id,
                                unit_id=context.unit_id,
                                original=context.text,
                                replacement=None,
                                reason=f"句子模型响应失败，按 Fail Closed 保留原文: {exc}",
                                stage="model_runtime",
                            )
                        )

                if sentence_patch_added or not context.candidates:
                    continue
                try:
                    envelope = self._call_runtime(context, settings.model_timeout_seconds)
                except (ModelUnavailable, TimeoutError) as exc:
                    kept += len(context.candidates)
                    warnings.append(f"{context.sentence_id}: 模型不可用或超时，候选 KEEP: {exc}")
                    continue
                except Exception as exc:
                    kept += len(context.candidates)
                    rejected.extend(
                        RejectedProposal(
                            candidate_id=candidate.id,
                            unit_id=candidate.unit_id,
                            original=candidate.text,
                            replacement=None,
                            reason=f"模型响应失败，按 Fail Closed 保留原文: {exc}",
                            stage="model_runtime",
                        )
                        for candidate in context.candidates
                    )
                    continue
                outcome = self.validator.validate(
                    context,
                    envelope,
                    layout_sensitivity=rewrite_settings.layout_sensitivity,
                    preserve_layout=rewrite_settings.preserve_layout,
                )
                approved = sorted(outcome.patches, key=lambda item: (item.start, item.end))
                patches.extend(approved[:lexical_cap])
                for extra in approved[lexical_cap:]:
                    rejected.append(
                        RejectedProposal(
                            candidate_id=extra.change_id,
                            unit_id=extra.unit_id,
                            original=extra.original,
                            replacement=extra.replacement,
                            reason=f"超过当前强度的每句词语替换额度（{lexical_cap}）",
                            stage="strength_validator",
                        )
                    )
                rejected.extend(outcome.rejected)
                kept += outcome.kept

        # Never allow overlapping patches to reach a writer.
        by_unit: dict[str, list[Patch]] = defaultdict(list)
        for patch in patches:
            by_unit[patch.unit_id].append(patch)
        non_overlapping: list[Patch] = []
        for unit_id, unit_patches in by_unit.items():
            last_end = -1
            for patch in sorted(unit_patches, key=lambda item: (item.start, item.end)):
                if patch.start < last_end:
                    rejected.append(
                        RejectedProposal(
                            candidate_id=patch.change_id,
                            unit_id=unit_id,
                            original=patch.original,
                            replacement=patch.replacement,
                            reason="patch 与另一个 patch 重叠",
                            stage="patch_validator",
                        )
                    )
                    continue
                non_overlapping.append(patch)
                last_end = patch.end
        patches = non_overlapping

        # A paragraph-level semantic check can reject the entire paragraph plan.
        unit_by_id = {unit.unit_id: unit for unit in snapshot.units}
        paragraph_safe: list[Patch] = []
        patches_by_unit: dict[str, list[Patch]] = defaultdict(list)
        for patch in patches:
            patches_by_unit[patch.unit_id].append(patch)
        for unit_id, unit_patches in patches_by_unit.items():
            current = sorted(unit_patches, key=lambda item: item.start)
            if not current:
                continue
            unit = unit_by_id[unit_id]
            try:
                paragraph_evidence = validate_paragraph_semantics(
                    unit.text, current, self.semantic
                )
            except Exception as exc:
                paragraph_evidence = None
                reason = f"paragraph patch 校验失败: {exc}"
            else:
                reason = paragraph_evidence.reason
            if paragraph_evidence is None or not paragraph_evidence.passed:
                warnings.append(f"{unit_id}: 段落级语义校验失败，整段 patch 丢弃。{reason}")
                rejected.extend(
                    RejectedProposal(
                        candidate_id=patch.change_id,
                        unit_id=unit_id,
                        original=patch.original,
                        replacement=patch.replacement,
                        reason=reason,
                        stage="paragraph_semantic_validator",
                    )
                    for patch in current
                )
                continue
            paragraph_safe.extend(
                patch.model_copy(
                    update={
                        "similarity": min(
                            paragraph_evidence.embedding_similarity or 0.0,
                            patch.similarity
                            if patch.similarity is not None
                            else paragraph_evidence.embedding_similarity or 0.0,
                        ),
                        "validation_trace": [*patch.validation_trace, "paragraph_semantic:pass"],
                    }
                )
                for patch in current
            )
        patches = paragraph_safe
        unit_by_id = {unit.unit_id: unit for unit in snapshot.units}
        patches = [
            patch.model_copy(
                update={
                    "document_start": unit_by_id[patch.unit_id].start_offset + patch.start,
                    "document_end": unit_by_id[patch.unit_id].start_offset + patch.end,
                }
            )
            for patch in patches
        ]
        return patches, rejected, kept, protected_count, warnings

    def _write_audit(self, path: Path, audit: AuditReport) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(audit.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def rewrite_file(
        self,
        source_path: Path,
        job_id: str | None = None,
        rewrite_settings: RewriteSettings | None = None,
        job_dir: Path | None = None,
    ) -> RewriteResult:
        job_id = job_id or str(uuid.uuid4())
        rewrite_settings = rewrite_settings or RewriteSettings()
        job_dir = job_dir or settings.job_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        self._job_dirs[job_id] = job_dir
        adapter = adapter_for_path(source_path)
        snapshot = adapter.load(source_path)
        snapshot_path = job_dir / "snapshot.json"
        snapshot_path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        patches_path = job_dir / "patches.json"
        output_path = job_dir / f"{source_path.stem}_rewritten{source_path.suffix.lower()}"
        audit_path = job_dir / f"{source_path.stem}_rewrite_audit.json"
        patches, rejected, kept, protected_count, warnings = self._plan(
            snapshot, job_id, rewrite_settings
        )
        patches_path.write_text(
            json.dumps(
                {
                    "rewrite_settings": rewrite_settings.model_dump(mode="json"),
                    "patches": [patch.model_dump(mode="json") for patch in patches],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        model_status = self.runtime.status()
        if model_status.get("state") != "ready":
            warnings.append(
                "当前模型未处于 ready 状态；所有未得到可信模型提案的候选均已 KEEP。"
            )
        audit = AuditReport(
            job_id=job_id,
            document_id=snapshot.document_id,
            format=snapshot.format,
            status="planning",
            original_sha256=snapshot.source_hash,
            changed=len(patches),
            kept=kept,
            rejected=len(rejected),
            protected=protected_count,
            model_status=str(model_status.get("state", "unknown")),
            warnings=warnings,
            changes=patches,
            rejected_proposals=rejected,
        )
        try:
            temporary_output = output_path.with_suffix(output_path.suffix + ".tmp")
            temporary_output.unlink(missing_ok=True)
            adapter.write(snapshot, patches, temporary_output)
            adapter.validate_output(source_path, temporary_output, patches)
            os.replace(temporary_output, output_path)
            audit.status = "completed"
        except Exception as exc:
            temporary_output = output_path.with_suffix(output_path.suffix + ".tmp")
            temporary_output.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            audit.status = "failed"
            audit.warnings.append(f"输出未生成：{exc}")
        self._write_audit(audit_path, audit)
        return RewriteResult(
            success=audit.status == "completed",
            job_id=job_id,
            document_id=snapshot.document_id,
            format=snapshot.format,
            output_file=str(output_path) if output_path.exists() else None,
            audit_file=str(audit_path),
            audit=audit,
        )

    def rewrite_text(
        self,
        text: str,
        rewrite_settings: RewriteSettings | None = None,
        job_id: str | None = None,
    ) -> RewriteResult:
        job_id = job_id or str(uuid.uuid4())
        job_dir = settings.job_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "input.txt"
        source_path.write_text(text, encoding="utf-8", newline="")
        return self.rewrite_file(
            source_path,
            job_id=job_id,
            rewrite_settings=rewrite_settings,
            job_dir=job_dir,
        )

    def export_selected(self, job_id: str, accepted_change_ids: list[str]) -> Path:
        job_dir = self._job_dirs.get(job_id, settings.job_root / job_id)
        snapshot = DocumentSnapshot.model_validate(
            json.loads((job_dir / "snapshot.json").read_text(encoding="utf-8"))
        )
        patch_payload = json.loads((job_dir / "patches.json").read_text(encoding="utf-8"))
        audit_path = next(job_dir.glob("*_rewrite_audit.json"), None)
        if audit_path is None:
            raise ValueError("审计文件不存在，无法安全导出。")
        audit = AuditReport.model_validate(
            json.loads(audit_path.read_text(encoding="utf-8"))
        )
        valid_ids = {patch.change_id for patch in audit.changes}
        unknown_ids = set(accepted_change_ids) - valid_ids
        if unknown_ids:
            raise ValueError(f"导出选择包含未知 change_id: {sorted(unknown_ids)}")
        patches = [
            Patch.model_validate(item)
            for item in patch_payload.get("patches", [])
            if item["change_id"] in set(accepted_change_ids)
        ]
        adapter = adapter_for_path(Path(snapshot.source_path))
        output_path = job_dir / f"{Path(snapshot.source_path).stem}_rewritten{Path(snapshot.source_path).suffix.lower()}"
        temporary_output = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary_output.unlink(missing_ok=True)
        adapter.write(snapshot, patches, temporary_output)
        adapter.validate_output(Path(snapshot.source_path), temporary_output, patches)
        os.replace(temporary_output, output_path)
        accepted = set(accepted_change_ids)
        audit.changes = [
            patch.model_copy(update={"accepted": patch.change_id in accepted})
            for patch in audit.changes
        ]
        audit.status = "exported"
        export_note = f"用户导出选择：{len(accepted)} / {len(audit.changes)} 条提案。"
        if export_note not in audit.warnings:
            audit.warnings.append(export_note)
        self._write_audit(audit_path, audit)
        return output_path

    def update_review(self, job_id: str, accepted_change_ids: list[str]) -> AuditReport:
        job_dir = self._job_dirs.get(job_id, settings.job_root / job_id)
        audit_path = next(job_dir.glob("*_rewrite_audit.json"), None)
        if audit_path is None:
            raise ValueError("审计文件不存在。")
        audit = AuditReport.model_validate(
            json.loads(audit_path.read_text(encoding="utf-8"))
        )
        valid_ids = {patch.change_id for patch in audit.changes}
        unknown_ids = set(accepted_change_ids) - valid_ids
        if unknown_ids:
            raise ValueError(f"审阅选择包含未知 change_id: {sorted(unknown_ids)}")
        accepted = set(accepted_change_ids)
        audit.changes = [
            patch.model_copy(update={"accepted": patch.change_id in accepted})
            for patch in audit.changes
        ]
        audit.status = "reviewed"
        self._write_audit(audit_path, audit)
        return audit

    def forget_job(self, job_id: str) -> None:
        """Drop the in-memory job directory hint after local deletion."""
        self._job_dirs.pop(job_id, None)
