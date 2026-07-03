"""Named cross-validation rules over an extraction run's fields.

Each rule returns {rule, status, severity, detail, relatedFieldIds}:
- status: "pass" | "warn" | "fail" (fail requires an explicit user
  acknowledgment on the review screen before Apply — still never a hard
  block, per this app's human-review-gate principle).
- A rule that can't be evaluated (its inputs weren't extracted) emits
  nothing, so the review screen only shows checks that actually ran.
"""

# Tunable bands — deliberately module-level constants, not buried literals.
GPR_TOLERANCE_WARN = 0.10  # rent-roll vs T-12 GPR relative difference
GPR_TOLERANCE_FAIL = 0.25
EXPENSE_RATIO_BAND = (0.30, 0.55)  # opex / EGI, typical stabilized range
OCCUPANCY_VS_VACANCY_TOLERANCE = 0.05
LOW_OCCUPANCY_THRESHOLD = 0.75
CAP_RATE_GAP_WARN_BPS = 50

_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

_SEVERITY = {"pass": "info", "warn": "warning", "fail": "error"}


def _rule(rule: str, status: str, detail: str, related: list[str] | None = None) -> dict:
    return {
        "rule": rule,
        "status": status,
        "severity": _SEVERITY[status],
        "detail": detail,
        "relatedFieldIds": related or [],
    }


def _val(fields: dict, key: str):
    entry = fields.get(key)
    return entry["value"] if entry else None


def _check_rent_roll_vs_t12_gpr(fields: dict) -> list[dict]:
    rr_gpr = _val(fields, "_rentRollGprAnnual")
    t12_gpr = _val(fields, "grossPotentialRent")
    if not rr_gpr or not t12_gpr:
        return []
    diff = abs(rr_gpr - t12_gpr) / t12_gpr
    detail = (
        f"Rent-roll GPR ${rr_gpr:,.0f}/yr vs T-12 GPR ${t12_gpr:,.0f}/yr "
        f"({diff * 100:.0f}% apart)."
    )
    if diff > GPR_TOLERANCE_FAIL:
        status = "fail"
    elif diff > GPR_TOLERANCE_WARN:
        status = "warn"
    else:
        status = "pass"
    return [_rule("rent_roll_vs_t12_gpr", status, detail, ["grossPotentialRent"])]


def _check_unit_count_consistency(fields: dict) -> list[dict]:
    total_units = _val(fields, "_rentRollTotalUnits")
    unit_mix = _val(fields, "unitMix")
    if not total_units or not isinstance(unit_mix, list):
        return []
    mix_total = sum(
        row.get("unitCount") or 0 for row in unit_mix if isinstance(row, dict)
    )
    if mix_total == total_units:
        return [
            _rule(
                "unit_count_consistency", "pass",
                f"Unit mix totals {mix_total} units, matching the {total_units} rent-roll rows.",
                ["unitMix"],
            )
        ]
    return [
        _rule(
            "unit_count_consistency", "fail",
            f"Unit mix totals {mix_total} units but the rent roll parsed {total_units} rows "
            "— rows were lost or double-grouped during aggregation.",
            ["unitMix"],
        )
    ]


def _check_t12_month_coverage(fields: dict) -> list[dict]:
    months = _val(fields, "_t12Months")
    period_type = _val(fields, "_t12PeriodType")
    if period_type is None:
        return []
    if period_type == "annual":
        return [
            _rule(
                "t12_month_coverage", "warn",
                "Operating statement has an annual total only — monthly seasonality and "
                "partial-year artifacts can't be checked.",
            )
        ]
    if not isinstance(months, list):
        return []
    normalized = [str(m).strip().lower()[:3] for m in months]
    indexes = [_MONTHS.index(m) for m in normalized if m in _MONTHS]
    distinct = len(set(indexes))
    if period_type in ("T3", "T6"):
        return [
            _rule(
                "t12_month_coverage", "warn",
                f"Statement covers {distinct} month(s) ({period_type}) and was annualized — "
                "seasonality is extrapolated.",
            )
        ]
    if distinct == 12:
        # Contiguity: sorted month indexes must be consecutive mod 12 — with
        # all 12 present that's automatic, so this is a clean pass.
        return [_rule("t12_month_coverage", "pass", "T-12 covers 12 distinct months.")]
    duplicates = len(indexes) - distinct
    detail = f"T-12 shows {distinct} distinct month column(s)"
    if duplicates:
        detail += f" with {duplicates} duplicate(s)"
    detail += " — a full trailing-12 needs 12 distinct months with no gaps."
    return [_rule("t12_month_coverage", "fail", detail)]


