"""Pydantic schemas: request validation + API responses."""
import re
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from app.config import settings

# Deliberately simple: one "@", a dotted domain, a TLD of 2+ letters.
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class RecipientIn(BaseModel):
    """One recipient. Validated *per item* by the service layer (not by FastAPI),
    so a single bad recipient doesn't reject the whole request."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: StrictStr = Field(min_length=1, max_length=70)
    email: StrictStr = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        if not EMAIL_RE.match(value):
            raise ValueError("Invalid email address")
        return value.lower()


class JobCreate(BaseModel):
    """Request body for POST /api/v1/jobs.

    The shared certificate info and the *shape* of the request are validated
    strictly (-> 422). The individual recipients are only checked to be a
    non-empty list here; each one is validated separately later.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "course_name": "Advanced Python Programming",
                "issued_by": "Acme Academy",
                "issue_date": "2026-10-10",
                "recipients": [
                    {"name": "Asha Verma", "email": "asha@example.com"},
                    {"name": "Ravi Kumar", "email": "ravi@example.com"},
                ],
            }
        },
    )

    course_name: str = Field(min_length=1, max_length=150)
    issued_by: str = Field(min_length=1, max_length=80)
    issue_date: Optional[date] = Field(default=None, description="Defaults to today (UTC)")
    recipients: list[Any] = Field(min_length=1, max_length=settings.max_recipients_per_job)


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #
class Progress(BaseModel):
    total: int
    succeeded: int
    failed: int
    pending: int
    percent_complete: float


class JobLinks(BaseModel):
    self: str
    certificates: str
    download_all: str


class JobOut(BaseModel):
    id: str
    status: str
    course_name: str
    issued_by: str
    issue_date: date
    progress: Progress
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    links: JobLinks


class JobList(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[JobOut]


class CertificateOut(BaseModel):
    id: str
    position: int
    recipient_name: Optional[str]
    recipient_email: Optional[str]
    status: str
    error_message: Optional[str] = None
    download_url: Optional[str] = None
    completed_at: Optional[datetime] = None


class CertificateList(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CertificateOut]
