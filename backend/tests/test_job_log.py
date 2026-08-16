from pathlib import Path

from backend.app.service.job_log import JobLogStore


def test_job_log_delete_removes_only_requested_record(tmp_path: Path) -> None:
    store = JobLogStore(tmp_path / "jobs.sqlite3")
    store.upsert("job-a", "a.txt", "completed")
    store.upsert("job-b", "b.txt", "completed")

    assert store.delete("job-a") is True
    assert store.get("job-a") is None
    assert store.get("job-b") is not None
    assert store.delete("job-a") is False
