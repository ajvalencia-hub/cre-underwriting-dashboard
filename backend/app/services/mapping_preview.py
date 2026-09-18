"""Read-only preview of what Generate would do with a mapping.

For every schema field it reports where the value lands (named ranges
resolved to Sheet!A1), what that cell holds in the template today, its
number format, and whether excel_writer.inject_values would write it or
skip it (blank value, formula cell, multi-cell range, unresolved). It also
flags likely unit mismatches (fraction vs whole-number percent, monthly vs
annual) — warnings only; nothing is changed.

This deliberately reuses excel_writer's own resolution helpers so the
preview can't disagree with what generation actually does. It never
writes: the workbook is opened read-only and the injection logic is
untouched.
"""

from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.cell.cell import MergedCell
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

from app.services import mapping_service
from app.services.excel_writer import _is_formula_cell, _merge_anchor, _resolve_scalar_cell

NUMERIC_TYPES = {"number", "currency", "percent"}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _is_blank(value: Any) -> bool:
    # Mirrors inject_values: these values are skipped, not written.
    return value in (None, "", [])


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def unit_warning(field_type: str, write_value: Any, cell_value: Any, number_format: str | None) -> str | None:
    """Heuristic, warning-only checks for the classic silent errors."""
    new = _as_number(write_value)
    old = _as_number(cell_value)
    if new is None:
        return None
    is_pct_format = bool(number_format and "%" in number_format)

    if field_type == "percent":
        # The app stores percents as fractions (5.5% -> 0.055).
        if old is not None and not is_pct_format and abs(old) > 1 and abs(new) <= 1:
            return (
                f"This cell holds {old:g} and isn't formatted as a percentage — the template may "
                f"expect whole-number percents, but {new:g} (= {new * 100:g}%) will be written."
            )
        return None

    if old is None or old == 0 or new == 0:
        return None
    ratio = abs(new / old)
    for factor, label in ((12, "annual vs monthly"), (1 / 12, "monthly vs annual")):
        if abs(ratio - factor) / factor < 0.08:
            return (
                f"The value to write ({new:,.2f}) is about {ratio:.1f}× the template's current "
                f"{old:,.2f} — check {label}."
            )
    if ratio >= 50 or ratio <= 1 / 50:
        return (
            f"The value to write ({new:,.2f}) differs from the template's current {old:,.2f} by "
            f"~{ratio if ratio >= 1 else 1 / ratio:,.0f}× — check the units (thousands, $/SF vs total, %)."
        )
    return None


def _scalar_row(wb, field: dict, entry: dict, value: Any, is_output: bool) -> dict:
    row: dict[str, Any] = {"target": entry.get("target")}
    resolved = _resolve_scalar_cell(wb, entry)
    if resolved is None:
        row.update(status="unresolved", resolvedRef=None)
        row["message"] = (
            f"Named range '{entry.get('ref')}' isn't in this workbook"
            if entry.get("target") == "namedRange"
            else f"Sheet for {entry.get('ref')} isn't in this workbook"
        )
        return row
    ws, coord = resolved
    row["resolvedRef"] = f"{ws.title}!{coord}"
    if ":" in coord:
        row.update(status="multiCell", message="Maps to a multi-cell range — nothing is written. Map a single cell.")
        return row

    cell = _merge_anchor(ws, ws[coord])
    if cell.coordinate != coord:
        row["resolvedRef"] = f"{ws.title}!{cell.coordinate}"
        row["mergedFrom"] = coord
    is_formula = _is_formula_cell(cell)
    row["cellFormula"] = cell.value if is_formula else None
    row["cellValue"] = None if is_formula else _json_safe(cell.value)
    row["numberFormat"] = cell.number_format
    row["isFormula"] = is_formula

    if is_output:
        row["status"] = "output"
        if not is_formula:
            row["message"] = (
                "This output cell holds a fixed value, not a formula — it won't change when inputs change."
            )
        return row

    if is_formula:
        row.update(
            status="formula",
            message="Cell contains a formula — the value is NOT written (to protect the model). Map the input cell it reads from.",
        )
        return row
    if _is_blank(value):
        shown = "empty" if cell.value in (None, "") else f"its current value ({_json_safe(cell.value)})"
        row.update(
            status="blank",
            message=f"No value on this deal — the template keeps {shown}.",
        )
        return row

    row["status"] = "ok"
    row["writeValue"] = _json_safe(value)
    warning = unit_warning(field.get("type", ""), value, cell.value, cell.number_format)
    if warning:
        row["status"] = "unitWarning"
        row["message"] = warning
    return row


def _table_row(wb, entry: dict, value: Any) -> dict:
    row: dict[str, Any] = {"target": "table"}
    sheet_name = entry.get("sheet")
    if sheet_name is None or sheet_name not in wb.sheetnames:
        row.update(status="unresolved", resolvedRef=None, message=f"Sheet '{sheet_name}' isn't in this workbook")
        return row
    ws = wb[sheet_name]
    row["resolvedRef"] = f"{ws.title}!{entry.get('anchor')}"
    rows = value if isinstance(value, list) else []
    if not rows:
        row.update(status="blank", message="No rows on this deal — the template's table is left as is.")
        return row
    col_letter, start_row = coordinate_from_string(entry["anchor"])
    start_col = column_index_from_string(col_letter)
    columns = entry.get("columnOrder") or ["key", "value"]
    formula = merged = 0
    for r in range(len(rows)):
        for c in range(len(columns)):
            cell = ws.cell(row=start_row + r, column=start_col + c)
            if isinstance(cell, MergedCell):
                merged += 1
            elif _is_formula_cell(cell):
                formula += 1
    row["tableRows"] = len(rows)
    row["tableColumns"] = len(columns)
    problems = []
    if formula:
        problems.append(f"{formula} cell(s) with formulas will be skipped")
    if merged:
        problems.append(f"{merged} merged cell(s) will be skipped")
    row["status"] = "tableSkips" if problems else "ok"
    if problems:
        row["message"] = "; ".join(problems) + "."
    return row


def preview(template_path: Path, mappings: dict, values: dict) -> list[dict]:
    fields = mapping_service.load_flat_fields(include_outputs=False)
    outputs = mapping_service.load_output_fields()
    wb = openpyxl.load_workbook(template_path, keep_vba=False)
    try:
        result: list[dict] = []
        for field, is_output in [(f, False) for f in fields] + [(o, True) for o in outputs]:
            field_id = field["id"]
            entry = mappings.get(field_id)
            value = None if is_output else values.get(field_id)
            base = {"fieldId": field_id, "isOutput": is_output, "hasValue": not _is_blank(value)}
            if entry is None:
                status = "unmapped"
                message = None
                if not is_output and not _is_blank(value):
                    message = "Has a value on this deal but isn't mapped — the template's own number is used."
                result.append({**base, "status": status, "resolvedRef": None, "message": message})
                continue
            if entry.get("target") == "table":
                result.append({**base, **_table_row(wb, entry, value)})
            else:
                result.append({**base, **_scalar_row(wb, field, entry, value, is_output)})
        return result
    finally:
        wb.close()
