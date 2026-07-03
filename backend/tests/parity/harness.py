"""Parity harness: run a (template, mapping, inputs) triple through both the
openpyxl+LibreOffice path and the native engine, and diff every mapped output
under per-type tolerances. Also verifies the injection layer itself (right
cells, sheet-scoped names, merged anchors, fullCalcOnLoad) with no LibreOffice
required.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from app.services import excel_writer, recalc_service
from app.services.excel_writer import _merge_anchor, _resolve_scalar_cell
from app.services.proforma import engine

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "app" / "data" / "input_schema.json"
_OUTPUT_TYPES: dict[str, str] = {
    o["id"]: o["type"] for o in json.loads(_SCHEMA_PATH.read_text())["outputs"]
}

TOLERANCES = {
    "currency": 1.0,   # +-$1
    "percent": 0.0001,  # +-1bp
    "multiple": 0.001,
    "years": 0.05,
    "number": 0.01,
}
IRR_FIELDS = {"unleveredIrr", "leveredIrr", "lpIrr", "gpIrr"}
IRR_TOLERANCE = 0.0002  # +-2bp


def tolerance_for(field_id: str) -> float:
    if field_id in IRR_FIELDS:
        return IRR_TOLERANCE
    return TOLERANCES.get(_OUTPUT_TYPES.get(field_id, "number"), 0.01)


@dataclass
class Diff:
    field: str
    native: float | None
    excel: float | None
    tolerance: float

    @property
    def delta(self) -> float | None:
        if self.native is None or self.excel is None:
            return None
        return abs(self.native - self.excel)

    @property
    def ok(self) -> bool:
        if self.native is None or self.excel is None:
            return False  # one side produced a value the other didn't
        return self.delta <= self.tolerance


def verify_injection(output_path: Path, mapping: dict, inputs: dict) -> list[str]:
    """Assert the openpyxl layer put every mapped input in the right physical
    cell (through named ranges, sheet-scoped names, and merge anchors) and set
    fullCalcOnLoad. Returns a list of problems (empty = clean)."""
    problems: list[str] = []
    wb = openpyxl.load_workbook(output_path)

    if not wb.calculation.fullCalcOnLoad:
        problems.append("fullCalcOnLoad is not set on the generated workbook")

    for field_id, entry in mapping.items():
        if field_id not in inputs or _OUTPUT_TYPES.get(field_id):
            continue  # outputs aren't injected
        resolved = _resolve_scalar_cell(wb, entry)
        if resolved is None:
            problems.append(f"{field_id}: mapping did not resolve ({entry})")
            continue
        ws, coord = resolved
        cell = _merge_anchor(ws, ws[coord])
        expected = inputs[field_id]
        if cell.value != expected:
            problems.append(
                f"{field_id}: expected {expected!r} at {ws.title}!{cell.coordinate}, "
                f"found {cell.value!r}"
            )
    wb.close()
    return problems


def run_case(template_path: Path, mapping: dict, inputs: dict, workdir: Path) -> dict:
    """Returns {"injectionProblems": [...], "diffs": [Diff] | None,
    "skipReason": str | None}. diffs is None when LibreOffice is unavailable."""
    output_path = workdir / f"parity-{template_path.stem}.xlsx"
    excel_writer.inject_values(template_path, output_path, mapping, inputs)
    injection_problems = verify_injection(output_path, mapping, inputs)

    native = engine.compute(inputs)["outputs"]
    mapped_output_ids = [f for f in mapping if f in _OUTPUT_TYPES]

    if not recalc_service.is_available():
        return {
            "injectionProblems": injection_problems,
            "diffs": None,
            "skipReason": "LibreOffice not installed — Excel recalc diff skipped",
        }

    recalc_service.recalc_with_libreoffice(output_path)
    excel_outputs = excel_writer.read_output_values(output_path, mapping, mapped_output_ids)

    diffs = [
        Diff(
            field=field_id,
            native=native.get(field_id) if isinstance(native.get(field_id), (int, float)) else None,
            excel=(
                float(excel_outputs[field_id])
                if isinstance(excel_outputs.get(field_id), (int, float))
                else None
            ),
            tolerance=tolerance_for(field_id),
        )
        for field_id in mapped_output_ids
    ]
    return {"injectionProblems": injection_problems, "diffs": diffs, "skipReason": None}


def format_diff_table(case_name: str, diffs: list[Diff]) -> str:
    lines = [
        f"{case_name}",
        f"  {'field':<24}{'native':>16}{'excel':>16}{'delta':>12}{'tol':>10}  status",
    ]
    for d in diffs:
        native = f"{d.native:.6f}" if d.native is not None else "—"
        excel = f"{d.excel:.6f}" if d.excel is not None else "—"
        delta = f"{d.delta:.6f}" if d.delta is not None else "—"
        lines.append(
            f"  {d.field:<24}{native:>16}{excel:>16}{delta:>12}{d.tolerance:>10}  "
            f"{'ok' if d.ok else 'DIVERGED'}"
        )
    return "\n".join(lines)
