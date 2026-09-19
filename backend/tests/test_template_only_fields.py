"""The form marks inputs the built-in engine doesn't read ("templateOnly":
only written to a mapped Excel template). This keeps the flag honest both
ways: a flagged field the engine starts reading, or an unflagged model
input it never reads, fails here — so the form never tells an analyst a
number is used when it isn't (the engine-audit finding: hotel ADR, draw
schedule, loan term... looked modeled but weren't)."""

import json
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_SCHEMA = json.loads((_BACKEND / "app" / "data" / "input_schema.json").read_text())
_ENGINE_SOURCE = "".join(p.read_text() for p in (_BACKEND / "app" / "services" / "proforma").glob("*.py"))

# Descriptive fields: identify or describe the deal, never model inputs.
DESCRIPTIVE = {
    "dealName", "investmentThesis", "address", "submarket", "propertyType",
    "mixedUseComponents", "clearHeightFt", "tenancyType", "customKeyValues",
}


def _read_by_engine(field_id: str) -> bool:
    return f'"{field_id}"' in _ENGINE_SOURCE or f"'{field_id}'" in _ENGINE_SOURCE


def _fields():
    return [f for section in _SCHEMA["sections"] for f in section["fields"]]


def test_template_only_fields_really_are_ignored_by_the_engine():
    wrongly_flagged = [f["id"] for f in _fields() if f.get("templateOnly") and _read_by_engine(f["id"])]
    assert wrongly_flagged == [], "the engine reads these now — drop templateOnly"


def test_every_unread_model_input_is_flagged():
    unflagged = [
        f["id"] for f in _fields()
        if not f.get("templateOnly") and f["id"] not in DESCRIPTIVE and not _read_by_engine(f["id"])
    ]
    assert unflagged == [], "the engine ignores these — mark them templateOnly (or DESCRIPTIVE)"
