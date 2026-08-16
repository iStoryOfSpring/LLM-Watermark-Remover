export type LayoutSensitivity = "STRICT" | "NORMAL" | "LOOSE";
export type RewriteScope = "lexical" | "lexical_and_sentence";
export type ReviewFilter = "all" | "accepted" | "restored";

export interface AuditChange {
  change_id: string;
  unit_id: string;
  sentence_id: string;
  start: number;
  end: number;
  document_start?: number | null;
  document_end?: number | null;
  original: string;
  replacement: string;
  reason: string;
  kind?: "lexical" | "sentence";
  source_sentence?: string | null;
  similarity?: number | null;
  validation_trace: string[];
  accepted: boolean;
}

export interface RejectedProposal {
  candidate_id: string;
  unit_id: string;
  original: string;
  replacement?: string | null;
  reason: string;
  stage: string;
}

export interface AuditReport {
  schema_version: string;
  job_id: string;
  document_id: string;
  format: "txt" | "docx";
  status: string;
  original_sha256: string;
  changed: number;
  kept: number;
  rejected: number;
  protected: number;
  model_status: string;
  warnings: string[];
  changes: AuditChange[];
  rejected_proposals: RejectedProposal[];
}

export interface RewriteResult {
  success: boolean;
  job_id: string;
  document_id: string;
  format: "txt" | "docx";
  output_file?: string | null;
  audit_file?: string | null;
  audit: AuditReport;
}

export interface JobState {
  job_id: string;
  state: "queued" | "running" | "completed" | "failed";
  filename: string;
  result?: RewriteResult | null;
  error?: string | null;
}

export interface RecentJob {
  job_id: string;
  filename: string;
  state: string;
  format?: "txt" | "docx" | null;
  changed: number;
  kept: number;
  rejected: number;
  protected: number;
  output_file?: string | null;
  audit_file?: string | null;
  updated_at?: string;
}

export interface ModelStatus {
  state: string;
  backend: string;
  mode?: string;
  reason?: string;
  model_path?: string;
  semantic_validator: string;
  failure_policy: string;
  rewrite_granularity: string;
}

export interface PreviewParagraph {
  unit_id: string;
  text: string;
  rewritten_text: string;
  changes: AuditChange[];
}

export interface PreviewResponse {
  original_text: string;
  rewritten_text: string;
  paragraphs: PreviewParagraph[];
}

export interface ReportTabState {
  jobId: string;
  filter: ReviewFilter;
  selectedChangeId: string | null;
}
