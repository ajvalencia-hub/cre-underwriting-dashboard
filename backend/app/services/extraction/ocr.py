"""OCR fallback for scanned/image PDFs (little/no extractable text).

Pluggable by design: `is_available()` checks for a local Tesseract install
(PATH first, then common Windows install locations — the same fallback
pattern used for LibreOffice in recalc_service.py, since a freshly-installed
system binary often isn't on PATH for an already-running process); if
neither is found, `ocr_pdf_text()` returns a clear "unavailable" result
instead of silently producing nothing. Swap this module's implementation
for a cloud OCR provider (Google Document AI, AWS Textract, Azure Document
Intelligence) for meaningfully better accuracy on real scanned OMs/rent
rolls — this local Tesseract path is a functional but lower-quality
baseline.
"""

import glob
import shutil
from pathlib import Path

_TESSERACT_FALLBACK_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Users\{user}\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
]
_POPPLER_BIN_GLOBS = [
    r"C:\Users\{user}\AppData\Local\Microsoft\WinGet\Packages\oschwartz10612.Poppler_*\poppler-*\Library\bin",
    r"C:\Program Files\poppler*\Library\bin",
    r"C:\Program Files\poppler*\bin",
]


def _find_tesseract() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    import os

    user = os.environ.get("USERNAME", "")
    for template in _TESSERACT_FALLBACK_PATHS:
        candidate = template.format(user=user)
        if Path(candidate).exists():
            return candidate
    return None


def _find_poppler_bin() -> str | None:
    if shutil.which("pdftoppm"):
        return None  # already on PATH, no explicit poppler_path needed
    import os

    user = os.environ.get("USERNAME", "")
    for template in _POPPLER_BIN_GLOBS:
        pattern = template.format(user=user)
        matches = glob.glob(pattern)
        for match in matches:
            if Path(match, "pdftoppm.exe").exists():
                return match
    return None


_TESSERACT_BIN = _find_tesseract()
_POPPLER_BIN = _find_poppler_bin()


def is_available() -> bool:
    return _TESSERACT_BIN is not None


def ocr_pdf_text(path: Path, max_pages: int = 10) -> dict:
    if not is_available():
        return {
            "available": False,
            "text": "",
            "note": (
                "Tesseract OCR is not installed on this machine, so this scanned PDF "
                "can't be read automatically. Install Tesseract (or swap in a cloud OCR "
                "provider in app/services/extraction/ocr.py) to enable this, or transcribe "
                "key figures manually."
            ),
        }

    try:
        import pytesseract
        from pdf2image import convert_from_path

        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_BIN

        convert_kwargs = {"first_page": 1, "last_page": max_pages}
        if _POPPLER_BIN:
            convert_kwargs["poppler_path"] = _POPPLER_BIN

        images = convert_from_path(str(path), **convert_kwargs)
        text_chunks = [pytesseract.image_to_string(img) for img in images]
        return {"available": True, "text": "\n".join(text_chunks), "note": ""}
    except Exception as exc:  # noqa: BLE001 - poppler (pdf2image's system dependency) may be missing
        return {
            "available": False,
            "text": "",
            "note": f"OCR page rendering failed ({exc}). Poppler may not be installed.",
        }
