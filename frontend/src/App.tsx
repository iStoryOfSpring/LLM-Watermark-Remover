import {
  ArrowDownToLine,
  Check,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  FileDiff,
  FileText,
  Github,
  History,
  Import,
  RotateCcw,
  ScanSearch,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type DragEvent, type KeyboardEvent, type RefObject } from "react";
import {
  downloadAuditUrl,
  deleteJob as deleteJobRequest,
  exportNative,
  exportSelected,
  fetchDownload,
  fetchModelStatus,
  getJob,
  getPreview,
  getRecentJobs,
  parseDictionary,
  rewriteText,
  submitRewrite,
  updateReview,
} from "./api";
import type {
  AuditChange,
  AuditReport,
  JobState,
  LayoutSensitivity,
  ModelStatus,
  PreviewParagraph,
  PreviewResponse,
  RecentJob,
  ReportTabState,
  ReviewFilter,
  RewriteResult,
  RewriteScope,
} from "./types";
import {
  PRODUCT_BOUNDARY,
  PRODUCT_DISCLAIMER,
  PRODUCT_AUTHORSHIP_LINE,
  PRODUCT_LOCAL_REWRITE_LINE,
  PRODUCT_NAME,
  PRODUCT_POSITIONING,
  PRODUCT_TAGLINE,
} from "./brand";

const TABS_STORAGE_KEY = "local-rewrite-desk.tabs";
const REPORT_STORAGE_KEY = "local-rewrite-desk.reports";

interface ReportState extends Omit<ReportTabState, "jobId"> {
  job: JobState;
  preview: PreviewResponse | null;
  acceptedChangeIds: string[];
}

declare global {
  interface Window {
    showSaveFilePicker?: (options?: {
      suggestedName?: string;
      types?: Array<{ description: string; accept: Record<string, string[]> }>;
    }) => Promise<{ createWritable: () => Promise<{ write: (data: Blob) => Promise<void>; close: () => Promise<void> }> }>;
  }
}

function splitTerms(value: string): string[] {
  return value.split(/\r?\n/).map((term) => term.trim()).filter(Boolean);
}

function formatScore(score?: number | null): string {
  return score == null ? "—" : score.toFixed(3);
}

function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function modelInfo(model: ModelStatus | null): { label: string; tone: "ready" | "idle" | "warn" | "error" } {
  if (model?.backend === "deterministic-local") return { label: "本地安全规则就绪", tone: "ready" };
  if (model?.state === "ready") return { label: "Qwen 本地就绪", tone: "ready" };
  if (model?.state === "unavailable") return { label: "模型不可用 · Fail Closed", tone: "error" };
  if (model?.state === "available") return { label: "首次任务时加载", tone: "idle" };
  return { label: "正在检查运行时", tone: "warn" };
}

function auditLabel(audit: AuditReport): string {
  if (audit.model_status === "unavailable") return "原文已安全保留";
  if (audit.changed > 0) return "审计完成";
  return "未提交变更";
}

function statusText(state: JobState["state"]): string {
  return { queued: "排队中", running: "处理中", completed: "已完成", failed: "失败" }[state];
}

