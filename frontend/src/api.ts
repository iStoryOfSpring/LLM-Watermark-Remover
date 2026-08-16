import type {
  AuditReport,
  JobState,
  LayoutSensitivity,
  ModelStatus,
  PreviewResponse,
  RecentJob,
  RewriteResult,
  RewriteScope,
} from "./types";

const apiRoot = import.meta.env.VITE_API_URL ?? "";

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? "请求失败（" + response.status + "）");
  }
  return response.json() as Promise<T>;
}

export async function fetchModelStatus(): Promise<ModelStatus> {
  return readJson<ModelStatus>(await fetch(apiRoot + "/api/model/status"));
}

export interface SubmitOptions {
  file: File;
  dictionary?: File | null;
  rewriteScope: RewriteScope;
  strength: 1 | 2 | 3;
  preserveLayout: boolean;
  layoutSensitivity: LayoutSensitivity;
  protectTerms: string[];
}

export async function submitRewrite(options: SubmitOptions): Promise<{ job_id: string; state: string }> {
  const body = new FormData();
  body.append("file", options.file);
  if (options.dictionary) body.append("dictionary", options.dictionary);
  body.append("rewrite_scope", options.rewriteScope);
  body.append("strength", String(options.strength));
  body.append("preserve_layout", String(options.preserveLayout));
  body.append("layout_sensitivity", options.layoutSensitivity);
  body.append("protect_terms", JSON.stringify(options.protectTerms));
  body.append("user_terms", JSON.stringify([]));
  return readJson(await fetch(apiRoot + "/api/rewrite", { method: "POST", body }));
}

export interface TextRewriteOptions {
  text: string;
  rewriteScope: RewriteScope;
  strength: 1 | 2 | 3;
  preserveLayout: boolean;
  layoutSensitivity: LayoutSensitivity;
  protectTerms: string[];
}

export interface TextRewriteResponse {
  success: boolean;
  job_id: string;
  rewritten_text: string;
  result: RewriteResult;
}

export async function rewriteText(options: TextRewriteOptions): Promise<TextRewriteResponse> {
  return readJson<TextRewriteResponse>(
    await fetch(apiRoot + "/api/rewrite/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: options.text,
        rewrite_scope: options.rewriteScope,
        strength: options.strength,
        preserve_layout: options.preserveLayout,
        layout_sensitivity: options.layoutSensitivity,
        protect_terms: options.protectTerms,
        user_terms: [],
      }),
    }),
  );
}

export async function getJob(jobId: string): Promise<JobState> {
  return readJson<JobState>(await fetch(apiRoot + "/api/jobs/" + encodeURIComponent(jobId)));
}

export async function getRecentJobs(): Promise<RecentJob[]> {
  return readJson<RecentJob[]>(await fetch(apiRoot + "/api/jobs?limit=50"));
}

export async function deleteJob(jobId: string): Promise<void> {
  await readJson<{ job_id: string; deleted: boolean }>(
    await fetch(apiRoot + "/api/jobs/" + encodeURIComponent(jobId), { method: "DELETE" }),
  );
}

export async function getPreview(jobId: string): Promise<PreviewResponse> {
  return readJson<PreviewResponse>(await fetch(apiRoot + "/api/jobs/" + encodeURIComponent(jobId) + "/preview"));
}

export async function updateReview(jobId: string, acceptedChangeIds: string[]): Promise<AuditReport> {
  const response = await fetch(apiRoot + "/api/jobs/" + encodeURIComponent(jobId) + "/review", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accepted_change_ids: acceptedChangeIds }),
  });
  const payload = await readJson<{ audit: AuditReport }>(response);
  return payload.audit;
}

export interface ExportResponse {
  success?: boolean;
  job_id: string;
  output_file?: string;
  audit_file?: string;
  download_url?: string;
}

export async function exportSelected(jobId: string, acceptedChangeIds: string[]): Promise<ExportResponse> {
  return readJson<ExportResponse>(
    await fetch(apiRoot + "/api/jobs/" + encodeURIComponent(jobId) + "/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accepted_change_ids: acceptedChangeIds }),
    }),
  );
}

export async function exportNative(jobId: string, acceptedChangeIds: string[]): Promise<ExportResponse> {
  return readJson<ExportResponse>(
    await fetch(apiRoot + "/api/jobs/" + encodeURIComponent(jobId) + "/export/native", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accepted_change_ids: acceptedChangeIds }),
    }),
  );
}

export async function fetchDownload(jobId: string): Promise<Blob> {
  const response = await fetch(apiRoot + "/api/jobs/" + encodeURIComponent(jobId) + "/download/output");
  if (!response.ok) throw new Error("输出文件下载失败（" + response.status + "）");
  return response.blob();
}

export async function parseDictionary(file: File): Promise<{ filename: string; terms: string[]; count: number }> {
  const body = new FormData();
  body.append("file", file);
  return readJson(await fetch(apiRoot + "/api/dictionaries/parse", { method: "POST", body }));
}

export function downloadAuditUrl(jobId: string): string {
  return apiRoot + "/api/jobs/" + encodeURIComponent(jobId) + "/download/audit";
}

export function outputDownloadUrl(jobId: string): string {
  return apiRoot + "/api/jobs/" + encodeURIComponent(jobId) + "/download/output";
}
