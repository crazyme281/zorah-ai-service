from datetime import datetime, timezone

from access.db import select, insert, patch


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(user_id: str, original_file_name: str, upload_path: str) -> dict:
    return insert(
        "code_fixer_jobs",
        {
            "user_id": user_id,
            "original_file_name": original_file_name,
            "upload_path": upload_path,
            "status": "queued",
        },
    )


def update_job(job_id: str, **fields) -> dict | None:
    fields["updated_at"] = _now()
    rows = patch("code_fixer_jobs", {"id": f"eq.{job_id}"}, fields)
    return rows[0] if rows else None


def get_job(job_id: str, user_id: str) -> dict | None:
    """Scoped to user_id on every read — a user asking for a job_id that
    isn't theirs gets the same "not found" as one that doesn't exist,
    rather than a 403 that would confirm the ID is real."""
    rows = select(
        "code_fixer_jobs",
        {"id": f"eq.{job_id}", "user_id": f"eq.{user_id}", "select": "*", "limit": "1"},
    )
    return rows[0] if rows else None


def list_jobs(user_id: str, limit: int = 20) -> list[dict]:
    return select(
        "code_fixer_jobs",
        {"user_id": f"eq.{user_id}", "select": "*", "order": "created_at.desc", "limit": str(limit)},
    )