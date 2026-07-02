"""Raw text + table extraction from PDFs, with an OCR fallback for scanned
documents. This is the "get the raw content out" layer — deterministic and
LLM parsers downstream turn this into structured data.
"""

from pathlib import Path

import pdfplumber

from app.services.extraction import ocr


def extract_pdf(path: Path, max_pages: int = 30) -> dict:
    """Returns {"pages": [{"pageNumber", "text", "tables": [[[cell,...],...]]}],
    "scanned": bool, "ocrNote": str}. Falls back to OCR when the PDF has
    negligible extractable text.
    """
    pages = []
    total_text_len = 0

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages[:max_pages]):
            text = page.extract_text() or ""
            tables = page.extract_tables() or []
            pages.append({"pageNumber": i + 1, "text": text, "tables": tables})
            total_text_len += len(text.strip())

    scanned = total_text_len < 100
    ocr_note = ""
    if scanned:
        ocr_result = ocr.ocr_pdf_text(path, max_pages=max_pages)
        ocr_note = ocr_result["note"]
        if ocr_result["available"]:
            # Replace page text with OCR output (page-level split is approximate
            # since pytesseract processes whole rendered pages, not pdfplumber's
            # per-page text objects).
            ocr_pages = ocr_result["text"].split("\f")  # form-feed between pages in some outputs
            for i, page_text in enumerate(ocr_pages):
                if i < len(pages):
                    pages[i]["text"] = page_text
                else:
                    pages.append({"pageNumber": i + 1, "text": page_text, "tables": []})
            scanned = False  # OCR succeeded; downstream can treat this as readable now

    return {"pages": pages, "scanned": scanned, "ocrNote": ocr_note}


def full_text(extraction: dict, max_chars: int = 12000) -> str:
    text = "\n".join(p["text"] for p in extraction["pages"])
    return text[:max_chars]
