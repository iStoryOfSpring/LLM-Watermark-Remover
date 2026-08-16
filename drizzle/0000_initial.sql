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
);

CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs(updated_at DESC);
