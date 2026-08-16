from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentFormat(str, Enum):
    TXT = "txt"
    DOCX = "docx"


class UnitType(str, Enum):
    PARAGRAPH = "paragraph"


class SpanType(str, Enum):
    USER_TERM = "USER_TERM"
    BUILTIN_TERM = "TERM"
    DATE = "DATE"
    NUMBER = "NUMBER"
    NUMBER_UNIT = "NUMBER_UNIT"
    PERCENTAGE = "PERCENTAGE"
    URL = "URL"
    EMAIL = "EMAIL"
    CODE = "CODE"
    FORMULA = "FORMULA"
    NAMED_ENTITY = "NAMED_ENTITY"
    NEGATION = "NEGATION"
    MODALITY = "MODALITY"
    LOGIC = "LOGIC"
    RISK = "RISK"
    TITLE = "TITLE"
    UNSUPPORTED = "UNSUPPORTED"


class Action(str, Enum):
    KEEP = "keep"
    REPLACE = "replace"


class RewriteScope(str, Enum):
    LEXICAL = "lexical"
    LEXICAL_AND_SENTENCE = "lexical_and_sentence"


class LayoutSensitivity(str, Enum):
    STRICT = "STRICT"
    NORMAL = "NORMAL"
    LOOSE = "LOOSE"


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part: str
    paragraph_index: int
    xml_node_keys: list[str] = Field(default_factory=list)
    protected_reason: str | None = None


class TextMappingSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int
    end: int
    node_key: str
    part: str
    run_key: str
    formatting_fingerprint: str


class DocumentUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_id: str
    type: UnitType = UnitType.PARAGRAPH
    text: str
    start_offset: int
    end_offset: int
    location: Location
    text_mapping: list[TextMappingSegment] = Field(default_factory=list)
    editable: bool = True
    protection_reason: str | None = None


class DocumentSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    format: DocumentFormat
    source_path: str
    source_hash: str
    source_size: int
    logical_text: str
    units: list[DocumentUnit]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProtectedSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int
    end: int
    text: str
    type: SpanType
    reason: str
    priority: int = 0
    source: str = "analyzer"


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    unit_id: str
    sentence_id: str
    text: str
    start: int
    end: int
    pos: str
    allowed_replacements: list[str] = Field(default_factory=list)
    reason: str


class SentenceContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentence_id: str
    unit_id: str
    text: str
    start: int
    end: int
    previous_sentence: str = ""
    next_sentence: str = ""
    protected: list[ProtectedSpan] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)


class RewriteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    action: Action
    replacement: str | None = None
    reason: str | None = None


class DecisionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    decisions: list[RewriteDecision]


class SentenceRewriteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    action: Action
    replacement: str | None = None
    reason: str | None = None


class SentenceDecisionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"]
    task: Literal["sentence_rewrite"]
    decisions: list[SentenceRewriteDecision]


class Patch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_id: str
    unit_id: str
    sentence_id: str
    start: int
    end: int
    document_start: int | None = None
    document_end: int | None = None
    original: str
    replacement: str
    reason: str
    kind: Literal["lexical", "sentence"] = "lexical"
    source_sentence: str | None = None
    similarity: float | None = None
    validation_trace: list[str] = Field(default_factory=list)
    accepted: bool = True


class RejectedProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    unit_id: str
    original: str
    replacement: str | None = None
    reason: str
    stage: str


class AuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0", "1.1"] = "1.1"
    job_id: str
    document_id: str
    format: DocumentFormat
    status: str
    original_sha256: str
    changed: int = 0
    kept: int = 0
    rejected: int = 0
    protected: int = 0
    model_status: str
    warnings: list[str] = Field(default_factory=list)
    changes: list[Patch] = Field(default_factory=list)
    rejected_proposals: list[RejectedProposal] = Field(default_factory=list)


class RewriteSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rewrite_scope: RewriteScope = RewriteScope.LEXICAL
    strength: Literal[1, 2, 3] = 2
    preserve_layout: bool = True
    layout_sensitivity: LayoutSensitivity = LayoutSensitivity.STRICT
    protect_terms: list[str] = Field(default_factory=list)
    user_terms: list[str] = Field(default_factory=list)

    @property
    def all_user_terms(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for term in [*self.protect_terms, *self.user_terms]:
            normalized = term.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result


class RewriteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    job_id: str
    document_id: str
    format: DocumentFormat
    output_file: str | None = None
    audit_file: str | None = None
    audit: AuditReport
