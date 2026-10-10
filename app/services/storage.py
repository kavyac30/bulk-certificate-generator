"""Where generated files live on disk.

Only *relative* paths are stored in the database, so the storage directory can
be moved (or swapped for S3 later) without rewriting rows.
"""
from pathlib import Path

from app.config import settings


def relative_path(job_id: str, certificate_id: str) -> str:
    return f"{job_id}/{certificate_id}.pdf"


def absolute_path(relative: str) -> Path:
    base = settings.storage_dir.resolve()
    path = (base / relative).resolve()
    if base not in path.parents:  # defence in depth against path traversal
        raise ValueError("Invalid storage path")
    return path
