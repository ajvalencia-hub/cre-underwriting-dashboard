"""LLM structuring layer: the robust fallback for narrative/messy content
that deterministic parsing can't handle — Offering Memoranda, "other"
documents, and rent-roll/T-12 files whose formatting is too inconsistent
for the header-alias matching in rent_roll_parser.py / t12_parser.py to
produce a usable result.

Sends extracted text (plus the app's actual input-schema field list as the
allowed vocabulary) to the Anthropic API and requires strict JSON back,
which is validated against LlmExtractionResponse before ever being used —
an LLM response that doesn't parse or doesn't validate is treated exactly
like "LLM unavailable", never silently accepted.
"""

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from app.config import ANTHROPIC_API_KEY, ANTHROPIC_EXTRACTION_MODEL

_MAX_TEXT_CHARS = 15000


class SourceRef(BaseModel):
    doc: str | None = None
    page: int | None = None
    sheet: str | None = None
    cell: str | None = None
    row: int | None = None


class ScalarExtraction(BaseModel):
    fieldId: str
    value: Any
    rawText: str | None = None
    sourceRef: SourceRef = SourceRef()
    confidence: float
    notes: str | None = None


class RentRollRowExtraction(BaseModel):
    unit: str | None = None
    tenant: str | None = None
    sf: float | None = None
    unitType: str | None = None
    status: str | None = None
    inPlaceRentMonthly: float | None = None
    marketRentMonthly: float | None = None
    leaseStart: str | None = None
    leaseEnd: str | None = None
    sourceRef: SourceRef = SourceRef()
    confidence: float


class T12LineItemExtraction(BaseModel):
    label: str
    amount: float
    mappedCategory: str | None = None
    isNonRecurring: bool = False
    sourceRef: SourceRef = SourceRef()
    confidence: float


class UnmatchedExtraction(BaseModel):
    suggestedLabel: str
    value: Any
    rawText: str | None = None
    sourceRef: SourceRef = SourceRef()
    confidence: float


class LlmExtractionResponse(BaseModel):
    documentType: str
    scalarExtractions: list[ScalarExtraction] = []
    rentRollRows: list[RentRollRowExtraction] = []
    t12LineItems: list[T12LineItemExtraction] = []
    unmatchedExtractions: list[UnmatchedExtraction] = []
    warnings: list[str] = []


_CONTRACT_DESCRIPTION = """Return JSON ONLY, no other text, matching exactly this shape:
{
  "documentType": "offering_memorandum" | "rent_roll" | "t12_operating_statement" | "other",
  "scalarExtractions": [
    {"fieldId": "<one of the allowed field ids below>", "value": <number|string|boolean>,
     "rawText": "<exact text/cell the value came from>",
     "sourceRef": {"page": <int|null>, "sheet": <string|null>, "cell": <string|null>, "row": <int|null>},
     "confidence": <0.0-1.0>, "notes": <string|null>}
  ],
  "rentRollRows": [
    {"unit": <string|null>, "tenant": <string|null>, "sf": <number|null>, "unitType": <string|null>,
     "status": "occupied"|"vacant"|"unknown", "inPlaceRentMonthly": <number|null>,
     "marketRentMonthly": <number|null>, "leaseStart": "<ISO date|null>", "leaseEnd": "<ISO date|null>",
     "sourceRef": {...}, "confidence": <0.0-1.0>}
  ],
  "t12LineItems": [
    {"label": "<original line label>", "amount": <number>,
     "mappedCategory": "<one of: realEstateTaxes, insurance, utilities, repairsMaintenance, payroll, "
     "managementFeePct, generalAdmin, replacementReserves, grossPotentialRent, vacancyLoss, creditLoss, "
     "otherIncome, or null if it doesn't fit any>",
     "isNonRecurring": <boolean>, "sourceRef": {...}, "confidence": <0.0-1.0>}
  ],
  "unmatchedExtractions": [
    {"suggestedLabel": "<short label>", "value": <number|string>, "rawText": "<source text>",
     "sourceRef": {...}, "confidence": <0.0-1.0>}
  ],
  "warnings": ["<short strings, e.g. 'statement appears to be a T-6; not annualized by me'>"]
}
Only use a fieldId that appears in the allowed list below. If you find a value that doesn't map to any
allowed field, put it in unmatchedExtractions instead of inventing a new fieldId. Only include entries you
actually found in the document — do not guess or fill in typical/expected values."""


def _strip_code_fences(text: str) -> str:
    return re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()


def extract_with_llm(
    document_type: str, text: str, source_doc: str, schema_fields: list[dict]
) -> dict:
    """Returns a dict with either the validated extraction (under "result") or
    an "error"/"unavailable" note — callers check for "result" before using it.
    """
    if not ANTHROPIC_API_KEY:
        return {
            "result": None,
            "note": "LLM extraction unavailable — set ANTHROPIC_API_KEY in backend/.env.",
        }
    if not text.strip():
        return {"result": None, "note": "No extractable text to send to the LLM."}

    import anthropic

    field_list = "\n".join(f"- {f['id']} ({f['label']}, type={f['type']})" for f in schema_fields)
    prompt = (
        f"You are extracting structured data from a commercial real estate document "
        f"(classified as: {document_type}) for underwriting review.\n\n"
        f"Allowed field ids for scalarExtractions:\n{field_list}\n\n"
        f"{_CONTRACT_DESCRIPTION}\n\n"
        f"Document excerpt:\n{text[:_MAX_TEXT_CHARS]}"
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=ANTHROPIC_EXTRACTION_MODEL,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _strip_code_fences(response.content[0].text)
        parsed = json.loads(raw)
        validated = LlmExtractionResponse.model_validate(parsed)
    except (json.JSONDecodeError, ValidationError) as exc:
        return {"result": None, "note": f"LLM response failed validation, discarded: {exc}"}
    except Exception as exc:  # noqa: BLE001 - network/API errors etc.
        return {"result": None, "note": f"LLM extraction call failed: {exc}"}

    result = validated.model_dump()
    for bucket in ("scalarExtractions", "rentRollRows", "t12LineItems", "unmatchedExtractions"):
        for entry in result[bucket]:
            entry["sourceRef"]["doc"] = source_doc

    return {"result": result, "note": None}
