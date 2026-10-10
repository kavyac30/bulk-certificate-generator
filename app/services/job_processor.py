"""Generates all pending certificates of a job.

Key properties
--------------
* Failure isolation: each certificate is rendered inside its own try/except and
  committed on its own. One bad certificate never stops the others.
* Live progress: because we commit per certificate, GET /jobs/{id} shows real
  progress while the job is running.
* Idempotent / resumable: only certificates still "pending" are processed, so
  re-running a job (e.g. after a server restart) never regenerates finished work.
"""
import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Certificate, CertificateStatus, Job, JobStatus, utcnow
from app.services import storage
from app.services.certificate_renderer import CertificateData, CertificateRenderError, render_certificate
from app.services.jobs import get_progress

logger = logging.getLogger(__name__)


def process_job(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None or job.status in JobStatus.FINISHED:
            return

        try:
            job.status = JobStatus.PROCESSING
            job.started_at = job.started_at or utcnow()
            db.commit()

            pending_ids = db.scalars(
                select(Certificate.id)
                .where(Certificate.job_id == job_id, Certificate.status == CertificateStatus.PENDING)
                .order_by(Certificate.position)
            ).all()

            for cert_id in pending_ids:
                cert = db.get(Certificate, cert_id)
                _generate_one(job, cert)
                db.commit()

            _finalize(db, job)
        except Exception as exc:  # unexpected, job-level problem (DB down, disk full, ...)
            logger.exception("Job %s crashed", job_id)
            db.rollback()
            job = db.get(Job, job_id)
            job.status = JobStatus.FAILED
            job.error = f"Unexpected error while processing job: {exc}"
            job.completed_at = utcnow()
            db.commit()


def _generate_one(job: Job, cert: Certificate) -> None:
    """Render one certificate; record success or failure on the row (never raises)."""
    try:
        data = CertificateData(
            certificate_id=cert.id,
            recipient_name=cert.recipient_name,
            course_name=job.course_name,
            issued_by=job.issued_by,
            issue_date=job.issue_date,
        )
        relative = storage.relative_path(job.id, cert.id)
        render_certificate(data, storage.absolute_path(relative))
        cert.status = CertificateStatus.SUCCESS
        cert.file_path = relative
        cert.error_message = None
    except CertificateRenderError as exc:
        cert.status = CertificateStatus.FAILED
        cert.error_message = f"Generation failed: {exc}"
    except Exception as exc:  # any other per-certificate bug must not kill the job
        logger.exception("Certificate %s (job %s) failed", cert.id, job.id)
        cert.status = CertificateStatus.FAILED
        cert.error_message = f"Generation failed: unexpected error ({type(exc).__name__}: {exc})"
    cert.completed_at = utcnow()


def _finalize(db, job: Job) -> None:
    progress = get_progress(db, job)
    if progress.succeeded == progress.total:
        job.status = JobStatus.COMPLETED
    elif progress.succeeded == 0:
        job.status = JobStatus.FAILED
    else:
        job.status = JobStatus.COMPLETED_WITH_ERRORS
    job.completed_at = utcnow()
    db.commit()
