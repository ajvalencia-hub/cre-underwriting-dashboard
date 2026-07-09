"""Sensitivity analysis: sweep 1-2 "driver" input fields across a range of
values and see how the mapped output metrics respond. Deliberately reuses
the exact same injection + recalc + read-back pipeline as a normal
generate() call, one grid point at a time — no separate cash-flow/IRR engine
lives in this app; the uploaded template already does that math, this just
runs it repeatedly with different inputs.

Runs sequentially (not in parallel) because concurrent headless LibreOffice
instances can contend for the same user-profile lock and fail intermittently
— a grid point taking ~1-2s each is an acceptable tradeoff for reliability
over speed at the grid sizes this supports.
"""

import itertools
import uuid
from pathlib import Path

from app.config import GENERATED_DIR
from app.services import excel_writer, recalc_service
from app.services.proforma import engine

MAX_GRID_POINTS = 30  # template mode: each point is a real LibreOffice recalc
MAX_NATIVE_GRID_POINTS = 625  # native mode: 25 x 25, pure in-process math


def cartesian_combos(drivers: list[dict]) -> list[dict]:
    """drivers: [{"fieldId": str, "values": [float, ...]}, ...] (1 or 2 entries)
    -> [{"exitCapRatePct": 0.05, ...}, ...] one dict per grid point.
    """
    field_ids = [d["fieldId"] for d in drivers]
    value_lists = [d["values"] for d in drivers]
    return [dict(zip(field_ids, combo, strict=True)) for combo in itertools.product(*value_lists)]


def run_sensitivity(
    template_path: Path,
    mappings: dict,
    base_values: dict,
    drivers: list[dict],
    output_field_ids: list[str],
) -> dict:
    combos = cartesian_combos(drivers)
    points = []

    for combo in combos:
        values = {**base_values, **combo}
        output_path = GENERATED_DIR / f"{uuid.uuid4()}{template_path.suffix}"
        try:
            result = excel_writer.inject_values(template_path, output_path, mappings, values)
            recalc_service.recalc_with_libreoffice(output_path)
            outputs = excel_writer.read_output_values(output_path, mappings, output_field_ids)
            points.append({"driverValues": combo, "outputs": outputs, "warnings": result["warnings"]})
        except Exception as exc:  # noqa: BLE001
            points.append({"driverValues": combo, "outputs": {}, "warnings": [f"Grid point failed: {exc}"]})
        finally:
            output_path.unlink(missing_ok=True)

    return {"points": points}


def run_native_sensitivity(
    base_values: dict,
    drivers: list[dict],
    output_field_ids: list[str],
) -> dict:
    """Native-engine sweep: same response shape as the template path, but each
    grid point is an in-process engine.compute — no template, no mapping, no
    LibreOffice. Insufficient inputs at a point become that point's warning
    rather than a failed run (a sweep can push a deal into invalid territory)."""
    combos = cartesian_combos(drivers)
    wanted = set(output_field_ids)
    points = []
    for combo in combos:
        values = {**base_values, **combo}
        try:
            result = engine.compute(values)
            outputs = {
                key: value
                for key, value in result["outputs"].items()
                if not wanted or key in wanted
            }
            points.append({"driverValues": combo, "outputs": outputs, "warnings": []})
        except engine.InsufficientInputsError as exc:
            points.append(
                {
                    "driverValues": combo,
                    "outputs": {},
                    "warnings": [f"Grid point not computable: missing {', '.join(exc.missing)}"],
                }
            )
    return {"points": points}
