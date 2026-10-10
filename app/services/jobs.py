"""Business logic for creating jobs and reporting on them."""
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Certificate, CertificateStatus, Job, JobStatus, utcnow
from app.schemas import JobCreate, Progress, RecipientIn


def _format_validation_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "recipient"
        msg = str(err["msg"]).removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}")
    return "Validation failed - " + "; ".join(parts)


def _safe_str(value: Any, limit: int) -> str | None:
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def create_job(db: Session, payload: JobCreate) -> Job:
    """Validate every recipient and persist the job + one Certificate row per entry.

    * valid recipients      -> status "pending" (will be generated)
    * invalid recipients    -> status "failed" immediately, with a readable error
    * duplicate e-mails     -> status "failed" (first occurrence wins)

    Everything is written in a single transaction.
    """
    job = Job(
        course_name=payload.course_name,
        issued_by=payload.issued_by,
        issue_date=payload.issue_date or datetime.now(timezone.utc).date(),
        total=len(payload.recipients),
        status=JobStatus.PENDING,
    )

    seen_emails: dict[str, int] = {}
    certificates: list[Certificate] = []

    for position, raw in enumerate(payload.recipients):
        cert = Certificate(job=job, position=position)
        try:
            recipient = RecipientIn.model_validate(raw)
        except ValidationError as exc:
            raw_dict = raw if isinstance(raw, dict) else {}
            cert.recipient_name = _safe_str(raw_dict.get("name"), 255)
            cert.recipient_email = _safe_str(raw_dict.get("email"), 320)
            cert.status = CertificateStatus.FAILED
            cert.error_message = _format_validation_error(exc)
            cert.completed_at = utcnow()
        else:
            cert.recipient_name = recipient.name
            cert.recipient_email = recipient.email
            if recipient.email in seen_emails:
                cert.status = CertificateStatus.FAILED
                cert.error_message = (
                    f"Duplicate recipient email (already used at position {seen_emails[recipient.email]})"
                )
                cert.completed_at = utcnow()
            else:
                seen_emails[recipient.email] = position
                cert.status = CertificateStatus.PENDING
        certificates.append(cert)

    # Nothing valid -> there is no work to do, finish immediately.
    if not any(c.status == CertificateStatus.PENDING for c in certificates):
        job.status = JobStatus.FAILED
        job.completed_at = utcnow()

    db.add(job)
    db.add_all(certificates)
    db.commit()
    return job


def get_progress(db: Session, job: Job) -> Progress:
    """Counts are derived from the certificate rows (single GROUP BY query), so they
    can never drift out of sync with the real per-certificate results."""
    rows = db.execute(
        select(Certificate.status, func.count())
        .where(Certificate.job_id == job.id)
        .group_by(Certificate.status)
    ).all()
    counts = {status: n for status, n in rows}
    succeeded = counts.get(CertificateStatus.SUCCESS, 0)
    failed = counts.get(CertificateStatus.FAILED, 0)
    pending = counts.get(CertificateStatus.PENDING, 0)
    done = succeeded + failed
    percent = round(done / job.total * 100, 1) if job.total else 100.0
    return Progress(
        total=job.total, succeeded=succeeded, failed=failed, pending=pending, percent_complete=percent
    )
