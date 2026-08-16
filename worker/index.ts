import { strFromU8, strToU8, unzipSync, zipSync } from "fflate";
import dictionary from "../backend/app/dictionaries/default_protected.json";

type Binding = {
  prepare(sql: string): {
    bind(...values: unknown[]): {
      first<T = Record<string, unknown>>(column?: string): Promise<T | null>;
      all<T = Record<string, unknown>>(): Promise<{ results: T[] }>;
      run(): Promise<unknown>;
    };
    first<T = Record<string, unknown>>(column?: string): Promise<T | null>;
    all<T = Record<string, unknown>>(): Promise<{ results: T[] }>;
    run(): Promise<unknown>;
  };
  batch(statements: unknown[]): Promise<unknown>;
};

type Bucket = {
  put(key: string, value: ArrayBuffer | ArrayBufferView | ReadableStream | string, options?: Record<string, unknown>): Promise<unknown>;
  get(key: string): Promise<{ body: ReadableStream; httpMetadata?: Record<string, string> } | null>;
  delete(keys: string | string[]): Promise<unknown>;
};

type Env = {
  ASSETS?: { fetch(request: Request): Promise<Response> };
  DB?: Binding;
  FILES?: Bucket;
};

type ExecutionContextLike = {
  waitUntil(promise: Promise<unknown>): void;
};

type Settings = {
  rewrite_scope: "lexical" | "lexical_and_sentence";
  strength: 1 | 2 | 3;
  preserve_layout: boolean;
  layout_sensitivity: "STRICT" | "NORMAL" | "LOOSE";
  protect_terms: string[];
  user_terms: string[];
};

type Span = {
  start: number;
  end: number;
  text: string;
  type: string;
  reason: string;
  priority: number;
};

type Unit = {
  unit_id: string;
  type: "paragraph";
  text: string;
  start_offset: number;
  end_offset: number;
  location: Record<string, unknown>;
  text_mapping?: Array<Record<string, unknown>>;
  editable: boolean;
  protection_reason?: string | null;
};

type Snapshot = {
  document_id: string;
  format: "txt" | "docx";
  source_path: string;
  source_hash: string;
  source_size: number;
  logical_text: string;
  units: Unit[];
  metadata: Record<string, unknown>;
};

type Change = {
  change_id: string;
  unit_id: string;
  sentence_id: string;
  start: number;
  end: number;
  document_start: number;
  document_end: number;
  original: string;
  replacement: string;
  reason: string;
  kind: "lexical";
  source_sentence: string;
  similarity: number;
  validation_trace: string[];
  accepted: boolean;
};

type RejectedProposal = {
  candidate_id: string;
  unit_id: string;
  original: string;
  replacement: string | null;
  reason: string;
  stage: string;
};

type Audit = {
  schema_version: "1.1";
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
  changes: Change[];
  rejected_proposals: RejectedProposal[];
};

type Plan = {
  snapshot: Snapshot;
  audit: Audit;
  patches: Change[];
  outputBytes: Uint8Array;
};

type JobRow = {
  job_id: string;
  filename: string;
  format: "txt" | "docx";
  state: "queued" | "running" | "completed" | "failed" | "exported";
  created_at: string;
  updated_at: string;
  document_id: string | null;
  source_hash: string | null;
  source_key: string;
  output_key: string | null;
  snapshot_json: string | null;
  audit_json: string | null;
  error: string | null;
};

const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });
const schemaSql = `
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  format TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  document_id TEXT,
  source_hash TEXT,
  source_key TEXT NOT NULL,
  output_key TEXT,
  snapshot_json TEXT,
  audit_json TEXT,
  error TEXT
)`;
const indexSql = `CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs(updated_at DESC)`;
let schemaReady: Promise<void> | null = null;

const safeReplacements = (dictionary as { safe_replacements: Array<{ text: string; pos?: string; replacements?: string[]; reason?: string }> }).safe_replacements ?? [];
const protectedTerms = (dictionary as { protected_terms?: string[] }).protected_terms ?? [];
const riskTerms = (dictionary as { risk_terms?: Record<string, string[]> }).risk_terms ?? {};

