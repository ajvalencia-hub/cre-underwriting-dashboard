"""J7: generalized goal-seek over the native engine.

Robust bracket-scan + bisection — monotonicity is NEVER assumed. The input
is scanned over sensible bounds (schema min/max where defined, else ±80% of
the current value) at 12 points; every sign change of (metric − target) is a
candidate bracket, and the one nearest the current input wins (the others
are reported). Bisection runs to a metric-typed tolerance with a hard
iteration cap. Every evaluation goes through the compute cache — the engine
is pure, so repeated goal-seeks over the same deal re-use prior points.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Callable

from app.services import compute_cache
from app.services.proforma import engine

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "data" / "input_schema.json"
SCAN_POINTS = 12
MAX_ITERATIONS = 60

_NUMERIC_FIELD_TYPES = {"number", "currency", "percent"}

# Metric-typed tolerances: 0.1bp for rates/IRRs, $100 for dollars, 1e-4 for
# ratios/multiples.
_TOLERANCE_BY_TYPE = {"percent": 1e-5, "currency": 100.0}
_DEFAULT_TOLERANCE = 1e-4


class GoalSeekError(ValueError):
    """Bad request — unknown field/metric or unusable bounds."""


@lru_cache(maxsize=1)
def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def numeric_input_fields() -> dict[str, dict]:
    """Flat {fieldId: field} for every scalar numeric schema input."""
    fields: dict[str, dict] = {}
    for section in _schema()["sections"]:
        for field in section["fields"]:
            if field.get("type") in _NUMERIC_FIELD_TYPES:
                fields[field["id"]] = field
    return fields


def _metric_tolerance(metric: str) -> float:
    for out in _schema().get("outputs", []):
        if out["id"] == metric:
            return _TOLERANCE_BY_TYPE.get(out.get("type", ""), _DEFAULT_TOLERANCE)
    raise GoalSeekError(f"Unknown output metric '{metric}'.")


def _resolve_bounds(
    field: dict, current: float, bounds: tuple[float, float] | None
) -> tuple[float, float]:
    if bounds is not None:
        lo, hi = float(bounds[0]), float(bounds[1])
    else:
        f_min, f_max = field.get("min"), field.get("max")
        if isinstance(f_min, (int, float)) and isinstance(f_max, (int, float)):
            lo, hi = float(f_min), float(f_max)
        elif current != 0:
            lo, hi = current * 0.2, current * 1.8
            if lo > hi:  # negative current value
                lo, hi = hi, lo
        else:
            raise GoalSeekError(
                f"'{field['id']}' is 0 with no schema min/max — pass explicit "
                "bounds to scan."
            )
    if not lo < hi:
        raise GoalSeekError(f"Bounds must satisfy lo < hi (got {lo} .. {hi}).")
    return lo, hi


def _solve(
    evaluate: Callable[[float], float | None],
    current: float,
    lo: float,
    hi: float,
    target: float,
    tolerance: float,
) -> dict:
    """The core solver, engine-agnostic for testability. `evaluate` returns
    the metric at an input value, or None when the metric doesn't exist
    there (e.g. no debt at LTV 0)."""
    step = (hi - lo) / (SCAN_POINTS - 1)
    scanned: list[dict] = []
    for i in range(SCAN_POINTS):
        value = lo + step * i
        metric = evaluate(value)
        scanned.append({"value": value, "metric": metric})
        if metric is not None and abs(metric - target) <= tolerance:
            return {
                "solvedValue": value,
                "achievedMetric": metric,
                "iterations": i + 1,
                "otherCrossings": [],
                "scannedRange": [lo, hi],
            }

    # Every adjacent pair of VALID points with a sign change brackets a
    # solution (a None between two points breaks the bracket).
    crossings: list[tuple[float, float, float, float]] = []
    for a, b in zip(scanned, scanned[1:]):
        if a["metric"] is None or b["metric"] is None:
            continue
        fa, fb = a["metric"] - target, b["metric"] - target
        if fa * fb <= 0:
            crossings.append((a["value"], b["value"], fa, fb))
    if not crossings:
        return {
            "solvedValue": None,
            "reason": "no_crossing",
            "detail": (
                f"The metric never crosses the target over the scanned range "
                f"{lo:g} .. {hi:g}."
            ),
            "scanned": scanned,
            "scannedRange": [lo, hi],
        }

    # Multiple crossings: bisect the one nearest the current input; report
    # the midpoints of the others so the user knows they exist.
    crossings.sort(key=lambda c: abs((c[0] + c[1]) / 2 - current))
    a, b, fa, fb = crossings[0]
    other_crossings = [round((c[0] + c[1]) / 2, 10) for c in crossings[1:]]

    iterations = SCAN_POINTS
    best_value, best_metric = (a, fa + target) if abs(fa) <= abs(fb) else (b, fb + target)
    while iterations < MAX_ITERATIONS:
        mid = (a + b) / 2
        metric = evaluate(mid)
        iterations += 1
        if metric is None:
            return {
                "solvedValue": None,
                "reason": "metric_unavailable",
                "detail": f"The metric disappeared at {mid:g} during bisection.",
                "scanned": scanned,
                "scannedRange": [lo, hi],
            }
        fm = metric - target
        if abs(fm) <= abs(best_metric - target):
            best_value, best_metric = mid, metric
        if abs(fm) <= tolerance or (b - a) <= abs(hi - lo) * 1e-12:
            break
        if fa * fm <= 0:
            b, fb = mid, fm
        else:
            a, fa = mid, fm

    return {
        "solvedValue": best_value,
        "achievedMetric": best_metric,
        "iterations": iterations,
        "otherCrossings": other_crossings,
        "scannedRange": [lo, hi],
    }


def run_goal_seek(
    values: dict,
    target_input: str,
    output_metric: str,
    target_value: float,
    bounds: tuple[float, float] | None = None,
) -> dict:
    fields = numeric_input_fields()
    if target_input not in fields:
        raise GoalSeekError(f"'{target_input}' is not a numeric schema input.")
    tolerance = _metric_tolerance(output_metric)

    raw_current = values.get(target_input)
    current = float(raw_current) if isinstance(raw_current, (int, float)) else 0.0
    lo, hi = _resolve_bounds(fields[target_input], current, bounds)

    def evaluate(value: float) -> float | None:
        trial = {**values, target_input: value}
        try:
            result = compute_cache.cached_compute(trial)
        except engine.InsufficientInputsError:
            return None
        metric = result["outputs"].get(output_metric)
        return float(metric) if isinstance(metric, (int, float)) else None

    solution = _solve(evaluate, current, lo, hi, float(target_value), tolerance)
    solution["targetInput"] = target_input
    solution["outputMetric"] = output_metric
    solution["targetValue"] = float(target_value)
    solution["tolerance"] = tolerance
    return solution
