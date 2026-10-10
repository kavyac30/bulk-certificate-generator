"""Decides HOW a job gets processed.

background (default): hand the job to a small thread pool and return immediately.
inline:               process synchronously (handy for tests and tiny deployments).

To scale beyond one process, replace `dispatch()` with "enqueue to Celery / RQ /
SQS" - nothing else in the app needs to change, because `process_job(job_id)`
only needs a job id and the database.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import Job, JobStatus
from app.services.job_processor import process_job

logger = logging.getLogger(__name__)
_executor: Optional[ThreadPoolExecutor] = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=settings.worker_threads, thread_name_prefix="cert-worker"
        )
    return _executor


def dispatch(job_id: str) -> None:
    if settings.processing_mode == "inline":
        process_job(job_id)
    else:
        _get_executor().submit(process_job, job_id)


def recover_unfinished_jobs() -> int:
    """On startup, re-queue jobs that were interrupted by a restart/crash.
    Safe because process_job only touches certificates that are still pending."""
    with SessionLocal() as db:
        job_ids = db.scalars(select(Job.id).where(Job.status.in_(JobStatus.UNFINISHED))).all()
    for job_id in job_ids:
        dispatch(job_id)
    if job_ids:
        logger.info("Re-queued %d unfinished job(s)", len(job_ids))
    return len(job_ids)


def shutdown_executor() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None
