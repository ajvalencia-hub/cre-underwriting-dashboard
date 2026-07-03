"""Classify an uploaded deal document as one of:
  offering_memorandum | rent_roll | t12_operating_statement | other

Two-stage, cheapest-first:
  1. Deterministic keyword-scoring heuristic (spreadsheet headers / PDF text)
     — free, instant, no network call. Used alone whenever it's confident.
  2. LLM fallback (Anthropic API) only when the heuristic is ambiguous (top
     two scores too close together, or nothing scored meaningfully). Skipped
     entirely if ANTHROPIC_API_KEY isn't configured — the heuristic result
     stands, with a note that LLM confirmation wasn't available.

This is classification only — it never trusts itself. The API always returns
this alongside a manual-override affordance in the UI; nothing here silently
becomes a deal input.
"""

import csv
import io
import json
import re
from pathlib import Path

import openpyxl
import pdfplumber

from app.config import ANTHROPIC_API_KEY, ANTHROPIC_CLASSIFIER_MODEL
from app.services.extraction import ocr

DOCUMENT_TYPES = ("offering_memorandum", "rent_roll", "t12_operating_statement", "other")

_AMBIGUITY_MARGIN = 0.08  # if top two heuristic scores are this close, ask the LLM
_MIN_CONFIDENT_SCORE = 0.15

_MONTHS = {
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december",
}

_RENT_ROLL_KEYWORDS = {
    "unit", "suite", "tenant", "sf", "square feet", "square footage", "rent",
    "lease start", "lease end", "commencement", "expiration", "market rent",
    "in-place rent", "rent roll", "occupied", "vacant",
}
_T12_KEYWORDS = {
    "gross potential rent", "vacancy", "credit loss", "effective gross income",
    "operating expenses", "net operating income", "noi", "real estate taxes",
    "insurance", "management fee", "trailing 12", "t-12", "t12", "operating statement",
    "income statement", "statement of operations", "replacement reserves",
}
_OM_KEYWORDS = {
    "offering memorandum", "investment summary", "executive summary",
    "investment highlights", "confidential", "asking price", "marketing package",
    "for sale", "investment opportunity", "cushman", "cbre", "jll",
    "marcus & millichap", "colliers", "newmark", "walker & dunlop",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _score_keywords(text: str, keyword_sets: dict[str, set[str]]) -> dict[str, float]:
    norm = _normalize(text)
    scores = {}
    for doc_type, keywords in keyword_sets.items():
        hits = sum(1 for kw in keywords if kw in norm)
        scores[doc_type] = hits / len(keywords) if keywords else 0.0
    return scores


def _spreadsheet_headers_and_text(path: Path, ext: str) -> str:
    """Pull header rows (and a little content) from every sheet/the CSV, as a
    single blob of text for keyword scoring."""
    chunks: list[str] = []
    if ext == "csv":
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                chunks.append(" ".join(str(c) for c in row))
                if i >= 15:
                    break
    else:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            chunks.append(ws.title)
            for i, row in enumerate(ws.iter_rows(max_row=15, values_only=True)):
                chunks.append(" ".join(str(c) for c in row if c is not None))
        wb.close()
    return "\n".join(chunks)


def _pdf_text_and_scanned_flag(path: Path, max_pages: int = 3) -> tuple[str, bool]:
    text_chunks: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[:max_pages]:
            page_text = page.extract_text() or ""
            text_chunks.append(page_text)
    text = "\n".join(text_chunks)
    scanned = len(text.strip()) < 100
    return text, scanned


def _heuristic_classify(path: Path, ext: str) -> dict:
    if ext in ("xlsx", "xls", "csv"):
        text = _spreadsheet_headers_and_text(path, ext)
        scores = _score_keywords(
            text, {"rent_roll": _RENT_ROLL_KEYWORDS, "t12_operating_statement": _T12_KEYWORDS}
        )
        # month-name columns are a strong T-12 signal spreadsheets carry that
        # PDFs mostly don't (a full 12-column layout), so weight it in.
        month_hits = sum(1 for m in _MONTHS if m in _normalize(text))
        if month_hits >= 3:
            scores["t12_operating_statement"] = min(1.0, scores.get("t12_operating_statement", 0) + 0.3)
        scores["offering_memorandum"] = 0.0
        return {"scores": scores, "sourceText": text[:4000], "scanned": False}

    if ext == "pdf":
        text, scanned = _pdf_text_and_scanned_flag(path)
        ocr_note = ""
        if scanned:
            # The extraction path already OCRs scanned PDFs; classification
            # must use the same fallback or a scanned rent roll lands as
            # "other" even though extraction could read it (FINDINGS.md M13).
            ocr_result = ocr.ocr_pdf_text(path, max_pages=3)
            if ocr_result["available"] and ocr_result["text"].strip():
                text = ocr_result["text"]
                scanned = False
            else:
                ocr_note = ocr_result["note"]
        if scanned:
            return {
                "scores": {t: 0.0 for t in DOCUMENT_TYPES},
                "sourceText": "",
                "scanned": True,
                "ocrNote": ocr_note,
            }
        scores = _score_keywords(
            text,
            {
                "offering_memorandum": _OM_KEYWORDS,
                "rent_roll": _RENT_ROLL_KEYWORDS,
                "t12_operating_statement": _T12_KEYWORDS,
            },
        )
        return {"scores": scores, "sourceText": text[:4000], "scanned": False}

    return {"scores": {t: 0.0 for t in DOCUMENT_TYPES}, "sourceText": "", "scanned": False}


def _best_two(scores: dict[str, float]) -> list[tuple[str, float]]:
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:2]


