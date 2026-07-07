"""L4: an optional junior capital tranche (mezzanine debt or preferred
equity) ranking between senior debt and common equity. See DECISIONS.md's
L4 entry for the ranking/PIK/leverage-exclusion decisions. Acquisition-only
for this pass — see the entry for why (mirrors L1's scoping rationale)."""

from dataclasses import dataclass


@dataclass
class JuniorTrancheSizing:
    kind: str  # "mezz" | "pref_equity"
    amount: float
    rate_pct: float
    pay_mode: str  # "current" | "accrued"
    origination_fee: float


def size_junior_tranche(inputs: dict, senior_loan_amount: float, basis: float) -> JuniorTrancheSizing | None:
    """Returns None when no tranche is configured. fill_to_total_ltc sizes
    the junior tranche to whatever's needed to reach a target COMBINED
    senior+junior leverage against basis; senior sizing itself is never
    touched by this — it's purely an additive layer on top."""
    kind = inputs.get("juniorTrancheKind")
    if kind not in ("mezz", "pref_equity"):
        return None

    def _num(key: str, default: float = 0.0) -> float:
        value = inputs.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return float(value)

    sizing_mode = inputs.get("juniorTrancheSizing") or "fixed"
    if sizing_mode == "fill_to_total_ltc":
        target_pct = _num("juniorTrancheTotalLtcPct")
        amount = max(0.0, target_pct * basis - senior_loan_amount)
    else:
        amount = _num("juniorTrancheAmount")

    if amount <= 0:
        return None

    rate_pct = _num("juniorTrancheRatePct")
    pay_mode = inputs.get("juniorTranchePayMode") or "current"
    if pay_mode not in ("current", "accrued"):
        pay_mode = "current"
    origination_fee = amount * _num("juniorTrancheOriginationFeePct")

    return JuniorTrancheSizing(kind=kind, amount=amount, rate_pct=rate_pct, pay_mode=pay_mode, origination_fee=origination_fee)


def run_junior_tranche(
    sizing: JuniorTrancheSizing, noi: list[float], senior_debt_service: list[float],
) -> dict:
    """Month-by-month cash-flow logic for one tranche, given the deal's
    already-computed NOI and senior debt service vectors (both indexed
    0..total_months-1, i.e. month 1 = index 0). current-pay: monthly
    service = amount * rate/12, paid from whatever's left after senior
    debt service; a month where that residual can't cover it converts the
    SHORTFALL to PIK (accrues into the balance) rather than defaulting —
    the safer of the two options for a v1, and what the spec asks for.
    accrued mode: compounds monthly, zero cash service, full balance due
    at exit. Both rank AFTER senior debt service, BEFORE common equity —
    the caller subtracts serviceByMonth from levered cash flow and
    exitRepayment from levered at exit, after the senior payoff is already
    netted out."""
    total_months = len(noi)
    balance = sizing.amount
    monthly_rate = sizing.rate_pct / 12
    service_by_month = [0.0] * total_months
    interest_by_month = [0.0] * total_months
    balance_by_month = [0.0] * total_months
    shortfall_months: list[int] = []

    for m in range(total_months):
        interest_due = balance * monthly_rate
        if sizing.pay_mode == "accrued":
            balance += interest_due
            interest_by_month[m] = interest_due
        else:
            residual = max(0.0, noi[m] - senior_debt_service[m])
            paid = min(interest_due, residual)
            service_by_month[m] = paid
            interest_by_month[m] = interest_due
            if paid < interest_due - 1e-9:
                shortfall_months.append(m + 1)
                balance += interest_due - paid
        balance_by_month[m] = balance

    warnings = []
    if shortfall_months:
        warnings.append(
            f"Junior tranche current-pay service fell short of full coverage in "
            f"{len(shortfall_months)} month(s) (e.g. month {shortfall_months[0]}) — "
            "the shortfall converted to PIK (added to the outstanding balance) "
            "rather than defaulting."
        )

    return {
        "serviceByMonth": service_by_month,
        "interestByMonth": interest_by_month,
        "balanceByMonth": balance_by_month,
        "exitRepayment": balance,
        "warnings": warnings,
    }