const URL_RE = /https?:\/\/[^\s，。；！？]+|www\.[^\s，。；！？]+/gi;
const EMAIL_RE = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi;
const DATE_RE = /(?<!\w)(?:\d{2,4}年(?:\d{1,2}月(?:\d{1,2}日)?)?|\d{1,2}月\d{1,2}日|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})(?!\w)/g;
const PERCENTAGE_RE = /(?<!\w)\d+(?:\.\d+)?\s*%(?!\w)/g;
const NUMBER_UNIT_RE = /(?<!\w)(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?\s*(?:万|亿|千|百|元|万元|亿元|人|件|个|次|年|月|日|吨|公里|km|kg|GB|TB)(?!\w)/gi;
const NUMBER_RE = /(?<!\w)\d+(?:\.\d+)?(?!\w)/g;
const CODE_RE = /`[^`]+`|(?<!\w)(?:[A-Za-z_][A-Za-z0-9_.-]*\([^)]*\))(?!\w)/g;
const ORG_RE = /[\u4e00-\u9fff]{2,16}(?:大学|学院|公司|集团|研究院|研究所|银行|医院|委员会|中心|实验室)/g;
const LOCATION_RE = /[\u4e00-\u9fff]{2,8}(?:省|市|区|县|乡|镇|街道|村)(?![\u4e00-\u9fff])/g;
const LATIN_PROPER_RE = /(?<!\w)(?:[A-Z][A-Za-z0-9.+-]{1,}|[A-Za-z]+(?:\s+[A-Za-z]+){1,3})(?!\w)/g;

function json(data: unknown, status = 200, extraHeaders: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...extraHeaders,
    },
  });
}

function now(): string {
  return new Date().toISOString();
}

function newId(): string {
  return crypto.randomUUID();
}

function normalizeTerms(values: unknown): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of Array.isArray(values) ? values : []) {
    const term = String(value ?? "").trim();
    if (term && !seen.has(term)) {
      seen.add(term);
      result.push(term);
    }
  }
  return result;
}

function parseSettings(payload: Record<string, unknown>): Settings {
  const scope = payload.rewrite_scope === "lexical_and_sentence" ? "lexical_and_sentence" : "lexical";
  const strength = Number(payload.strength ?? 2);
  if (![1, 2, 3].includes(strength)) throw new Error("strength 必须是 1、2 或 3。");
  const sensitivity = String(payload.layout_sensitivity ?? "STRICT").toUpperCase();
  if (!["STRICT", "NORMAL", "LOOSE"].includes(sensitivity)) throw new Error("layout_sensitivity 无效。");
  return {
    rewrite_scope: scope,
    strength: strength as 1 | 2 | 3,
    preserve_layout: payload.preserve_layout !== false && String(payload.preserve_layout).toLowerCase() !== "false",
    layout_sensitivity: sensitivity as Settings["layout_sensitivity"],
    protect_terms: normalizeTerms(payload.protect_terms),
    user_terms: normalizeTerms(payload.user_terms),
  };
}

async function sha256(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((part) => part.toString(16).padStart(2, "0")).join("");
}

function decodeUtf8(bytes: Uint8Array): string {
  try {
    return decoder.decode(bytes).replace(/^\uFEFF/, "");
  } catch (error) {
    throw new Error("TXT 必须是 UTF-8 编码；无法安全解码，已按 Fail Closed 拒绝。");
  }
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function decodeXml(value: string): string {
  return value
    .replace(/&#x([0-9a-f]+);/gi, (_, code: string) => String.fromCodePoint(Number.parseInt(code, 16)))
    .replace(/&#(\d+);/g, (_, code: string) => String.fromCodePoint(Number(code)))
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

function addTermSpans(text: string, terms: string[], type: string, reason: string, priority: number): Span[] {
  const spans: Span[] = [];
  for (const term of [...terms].filter(Boolean).sort((a, b) => b.length - a.length)) {
    let start = 0;
    while (true) {
      const index = text.indexOf(term, start);
      if (index < 0) break;
      spans.push({ start: index, end: index + term.length, text: term, type, reason, priority });
      start = index + term.length;
    }
  }
  return spans;
}

function addRegexSpans(text: string, pattern: RegExp, type: string, reason: string, priority: number): Span[] {
  pattern.lastIndex = 0;
  return [...text.matchAll(pattern)].map((match) => ({
    start: match.index ?? 0,
    end: (match.index ?? 0) + match[0].length,
    text: match[0],
    type,
    reason,
    priority,
  }));
}

function protectedSpans(text: string, settings: Settings): Span[] {
  const userTerms = normalizeTerms([...settings.protect_terms, ...settings.user_terms]);
  const spans: Span[] = [
    ...addTermSpans(text, userTerms, "USER_TERM", "用户自定义词典", 100),
    ...addTermSpans(text, protectedTerms, "TERM", "内置保护词典", 80),
  ];
  for (const [type, terms] of Object.entries(riskTerms)) {
    spans.push(...addTermSpans(text, terms, type, "风险词保护", 75));
  }
  for (const [pattern, type, reason, priority] of [
    [URL_RE, "URL", "URL", 90],
    [EMAIL_RE, "EMAIL", "email", 90],
    [DATE_RE, "DATE", "date", 90],
    [PERCENTAGE_RE, "PERCENTAGE", "percentage", 90],
    [NUMBER_UNIT_RE, "NUMBER_UNIT", "number_unit", 90],
    [CODE_RE, "CODE", "code", 90],
    [NUMBER_RE, "NUMBER", "number", 90],
    [ORG_RE, "NAMED_ENTITY", "organization heuristic", 70],
    [LOCATION_RE, "NAMED_ENTITY", "location heuristic", 70],
    [LATIN_PROPER_RE, "NAMED_ENTITY", "latin named-entity heuristic", 70],
  ] as const) {
    spans.push(...addRegexSpans(text, pattern, type, reason, priority));
  }
  const selected: Span[] = [];
  for (const span of spans
    .filter((item) => item.end > item.start)
    .sort((a, b) => b.priority - a.priority || (b.end - b.start) - (a.end - a.start) || a.start - b.start)) {
    if (!selected.some((current) => !(span.end <= current.start || span.start >= current.end))) selected.push(span);
  }
  return selected.sort((a, b) => a.start - b.start || a.end - b.end);
}

function splitSentences(text: string): Array<{ sentenceId: string; start: number; end: number; text: string }> {
  const result: Array<{ sentenceId: string; start: number; end: number; text: string }> = [];
  let start = 0;
  for (const match of text.matchAll(/[。！？!?；;]/g)) {
    const end = (match.index ?? 0) + match[0].length;
    const part = text.slice(start, end);
    if (part.trim()) result.push({ sentenceId: `s_${String(result.length).padStart(4, "0")}`, start, end, text: part });
    start = end;
  }
  if (text.slice(start).trim()) result.push({ sentenceId: `s_${String(result.length).padStart(4, "0")}`, start, end: text.length, text: text.slice(start) });
  return result;
}

function splitTxtUnits(text: string): Unit[] {
  const units: Unit[] = [];
  const linePattern = /[^\r\n]*(?:\r\n|\n|\r|$)/g;
  let match: RegExpExecArray | null;
  while ((match = linePattern.exec(text))) {
    const raw = match[0];
    if (!raw) break;
    const line = raw.replace(/\r?\n$|\r$/, "");
    if (line || match.index < text.length) {
      units.push({
        unit_id: `p_${String(units.length).padStart(4, "0")}`,
        type: "paragraph",
        text: line,
        start_offset: match.index,
        end_offset: match.index + line.length,
        location: { part: "text", paragraph_index: units.length, xml_node_keys: [] },
        editable: true,
        protection_reason: null,
      });
    }
    if (match.index + raw.length >= text.length) break;
  }
  return units;
}

function isProtected(start: number, end: number, spans: Span[]): boolean {
  return spans.some((span) => !(end <= span.start || start >= span.end));
}

function planUnits(snapshot: Snapshot, settings: Settings, jobId: string): { audit: Audit; patches: Change[] } {
  const patches: Change[] = [];
  const rejected: RejectedProposal[] = [];
  const warnings: string[] = ["云端 Worker 使用确定性安全词典；未接入生成式模型时不会猜测或扩写原文。"];
  if (settings.rewrite_scope === "lexical_and_sentence") warnings.push("当前云端安全模式不执行句子级改写，已按词语级安全替换处理。");
  let protectedCount = Number(snapshot.metadata.protected_region_count ?? 0);
  let kept = 0;
  const cap = { 1: 1, 2: 2, 3: 3 }[settings.strength];
  const deltaLimit = { STRICT: 0.1, NORMAL: 0.2, LOOSE: 0.3 }[settings.layout_sensitivity];

  for (const unit of snapshot.units) {
    if (!unit.editable) {
      if (unit.text) protectedCount += 1;
      continue;
    }
    const spans = protectedSpans(unit.text, settings);
    protectedCount += spans.length;
    let acceptedInSentence = 0;
    const seenRanges: Array<[number, number]> = [];
    for (const sentence of splitSentences(unit.text)) {
      let sentenceAccepted = 0;
      const sentenceSpans = spans
        .filter((span) => span.start >= sentence.start && span.end <= sentence.end)
        .map((span) => ({ ...span, start: span.start - sentence.start, end: span.end - sentence.start }));
      const candidates: Array<{ start: number; end: number; original: string; replacement: string; reason: string; id: string }> = [];
      for (const entry of [...safeReplacements].sort((a, b) => b.text.length - a.text.length || a.text.localeCompare(b.text))) {
        let cursor = 0;
        while (true) {
          const start = sentence.text.indexOf(entry.text, cursor);
          if (start < 0) break;
          const end = start + entry.text.length;
          if (!isProtected(start, end, sentenceSpans) && !candidates.some((candidate) => !(end <= candidate.start || start >= candidate.end))) {
            candidates.push({
              start,
              end,
              original: entry.text,
              replacement: entry.replacements?.[0] ?? "",
              reason: entry.reason ?? "高置信安全词典替换",
              id: `${unit.unit_id}:${sentence.sentenceId}:c${String(candidates.length).padStart(3, "0")}`,
            });
          }
          cursor = end;
        }
      }
      candidates.sort((a, b) => a.start - b.start || b.end - b.start - (a.end - a.start));
      for (const candidate of candidates) {
        if (!candidate.replacement) {
          kept += 1;
          continue;
        }
        if (sentenceAccepted >= cap) {
          rejected.push({ candidate_id: candidate.id, unit_id: unit.unit_id, original: candidate.original, replacement: candidate.replacement, reason: `超过当前强度的每句词语替换额度（${cap}）`, stage: "strength_validator" });
          continue;
        }
        const lengthDelta = Math.abs(candidate.replacement.length - candidate.original.length) / Math.max(candidate.original.length, 1);
        if (settings.preserve_layout && lengthDelta > deltaLimit) {
          rejected.push({ candidate_id: candidate.id, unit_id: unit.unit_id, original: candidate.original, replacement: candidate.replacement, reason: `版式敏感度 ${settings.layout_sensitivity} 拒绝长度变化`, stage: "layout_validator" });
          continue;
        }
        const start = sentence.start + candidate.start;
        const end = sentence.start + candidate.end;
        if (seenRanges.some(([left, right]) => !(end <= left || start >= right))) {
          rejected.push({ candidate_id: candidate.id, unit_id: unit.unit_id, original: candidate.original, replacement: candidate.replacement, reason: "patch 与另一个 patch 重叠", stage: "patch_validator" });
          continue;
        }
        seenRanges.push([start, end]);
        const patch: Change = {
          change_id: `${jobId}:${candidate.id}`,
          unit_id: unit.unit_id,
          sentence_id: `${unit.unit_id}:${sentence.sentenceId}`,
          start,
          end,
          document_start: unit.start_offset + start,
          document_end: unit.start_offset + end,
          original: candidate.original,
          replacement: candidate.replacement,
          reason: candidate.reason,
          kind: "lexical",
          source_sentence: sentence.text,
          similarity: 1,
          validation_trace: ["protected_span:pass", "dictionary:pass", "layout:pass", "deterministic_cloud:pass"],
          accepted: true,
        };
        patches.push(patch);
        sentenceAccepted += 1;
        acceptedInSentence += 1;
      }
      if (sentenceAccepted === 0 && candidates.length > 0) kept += candidates.length;
    }
    if (acceptedInSentence === 0 && spans.length === 0 && unit.text.trim()) kept += 1;
  }

  const audit: Audit = {
    schema_version: "1.1",
    job_id: jobId,
    document_id: snapshot.document_id,
    format: snapshot.format,
    status: "completed",
    original_sha256: snapshot.source_hash,
    changed: patches.length,
    kept,
    rejected: rejected.length,
    protected: protectedCount,
    model_status: "deterministic-cloud",
    warnings,
    changes: patches,
    rejected_proposals: rejected,
  };
  return { audit, patches };
}

function applyTextPatches(text: string, patches: Change[]): string {
  let result = text;
  for (const patch of [...patches].sort((a, b) => b.document_start - a.document_start)) {
    if (result.slice(patch.document_start, patch.document_end) !== patch.original) throw new Error("TXT patch 原文校验失败，拒绝写出。");
    result = result.slice(0, patch.document_start) + patch.replacement + result.slice(patch.document_end);
  }
  return result;
}

type XmlNode = {
  nodeKey: string;
  contentStart: number;
  contentEnd: number;
  text: string;
};

type DocxSnapshot = {
  snapshot: Snapshot;
  xml: string;
  nodes: XmlNode[];
};

function buildDocxSnapshot(bytes: Uint8Array, sourceKey: string, sourceHash: string): DocxSnapshot {
  const archive = unzipSync(bytes);
  const xmlBytes = archive["word/document.xml"];
  if (!xmlBytes) throw new Error("DOCX 缺少 word/document.xml，无法安全处理。");
  const xml = strFromU8(xmlBytes);
  const allNodes: XmlNode[] = [];
  const textPattern = /<(?:[A-Za-z_][\w.-]*:)?t\b[^>]*>([\s\S]*?)<\/(?:[A-Za-z_][\w.-]*:)?t>/g;
  for (const match of xml.matchAll(textPattern)) {
    const fullStart = match.index ?? 0;
    const full = match[0];
    const openEnd = full.indexOf(">") + 1;
    allNodes.push({
      nodeKey: `t:${allNodes.length}`,
      contentStart: fullStart + openEnd,
      contentEnd: fullStart + full.lastIndexOf("</"),
      text: decodeXml(match[1]),
    });
  }
  const bodyOpen = xml.indexOf("<w:body");
  const bodyStart = bodyOpen >= 0 ? xml.indexOf(">", bodyOpen) + 1 : 0;
  const bodyEnd = xml.lastIndexOf("</w:body>");
  const body = xml.slice(bodyStart, bodyEnd >= bodyStart ? bodyEnd : xml.length);
  const paragraphPattern = /<w:p\b[^>]*>[\s\S]*?<\/w:p>/g;
  const units: Unit[] = [];
  let logicalOffset = 0;
  let protectedTableParagraphs = 0;
  for (const match of body.matchAll(paragraphPattern)) {
    const paragraphXml = match[0];
    const relativeStart = match.index ?? 0;
    const prefix = body.slice(0, relativeStart);
    const inTable = (prefix.match(/<w:tbl\b/g) ?? []).length > (prefix.match(/<\/w:tbl>/g) ?? []).length;
    const paragraphStart = bodyStart + relativeStart;
    const paragraphEnd = paragraphStart + paragraphXml.length;
    const nodes = allNodes.filter((node) => node.contentStart >= paragraphStart && node.contentEnd <= paragraphEnd);
    const text = nodes.map((node) => node.text).join("");
    if (inTable) {
      if (text) protectedTableParagraphs += 1;
      continue;
    }
    const styleMatch = paragraphXml.match(/w:val=["']([^"']+)["']/i);
    const style = styleMatch?.[1]?.toLowerCase() ?? "";
    const heading = style.startsWith("heading") || style.startsWith("title") || style.includes("标题");
    const unsupported = paragraphXml.includes("<w:hyperlink")
      ? "hyperlink"
      : /<w:(?:object|txbxContent|commentReference|footnoteReference|endnoteReference)\b/.test(paragraphXml)
        ? "object_or_reference"
        : paragraphXml.includes("<w:instrText") || paragraphXml.includes("<w:fldSimple")
          ? "field_or_toc"
          : paragraphXml.includes("<w:oMath") || paragraphXml.includes("<m:oMath")
            ? "formula"
            : null;
    const protectionReason = heading ? "title_or_heading" : unsupported;
    const mapping = nodes.map((node) => {
      const unitStart = nodes.slice(0, nodes.indexOf(node)).reduce((sum, current) => sum + current.text.length, 0);
      return {
        start: unitStart,
        end: unitStart + node.text.length,
        node_key: node.nodeKey,
        part: "word/document.xml",
        run_key: node.nodeKey,
        formatting_fingerprint: "cloud-preserved",
      };
    });
    units.push({
      unit_id: `p_${String(units.length).padStart(4, "0")}`,
      type: "paragraph",
      text,
      start_offset: logicalOffset,
      end_offset: logicalOffset + text.length,
      location: { part: "word/document.xml", paragraph_index: units.length, xml_node_keys: nodes.map((node) => node.nodeKey), protected_reason: protectionReason },
      text_mapping: mapping,
      editable: Boolean(nodes.length && !protectionReason),
      protection_reason: protectionReason,
    });
    logicalOffset += text.length + 1;
  }
  const snapshot: Snapshot = {
    document_id: newId(),
    format: "docx",
    source_path: sourceKey,
    source_hash: sourceHash,
    source_size: bytes.byteLength,
    logical_text: units.map((unit) => unit.text).join("\n"),
    units,
    metadata: {
      main_part: "word/document.xml",
      all_text_node_count: allNodes.length,
      editable_scope: "body_direct_paragraphs_only",
      protected_region_count: protectedTableParagraphs,
    },
  };
  return { snapshot, xml, nodes: allNodes };
}

function patchDocx(bytes: Uint8Array, docx: DocxSnapshot, patches: Change[]): Uint8Array {
  const updates = new Map<string, Array<{ start: number; end: number; original: string; replacement: string }>>();
  const unitById = new Map(docx.snapshot.units.map((unit) => [unit.unit_id, unit]));
  for (const patch of patches) {
    const unit = unitById.get(patch.unit_id);
    if (!unit?.editable) throw new Error("DOCX patch 目标段落受保护或不存在。");
    const mapping = (unit.text_mapping ?? []).filter((segment) => Number(segment.start) <= patch.start && patch.end <= Number(segment.end));
    if (mapping.length !== 1) throw new Error("DOCX span 跨格式或跨文本节点，按 Fail Closed 拒绝。");
    const nodeKey = String(mapping[0].node_key);
    const nodeStart = Number(mapping[0].start);
    const current = updates.get(nodeKey) ?? [];
    current.push({ start: patch.start - nodeStart, end: patch.end - nodeStart, original: patch.original, replacement: patch.replacement });
    updates.set(nodeKey, current);
  }
  let xml = docx.xml;
  const orderedUpdates = [...updates.entries()].sort(([leftKey], [rightKey]) => {
    const leftNode = docx.nodes.find((item) => item.nodeKey === leftKey);
    const rightNode = docx.nodes.find((item) => item.nodeKey === rightKey);
    return (rightNode?.contentStart ?? 0) - (leftNode?.contentStart ?? 0);
  });
  for (const [nodeKey, changes] of orderedUpdates) {
    const node = docx.nodes.find((item) => item.nodeKey === nodeKey);
    if (!node) throw new Error("DOCX text node mapping 越界。");
    let text = node.text;
    for (const change of [...changes].sort((a, b) => b.start - a.start)) {
      if (text.slice(change.start, change.end) !== change.original) throw new Error("DOCX patch 原文校验失败。");
      if (change.original.trim() !== change.original || change.replacement.trim() !== change.replacement) throw new Error("DOCX patch 会改变空白边界，拒绝以保护 xml:space。");
      text = text.slice(0, change.start) + change.replacement + text.slice(change.end);
    }
    const replacement = escapeXml(text);
    xml = xml.slice(0, node.contentStart) + replacement + xml.slice(node.contentEnd);
  }
  const archive = unzipSync(bytes);
  archive["word/document.xml"] = strToU8(xml);
  return zipSync(archive, { level: 6 });
}

async function buildPlan(bytes: Uint8Array, filename: string, sourceKey: string, settings: Settings, jobId: string): Promise<Plan> {
  const format = filename.toLowerCase().endsWith(".docx") ? "docx" : "txt";
  const sourceHash = await sha256(bytes);
  let snapshot: Snapshot;
  let docx: DocxSnapshot | null = null;
  let text = "";
  if (format === "txt") {
    text = decodeUtf8(bytes);
    snapshot = {
      document_id: newId(),
      format: "txt",
      source_path: sourceKey,
      source_hash: sourceHash,
      source_size: bytes.byteLength,
      logical_text: text,
      units: splitTxtUnits(text),
      metadata: { encoding: "utf-8", newline_preserved: true, protected_region_count: 0 },
    };
  } else {
    docx = buildDocxSnapshot(bytes, sourceKey, sourceHash);
    snapshot = docx.snapshot;
    text = snapshot.logical_text;
  }
  const { audit, patches } = planUnits(snapshot, settings, jobId);
  const outputBytes = format === "txt" ? encoder.encode(applyTextPatches(text, patches)) : patchDocx(bytes, docx!, patches);
  return { snapshot, audit, patches, outputBytes };
}

function safeFilename(filename: string): string {
  const cleaned = filename.replace(/[^\w.\-\u4e00-\u9fff]+/g, "_").replace(/^\.+/, "");
  return cleaned || "document.txt";
}

function requireDb(env: Env): Binding {
  if (!env.DB) throw new Error("云端数据库尚未配置。");
  return env.DB;
}

function requireFiles(env: Env): Bucket {
  if (!env.FILES) throw new Error("云端文件存储尚未配置。");
  return env.FILES;
}

async function ensureSchema(env: Env): Promise<void> {
  const db = requireDb(env);
  if (!schemaReady) {
    schemaReady = db.batch([db.prepare(schemaSql), db.prepare(indexSql)]).then(() => undefined);
  }
  await schemaReady;
}

function parseAudit(row: JobRow): Audit | null {
  if (!row.audit_json) return null;
  try {
    return JSON.parse(row.audit_json) as Audit;
  } catch {
    return null;
  }
}

function rowToJob(row: JobRow): Record<string, unknown> {
  const audit = parseAudit(row);
  const result = audit
    ? {
        success: row.state === "completed" || row.state === "exported",
        job_id: row.job_id,
        document_id: row.document_id,
        format: row.format,
        output_file: row.output_key ? `/api/jobs/${encodeURIComponent(row.job_id)}/download/output` : null,
        audit_file: `/api/jobs/${encodeURIComponent(row.job_id)}/download/audit`,
        audit,
      }
    : null;
  return { job_id: row.job_id, state: row.state, filename: row.filename, result, error: row.error };
}

function rowToRecent(row: JobRow): Record<string, unknown> {
  const audit = parseAudit(row);
  return {
    job_id: row.job_id,
    filename: row.filename,
    state: row.state,
    format: row.format,
    changed: audit?.changed ?? 0,
    kept: audit?.kept ?? 0,
    rejected: audit?.rejected ?? 0,
    protected: audit?.protected ?? 0,
    output_file: row.output_key,
    audit_file: row.audit_json ? `/api/jobs/${encodeURIComponent(row.job_id)}/download/audit` : null,
    updated_at: row.updated_at,
  };
}

function fileResponse(body: ReadableStream | Uint8Array | string, filename: string, contentType: string): Response {
  return new Response(body as BodyInit, {
    headers: {
      "content-type": contentType,
      "content-disposition": `attachment; filename*=UTF-8''${encodeURIComponent(filename)}`,
      "cache-control": "no-store",
    },
  });
}

async function parseDictionaryFile(file: FormDataEntryValue | null): Promise<string[]> {
  if (!file || typeof file === "string" || typeof (file as File).arrayBuffer !== "function") throw new Error("请提供 .txt 或 .csv 词典文件。");
  const name = (file as File).name ?? "dictionary.txt";
  const suffix = name.toLowerCase().split(".").pop();
  if (suffix !== "txt" && suffix !== "csv") throw new Error("词典只支持 .txt 或 .csv。");
  const text = new TextDecoder().decode(await (file as File).arrayBuffer()).replace(/^\uFEFF/, "");
  const terms = text.split(/\r?\n/).map((line) => (suffix === "csv" ? line.split(",")[0] : line).trim()).filter((term) => term && !term.startsWith("#"));
  return normalizeTerms(terms);
}

async function processFileJob(env: Env, jobId: string, filename: string, sourceKey: string, bytes: Uint8Array, settings: Settings, ctx: ExecutionContextLike): Promise<void> {
  const db = requireDb(env);
  const files = requireFiles(env);
  const started = now();
  await db.prepare("UPDATE jobs SET state = ?, updated_at = ?, error = NULL WHERE job_id = ?").bind("running", started, jobId).run();
  try {
    const plan = await buildPlan(bytes, filename, sourceKey, settings, jobId);
    const outputKey = `jobs/${jobId}/output-${safeFilename(filename)}`;
    await files.put(outputKey, plan.outputBytes, { httpMetadata: { contentType: filename.toLowerCase().endsWith(".docx") ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document" : "text/plain; charset=utf-8" } });
    await db.prepare("UPDATE jobs SET state = ?, updated_at = ?, document_id = ?, source_hash = ?, output_key = ?, snapshot_json = ?, audit_json = ?, error = NULL WHERE job_id = ?")
      .bind("completed", now(), plan.snapshot.document_id, plan.snapshot.source_hash, outputKey, JSON.stringify(plan.snapshot), JSON.stringify(plan.audit), jobId).run();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await db.prepare("UPDATE jobs SET state = ?, updated_at = ?, error = ? WHERE job_id = ?").bind("failed", now(), message, jobId).run();
  }
  ctx.waitUntil(Promise.resolve());
}

async function handleTextRewrite(request: Request): Promise<Response> {
  const payload = await request.json().catch(() => null) as Record<string, unknown> | null;
  if (!payload || typeof payload.text !== "string") return json({ detail: "text 必须是字符串。" }, 400);
  if (!payload.text.trim() || payload.text.length > 2000) return json({ detail: "直接粘贴文本最多支持 2000 字。" }, 400);
  const settings = parseSettings(payload);
  const jobId = newId();
  const bytes = encoder.encode(payload.text);
  const plan = await buildPlan(bytes, "input.txt", `inline/${jobId}/input.txt`, settings, jobId);
  return json({ success: true, job_id: jobId, rewritten_text: decodeUtf8(plan.outputBytes), result: { success: true, job_id: jobId, document_id: plan.snapshot.document_id, format: "txt", output_file: null, audit_file: null, audit: plan.audit } });
}

async function handleFileRewrite(request: Request, env: Env, ctx: ExecutionContextLike): Promise<Response> {
  const form = await request.formData();
  const file = form.get("file");
  if (!file || typeof file === "string" || typeof (file as File).arrayBuffer !== "function") return json({ detail: "请提供 TXT 或 DOCX 文件。" }, 400);
  const filename = safeFilename((file as File).name || "document.txt");
  if (!/\.(txt|docx)$/i.test(filename)) return json({ detail: "只支持 .txt 和 .docx 文件。" }, 400);
  const bytes = new Uint8Array(await (file as File).arrayBuffer());
  if (bytes.byteLength > 10 * 1024 * 1024) return json({ detail: "云端单文件上限为 10 MB。" }, 413);
  const dictionaryTerms = await parseDictionaryFile(form.get("dictionary")).catch(() => []);
  const settings = parseSettings({
    rewrite_scope: form.get("rewrite_scope"),
    strength: form.get("strength"),
    preserve_layout: form.get("preserve_layout"),
    layout_sensitivity: form.get("layout_sensitivity"),
    protect_terms: JSON.parse(String(form.get("protect_terms") ?? "[]")),
    user_terms: [...JSON.parse(String(form.get("user_terms") ?? "[]")), ...dictionaryTerms],
  });
  const jobId = newId();
  const sourceKey = `jobs/${jobId}/source-${filename}`;
  await requireFiles(env).put(sourceKey, bytes, { httpMetadata: { contentType: filename.toLowerCase().endsWith(".docx") ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document" : "text/plain; charset=utf-8" } });
  const timestamp = now();
  await requireDb(env).prepare("INSERT INTO jobs (job_id, filename, format, state, created_at, updated_at, source_key) VALUES (?, ?, ?, ?, ?, ?, ?)")
    .bind(jobId, filename, filename.toLowerCase().endsWith(".docx") ? "docx" : "txt", "queued", timestamp, timestamp, sourceKey).run();
  ctx.waitUntil(processFileJob(env, jobId, filename, sourceKey, bytes, settings, ctx));
  return json({ job_id: jobId, state: "queued" });
}

async function getJobRow(env: Env, jobId: string): Promise<JobRow | null> {
  return requireDb(env).prepare("SELECT * FROM jobs WHERE job_id = ?").bind(jobId).first<JobRow>();
}

async function previewJob(env: Env, row: JobRow): Promise<Record<string, unknown>> {
  const snapshot = row.snapshot_json ? JSON.parse(row.snapshot_json) as Snapshot : null;
  const audit = parseAudit(row);
  if (!snapshot || !audit) throw new Error("逻辑文本快照不存在。");
  const paragraphs = snapshot.units.map((unit) => {
    const changes = audit.changes.filter((change) => change.unit_id === unit.unit_id).sort((a, b) => a.start - b.start);
    const accepted = changes.filter((change) => change.accepted);
    let rewritten = unit.text;
    for (const change of [...accepted].sort((a, b) => b.start - a.start)) {
      if (rewritten.slice(change.start, change.end) !== change.original) throw new Error("段落预览 patch 校验失败。");
      rewritten = rewritten.slice(0, change.start) + change.replacement + rewritten.slice(change.end);
    }
    return { unit_id: unit.unit_id, text: unit.text, rewritten_text: rewritten, changes };
  });
  let rewrittenText = snapshot.logical_text;
  for (const change of [...audit.changes.filter((item) => item.accepted)].sort((a, b) => b.document_start - a.document_start)) {
    if (rewrittenText.slice(change.document_start, change.document_end) !== change.original) throw new Error("预览 patch 校验失败。");
    rewrittenText = rewrittenText.slice(0, change.document_start) + change.replacement + rewrittenText.slice(change.document_end);
  }
  return { original_text: snapshot.logical_text, rewritten_text: rewrittenText, paragraphs };
}

async function exportJob(env: Env, row: JobRow, acceptedIds: string[]): Promise<void> {
  const audit = parseAudit(row);
  if (!audit || !row.snapshot_json) throw new Error("审计文件不存在，无法安全导出。");
  const valid = new Set(audit.changes.map((change) => change.change_id));
  const unknown = acceptedIds.filter((id) => !valid.has(id));
  if (unknown.length) throw new Error(`导出选择包含未知 change_id: ${unknown.join(", ")}`);
  const snapshot = JSON.parse(row.snapshot_json) as Snapshot;
  const sourceObject = await requireFiles(env).get(row.source_key);
  if (!sourceObject) throw new Error("原文文件不存在。");
  const source = new Uint8Array(await new Response(sourceObject.body).arrayBuffer());
  const selected = audit.changes.filter((change) => acceptedIds.includes(change.change_id));
  let output: Uint8Array;
  if (snapshot.format === "txt") output = encoder.encode(applyTextPatches(decodeUtf8(source), selected));
  else output = patchDocx(source, buildDocxSnapshot(source, row.source_key, snapshot.source_hash), selected);
  const outputKey = `jobs/${row.job_id}/output-${safeFilename(row.filename)}`;
  await requireFiles(env).put(outputKey, output, { httpMetadata: { contentType: row.format === "docx" ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document" : "text/plain; charset=utf-8" } });
  const updatedAudit: Audit = { ...audit, status: "exported", changes: audit.changes.map((change) => ({ ...change, accepted: acceptedIds.includes(change.change_id) })), warnings: [...audit.warnings, `用户导出选择：${acceptedIds.length} / ${audit.changes.length} 条提案。`] };
  await requireDb(env).prepare("UPDATE jobs SET state = ?, updated_at = ?, output_key = ?, audit_json = ? WHERE job_id = ?").bind("exported", now(), outputKey, JSON.stringify(updatedAudit), row.job_id).run();
}

async function handleApi(request: Request, env: Env, ctx: ExecutionContextLike): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname;
  if (path === "/api/health" && request.method === "GET") return json({ status: "ok", service: "cloud-rewrite-worker" });
  if (path === "/api/model/status" && request.method === "GET") return json({ state: "ready", backend: "deterministic-cloud", mode: "safe-dictionary", semantic_validator: "protected-span", source_scope: "body_direct_paragraphs_only_for_docx", rewrite_granularity: "lexical_default_sentence_opt_in", failure_policy: "fail_closed" });
  if (path === "/api/dictionaries/parse" && request.method === "POST") {
    const file = (await request.formData()).get("file");
    const terms = await parseDictionaryFile(file);
    return json({ filename: typeof file === "string" || !file ? "dictionary.txt" : (file as File).name, terms, count: terms.length });
  }
  if (path === "/api/rewrite/text" && request.method === "POST") return handleTextRewrite(request);
  if (path === "/api/rewrite" && request.method === "POST") {
    await ensureSchema(env);
    return handleFileRewrite(request, env, ctx);
  }
  if (path === "/api/jobs" && request.method === "GET") {
    await ensureSchema(env);
    const rows = await requireDb(env).prepare("SELECT * FROM jobs ORDER BY updated_at DESC LIMIT 50").all<JobRow>();
    return json(rows.results.map(rowToRecent));
  }
  const match = path.match(/^\/api\/jobs\/([^/]+)(?:\/(preview|review|export|export\/native|download\/output|download\/audit))?$/);
  if (!match) return json({ detail: "Not found" }, 404);
  await ensureSchema(env);
  const jobId = decodeURIComponent(match[1]);
  const action = match[2] ?? "get";
  const row = await getJobRow(env, jobId);
  if (!row) return json({ detail: "job not found" }, 404);
  if (action === "get" && request.method === "GET") return json(rowToJob(row));
  if (action === "preview" && request.method === "GET") return json(await previewJob(env, row));
  if (action === "review" && request.method === "PUT") {
    const body = await request.json() as { accepted_change_ids?: string[] };
    const audit = parseAudit(row);
    const ids = normalizeTerms(body.accepted_change_ids);
    if (!audit) return json({ detail: "审计文件不存在。" }, 409);
    const valid = new Set(audit.changes.map((change) => change.change_id));
    if (ids.some((id) => !valid.has(id))) return json({ detail: "审阅选择包含未知 change_id。" }, 400);
    const updated: Audit = { ...audit, status: "reviewed", changes: audit.changes.map((change) => ({ ...change, accepted: ids.includes(change.change_id) })) };
    await requireDb(env).prepare("UPDATE jobs SET updated_at = ?, audit_json = ? WHERE job_id = ?").bind(now(), JSON.stringify(updated), jobId).run();
    return json({ job_id: jobId, audit: updated });
  }
  if (action === "export/native" && request.method === "POST") return json({ detail: "云端网站不支持原生文件选择器，请使用浏览器下载。" }, 501);
  if (action === "export" && request.method === "POST") {
    const body = await request.json() as { accepted_change_ids?: string[] };
    await exportJob(env, row, normalizeTerms(body.accepted_change_ids));
    return json({ success: true, job_id: jobId, download_url: `/api/jobs/${encodeURIComponent(jobId)}/download/output` });
  }
  if (action === "download/output" && request.method === "GET") {
    if (!row.output_key) return json({ detail: "输出文件尚未生成。" }, 409);
    const object = await requireFiles(env).get(row.output_key);
    if (!object) return json({ detail: "输出文件不存在。" }, 404);
    return fileResponse(object.body, `${row.filename.replace(/\.(txt|docx)$/i, "")}_rewritten.${row.format}`, row.format === "docx" ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document" : "text/plain; charset=utf-8");
  }
  if (action === "download/audit" && request.method === "GET") {
    const audit = parseAudit(row);
    if (!audit) return json({ detail: "审计文件尚未生成。" }, 409);
    return fileResponse(JSON.stringify(audit, null, 2), `${row.filename.replace(/\.(txt|docx)$/i, "")}_rewrite_audit.json`, "application/json; charset=utf-8");
  }
  if (path.match(/^\/api\/jobs\/[^/]+$/) && request.method === "DELETE") {
    await requireFiles(env).delete([row.source_key, ...(row.output_key ? [row.output_key] : [])]);
    await requireDb(env).prepare("DELETE FROM jobs WHERE job_id = ?").bind(jobId).run();
    return json({ job_id: jobId, deleted: true });
  }
  return json({ detail: "Not found" }, 404);
}

async function serveAsset(request: Request, env: Env): Promise<Response> {
  if (!env.ASSETS) return new Response("Static assets are not configured.", { status: 503 });
  const direct = await env.ASSETS.fetch(request);
  if (direct.status !== 404) return direct;
  const fallback = new URL(request.url);
  fallback.pathname = "/index.html";
  return env.ASSETS.fetch(new Request(fallback, request));
}

const worker = {
  async fetch(request: Request, env: Env, ctx: ExecutionContextLike): Promise<Response> {
    const url = new URL(request.url);
    try {
      if (url.pathname.startsWith("/api/")) return await handleApi(request, env, ctx);
      return await serveAsset(request, env);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return json({ detail: message }, 500);
    }
  },
};

export default worker;
