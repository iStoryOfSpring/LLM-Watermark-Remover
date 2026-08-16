from __future__ import annotations

import sqlite3
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JobLogStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    state TEXT NOT NULL,
                    original_sha256 TEXT,
                    format TEXT,
                    changed INTEGER NOT NULL DEFAULT 0,
                    kept INTEGER NOT NULL DEFAULT 0,
                    rejected INTEGER NOT NULL DEFAULT 0,
                    protected INTEGER NOT NULL DEFAULT 0,
                    output_file TEXT,
                    audit_file TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "accepted_change_ids" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN accepted_change_ids TEXT NOT NULL DEFAULT '[]'"
                )

    def upsert(
        self,
        job_id: str,
        filename: str,
        state: str,
        *,
        result: Any | None = None,
        error: str | None = None,
    ) -> None:
        audit = result.audit if result is not None else None
        accepted_change_ids = (
            [patch.change_id for patch in audit.changes if patch.accepted]
            if audit is not None
            else []
        )
        values = (
            job_id,
            filename,
            state,
            audit.original_sha256 if audit else None,
            audit.format.value if audit else None,
            audit.changed if audit else 0,
            audit.kept if audit else 0,
            audit.rejected if audit else 0,
            audit.protected if audit else 0,
            result.output_file if result else None,
            result.audit_file if result else None,
            error,
            json.dumps(accepted_change_ids, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, filename, state, original_sha256, format,
                    changed, kept, rejected, protected, output_file,
                    audit_file, error, accepted_change_ids, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    filename=excluded.filename,
                    state=excluded.state,
                    original_sha256=excluded.original_sha256,
                    format=excluded.format,
                    changed=excluded.changed,
                    kept=excluded.kept,
                    rejected=excluded.rejected,
                    protected=excluded.protected,
                    output_file=excluded.output_file,
                    audit_file=excluded.audit_file,
                    error=excluded.error,
                    accepted_change_ids=excluded.accepted_change_ids,
                    updated_at=excluded.updated_at
                """,
                values,
            )

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def set_review(self, job_id: str, accepted_change_ids: list[str]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET accepted_change_ids = ?, updated_at = ? WHERE job_id = ?",
                (
                    json.dumps(accepted_change_ids, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                    job_id,
                ),
            )

    def delete(self, job_id: str) -> bool:
        """Delete one local history record and return whether it existed."""
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            return cursor.rowcount > 0
