"""Regression tests for FINDINGS.md M13: scanned PDFs were always classified
'other' with a stale "OCR isn't implemented yet" rationale, even though the
extraction path OCRs them. Classification now runs the same OCR fallback and
scores the recovered text; when OCR is unavailable the rationale carries the
real reason.
"""

from pathlib import Path

from app.services import document_classifier
from app.services.extraction import ocr

_T12_TEXT = """
Trailing 12 Operating Statement
Gross Potential Rent   500,000
Vacancy                (25,000)
Effective Gross Income 475,000
Real Estate Taxes       60,000
Insurance               18,000
Management Fee          20,000
Net Operating Income   337,000
"""


def _pretend_scanned(monkeypatch):
    monkeypatch.setattr(
        document_classifier, "_pdf_text_and_scanned_flag", lambda path, max_pages=8: ("", True, 1)
    )


def test_scanned_pdf_with_ocr_is_classified_from_ocr_text(monkeypatch):
    _pretend_scanned(monkeypatch)
    monkeypatch.setattr(
        ocr, "ocr_pdf_text", lambda path, max_pages=3: {"available": True, "text": _T12_TEXT, "note": ""}
    )

    result = document_classifier.classify_document(Path("scan.pdf"), "scan.pdf")
    assert result["documentType"] == "t12_operating_statement"
    assert result["source"] == "heuristic"


def test_scanned_pdf_without_ocr_reports_the_real_reason(monkeypatch):
    _pretend_scanned(monkeypatch)
    unavailable_note = "Tesseract OCR is not installed on this machine."
    monkeypatch.setattr(
        ocr, "ocr_pdf_text", lambda path, max_pages=3: {"available": False, "text": "", "note": unavailable_note}
    )

    result = document_classifier.classify_document(Path("scan.pdf"), "scan.pdf")
    assert result["documentType"] == "other"
    assert unavailable_note in result["rationale"]
    assert "isn't implemented" not in result["rationale"]  # the stale message
