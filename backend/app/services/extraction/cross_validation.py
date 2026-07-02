"""Sanity checks across whatever fields an extraction run produced. These
never block anything — they surface warnings next to the relevant fields on
the review screen so the user can eyeball a mismatch before confirming.
"""

_EXPENSE_RATIO_RANGE = (0.30, 0.55)  # opex / EGI, typical stabilized multifamily/commercial
_OCCUPANCY_LOW_WARNING = 0.75


def _val(fields: dict, key: str):
    entry = fields.get(key)
    return entry["value"] if entry else None


def run_checks(fields: dict) -> list[dict]:
    checks: list[dict] = []

    rr_gpr_annual = _val(fields, "_rentRollGprAnnual")  # internal, set by extraction_service
    t12_gpr = _val(fields, "grossPotentialRent")
    if rr_gpr_annual and t12_gpr:
        diff_pct = abs(rr_gpr_annual - t12_gpr) / t12_gpr
        if diff_pct > 0.10:
            checks.append(
                {
                    "severity": "warning",
                    "message": (
                        f"Rent-roll gross potential rent (${rr_gpr_annual:,.0f}/yr) differs from the "
                        f"T-12's (${t12_gpr:,.0f}/yr) by {diff_pct * 100:.0f}% — worth reconciling."
                    ),
                    "relatedFieldIds": ["grossPotentialRent"],
                }
            )

    price = _val(fields, "purchasePrice") or _val(fields, "totalCostBasis")
    noi = _val(fields, "_noi")  # internal, set by extraction_service
    stated_cap_rate = _val(fields, "_statedCapRate")
    if price and noi and stated_cap_rate:
        implied_cap_rate = noi / price
        diff_bps = abs(implied_cap_rate - stated_cap_rate) * 10000
        if diff_bps > 50:
            checks.append(
                {
                    "severity": "warning",
                    "message": (
                        f"NOI ÷ price implies a {implied_cap_rate * 100:.2f}% cap rate, vs. the "
                        f"{stated_cap_rate * 100:.2f}% stated — a {diff_bps:.0f} bps gap."
                    ),
                    "relatedFieldIds": ["purchasePrice"],
                }
            )

    occupancy = _val(fields, "_occupancyPct")
    if occupancy is not None and occupancy < _OCCUPANCY_LOW_WARNING:
        checks.append(
            {
                "severity": "info",
                "message": f"Extracted occupancy is {occupancy * 100:.0f}%, low enough to double-check against the source.",
                "relatedFieldIds": ["vacancyPct"],
            }
        )

    egi = t12_gpr - (_val(fields, "vacancyPct") or 0) * t12_gpr if t12_gpr else None
    total_expenses = _val(fields, "_totalExpenses")
    if egi and total_expenses:
        ratio = total_expenses / egi
        if not (_EXPENSE_RATIO_RANGE[0] <= ratio <= _EXPENSE_RATIO_RANGE[1]):
            checks.append(
                {
                    "severity": "info",
                    "message": (
                        f"Operating expenses are {ratio * 100:.0f}% of income, outside the typical "
                        f"{_EXPENSE_RATIO_RANGE[0] * 100:.0f}–{_EXPENSE_RATIO_RANGE[1] * 100:.0f}% range — "
                        "not necessarily wrong, worth a second look."
                    ),
                    "relatedFieldIds": ["realEstateTaxes", "insurance", "utilities"],
                }
            )

    return checks
