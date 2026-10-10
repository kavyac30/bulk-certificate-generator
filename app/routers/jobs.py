"""HTTP API for certificate jobs."""
import csv
import io
import os
import re
import tempfile
import unicodedata
import zipfile
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.database import get_db
from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas import (
    CertificateList,
    CertificateOut,
    JobCreate,
    JobLinks,
    JobList,
    JobOut,
)
from app.services import jobs as jobs_service
from app.services import storage
from app.services.dispatcher import dispatch

router = APIRouter(prefix="/api/v1/jobs", tags=["certificate jobs"])

BASE = "/api/v1/jobs"


# ------------------------------ helpers ------------------------------------ #
def _get_job_or_404(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _job_out(db: Session, job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        status=job.status,
        course_name=job.course_name,
        issued_by=job.issued_by,
        issue_date=job.issue_date,
        progress=jobs_service.get_progress(db, job),
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        links=JobLinks(
            self=f"{BASE}/{job.id}",
            certificates=f"{BASE}/{job.id}/certificates",
            download_all=f"{BASE}/{job.id}/download",
        ),
    )


def _cert_out(cert: Certificate) -> CertificateOut:
    ready = cert.status == CertificateStatus.SUCCESS
    return CertificateOut(
        id=cert.id,
        position=cert.position,
        recipient_name=cert.recipient_name,
        recipient_email=cert.recipient_email,
        status=cert.status,
        error_message=cert.error_message,
        download_url=f"{BASE}/{cert.job_id}/certificates/{cert.id}/download" if ready else None,
        completed_at=cert.completed_at,
    )


def _slug(text: Optional[str]) -> str:
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", ascii_text).strip("_")[:40] or "recipient"


# ------------------------------ endpoints ---------------------------------- #
@router.post("", response_model=JobOut, status_code=202, summary="Submit a bulk generation request")
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    """Accepts the whole recipient list in ONE request. Responds `202 Accepted`
    with a job id; poll `GET /jobs/{id}` for progress."""
    job = jobs_service.create_job(db, payload)
    if job.status == JobStatus.PENDING:  # skip if every recipient was invalid
        dispatch(job.id)
        db.refresh(job)
    return _job_out(db, job)


@router.get("", response_model=JobList, summary="List jobs (newest first)")
def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="Filter by job status"),
    db: Session = Depends(get_db),
):
    query = select(Job)
    count_query = select(func.count()).select_from(Job)
    if status:
        query = query.where(Job.status == status)
        count_query = count_query.where(Job.status == status)
    rows = db.scalars(query.order_by(Job.created_at.desc()).limit(limit).offset(offset)).all()
    return JobList(
        total=db.scalar(count_query), limit=limit, offset=offset, items=[_job_out(db, j) for j in rows]
    )


@router.get("/{job_id}", response_model=JobOut, summary="Job status and progress")
def get_job(job_id: str, db: Session = Depends(get_db)):
    return _job_out(db, _get_job_or_404(db, job_id))


@router.get(
    "/{job_id}/certificates",
    response_model=CertificateList,
    summary="Per-recipient results (successes and failures)",
)
def list_certificates(
    job_id: str,
    status: Optional[str] = Query(None, pattern="^(pending|success|failed)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    _get_job_or_404(db, job_id)
    where = [Certificate.job_id == job_id]
    if status:
        where.append(Certificate.status == status)
    total = db.scalar(select(func.count()).select_from(Certificate).where(*where))
    rows = db.scalars(
        select(Certificate).where(*where).order_by(Certificate.position).limit(limit).offset(offset)
    ).all()
    return CertificateList(total=total, limit=limit, offset=offset, items=[_cert_out(c) for c in rows])


@router.get("/{job_id}/certificates/{certificate_id}/download", summary="Download one certificate (PDF)")
def download_certificate(job_id: str, certificate_id: str, db: Session = Depends(get_db)):
    _get_job_or_404(db, job_id)
    cert = db.get(Certificate, certificate_id)
    if cert is None or cert.job_id != job_id:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if cert.status != CertificateStatus.SUCCESS:
        detail = "Certificate is not ready yet" if cert.status == CertificateStatus.PENDING else (
            f"Certificate was not generated: {cert.error_message}"
        )
        raise HTTPException(status_code=409, detail=detail)
    path = storage.absolute_path(cert.file_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="Certificate file is missing from storage")
    return FileResponse(
        path, media_type="application/pdf", filename=f"certificate_{cert.position:05d}_{_slug(cert.recipient_name)}.pdf"
    )


@router.get("/{job_id}/download", summary="Download all generated certificates as a ZIP")
def download_all(job_id: str, db: Session = Depends(get_db)):
    """ZIP contains every successful PDF plus `manifest.csv` listing ALL recipients
    (including failed ones and the reason). Only available once the job has finished."""
    job = _get_job_or_404(db, job_id)
    if job.status in JobStatus.UNFINISHED:
        raise HTTPException(status_code=409, detail=f"Job is still {job.status}; try again when it has finished")

    certs = db.scalars(
        select(Certificate).where(Certificate.job_id == job_id).order_by(Certificate.position)
    ).all()
    if not any(c.status == CertificateStatus.SUCCESS for c in certs):
        raise HTTPException(status_code=404, detail="No certificates were generated for this job")

    manifest = io.StringIO()
    writer = csv.writer(manifest)
    writer.writerow(["position", "name", "email", "status", "filename", "error"])

    tmp = tempfile.NamedTemporaryFile(prefix="certs_", suffix=".zip", delete=False)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for c in certs:
                filename, error = "", c.error_message or ""
                if c.status == CertificateStatus.SUCCESS:
                    path = storage.absolute_path(c.file_path)
                    if path.exists():
                        filename = f"{c.position:05d}_{_slug(c.recipient_name)}.pdf"
                        zf.write(path, filename)
                    else:
                        error = "File missing from storage"
                writer.writerow([c.position, c.recipient_name or "", c.recipient_email or "", c.status, filename, error])
            zf.writestr("manifest.csv", manifest.getvalue())
        tmp.close()
    except Exception:
        tmp.close()
        os.remove(tmp.name)
        raise

    return FileResponse(
        tmp.name,
        media_type="application/zip",
        filename=f"certificates_{job_id}.zip",
        background=BackgroundTask(os.remove, tmp.name),  # clean up after sending
    )
