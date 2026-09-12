"""Tornado analysis: perturb one driver at a time through the native engine
and measure the swing in a chosen output metric. Orchestration only — every
number comes from engine.compute; the perturbation rules are input surgery,
not financial math.

Driver set (G4 spec): rent, exit cap, hard cost (purchase price for
acquisitions), opex, interest rate, vacancy. Percentages move +/-10%
RELATIVE; rate and cap move +/-50bps ABSOLUTE.
"""

import copy

from app.services.proforma import engine, leases, operations

RELATIVE_DELTA = 0.10
BPS_DELTA = 0.005

DRIVERS = [
    {"key": "rent", "label": "Rent"},
    {"key": "exitCap", "label": "Exit cap rate (±50 bps)"},
    # The cost driver's label is resolved per deal type at run time — it
    # perturbs hardCosts on developments and purchasePrice on acquisitions,
    # and the chart should say which one actually moved.
    {"key": "cost", "label": "Hard costs / purchase price"},
    {"key": "opex", "label": "Operating expenses"},
    {"key": "rate", "label": "Interest rate (±50 bps)"},
    {"key": "vacancy", "label": "Vacancy"},
]


def _driver_label(driver: dict, values: dict) -> str:
    if driver["key"] == "cost":
        return "Hard costs" if values.get("dealType") == "development" else "Purchase price"
    return driver["label"]

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


def _has_unit_mix(values: dict) -> bool:
    unit_mix = values.get("unitMix")
    return isinstance(unit_mix, list) and any(
        isinstance(r, dict) and r.get("unitCount") for r in unit_mix
    )


def inert_reason(values: dict, driver_key: str) -> str | None:
    """Run 6: why a driver cannot move THIS deal — the perturbed field is not
    read by the engine for the deal's shape. None when the driver is live.
    Mirrors the engine's own precedence rules (never a heuristic on the
    metric): a silent 0-impact bar used to be indistinguishable from a
    genuinely insensitive deal."""
    lease_driven = leases.has_leases(values)
    if driver_key == "opex" and operations.has_opex_detail(values):
        return (
            "Expenses are modeled as line items (opexLineItems) — the flat "
            "expense fields and managementFeePct this driver scales are not read."
        )
    if driver_key == "rent" and lease_driven and not _has_unit_mix(values):
        return (
            "Rent comes from the commercial rent roll (lease-level) — the flat "
            "GPR / rent-PSF fields this driver scales are not read."
        )
    if driver_key == "vacancy" and lease_driven and not _has_unit_mix(values):
        return (
            "Lease-modeled deals carry vacancy as rollover downtime — the "
            "vacancyPct input this driver scales never applies (H1)."
        )
    if driver_key == "rate" and values.get("rateMode") == "floating":
        return (
            "Floating-rate debt prices off currentIndexPct / spreadBps / the "
            "forward curve — the fixed interestRate this driver moves is not read."
        )
    if (
        driver_key == "exitCap"
        and values.get("dealType") == "acquisition"
        and (values.get("residentialExitCapPct") or 0) > 0
        and (values.get("commercialExitCapPct") or 0) > 0
        and values.get("propertyType") == "mixed_use"
    ):
        return (
            "Both component exit caps are set (residentialExitCapPct / "
            "commercialExitCapPct) — the blended exitCapRatePct does not price "
            "the exit of a mixed-use acquisition."
        )
    return None


def run_tornado(values: dict, metric: str = "leveredIrr") -> dict:
    """Returns {"metric", "base", "bars": [{key, label, low, high, impact,
    inert, reason?}]} sorted by impact descending. Drivers whose perturbed
    compute fails, or that don't move the metric, still appear (impact 0)
    so the chart is honest about what was tested. Run 6: a driver the deal
    shape cannot use is reported `inert: true` with a reason instead of a
    silent 0-impact bar (it is still computed — the zero corroborates)."""
    # Run 6 (P1): the tornado reads outputs[metric] only — every compute
    # skips the insurance-stress sub-computes (detail-mode deals with an
    # insurance line would otherwise run 3 engine passes per bar end).
    base_result = engine.compute({**values, "_skipCategoricalStress": True})
    base = base_result["outputs"].get(metric)
    if base is None:
        raise ValueError(
            f"Metric '{metric}' is not computable for this deal — pick another output."
        )

    bars = []
    for driver in DRIVERS:
        # Inert drivers are STILL computed: the shape rule names the cause,
        # the (zero) computed impact corroborates it, and the per-deal
        # compute count stays 2 x drivers + 1 (pinned by the P1 test).
        reason = inert_reason(values, driver["key"])
        low = high = None
        for direction, slot in ((-1, "low"), (1, "high")):
            try:
                perturbed = engine.compute(
                    {**perturb(values, driver["key"], direction), "_skipCategoricalStress": True}
                )
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
        bar = {
            "key": driver["key"], "label": _driver_label(driver, values),
            "low": low, "high": high, "impact": impact, "inert": reason is not None,
        }
        if reason is not None:
            bar["reason"] = reason
        bars.append(bar)

    bars.sort(key=lambda b: b["impact"], reverse=True)
    return {"metric": metric, "base": base, "bars": bars}
