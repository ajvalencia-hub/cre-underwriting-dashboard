"""Tornado analysis: perturb one driver at a time through the native engine
and measure the swing in a chosen output metric. Orchestration only — every
number comes from engine.compute; the perturbation rules are input surgery,
not financial math.

Driver set (G4 spec): rent, exit cap, hard cost (purchase price for
acquisitions), opex, interest rate, vacancy. Percentages move +/-10%
RELATIVE; rate and cap move +/-50bps ABSOLUTE.
"""

import copy

from app.services.proforma import engine

RELATIVE_DELTA = 0.10
BPS_DELTA = 0.005

DRIVERS = [
    {"key": "rent", "label": "Rent"},
    {"key": "exitCap", "label": "Exit cap rate (±50 bps)"},
    {"key": "cost", "label": "Hard costs / purchase price"},
    {"key": "opex", "label": "Operating expenses"},
    {"key": "rate", "label": "Interest rate (±50 bps)"},
    {"key": "vacancy", "label": "Vacancy"},
]

_OPEX_FIELDS = [
    "realEstateTaxes", "insurance", "utilities", "repairsMaintenance",
    "payroll", "generalAdmin", "replacementReserves",
]


def _scaled(value, factor: float):
    return value * factor if isinstance(value, (int, float)) else value


def perturb(values: dict, driver_key: str, direction: int) -> dict:
    """Returns a copy of `values` with the driver moved up (+1) or down (-1).
    Rules mirror how each driver actually enters the engine."""
    out = copy.deepcopy(values)
    factor = 1 + direction * RELATIVE_DELTA

    if driver_key == "rent":
        unit_mix = out.get("unitMix")
        if isinstance(unit_mix, list) and any(
            isinstance(r, dict) and r.get("unitCount") for r in unit_mix
        ):
            for row in unit_mix:
                if isinstance(row, dict):
                    for field in ("inPlaceRent", "marketRent"):
                        if isinstance(row.get(field), (int, float)):
                            row[field] = row[field] * factor
        elif isinstance(out.get("rentPsf"), (int, float)) and out.get("rentPsf"):
            out["rentPsf"] = out["rentPsf"] * factor
        elif isinstance(out.get("officeRentPsf"), (int, float)) and out.get("officeRentPsf"):
            out["officeRentPsf"] = out["officeRentPsf"] * factor
        else:
            out["grossPotentialRent"] = _scaled(out.get("grossPotentialRent", 0), factor)
    elif driver_key == "exitCap":
        out["exitCapRatePct"] = (out.get("exitCapRatePct") or 0) + direction * BPS_DELTA
    elif driver_key == "cost":
        if out.get("dealType") == "development":
            out["hardCosts"] = _scaled(out.get("hardCosts", 0), factor)
        else:
            out["purchasePrice"] = _scaled(out.get("purchasePrice", 0), factor)
    elif driver_key == "opex":
        for field in _OPEX_FIELDS:
            if isinstance(out.get(field), (int, float)):
                out[field] = out[field] * factor
        if isinstance(out.get("managementFeePct"), (int, float)):
            out["managementFeePct"] = out["managementFeePct"] * factor
    elif driver_key == "rate":
        out["interestRate"] = (out.get("interestRate") or 0) + direction * BPS_DELTA
    elif driver_key == "vacancy":
        out["vacancyPct"] = (out.get("vacancyPct") or 0) * factor
    else:
        raise ValueError(f"Unknown tornado driver '{driver_key}'")
    return out


def run_tornado(values: dict, metric: str = "leveredIrr") -> dict:
    """Returns {"metric", "base", "bars": [{key, label, low, high, impact}]}
    sorted by impact descending. Drivers whose perturbed compute fails, or
    that don't move the metric, still appear (impact 0) so the chart is
    honest about what was tested."""
    base_result = engine.compute(values)
    base = base_result["outputs"].get(metric)
    if base is None:
        raise ValueError(
            f"Metric '{metric}' is not computable for this deal — pick another output."
        )

    bars = []
    for driver in DRIVERS:
        low = high = None
        for direction, slot in ((-1, "low"), (1, "high")):
            try:
                perturbed = engine.compute(perturb(values, driver["key"], direction))
                value = perturbed["outputs"].get(metric)
            except engine.InsufficientInputsError:
                value = None
            if slot == "low":
                low = value
            else:
                high = value
        impact = max(
            abs(low - base) if low is not None else 0.0,
            abs(high - base) if high is not None else 0.0,
        )
        bars.append(
            {"key": driver["key"], "label": driver["label"], "low": low, "high": high, "impact": impact}
        )

    bars.sort(key=lambda b: b["impact"], reverse=True)
    return {"metric": metric, "base": base, "bars": bars}
