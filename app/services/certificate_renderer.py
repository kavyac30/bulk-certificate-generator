"""Renders ONE certificate PDF from the single predefined template.

The "template" is code: a fixed landscape-A4 layout drawn with ReportLab.
Only the recipient/course/issuer/date text changes between certificates.
"""
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

NAVY = colors.HexColor("#1B2A49")
GOLD = colors.HexColor("#B8923A")
CREAM = colors.HexColor("#FFFDF6")
GREY = colors.HexColor("#6B7280")


class CertificateRenderError(Exception):
    """Raised when a certificate cannot be rendered (shown to the client per-certificate)."""


@dataclass(frozen=True)
class CertificateData:
    certificate_id: str
    recipient_name: str
    course_name: str
    issued_by: str
    issue_date: date


def _ensure_supported(text: str, label: str) -> None:
    # The built-in PDF fonts only cover Latin-1 / WinAnsi. Anything else would be
    # drawn as black boxes, so fail loudly instead of producing a broken certificate.
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        raise CertificateRenderError(
            f"{label} contains characters not supported by the certificate font"
        )


def _fit(text: str, font: str, sizes: list[int], max_width: float, max_lines: int, label: str):
    """Pick the largest font size at which `text` wraps into <= max_lines lines."""
    for size in sizes:
        lines = simpleSplit(text, font, size, max_width)
        if len(lines) <= max_lines:
            return lines, size
    raise CertificateRenderError(f"{label} is too long to fit on the certificate")


def render_certificate(data: CertificateData, output_path: Path) -> Path:
    """Write the certificate PDF to `output_path` (atomically) and return the path."""
    _ensure_supported(data.recipient_name, "Recipient name")
    _ensure_supported(data.course_name, "Course name")
    _ensure_supported(data.issued_by, "Issuer name")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".pdf.tmp")

    width, height = landscape(A4)
    cx = width / 2

    # Work out text layout first so a layout problem fails before any file is written.
    name_lines, name_size = _fit(
        data.recipient_name, "Times-BoldItalic", list(range(40, 11, -2)), width - 160, 1, "Recipient name"
    )
    course_lines, course_size = _fit(
        data.course_name, "Helvetica-Bold", [22, 20, 18, 16], width - 200, 3, "Course name"
    )
    issuer_lines, issuer_size = _fit(
        data.issued_by, "Helvetica", [13, 12, 11, 10, 9], 330, 2, "Issuer name"
    )

    try:
        c = canvas.Canvas(str(tmp_path), pagesize=(width, height))
        c.setTitle(f"Certificate - {data.recipient_name}")
        c.setAuthor(data.issued_by)
        c.setSubject(data.course_name)
        c.setCreator("Bulk Certificate Generator")

        # Background + double border
        c.setFillColor(CREAM)
        c.rect(0, 0, width, height, stroke=0, fill=1)
        c.setStrokeColor(NAVY)
        c.setLineWidth(3)
        c.rect(25, 25, width - 50, height - 50, stroke=1, fill=0)
        c.setStrokeColor(GOLD)
        c.setLineWidth(1)
        c.rect(35, 35, width - 70, height - 70, stroke=1, fill=0)

        # Heading
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 46)
        c.drawCentredString(cx, height - 120, "CERTIFICATE")
        c.setFillColor(GOLD)
        c.setFont("Helvetica", 18)
        c.drawCentredString(cx, height - 150, "OF COMPLETION")

        # Body
        c.setFillColor(GREY)
        c.setFont("Helvetica-Oblique", 15)
        c.drawCentredString(cx, height - 200, "This is to certify that")

        c.setFillColor(NAVY)
        c.setFont("Times-BoldItalic", name_size)
        c.drawCentredString(cx, height - 255, name_lines[0])
        line_half = min(stringWidth(name_lines[0], "Times-BoldItalic", name_size) / 2 + 30, width / 2 - 80)
        c.setStrokeColor(GOLD)
        c.setLineWidth(1)
        c.line(cx - line_half, height - 265, cx + line_half, height - 265)

        c.setFillColor(GREY)
        c.setFont("Helvetica-Oblique", 15)
        c.drawCentredString(cx, height - 300, "has successfully completed")

        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", course_size)
        y = height - 338
        for line in course_lines:
            c.drawCentredString(cx, y, line)
            y -= course_size + 6

        # Footer: date (left) and issuer (right)
        left_x, right_x, base_y = width * 0.27, width * 0.73, 115
        c.setStrokeColor(NAVY)
        c.setLineWidth(0.8)
        c.line(left_x - 110, base_y, left_x + 110, base_y)
        c.line(right_x - 150, base_y, right_x + 150, base_y)

        c.setFillColor(NAVY)
        c.setFont("Helvetica", 13)
        c.drawCentredString(left_x, base_y + 8, data.issue_date.strftime("%d %B %Y"))
        c.setFont("Helvetica", issuer_size)
        iy = base_y + 8 + (len(issuer_lines) - 1) * (issuer_size + 2)
        for line in issuer_lines:
            c.drawCentredString(right_x, iy, line)
            iy -= issuer_size + 2

        c.setFillColor(GREY)
        c.setFont("Helvetica", 9)
        c.drawCentredString(left_x, base_y - 14, "DATE OF ISSUE")
        c.drawCentredString(right_x, base_y - 14, "ISSUED BY")

        c.setFont("Helvetica", 8)
        c.drawCentredString(cx, 55, f"Certificate ID: {data.certificate_id}")

        c.showPage()
        c.save()
        os.replace(tmp_path, output_path)  # atomic: never leaves a half-written PDF
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return output_path
