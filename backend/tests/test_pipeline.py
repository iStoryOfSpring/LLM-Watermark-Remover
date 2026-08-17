from pathlib import Path

from backend.app.core.models import (
    DecisionEnvelope,
    RewriteScope,
    RewriteSettings,
    SentenceContext,
    SentenceDecisionEnvelope,
)
from backend.app.rewrite.parser import ModelJsonError
from backend.app.rewrite.runtime import ModelRuntime
from backend.app.service.rewrite_service import RewriteService
from backend.tests.fakes import fake_semantic_validator


class ReplaceRuntime(ModelRuntime):
    def status(self):
        return {"state": "ready", "backend": "test"}

    def propose(self, context: SentenceContext):
        return DecisionEnvelope(
            schema_version="1.0",
            decisions=[
                {
                    "id": candidate.id,
                    "action": "replace",
                    "replacement": candidate.allowed_replacements[0],
                    "reason": "test replacement",
                }
                for candidate in context.candidates
            ],
        )


class InvalidRuntime(ModelRuntime):
    def status(self):
        return {"state": "ready", "backend": "test"}

    def propose(self, context: SentenceContext):
        return DecisionEnvelope(schema_version="1.0", decisions=[])


class RetryRuntime(ReplaceRuntime):
    def __init__(self):
        self.calls = 0

    def propose(self, context: SentenceContext):
        self.calls += 1
        if self.calls == 1:
            raise ModelJsonError("invalid JSON")
        return super().propose(context)


class SentenceRuntime(ReplaceRuntime):
    def propose_sentence(self, context: SentenceContext, layout_sensitivity="STRICT"):
        return SentenceDecisionEnvelope(
            schema_version="1.1",
            task="sentence_rewrite",
            decisions=[
                {
                    "id": context.sentence_id,
                    "action": "replace",
                    "replacement": "该方案可以有效提高数据处理效率。",
                    "reason": "受约束句子测试",
                }
            ],
        )


class UnsafeSentenceRuntime(ReplaceRuntime):
    def propose_sentence(self, context: SentenceContext, layout_sensitivity="STRICT"):
        return SentenceDecisionEnvelope(
            schema_version="1.1",
            task="sentence_rewrite",
            decisions=[
                {
                    "id": context.sentence_id,
                    "action": "replace",
                    "replacement": "该方案可能显著提高数据处理效率。",
                    "reason": "unsafe sentence test",
                }
            ],
        )


def _service(runtime: ModelRuntime) -> RewriteService:
    return RewriteService(runtime=runtime, semantic=fake_semantic_validator())


def test_txt_pipeline_is_local_and_does_not_overwrite_source(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("该方案能够有效提高数据处理效率。", encoding="utf-8")
    result = _service(ReplaceRuntime()).rewrite_file(source, job_dir=tmp_path / "job")
    assert result.success is True
    assert source.read_text(encoding="utf-8") == "该方案能够有效提高数据处理效率。"
    assert Path(result.output_file).read_text(encoding="utf-8") == "该方案可以有效提高数据处理效率。"
    assert result.audit.changed == 1
    assert result.audit.rejected == 0
    assert result.audit.changes[0].original == "能够"
    assert result.audit.changes[0].replacement == "可以"
    assert result.audit.schema_version == "1.2"
    assert result.audit.changes[0].semantic_evidence is not None
    assert result.audit.changes[0].semantic_evidence.passed is True


def test_common_lexical_replacement_supports_bianyu_to_fangbian(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("这份说明便于后续整理、编码和报告引用。", encoding="utf-8")
    result = _service(ReplaceRuntime()).rewrite_file(source, job_dir=tmp_path / "job")

    assert result.success is True
    assert result.audit.changed == 1
    assert result.audit.changes[0].original == "便于"
    assert result.audit.changes[0].replacement == "方便"
    assert Path(result.output_file).read_text(encoding="utf-8") == "这份说明方便后续整理、编码和报告引用。"


def test_user_dictionary_has_highest_priority(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("该方案能够有效提高数据处理效率。", encoding="utf-8")
    result = _service(ReplaceRuntime()).rewrite_file(
        source,
        rewrite_settings=RewriteSettings(protect_terms=["能够"]),
        job_dir=tmp_path / "job",
    )
    assert result.success is True
    assert result.audit.changed == 0
    assert "能够" in Path(result.output_file).read_text(encoding="utf-8")


def test_invalid_model_decisions_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("该方案能够有效提高数据处理效率。", encoding="utf-8")
    result = _service(InvalidRuntime()).rewrite_file(source, job_dir=tmp_path / "job")
    assert result.success is True
    assert result.audit.changed == 0
    assert result.audit.kept == 1
    assert result.audit.rejected == 1
    assert Path(result.output_file).read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_model_json_is_retried_once(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("该方案能够有效提高数据处理效率。", encoding="utf-8")
    runtime = RetryRuntime()
    result = _service(runtime).rewrite_file(source, job_dir=tmp_path / "job")
    assert runtime.calls == 2
    assert result.audit.changed == 1


def test_sentence_scope_creates_auditable_local_patches(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("该方案能够有效提高数据处理效率。", encoding="utf-8")
    result = _service(SentenceRuntime()).rewrite_file(
        source,
        rewrite_settings=RewriteSettings(
            rewrite_scope=RewriteScope.LEXICAL_AND_SENTENCE,
            strength=1,
        ),
        job_dir=tmp_path / "job",
    )
    assert result.success is True
    assert result.audit.changed == 1
    assert result.audit.changes[0].kind == "sentence"
    assert Path(result.output_file).read_text(encoding="utf-8") == "该方案可以有效提高数据处理效率。"


def test_sentence_scope_rejects_new_modality_words(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("该方案能够有效提高数据处理效率。", encoding="utf-8")
    result = _service(UnsafeSentenceRuntime()).rewrite_file(
        source,
        rewrite_settings=RewriteSettings(
            rewrite_scope=RewriteScope.LEXICAL_AND_SENTENCE,
            strength=1,
        ),
        job_dir=tmp_path / "job",
    )
    assert result.success is True
    assert result.audit.changed == 1
    assert all(change.kind == "lexical" for change in result.audit.changes)
    assert "可能" not in Path(result.output_file).read_text(encoding="utf-8")


def test_lexical_strength_caps_approved_changes_per_sentence(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("该方案通常用于提高数据处理效率。", encoding="utf-8")
    result = _service(ReplaceRuntime()).rewrite_file(
        source,
        rewrite_settings=RewriteSettings(strength=1),
        job_dir=tmp_path / "job",
    )
    assert result.success is True
    assert result.audit.changed == 1
    assert result.audit.rejected == 1
    assert Path(result.output_file).read_text(encoding="utf-8") == "该方案一般用于提高数据处理效率。"


def test_lightweight_ner_does_not_protect_common_route_phrase(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text(
        "家庭：家长通常做路线、预算和安全决策，但孩子会改变停留点和是否购买项目；三代家庭还要同时处理步行强度和休息频率。",
        encoding="utf-8",
    )
    result = _service(ReplaceRuntime()).rewrite_file(
        source,
        rewrite_settings=RewriteSettings(strength=1),
        job_dir=tmp_path / "job",
    )
    assert result.success is True
    assert result.audit.changed == 1
    assert result.audit.changes[0].original == "通常"