def _llm_classify(source_text: str) -> dict | None:
    if not ANTHROPIC_API_KEY or not source_text.strip():
        return None

    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = (
        "Classify this commercial real estate document. Respond with JSON only, "
        'no other text, matching exactly: {"documentType": "offering_memorandum" '
        '| "rent_roll" | "t12_operating_statement" | "other", "confidence": 0.0-1.0, '
        '"rationale": "one short sentence"}\n\n'
        f"Document excerpt:\n{source_text[:4000]}"
    )
    try:
        response = client.messages.create(
            model=ANTHROPIC_CLASSIFIER_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        if parsed.get("documentType") not in DOCUMENT_TYPES:
            return None
        return {
            "documentType": parsed["documentType"],
            "confidence": float(parsed.get("confidence", 0.5)),
            "rationale": str(parsed.get("rationale", "")),
        }
    except Exception as exc:  # noqa: BLE001 - any failure here just falls back to heuristic
        return {"error": str(exc)}


def classify_document(path: Path, filename: str) -> dict:
    ext = Path(filename).suffix.lower().lstrip(".")

    try:
        heuristic = _heuristic_classify(path, ext)
    except Exception as exc:  # noqa: BLE001
        # Legacy .xls (pre-2007 binary format) isn't readable by openpyxl, and
        # any other unexpected parse failure shouldn't crash the upload —
        # surface it as "other" for manual classification instead.
        return {
            "documentType": "other",
            "confidence": 0.0,
            "source": "heuristic",
            "rationale": f"Could not parse this file for classification ({exc}). Classify manually.",
        }

    if heuristic["scanned"]:
        return {
            "documentType": "other",
            "confidence": 0.0,
            "source": "heuristic",
            "rationale": (
                "This PDF has little to no extractable text — it looks scanned/image-based. "
                + (heuristic.get("ocrNote") or "OCR produced no usable text; classify manually.")
            ),
        }

    scores = heuristic["scores"]
    top2 = _best_two(scores)
    top_type, top_score = top2[0] if top2 else ("other", 0.0)
    second_score = top2[1][1] if len(top2) > 1 else 0.0
    ambiguous = top_score < _MIN_CONFIDENT_SCORE or (top_score - second_score) < _AMBIGUITY_MARGIN

    if not ambiguous:
        return {
            "documentType": top_type,
            "confidence": round(min(0.95, 0.5 + top_score), 2),
            "source": "heuristic",
            "rationale": f"Keyword match score {top_score:.2f} for {top_type}, clearly ahead of alternatives.",
        }

    llm_result = _llm_classify(heuristic["sourceText"])
    if llm_result and "error" not in llm_result:
        return {
            "documentType": llm_result["documentType"],
            "confidence": llm_result["confidence"],
            "source": "llm",
            "rationale": llm_result["rationale"],
        }

    note = (
        "LLM classification unavailable — set ANTHROPIC_API_KEY for better accuracy on "
        "ambiguous documents."
        if not ANTHROPIC_API_KEY
        else f"LLM classification failed ({llm_result.get('error') if llm_result else 'no response'})."
    )
    return {
        "documentType": top_type if top_score > 0 else "other",
        "confidence": round(top_score, 2),
        "source": "heuristic",
        "rationale": f"Ambiguous keyword scores ({scores}). {note}",
    }
