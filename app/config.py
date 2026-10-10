"""Application settings, read from environment variables once at import time."""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    # Any SQLAlchemy URL works (e.g. postgresql+psycopg://user:pw@host/db).
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./certgen.db")
    )
    # Where generated PDFs are written: <storage_dir>/<job_id>/<certificate_id>.pdf
    storage_dir: Path = field(
        default_factory=lambda: Path(os.getenv("STORAGE_DIR", "./storage/certificates")).resolve()
    )
    # "background": POST returns immediately, a worker thread generates the PDFs.
    # "inline":     POST generates everything before responding (used by the tests).
    processing_mode: str = field(
        default_factory=lambda: os.getenv("PROCESSING_MODE", "background")
    )
    worker_threads: int = field(default_factory=lambda: int(os.getenv("WORKER_THREADS", "2")))
    # Upper bound on recipients in a single request (protects the API from huge bodies).
    max_recipients_per_job: int = field(
        default_factory=lambda: int(os.getenv("MAX_RECIPIENTS_PER_JOB", "5000"))
    )


settings = Settings()
