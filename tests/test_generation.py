from io import BytesIO
from datetime import date

import pytest
from pypdf import PdfReader

from app.models import Certificate
from app.services import storage
from app.services.certificate_renderer import (
    CertificateData,
    CertificateRenderError,
    render_certificate,
)


def _data(**kw):
    base = dict(
        certificate_id="abc-123",
        recipient_name="Asha Verma",
        course_name="Advanced Python Programming",
        issued_by="Acme Academy",
        issue_date=date(2026, 10, 10),
    )
    base.update(kw)
    return CertificateData(**base)


def _text(path) -> str:
    return PdfReader(str(path)).pages[0].extract_text()


# ---- renderer unit tests ---------------------------------------------------- #
def test_renderer_creates_a_valid_pdf_with_recipient_specific_text(tmp_path):
    out = render_certificate(_data(), tmp_path / "c.pdf")
    assert out.read_bytes().startswith(b"%PDF")
    text = _text(out)
    assert "Asha Verma" in text
    assert "Advanced Python Programming" in text
    assert "Acme Academy" in text
    assert "10 October 2026" in text
    assert "abc-123" in text


def test_renderer_leaves_no_temp_file_behind(tmp_path):
    render_certificate(_data(), tmp_path / "c.pdf")
    assert [p.name for p in tmp_path.iterdir()] == ["c.pdf"]


def test_renderer_accepts_accented_latin_names(tmp_path):
    out = render_certificate(_data(recipient_name="Jose Müller"), tmp_path / "c.pdf")
    assert out.exists()


def test_renderer_rejects_unsupported_characters(tmp_path):
    with pytest.raises(CertificateRenderError, match="not supported"):
        render_certificate(_data(recipient_name="张伟"), tmp_path / "c.pdf")
    assert not (tmp_path / "c.pdf").exists()


def test_renderer_handles_longest_allowed_inputs(tmp_path):
    out = render_certificate(
        _data(recipient_name="W" * 70, course_name="W" * 150, issued_by="W" * 80), tmp_path / "c.pdf"
    )
    assert out.exists()


# ---- end-to-end generation through the API ---------------------------------- #
def test_each_recipient_gets_their_own_pdf_on_disk(client, submit, db):
    job_id = submit().json()["id"]
    certs = db.query(Certificate).filter_by(job_id=job_id).order_by(Certificate.position).all()
    assert len(certs) == 3
    for cert in certs:
        assert cert.status == "success"
        path = storage.absolute_path(cert.file_path)
        assert path.exists() and path.read_bytes().startswith(b"%PDF")
        assert cert.recipient_name in _text(path)
    assert len({c.file_path for c in certs}) == 3  # distinct files
