"""Database models.

Job (1) ──< Certificate (N)

One Certificate row exists per recipient in the request, *including* recipients
that failed validation. That way the client can always see exactly what happened
to every entry it submitted.
"""
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite drops tzinfo anyway; everything is UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id() -> str:
    return str(uuid.uuid4())


class JobStatus:
    PENDING = "pending"                          # accepted, not started
    PROCESSING = "processing"                    # worker is generating
    COMPLETED = "completed"                      # every certificate succeeded
    COMPLETED_WITH_ERRORS = "completed_with_errors"  # some succeeded, some failed
    FAILED = "failed"                            # nothing could be generated

    FINISHED = (COMPLETED, COMPLETED_WITH_ERRORS, FAILED)
    UNFINISHED = (PENDING, PROCESSING)


class CertificateStatus:
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.PENDING, index=True)

    # Certificate-level info shared by every recipient in the job.
    course_name: Mapped[str] = mapped_column(String(200))
    issued_by: Mapped[str] = mapped_column(String(200))
    issue_date: Mapped[date] = mapped_column(Date)

    total: Mapped[int] = mapped_column(Integer)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # job-level crash only

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    certificates: Mapped[list["Certificate"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="Certificate.position"
    )


class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = (
        UniqueConstraint("job_id", "position", name="uq_certificate_job_position"),
        Index("ix_certificates_job_status", "job_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)

    # Index of this recipient in the request's "recipients" array (0-based),
    # so clients can map results/errors back to their own data.
    position: Mapped[int] = mapped_column(Integer)

    # Nullable because an invalid entry may not even have a usable name / email.
    recipient_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recipient_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    status: Mapped[str] = mapped_column(String(16), default=CertificateStatus.PENDING)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # relative to storage_dir

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    job: Mapped[Job] = relationship(back_populates="certificates")
