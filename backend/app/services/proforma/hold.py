"""Hold-period sweep and the refi-vs-sale-at-stabilization comparison.

Pure consumers of engine.compute — every row is a full engine run at a
different exit assumption; nothing here re-implements a formula.
"""

import math

from app.services.proforma import engine
from app.services.proforma.timeline import build_timeline


def _num(inputs: dict, field: str, default: float = 0.0) -> float:
    value = inputs.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def hold_sweep(inputs: dict) -> dict:
    """Re-evaluate the deal for each whole exit year from stabilization+1
    (year 1 for day-one-stabilized acquisitions) through the modeled hold.
    Returns {"rows": [{holdYear, unleveredIrr, leveredIrr, equityMultiple,
    netProceeds}], "modeledHoldYears", "warnings"}."""
    warnings: list[str] = []
    modeled_hold = _num(inputs, "holdPeriodYears")
    if modeled_hold <= 0:
        return {"rows": [], "modeledHoldYears": 0, "warnings": ["No hold period set."]}

    timeline, _ = build_timeline(
        inputs.get("dealType") or "acquisition",
        modeled_hold,
        construction_months=_num(inputs, "constructionMonths") or None,
        lease_up_months=_num(inputs, "leaseUpMonths") or None,
        stabilization_month=_num(inputs, "stabilizationMonth") or None,
    )
    stabilization_year = math.ceil(timeline.stabilization_month / 12)
    first_year = 1 if timeline.stabilization_month <= 1 else stabilization_year + 1

    if first_year > int(modeled_hold):
        return {
            "rows": [],
            "modeledHoldYears": modeled_hold,
            "warnings": [
                f"The deal stabilizes in year {stabilization_year}, at or after the "
                f"modeled {modeled_hold:g}-year hold — no post-stabilization exit "
                "years exist to sweep. Extend the hold period to analyze exits."
            ],
        }

    rows = []
    for hold_year in range(first_year, int(modeled_hold) + 1):
        try:
            result = engine.compute({**inputs, "holdPeriodYears": hold_year})
        except engine.InsufficientInputsError as exc:
            warnings.append(f"Hold year {hold_year}: not computable ({', '.join(exc.missing)})")
            continue
        outputs = result["outputs"]
        rows.append(
            {
                "holdYear": hold_year,
                "unleveredIrr": outputs.get("unleveredIrr"),
                "leveredIrr": outputs.get("leveredIrr"),
                "equityMultiple": outputs.get("equityMultiple"),
                "netProceeds": outputs.get("netSaleProceeds"),
            }
        )
    return {"rows": rows, "modeledHoldYears": modeled_hold, "warnings": warnings}


def refi_vs_sale(inputs: dict) -> dict:
    """Compare selling AT stabilization against refinancing at stabilization
    (the engine's perm takeout, priced at rate + refiRateSpreadPct with
    refiCostsPct costs) and holding to the modeled exit. Returns None-able
    sides with warnings instead of crashing on degenerate deals."""
    warnings: list[str] = []
    modeled_hold = _num(inputs, "holdPeriodYears")
    timeline, _ = build_timeline(
        inputs.get("dealType") or "acquisition",
        modeled_hold,
        construction_months=_num(inputs, "constructionMonths") or None,
        lease_up_months=_num(inputs, "leaseUpMonths") or None,
        stabilization_month=_num(inputs, "stabilizationMonth") or None,
    )
    stabilization_month = timeline.stabilization_month
    if stabilization_month <= 1:
        return {
            "saleAtStabilization": None,
            "holdThroughRefi": None,
            "warnings": ["The deal is stabilized at close — a stabilization refi/sale fork doesn't apply."],
        }
    if stabilization_month > timeline.total_months:
        return {
            "saleAtStabilization": None,
            "holdThroughRefi": None,
            "warnings": [
                "The deal never stabilizes inside the modeled hold — extend the hold "
                "period to analyze the stabilization refi-vs-sale fork."
            ],
        }

    sale_hold_years = stabilization_month / 12
    try:
        sale = engine.compute({**inputs, "holdPeriodYears": sale_hold_years})
        sale_side = {
            "holdYears": round(sale_hold_years, 2),
            "leveredIrr": sale["outputs"].get("leveredIrr"),
            "equityMultiple": sale["outputs"].get("equityMultiple"),
            "netProceeds": sale["outputs"].get("netSaleProceeds"),
        }
    except engine.InsufficientInputsError as exc:
        sale_side = None
        warnings.append(f"Sale-at-stabilization not computable: {', '.join(exc.missing)}")

    try:
        base = engine.compute(inputs)
        statement = base["statement"]
        takeout = min(stabilization_month, len(statement["debtDraws"]) - 1)
        refi_side = {
            "holdYears": modeled_hold,
            "leveredIrr": base["outputs"].get("leveredIrr"),
            "equityMultiple": base["outputs"].get("equityMultiple"),
            "refiLoan": (base["debt"] or {}).get("loanAmount"),
            "governingConstraint": (base["debt"] or {}).get("governingConstraint"),
            # Cash-out (+) or paydown (-) at takeout, and the explicit costs.
            "cashOutProceeds": statement["debtDraws"][takeout],
            "refiCosts": statement["loanFees"][takeout],
        }
        warnings.extend(w for w in base["warnings"] if "paydown" in w)
    except engine.InsufficientInputsError as exc:
        refi_side = None
        warnings.append(f"Hold-through-refi not computable: {', '.join(exc.missing)}")

    return {"saleAtStabilization": sale_side, "holdThroughRefi": refi_side, "warnings": warnings}