def _check_occupancy_vs_t12_vacancy(fields: dict) -> list[dict]:
    occupancy = _val(fields, "_occupancyPct")
    vacancy = _val(fields, "vacancyPct")
    checks: list[dict] = []
    if occupancy is not None and vacancy is not None:
        implied_occupancy = 1 - vacancy
        delta = abs(occupancy - implied_occupancy)
        detail = (
            f"Rent-roll occupancy {occupancy * 100:.0f}% vs {implied_occupancy * 100:.0f}% "
            f"implied by the T-12 vacancy ({vacancy * 100:.1f}%)."
        )
        status = "pass" if delta <= OCCUPANCY_VS_VACANCY_TOLERANCE else "warn"
        checks.append(_rule("occupancy_vs_t12_vacancy", status, detail, ["vacancyPct"]))
    if occupancy is not None and occupancy < LOW_OCCUPANCY_THRESHOLD:
        checks.append(
            _rule(
                "low_occupancy", "warn",
                f"Extracted occupancy is {occupancy * 100:.0f}% — low enough to double-check "
                "against the source.",
                ["vacancyPct"],
            )
        )
    return checks


def _check_expense_ratio(fields: dict) -> list[dict]:
    t12_gpr = _val(fields, "grossPotentialRent")
    vacancy = _val(fields, "vacancyPct") or 0
    total_expenses = _val(fields, "_totalExpenses")
    if not t12_gpr or not total_expenses:
        return []
    egi = t12_gpr * (1 - vacancy)
    if egi <= 0:
        return []
    ratio = total_expenses / egi
    low, high = EXPENSE_RATIO_BAND
    detail = (
        f"Operating expenses are {ratio * 100:.0f}% of income "
        f"(typical band {low * 100:.0f}–{high * 100:.0f}%)."
    )
    # Flag, never block: an unusual ratio can be legitimate.
    status = "pass" if low <= ratio <= high else "warn"
    return [
        _rule("expense_ratio_sanity", status, detail, ["realEstateTaxes", "insurance", "utilities"])
    ]


def _check_cap_rate_consistency(fields: dict) -> list[dict]:
    price = _val(fields, "purchasePrice") or _val(fields, "totalCostBasis")
    noi = _val(fields, "_noi")
    stated = _val(fields, "_statedCapRate")
    if not price or not noi or not stated:
        return []
    implied = noi / price
    gap_bps = abs(implied - stated) * 10000
    detail = (
        f"NOI ÷ price implies a {implied * 100:.2f}% cap rate vs the {stated * 100:.2f}% "
        f"stated ({gap_bps:.0f} bps apart)."
    )
    status = "pass" if gap_bps <= CAP_RATE_GAP_WARN_BPS else "warn"
    return [_rule("cap_rate_consistency", status, detail, ["purchasePrice"])]


def run_checks(fields: dict) -> list[dict]:
    checks: list[dict] = []
    checks += _check_rent_roll_vs_t12_gpr(fields)
    checks += _check_unit_count_consistency(fields)
    checks += _check_t12_month_coverage(fields)
    checks += _check_occupancy_vs_t12_vacancy(fields)
    checks += _check_expense_ratio(fields)
    checks += _check_cap_rate_consistency(fields)
    return checks