function readStoredTabs(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(TABS_STORAGE_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function readStoredReportState(): Record<string, Partial<ReportTabState>> {
  try {
    const value = JSON.parse(localStorage.getItem(REPORT_STORAGE_KEY) ?? "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

function App() {
  const [file, setFile] = useState<File | null>(null);
  const [dictionaryFile, setDictionaryFile] = useState<File | null>(null);
  const [termsText, setTermsText] = useState("");
  const [dictionaryNotice, setDictionaryNotice] = useState("");
  const [rewriteScope, setRewriteScope] = useState<RewriteScope>("lexical");
  const [strength, setStrength] = useState<1 | 2 | 3>(2);
  const [layout, setLayout] = useState<LayoutSensitivity>("STRICT");
  const [preserveLayout, setPreserveLayout] = useState(true);
  const [reports, setReports] = useState<Record<string, ReportState>>({});
  const [tabs, setTabs] = useState<string[]>(readStoredTabs);
  const [activeTab, setActiveTab] = useState("task");
  const [recentJobs, setRecentJobs] = useState<RecentJob[]>([]);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [model, setModel] = useState<ModelStatus | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pastedText, setPastedText] = useState("");
  const [textResult, setTextResult] = useState<{ rewrittenText: string; result: RewriteResult } | null>(null);
  const [isTextSubmitting, setIsTextSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const dictionaryInput = useRef<HTMLInputElement>(null);

  const runtime = modelInfo(model);
  const currentReport = activeTab === "task" ? null : reports[activeTab] ?? null;

  const refreshModelStatus = useCallback(async () => {
    try {
      const next = await fetchModelStatus();
      setModel(next);
      return next;
    } catch (reason) {
      setError((reason as Error).message);
      return null;
    }
  }, []);

  const refreshRecentJobs = useCallback(async () => {
    try {
      const jobs = await getRecentJobs();
      setRecentJobs(jobs);
      return jobs;
    } catch (reason) {
      setError((reason as Error).message);
      return [];
    }
  }, []);

  useEffect(() => {
    void refreshModelStatus();
    void refreshRecentJobs();
  }, [refreshModelStatus, refreshRecentJobs]);

  useEffect(() => {
    localStorage.setItem(TABS_STORAGE_KEY, JSON.stringify(tabs));
  }, [tabs]);

  useEffect(() => {
    const stored: Record<string, Partial<ReportTabState>> = {};
    Object.entries(reports).forEach(([jobId, report]) => {
      stored[jobId] = {
        filter: report.filter,
        selectedChangeId: report.selectedChangeId,
      };
    });
    localStorage.setItem(REPORT_STORAGE_KEY, JSON.stringify(stored));
  }, [reports]);

  useEffect(() => {
    if (!currentJobId) return;
    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const next = await getJob(currentJobId);
        if (cancelled) return;
        setReports((previous) => {
          const existing = previous[currentJobId];
          const accepted = existing?.acceptedChangeIds ?? next.result?.audit.changes.filter((item) => item.accepted).map((item) => item.change_id) ?? [];
          return {
            ...previous,
            [currentJobId]: {
              job: next,
              preview: existing?.preview ?? null,
              filter: existing?.filter ?? "all",
              selectedChangeId: existing?.selectedChangeId ?? null,
              acceptedChangeIds: accepted,
            },
          };
        });
        if (next.state === "completed" || next.state === "failed") {
          await refreshRecentJobs();
          if (next.state === "completed") {
            const preview = await getPreview(currentJobId);
            if (!cancelled) {
              setReports((previous) => ({
                ...previous,
                [currentJobId]: { ...previous[currentJobId], job: next, preview },
              }));
            }
          }
          return;
        }
        timer = window.setTimeout(poll, 800);
      } catch (reason) {
        if (!cancelled) setError((reason as Error).message);
      }
    };

    timer = window.setTimeout(poll, 450);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [currentJobId, refreshRecentJobs]);

  const acceptFile = useCallback((nextFile: File | null) => {
    if (!nextFile) return;
    const suffix = nextFile.name.toLowerCase().split(".").pop();
    if (suffix !== "txt" && suffix !== "docx") {
      setError("只支持 .txt 和 .docx 文件。");
      return;
    }
    setFile(nextFile);
    setError("");
    setNotice("");
  }, []);

  const clearFile = () => {
    setFile(null);
    if (fileInput.current) fileInput.current.value = "";
  };

  const handleDictionary = async (nextFile: File | null) => {
    if (!nextFile) return;
    try {
      const parsed = await parseDictionary(nextFile);
      setDictionaryFile(nextFile);
      setTermsText((current) => [...splitTerms(current), ...parsed.terms].filter((item, index, all) => all.indexOf(item) === index).join("\n"));
      setDictionaryNotice(`${parsed.filename} · 已导入 ${parsed.count} 个词`);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const startRewrite = async () => {
    if (!file) {
      setError("请先选择 TXT 或 DOCX 文件。");
      return;
    }
    setIsSubmitting(true);
    setError("");
    setNotice("");
    try {
      const response = await submitRewrite({
        file,
        dictionary: dictionaryFile,
        rewriteScope,
        strength,
        preserveLayout,
        layoutSensitivity: layout,
        protectTerms: splitTerms(termsText),
      });
      const nextJob: JobState = { job_id: response.job_id, state: "queued", filename: file.name, result: null };
      setReports((previous) => ({
        ...previous,
        [response.job_id]: {
          job: nextJob,
          preview: null,
          filter: "all",
          selectedChangeId: null,
          acceptedChangeIds: [],
        },
      }));
      setCurrentJobId(response.job_id);
      setNotice("处理任务已提交。本地规则正在锁定正文范围，只会提交可验证候选。");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const convertPastedText = async () => {
    if (!pastedText.trim()) {
      setError("请先粘贴需要转换的文本。");
      return;
    }
    if (pastedText.length > 2000) {
      setError("直接粘贴文本最多支持 2000 字。");
      return;
    }
    setIsTextSubmitting(true);
    setError("");
    setNotice("");
    try {
      const response = await rewriteText({
        text: pastedText,
        rewriteScope,
        strength,
        preserveLayout,
        layoutSensitivity: layout,
        protectTerms: splitTerms(termsText),
      });
      setTextResult({ rewrittenText: response.rewritten_text, result: response.result });
      setNotice(response.result.audit.changed > 0 ? `文本处理完成：通过 ${response.result.audit.changed} 处修改。` : "文本已完成安全检查，没有提案通过全部验证门。");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setIsTextSubmitting(false);
    }
  };

  const copyTextResult = async () => {
    if (!textResult) return;
    try {
      await navigator.clipboard.writeText(textResult.rewrittenText);
      setNotice("处理结果已复制到剪贴板。");
    } catch {
      setError("浏览器未允许访问剪贴板，请手动选择结果文本复制。");
    }
  };

  const loadReport = async (jobId: string) => {
    try {
      const job = await getJob(jobId);
      const stored = readStoredReportState()[jobId];
      const audit = job.result?.audit;
      const preview = job.state === "completed" ? await getPreview(jobId) : null;
      setReports((previous) => ({
        ...previous,
        [jobId]: {
          job,
          preview,
          filter: stored?.filter ?? previous[jobId]?.filter ?? "all",
          selectedChangeId: stored?.selectedChangeId ?? previous[jobId]?.selectedChangeId ?? null,
          acceptedChangeIds: audit?.changes.filter((item) => item.accepted).map((item) => item.change_id) ?? [],
        },
      }));
      return job;
    } catch (reason) {
      setError((reason as Error).message);
      return null;
    }
  };

  const openReport = async (jobId: string) => {
    if (!reports[jobId]) await loadReport(jobId);
    setTabs((previous) => previous.includes(jobId) ? previous : [...previous, jobId]);
    setActiveTab(jobId);
  };

  const closeReport = (jobId: string) => {
    setTabs((previous) => previous.filter((id) => id !== jobId));
    if (activeTab === jobId) setActiveTab("task");
  };

  const removeJob = async (jobId: string, filename?: string) => {
    const label = filename ?? reports[jobId]?.job.filename ?? "这项任务";
    if (!window.confirm(`删除“${label}”的本地任务记录、源副本、输出和审计文件？\n原始文件不会被修改。`)) return;
    try {
      await deleteJobRequest(jobId);
      setReports((previous) => {
        const next = { ...previous };
        delete next[jobId];
        return next;
      });
      setTabs((previous) => previous.filter((id) => id !== jobId));
      if (activeTab === jobId) setActiveTab("task");
      if (currentJobId === jobId) setCurrentJobId(null);
      await refreshRecentJobs();
      setNotice(`已删除“${label}”的本地任务副本。原始文件未被修改。`);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const updateAccepted = async (jobId: string, acceptedChangeIds: string[]) => {
    const report = reports[jobId];
    if (!report?.job.result) return;
    const before = report;
    setReports((previous) => ({
      ...previous,
      [jobId]: { ...previous[jobId], acceptedChangeIds },
    }));
    try {
      const audit = await updateReview(jobId, acceptedChangeIds);
      const preview = await getPreview(jobId);
      setReports((previous) => ({
        ...previous,
        [jobId]: {
          ...previous[jobId],
          preview,
          job: { ...previous[jobId].job, result: { ...previous[jobId].job.result!, audit } },
          acceptedChangeIds,
        },
      }));
      await refreshRecentJobs();
    } catch (reason) {
      setReports((previous) => ({ ...previous, [jobId]: before }));
      setError((reason as Error).message);
    }
  };

  const toggleChange = (jobId: string, changeId: string) => {
    const report = reports[jobId];
    if (!report?.job.result) return;
    const accepted = new Set(report.acceptedChangeIds);
    if (accepted.has(changeId)) accepted.delete(changeId); else accepted.add(changeId);
    void updateAccepted(jobId, [...accepted]);
  };

  const selectAll = (jobId: string) => {
    const report = reports[jobId];
    if (!report?.job.result) return;
    void updateAccepted(jobId, report.job.result.audit.changes.map((change) => change.change_id));
  };

  const restoreAll = (jobId: string) => void updateAccepted(jobId, []);

  const exportReport = async (jobId: string) => {
    const report = reports[jobId];
    if (!report?.job.result) return;
    const ids = report.acceptedChangeIds;
    try {
      const native = await exportNative(jobId, ids);
      setNotice(`已保存去标记副本：${native.output_file}；审计：${native.audit_file}`);
      await refreshRecentJobs();
      return;
    } catch (reason) {
      const message = (reason as Error).message;
      if (message.includes("取消")) {
        setNotice("已取消保存，原文件未被修改。");
        return;
      }
    }

    try {
      await exportSelected(jobId, ids);
      const blob = await fetchDownload(jobId);
      const extension = report.job.filename.toLowerCase().endsWith(".docx") ? "docx" : "txt";
      const suggestedName = report.job.filename.replace(/\.(txt|docx)$/i, "") + "_rewritten." + extension;
      if (window.showSaveFilePicker) {
        const handle = await window.showSaveFilePicker({ suggestedName });
        const writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
        const auditLink = document.createElement("a");
        auditLink.href = downloadAuditUrl(jobId);
        auditLink.download = report.job.filename.replace(/\.(txt|docx)$/i, "") + "_rewrite_audit.json";
        auditLink.click();
        setNotice("去标记副本已保存；浏览器无法访问同一目录，audit.json 已单独下载。");
      } else {
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = suggestedName;
        anchor.click();
        URL.revokeObjectURL(url);
        window.setTimeout(() => window.open(downloadAuditUrl(jobId), "_blank"), 120);
        setNotice("浏览器已开始下载去标记副本和 audit.json。");
      }
      await refreshRecentJobs();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const setReportFilter = (jobId: string, filter: ReviewFilter) => {
    setReports((previous) => ({ ...previous, [jobId]: { ...previous[jobId], filter } }));
  };

  const selectChange = (jobId: string, changeId: string | null) => {
    setReports((previous) => ({ ...previous, [jobId]: { ...previous[jobId], selectedChangeId: changeId } }));
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    acceptFile(event.dataTransfer.files[0] ?? null);
  };

  const openCurrentReport = currentJobId && reports[currentJobId]?.job.state === "completed"
    ? () => void openReport(currentJobId)
    : undefined;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand-lockup">
          <div className="brand-mark"><FileDiff size={18} strokeWidth={2.2} /></div>
          <div className="brand-copy"><strong>{PRODUCT_NAME}</strong><span>{PRODUCT_TAGLINE}</span></div>
        </div>
        <nav className="tab-strip" aria-label="应用标签页">
          <button className={activeTab === "task" ? "app-tab active" : "app-tab"} onClick={() => setActiveTab("task")}>
            <Sparkles size={14} /> 新处理
          </button>
          {tabs.map((jobId) => {
            const report = reports[jobId];
            const label = report?.job.filename ?? recentJobs.find((job) => job.job_id === jobId)?.filename ?? "报告";
            return (
              <button key={jobId} className={activeTab === jobId ? "app-tab active" : "app-tab"} onClick={() => void openReport(jobId)}>
                <FileText size={14} /><span>{label}</span><span className="tab-close" role="button" aria-label={`关闭 ${label}`} onClick={(event) => { event.stopPropagation(); closeReport(jobId); }}><X size={12} /></span>
              </button>
            );
          })}
        </nav>
        <div className="header-status">
          <span className="local-badge"><ShieldCheck size={13} /> CLOUD SAFE</span>
          <div className={`model-chip ${runtime.tone}`}><span className="model-dot" /><span>{runtime.label}</span></div>
        </div>
      </header>

      <main className="main-stage">
        {activeTab === "task" ? (
          <TaskView
            file={file}
            fileInput={fileInput}
            dictionaryInput={dictionaryInput}
            dictionaryNotice={dictionaryNotice}
            termsText={termsText}
            setTermsText={setTermsText}
            handleDictionary={handleDictionary}
            rewriteScope={rewriteScope}
            setRewriteScope={setRewriteScope}
            strength={strength}
            setStrength={setStrength}
            layout={layout}
            setLayout={setLayout}
            preserveLayout={preserveLayout}
            setPreserveLayout={setPreserveLayout}
            isDragging={isDragging}
            setIsDragging={setIsDragging}
            onDrop={onDrop}
            acceptFile={acceptFile}
            clearFile={clearFile}
            startRewrite={startRewrite}
            isSubmitting={isSubmitting}
            model={model}
            currentJob={currentJobId ? reports[currentJobId]?.job ?? null : null}
            openReport={openCurrentReport}
            recentJobs={recentJobs}
            openRecentReport={(jobId) => void openReport(jobId)}
            deleteRecentJob={(jobId, filename) => void removeJob(jobId, filename)}
            pastedText={pastedText}
            setPastedText={(value) => { setPastedText(value); setTextResult(null); }}
            textResult={textResult}
            convertPastedText={convertPastedText}
            copyTextResult={copyTextResult}
            clearText={() => { setPastedText(""); setTextResult(null); }}
            isTextSubmitting={isTextSubmitting}
            setNotice={setNotice}
          />
        ) : currentReport ? (
          <ReportView
            report={currentReport}
            onBack={() => setActiveTab("task")}
            onToggle={(id) => toggleChange(currentReport.job.job_id, id)}
            onSelect={(id) => selectChange(currentReport.job.job_id, id)}
            onFilter={(filter) => setReportFilter(currentReport.job.job_id, filter)}
            onAcceptAll={() => selectAll(currentReport.job.job_id)}
            onRestoreAll={() => restoreAll(currentReport.job.job_id)}
            onExport={() => void exportReport(currentReport.job.job_id)}
            onDelete={() => void removeJob(currentReport.job.job_id, currentReport.job.filename)}
          />
        ) : (
          <div className="empty-screen"><CircleAlert size={20} />报告已关闭或不存在。</div>
        )}
      </main>

      <footer className="app-footer">
        <span>LLM Watermark Remover · 受约束、可复核的文本处理</span>
        <div className="app-footer-links">
          <a className="app-footer-link" href="/api/licenses/third-party" target="_blank" rel="noopener noreferrer" aria-label="查看第三方开源许可证">
            <span>开源许可证</span>
            <span aria-hidden="true">↗</span>
          </a>
          <a
            className="app-footer-link"
            href="https://github.com/iStoryOfSpring/LLM-Watermark-Remover"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="打开 LLM Watermark Remover 的 GitHub 主页"
          >
            <Github size={14} aria-hidden="true" />
            <span>GitHub 主页</span>
            <span aria-hidden="true">↗</span>
          </a>
        </div>
      </footer>

      {(error || notice) && (
        <div className={`toast ${error ? "error" : "success"}`} role={error ? "alert" : "status"}>
          {error ? <CircleAlert size={16} /> : <CircleCheck size={16} />}
          <span>{error || notice}</span>
          <button aria-label="关闭提示" onClick={() => { setError(""); setNotice(""); }}><X size={14} /></button>
        </div>
      )}
    </div>
  );
}

interface TaskViewProps {
  file: File | null;
  fileInput: RefObject<HTMLInputElement>;
  dictionaryInput: RefObject<HTMLInputElement>;
  dictionaryNotice: string;
  termsText: string;
  setTermsText: (value: string) => void;
  handleDictionary: (file: File | null) => void;
  rewriteScope: RewriteScope;
  setRewriteScope: (value: RewriteScope) => void;
  strength: 1 | 2 | 3;
  setStrength: (value: 1 | 2 | 3) => void;
  layout: LayoutSensitivity;
  setLayout: (value: LayoutSensitivity) => void;
  preserveLayout: boolean;
  setPreserveLayout: (value: boolean) => void;
  isDragging: boolean;
  setIsDragging: (value: boolean) => void;
  onDrop: (event: DragEvent<HTMLDivElement>) => void;
  acceptFile: (file: File | null) => void;
  clearFile: () => void;
  startRewrite: () => void;
  isSubmitting: boolean;
  model: ModelStatus | null;
  currentJob: JobState | null;
  openReport?: () => void;
  recentJobs: RecentJob[];
  openRecentReport: (jobId: string) => void;
  deleteRecentJob: (jobId: string, filename?: string) => void;
  pastedText: string;
  setPastedText: (value: string) => void;
  textResult: { rewrittenText: string; result: RewriteResult } | null;
  convertPastedText: () => void;
  copyTextResult: () => void;
  clearText: () => void;
  isTextSubmitting: boolean;
  setNotice: (value: string) => void;
}

function TaskView(props: TaskViewProps) {
  const {
    file, fileInput, dictionaryInput, dictionaryNotice, termsText, setTermsText, handleDictionary,
    rewriteScope, setRewriteScope, strength, setStrength, layout, setLayout, preserveLayout,
    setPreserveLayout, isDragging, setIsDragging, onDrop, acceptFile, clearFile, startRewrite,
    isSubmitting, model, currentJob, openReport, recentJobs, openRecentReport, deleteRecentJob,
    pastedText, setPastedText, textResult, convertPastedText, copyTextResult, clearText, isTextSubmitting,
    setNotice,
  } = props;
  const running = currentJob?.state === "queued" || currentJob?.state === "running";

  return (
    <div className="task-page">
      <section className="hero-grid">
        <div className="hero-copy">
          <p className="kicker">LLM WATERMARK REMOVER / LOCAL FIRST</p>
          <h1>{PRODUCT_POSITIONING}</h1>
          <p className="lede">{PRODUCT_LOCAL_REWRITE_LINE}</p>
          <p className="hero-ethos">{PRODUCT_AUTHORSHIP_LINE}</p>
          <div className="hero-boundary"><ShieldCheck size={16} /><span>{PRODUCT_BOUNDARY}</span></div>
        </div>
      </section>

      <section className="workspace-grid" aria-label="处理工作台">
        <article className="intake-card">
          <div className="card-heading"><div><span className="section-step">01</span><div><p className="card-eyebrow">DOCUMENT INPUT</p><h2>选择要处理的文档</h2></div></div><span className="format-badge">TXT / DOCX</span></div>
          <p className="card-description">只处理 UTF-8 TXT 与 DOCX 正文普通段落。标题、表格、引用和其他非正文区域默认保护。</p>
          <div className="file-control">
            <input ref={fileInput} type="file" accept=".txt,.docx" hidden onChange={(event) => acceptFile(event.target.files?.[0] ?? null)} />
            <div
              className={`file-drop ${isDragging ? "dragging" : ""} ${file ? "picked" : ""}`}
              onDragEnter={(event) => { event.preventDefault(); setIsDragging(true); }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={() => setIsDragging(false)}
              onDrop={onDrop}
              onClick={() => fileInput.current?.click()}
              onKeyDown={(event: KeyboardEvent<HTMLDivElement>) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); fileInput.current?.click(); } }}
              role="button"
              tabIndex={0}
              aria-label="选择 TXT 或 DOCX 文档"
            >
              {file ? <><span className="file-control-icon"><FileText size={19} /></span><span className="file-control-copy"><strong>{file.name}</strong><small>{fileSize(file.size)} · {running ? "正在处理" : "待处理"}</small></span><button type="button" className="icon-button" aria-label="移除文件" onClick={(event) => { event.stopPropagation(); clearFile(); }}><X size={15} /></button></> : <><span className="file-control-icon"><UploadCloud size={21} /></span><span className="file-control-copy"><strong>拖入文档，或点击选择</strong><small>TXT / DOCX · 仅在本机处理</small></span><ChevronRight size={17} /></>}
            </div>
          </div>

          <div className="boundary-heading"><div><span className="section-step">02</span><div><p className="card-eyebrow">PROCESS BOUNDARY</p><h2>设置处理边界</h2></div></div><SlidersHorizontal size={18} /></div>
          <div className="boundary-grid">
            <div className="control-field scope-field"><label>处理范围</label><select value={rewriteScope} onChange={(event) => setRewriteScope(event.target.value as RewriteScope)}><option value="lexical">仅词 / 短语替换</option><option value="lexical_and_sentence">词语替换 + 有限句子改写</option></select></div>
            <div className="control-field"><label>处理强度</label><div className="segmented-control" role="group" aria-label="处理强度">{([1, 2, 3] as const).map((value) => <button type="button" key={value} className={strength === value ? "selected" : ""} aria-pressed={strength === value} onClick={() => setStrength(value)}><span>{value === 1 ? "轻" : value === 2 ? "中" : "强"}</span><small>{value === 1 ? "1 / 1" : value === 2 ? "2 / 1" : "3 / 2"}</small></button>)}</div></div>
            <div className="control-field"><label>版式敏感度</label><select value={layout} onChange={(event) => setLayout(event.target.value as LayoutSensitivity)}><option value="STRICT">严格 · ±10%</option><option value="NORMAL">普通 · ±20%</option><option value="LOOSE">宽松 · ±30%</option></select></div>
            <label className="check-control"><input type="checkbox" checked={preserveLayout} onChange={(event) => setPreserveLayout(event.target.checked)} /><span className="fake-check"><Check size={12} /></span><span><strong>保留原版式</strong><small>OOXML 定点 Patch</small></span></label>
            <div className="terms-control"><label>无条件保护词</label><div className="terms-inline"><input value={termsText} onChange={(event) => setTermsText(event.target.value)} placeholder="DeepSeek、营业收入、随机森林" aria-label="无条件保护词" /><button type="button" className="import-button" onClick={() => dictionaryInput.current?.click()}><Import size={14} />导入词典</button><input ref={dictionaryInput} hidden type="file" accept=".txt,.csv" onChange={(event) => handleDictionary(event.target.files?.[0] ?? null)} /></div><small>{dictionaryNotice || `${splitTerms(termsText).length} 个自定义保护词 · 最高优先级`}</small></div>
          </div>

          <div className="intake-footer">
            <div className={`status-message ${model?.state === "unavailable" ? "danger" : ""}`}><span className="status-pip" /><span><strong>{model?.state === "unavailable" ? "本地模型不可用，任务会 Fail Closed" : model?.backend === "deterministic-local" ? "本地安全规则已就绪" : model?.state === "ready" ? "本地模型已就绪 · non-thinking" : "本地运行时正在准备"}</strong><small>{model?.state === "unavailable" ? model.reason : model?.backend === "deterministic-local" ? "保护规则、词典替换和审计均在本机执行" : "原文不会离开本机，所有提案先经过验证"}</small></span></div>
            <div className="workspace-actions"><button className="primary-button" onClick={startRewrite} disabled={!file || running || isSubmitting || model?.state === "unavailable"}><Sparkles size={16} />{running || isSubmitting ? "正在建立审计" : "生成去标记副本"}<ChevronRight size={16} /></button>{openReport && <button className="secondary-button report-button" onClick={openReport} disabled={running}><ScanSearch size={15} />查看处理报告</button>}</div>
          </div>
          {currentJob && <div className="current-job-status"><span>{currentJob.filename}</span><strong className={`state-${currentJob.state}`}>{statusText(currentJob.state)}</strong></div>}
        </article>

        <article className="quick-card" aria-labelledby="paste-title">
          <div className="card-heading"><div><div><p className="card-eyebrow">QUICK TEXT CHECK</p><h2 id="paste-title">或者，可以先处理一小段文本</h2></div></div><span className={`paste-count ${pastedText.length >= 2000 ? "limit" : ""}`}>{pastedText.length} / 2000 字</span></div>
          <p className="card-description">直接调用同一套保护、提案和验证流程。适合先验证一个词或短段落。</p>
          <div className="paste-grid">
            <div className="paste-panel"><label htmlFor="paste-input">原文</label><textarea id="paste-input" value={pastedText} maxLength={2000} onChange={(event) => setPastedText(event.target.value)} placeholder="例如：这份说明便于后续整理和引用。" spellCheck={false} /><small>词语替换默认开启；不会拆句、合句或跨段落修改。</small></div>
            <div className="paste-panel"><div className="paste-result-heading"><label htmlFor="paste-result">处理结果</label>{textResult && <button type="button" className="text-button" onClick={copyTextResult}>复制结果</button>}</div><textarea id="paste-result" value={textResult?.rewrittenText ?? ""} readOnly placeholder="处理结果会显示在这里。" aria-label="处理结果" /><small>{textResult ? `通过 ${textResult.result.audit.changed} 处 · 拒绝 ${textResult.result.audit.rejected} 处 · 保护 ${textResult.result.audit.protected} 处` : "本地只提交规则候选，验证器决定是否落地。"}</small></div>
          </div>
          {textResult && textResult.result.audit.changes.length > 0 && <div className="paste-audit" aria-label="文本处理审计"><span>审计</span>{textResult.result.audit.changes.slice(0, 5).map((change) => <button type="button" key={change.change_id} onClick={() => setNotice(`${change.original} → ${change.replacement} · ${change.reason}`)}><del>{change.original}</del><ins>{change.replacement}</ins></button>)}{textResult.result.audit.changes.length > 5 && <small>还有 {textResult.result.audit.changes.length - 5} 处</small>}</div>}
          <div className="paste-actions"><button type="button" className="secondary-button" onClick={clearText} disabled={!pastedText && !textResult}>清空</button><button type="button" className="primary-button" onClick={convertPastedText} disabled={!pastedText.trim() || isTextSubmitting || model?.state === "unavailable"}><Sparkles size={15} />{isTextSubmitting ? "正在处理" : "处理这段文本"}<ChevronRight size={15} /></button></div>
          <p className="disclaimer">{PRODUCT_DISCLAIMER}</p>
        </article>
      </section>

      <section className="workflow-strip" aria-label="处理流程">
        <div className="workflow-step"><span>01</span><div><strong>保护</strong><p>Regex、NER、内置词典和用户词典先锁定不能改的区域。</p></div></div>
        <div className="workflow-step"><span>02</span><div><strong>提案</strong><p>本地 Qwen 只返回受限词语替换，不直接改写原文件。</p></div></div>
        <div className="workflow-step"><span>03</span><div><strong>验证</strong><p>数字、实体、逻辑、语义和版式不确定就保留原文。</p></div></div>
      </section>

      <RecentJobs jobs={recentJobs} onOpen={openRecentReport} onDelete={deleteRecentJob} />
    </div>
  );
}

function RecentJobs({ jobs, onOpen, onDelete }: { jobs: RecentJob[]; onOpen: (jobId: string) => void; onDelete: (jobId: string, filename?: string) => void }) {
  return (
    <section className="recent-section">
      <div className="section-heading"><div><p className="kicker">CLOUD HISTORY</p><h2>最近任务</h2></div><span>D1 任务记录</span></div>
      {jobs.length === 0 ? <div className="history-empty"><History size={17} /><span>完成一次任务后，报告会出现在这里。</span></div> : <div className="history-list">{jobs.slice(0, 8).map((job) => <div className="history-row" key={job.job_id}><button className="history-open" onClick={() => onOpen(job.job_id)} aria-label={`打开 ${job.filename}`}><span className="history-icon"><FileText size={16} /></span><span className="history-file"><strong>{job.filename}</strong><small>{job.format?.toUpperCase() ?? "DOCUMENT"} · {job.updated_at ? new Date(job.updated_at).toLocaleString() : "本地任务"}</small></span><span className="history-count"><strong>{job.changed}</strong><small>通过</small></span><span className="history-count"><strong>{job.protected}</strong><small>保护</small></span></button><span className={`history-state state-${job.state}`}>{job.state === "completed" ? "已完成" : job.state === "failed" ? "失败" : statusText(job.state as JobState["state"])}</span><button className="history-delete" onClick={() => onDelete(job.job_id, job.filename)} aria-label={`删除 ${job.filename}`} title="删除本地任务"><Trash2 size={15} /></button><ChevronRight className="history-chevron" size={15} aria-hidden="true" /></div>)}</div>}
    </section>
  );
}

function ReportView({ report, onBack, onToggle, onSelect, onFilter, onAcceptAll, onRestoreAll, onExport, onDelete }: { report: ReportState; onBack: () => void; onToggle: (id: string) => void; onSelect: (id: string | null) => void; onFilter: (filter: ReviewFilter) => void; onAcceptAll: () => void; onRestoreAll: () => void; onExport: () => void; onDelete: () => void }) {
  const audit = report.job.result?.audit ?? null;
  const acceptedCount = report.acceptedChangeIds.length;
  const changes = audit?.changes ?? [];
  const filteredChanges = changes.filter((change) => report.filter === "all" || (report.filter === "accepted" ? report.acceptedChangeIds.includes(change.change_id) : !report.acceptedChangeIds.includes(change.change_id)));
  const selected = changes.find((change) => change.change_id === report.selectedChangeId) ?? null;

  if (!audit || report.job.state !== "completed") {
    return <section className="report-shell"><div className="report-toolbar"><button className="back-button" onClick={onBack}>← 返回新处理</button><span className="report-toolbar-title">{report.job.filename}</span><button className="danger-button compact" onClick={onDelete}><Trash2 size={14} />删除本地任务</button></div><div className="report-loading"><div className="loading-ring" /><h2>{report.job.state === "failed" ? "任务未完成" : "正在准备处理报告"}</h2><p>{report.job.error ?? "保护规则、模型提案和验证器正在按顺序处理文档。"}</p></div></section>;
  }

  return (
    <section className="report-shell">
      <div className="report-toolbar">
        <div className="report-title-group"><button className="back-button" onClick={onBack}>← 新处理</button><span className="toolbar-divider" /><div><span className="report-product">{PRODUCT_NAME} · AUDIT REPORT</span><strong>{report.job.filename}</strong><small>{audit.format.toUpperCase()} · {audit.original_sha256.slice(0, 12)}…</small></div></div>
        <div className="report-actions"><div className="report-metric"><strong>{acceptedCount}</strong><span>已接受</span></div><div className="report-metric protected"><strong>{audit.protected}</strong><span>已保护</span></div><div className="report-metric muted"><strong>{audit.rejected}</strong><span>已拒绝</span></div><select value={report.filter} onChange={(event) => onFilter(event.target.value as ReviewFilter)} aria-label="审计筛选"><option value="all">全部修改</option><option value="accepted">已接受</option><option value="restored">已恢复</option></select><button className="secondary-button" onClick={onRestoreAll} disabled={acceptedCount === 0}><RotateCcw size={15} />全部恢复</button><button className="secondary-button" onClick={onAcceptAll} disabled={acceptedCount === changes.length}><Check size={15} />全部接受</button><button className="danger-button compact" onClick={onDelete}><Trash2 size={14} />删除本地任务</button><button className="primary-button compact" onClick={onExport}><ArrowDownToLine size={15} />导出 {audit.format.toUpperCase()}</button></div>
      </div>

      <div className="report-meta-line"><span className="report-state"><span className="state-dot" />{auditLabel(audit)}</span><span>正文普通段落 · 其余 DOCX 区域默认保护</span><span>{PRODUCT_BOUNDARY}</span><span className="report-legend"><i className="legend-delete" />原文 <i className="legend-insert" />提案</span></div>

      {report.preview && <DocumentReader paragraphs={report.preview.paragraphs} selectedChangeId={report.selectedChangeId} onSelect={onSelect} />}
      {!report.preview && <div className="report-loading inline"><div className="loading-ring" /><span>正在准备正文预览…</span></div>}

      {changes.length === 0 ? <div className="no-change-report"><ShieldCheck size={22} /><div><strong>原文已安全保留</strong><p>没有提案通过全部验证门。{audit.warnings.length > 0 ? "处理说明已写入审计。" : ""}</p></div></div> : <section className="change-ledger"><div className="ledger-heading"><div><p className="kicker">AUDIT LEDGER</p><h2>变更审计</h2></div><span>{filteredChanges.length} / {changes.length} 条</span></div><div className="ledger-list">{filteredChanges.map((change) => <AuditRow key={change.change_id} change={change} selected={report.acceptedChangeIds.includes(change.change_id)} focused={change.change_id === report.selectedChangeId} onSelect={() => onSelect(change.change_id)} onToggle={() => onToggle(change.change_id)} />)}</div></section>}

      {selected && <AuditDetail change={selected} selected={report.acceptedChangeIds.includes(selected.change_id)} onClose={() => onSelect(null)} onToggle={() => onToggle(selected.change_id)} />}

      {audit.warnings.length > 0 && <details className="report-warnings"><summary><CircleAlert size={14} />处理说明（{audit.warnings.length}）</summary>{audit.warnings.map((warning) => <p key={warning}>{warning}</p>)}</details>}
    </section>
  );
}

function DocumentReader({ paragraphs, selectedChangeId, onSelect }: { paragraphs: PreviewParagraph[]; selectedChangeId: string | null; onSelect: (id: string) => void }) {
  return <article className="document-reader">{paragraphs.map((paragraph, index) => <p className="document-paragraph" key={paragraph.unit_id}><span className="paragraph-index">{String(index + 1).padStart(2, "0")}</span><span className="paragraph-text">{renderParagraph(paragraph, selectedChangeId, onSelect)}</span></p>)}</article>;
}

function renderParagraph(paragraph: PreviewParagraph, selectedChangeId: string | null, onSelect: (id: string) => void) {
  const changes = paragraph.changes.filter((change) => change.accepted).sort((a, b) => a.start - b.start);
  if (changes.length === 0) return paragraph.text;
  const chunks: JSX.Element[] = [];
  let cursor = 0;
  changes.forEach((change) => {
    if (change.start < cursor || change.end > paragraph.text.length) return;
    if (change.start > cursor) chunks.push(<span key={`${change.change_id}-before`}>{paragraph.text.slice(cursor, change.start)}</span>);
    const focused = change.change_id === selectedChangeId;
    chunks.push(<span className={`inline-diff ${focused ? "focused" : ""}`} key={change.change_id} onClick={() => onSelect(change.change_id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onSelect(change.change_id); }} role="button" tabIndex={0} title="点击查看审计详情"><del>{change.original}</del><ins>{change.replacement}</ins></span>);
    cursor = change.end;
  });
  if (cursor < paragraph.text.length) chunks.push(<span key="tail">{paragraph.text.slice(cursor)}</span>);
  return chunks;
}

function AuditRow({ change, selected, focused, onSelect, onToggle }: { change: AuditChange; selected: boolean; focused: boolean; onSelect: () => void; onToggle: () => void }) {
  return <div className={`audit-row ${selected ? "accepted" : "restored"} ${focused ? "focused" : ""}`}><button className="audit-row-main" onClick={onSelect}><span className="audit-row-swap"><del>{change.original}</del><ChevronRight size={14} /><ins>{change.replacement}</ins></span><span className="audit-row-reason">{change.kind === "sentence" ? "有限句子提案" : change.reason}</span><span className="audit-row-score">semantic {formatScore(change.similarity)} · {selected ? "PASS" : "已恢复"}</span></button><button className={`audit-row-toggle ${selected ? "on" : ""}`} onClick={onToggle} aria-label={selected ? `恢复 ${change.original}` : `接受 ${change.replacement}`} aria-pressed={selected}>{selected ? <Check size={14} /> : <RotateCcw size={14} />}</button></div>;
}

function AuditDetail({ change, selected, onClose, onToggle }: { change: AuditChange; selected: boolean; onClose: () => void; onToggle: () => void }) {
  return <section className="audit-detail" aria-live="polite"><div className="detail-heading"><div><p className="kicker">CHANGE DETAIL</p><h2>审计详情</h2></div><button className="icon-button" onClick={onClose} aria-label="关闭审计详情"><X size={17} /></button></div><div className="detail-swap"><div><span>原文</span><del>{change.original}</del></div><ChevronRight size={18} /><div><span>改写后</span><ins>{change.replacement}</ins></div></div><div className="detail-grid"><div><span>状态</span><strong className={selected ? "text-green" : "text-muted"}>{selected ? "PASS · 已接受" : "KEEP · 已恢复"}</strong></div><div><span>类型</span><strong>{change.kind === "sentence" ? "有限句子改写" : "词 / 短语替换"}</strong></div><div><span>原因</span><strong>{change.reason}</strong></div><div><span>语义相似度</span><strong>{formatScore(change.similarity)}</strong></div></div><details className="trace-details"><summary>查看 validator trace</summary><div>{change.validation_trace.map((item) => <span key={item}>{item}</span>)}</div></details><button className={`detail-action ${selected ? "restore" : "accept"}`} onClick={onToggle}>{selected ? <><RotateCcw size={15} />恢复原文</> : <><Check size={15} />接受修改</>}</button></section>;
}

export default App;
