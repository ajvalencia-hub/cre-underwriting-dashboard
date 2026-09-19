"""Type and range checks on engine inputs, against input_schema.json.

The engine reads numbers with a lenient helper that treats anything
non-numeric as the field's default — so a vacancy imported as the text
"0.1" silently became 0 (levered IRR 11.6% -> 15.4% on the analytic deal),
and nothing on the server enforced the schema's min/max. Now:
- numeric text ("0.1", "1,250,000", "$5,000") is read as the number, with
  a warning naming the field;
- anything else in a numeric field stops the compute with the field named
  (InsufficientInputsError, which the UI already links to the field);
- values outside the schema's range are computed AS ENTERED with a warning
  (never silently clamped — the number on screen is the number used).
"""

import json
import math
from functools import lru_cache
from pathlib import Path

NUMERIC_TYPES = {"currency", "percent", "number", "multiple", "years"}
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "data" / "input_schema.json"


@lru_cache(maxsize=1)
def _schema_fields() -> dict[str, dict]:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return {f["id"]: f for section in schema["sections"] for f in section["fields"]}


def _as_number(value) -> float | None:
    """The number `value` holds, or None if it isn't one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        text = value.strip().replace(",", "").removeprefix("$").strip()
        try:
            number = float(text)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _describe(value: float, field_type: str) -> str:
    return f"{value * 100:g}%" if field_type == "percent" else f"{value:,.10g}"


def validate_inputs(inputs: dict) -> tuple[dict, list[str], list[str]]:
    """Returns (normalized inputs, warnings, errors). Only schema fields are
    checked; unknown keys pass through untouched."""
    fields = _schema_fields()
    normalized = dict(inputs)
    warnings: list[str] = []
    errors: list[str] = []

    def check(value, field_id: str, field_type: str, where: str, label: str):
        """Returns the value to use (coerced number, or the original)."""
        if value is None or value == "" or field_type not in NUMERIC_TYPES:
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return value
        number = _as_number(value)
        if number is None:
            errors.append(f"{field_id} ({where}not a number: {value!r})")
            return value
        warnings.append(f"{label} was text ({value!r}) — read as {number:g}.")
        return number

    for field_id, field in fields.items():
        if field_id not in inputs:
            continue
        label = field.get("label", field_id)
        field_type = field.get("type", "")
        if field_type == "table":
            rows = inputs.get(field_id)
            if not isinstance(rows, list):
                continue
            columns = {c["id"]: c.get("type", "") for c in field.get("columns", [])}
            new_rows = []
            for index, row in enumerate(rows, start=1):
                if not isinstance(row, dict):
                    new_rows.append(row)
                    continue
                new_row = dict(row)
                for col_id, col_type in columns.items():
                    if col_id in row:
                        new_row[col_id] = check(
                            row[col_id], field_id, col_type,
                            f"row {index} {col_id}: ", f"{label} row {index} {col_id}",
                        )
                new_rows.append(new_row)
            normalized[field_id] = new_rows
            continue

        value = check(inputs[field_id], field_id, field_type, "", label)
        normalized[field_id] = value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value == 0 and field.get("zeroDisables"):
                continue  # 0 switches the constraint off — a valid setting
            low, high = field.get("min"), field.get("max")
            if (low is not None and value < low) or (high is not None and value > high):
                bounds = (
                    f"{_describe(low, field_type) if low is not None else '…'}"
                    f"–{_describe(high, field_type) if high is not None else '…'}"
                )
                warnings.append(
                    f"{label} is {_describe(value, field_type)}, outside the allowed "
                    f"{bounds} — computed as entered."
                )
    return normalized, warnings, errors
