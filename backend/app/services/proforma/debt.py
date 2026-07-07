"""Debt mechanics: amortization, construction financing, takeout.

Conventions (see DECISIONS.md):
- Monthly rate = annual / 12 (30/360-style, the standard for CRE loan
  amortization schedules); payments monthly in arrears.
- Construction: equity funds first, then the loan draws (the institutional
  norm — lenders require equity ahead of their money). Interest accrues on
  the drawn balance and is capitalized into the balance (funded by the loan,
  as an interest reserve would be), NOT paid from operations.
- Permanent takeout at stabilization refinances the construction balance at
  par (no cash-out) in F2; constraint-based sizing arrives with the debt
  module feature (F3).
"""

from dataclasses import dataclass


def monthly_payment(principal: float, annual_rate: float, amort_years: float) -> float:
    """Standard level-payment mortgage PMT."""
    if principal <= 0:
        return 0.0
    n = round(amort_years * 12)
    if n <= 0:
        return principal  # degenerate: no amortization period -> due now
    r = annual_rate / 12
    if r == 0:
        return principal / n
    return principal * r / (1 - (1 + r) ** -n)


@dataclass(frozen=True)
class DebtServiceMonth:
    interest: float
    principal: float
    balance: float  # end-of-month balance

    @property
    def payment(self) -> float:
        return self.interest + self.principal


def amortization_schedule(
    principal: float,
    annual_rate: float | list[float],
    amort_years: float,
    io_months: int,
    months: int,
) -> list[DebtServiceMonth]:
    """Monthly schedule for `months` periods: IO for io_months, then level
    amortizing payments on the full amortization curve.

    `annual_rate` is normally a constant float (unchanged behavior). L5:
    passing a per-month list instead switches to a FLOATING-rate schedule —
    see DECISIONS.md for why a fixed payment computed once at close is
    wrong for these: the level payment is recomputed each amortizing month
    against the CURRENT rate and the REMAINING amortizing term (the
    standard ARM/floating-CRE-loan convention), never a payment fixed at
    the original rate for the life of the loan. The remaining-term clock
    only starts counting down once amortization actually begins — an IO
    period never shrinks it (matching the fixed-rate convention above,
    where `amort_years` is always the FULL original term regardless of
    `io_months`) — which is what makes a constant-rate floating schedule
    reproduce the fixed schedule exactly, IO period included."""
    schedule: list[DebtServiceMonth] = []
    if principal <= 0 or months <= 0:
        return [DebtServiceMonth(0.0, 0.0, 0.0) for _ in range(max(0, months))]

    is_floating = isinstance(annual_rate, list)
    balance = principal
    fixed_payment = None if is_floating else monthly_payment(principal, annual_rate, amort_years)

    for month in range(1, months + 1):
        rate = annual_rate[month - 1] if is_floating else annual_rate
        r = rate / 12
        interest = balance * r
        if month <= io_months:
            principal_paid = 0.0
        else:
            if is_floating:
                elapsed_amortizing_months = month - io_months - 1
                remaining_years = max(amort_years - elapsed_amortizing_months / 12, 1 / 12)
                payment = monthly_payment(balance, rate, remaining_years)
            else:
                payment = fixed_payment
            principal_paid = min(payment - interest, balance)
            principal_paid = max(principal_paid, 0.0)
        balance -= principal_paid
        schedule.append(DebtServiceMonth(interest, principal_paid, balance))
    return schedule


def resolve_floating_rate_schedule(
    spread_bps: float,
    floor_pct: float | None,
    forward_curve: list[dict],
    current_index_pct: float,
    rate_cap: dict | None,
    months: int,
) -> list[float]:
    """L5: month-by-month ALL-IN annual rate for a floating-rate loan.

    Step interpolation (curve value at the largest `month` <= the target
    month wins) — no smoothing, matching every other growth-curve
    convention already in this codebase (annual step-ups, not continuous
    compounding). No explicit forwardCurve -> a flat one-point curve seeded
    from currentIndexPct. A rate cap, if present, caps the ALL-IN rate
    (index+spread) at strike+spread for months within its term — the cap
    protects the borrower's total cost, not the index in isolation."""
    curve = sorted(
        ({"month": int(p["month"]), "indexPct": float(p["indexPct"])} for p in forward_curve),
        key=lambda p: p["month"],
    ) if forward_curve else [{"month": 0, "indexPct": current_index_pct}]

    spread = spread_bps / 10000
    cap_strike = float(rate_cap["strikePct"]) if rate_cap else None
    cap_term = int(rate_cap["termMonths"]) if rate_cap else 0

    rates: list[float] = []
    index_pct = curve[0]["indexPct"]
    for m in range(1, months + 1):
        for point in curve:
            if point["month"] <= m:
                index_pct = point["indexPct"]
            else:
                break
        rate = max(index_pct, floor_pct) if floor_pct is not None else index_pct
        rate += spread
        if cap_strike is not None and m <= cap_term:
            rate = min(rate, cap_strike + spread)
        rates.append(rate)
    return rates


@dataclass(frozen=True)
class PermSizing:
    amount: float
    governing_constraint: str  # 'ltv' | 'dscr' | 'debtYield' | 'none'
    candidates: dict[str, float]


def annual_loan_constant(annual_rate: float, amort_years: float) -> float:
    """Annual debt service per dollar of loan. Fully-IO loans (amort_years=0)
    have a constant equal to the rate."""
    if amort_years <= 0:
        return annual_rate
    return 12 * monthly_payment(1.0, annual_rate, amort_years)


def size_permanent_loan(
    sizing_noi: float,
    value: float,
    max_ltv: float,
    min_dscr: float,
    min_debt_yield: float,
    annual_rate: float,
    amort_years: float,
) -> PermSizing:
    """Sized loan = min(LTV x value, DSCR-constrained amount, NOI / debt-yield
    floor). DSCR sizes on the AMORTIZING constant even when the loan carries
    an IO period (the standard lender convention — the IO payment is never
    the sizing basis unless the loan is fully interest-only, i.e. amort=0)."""
    candidates: dict[str, float] = {}
    if max_ltv > 0 and value > 0:
        candidates["ltv"] = max_ltv * value
    constant = annual_loan_constant(annual_rate, amort_years)
    if min_dscr > 0 and sizing_noi > 0 and constant > 0:
        candidates["dscr"] = sizing_noi / min_dscr / constant
    if min_debt_yield > 0 and sizing_noi > 0:
        candidates["debtYield"] = sizing_noi / min_debt_yield

    if not candidates:
        return PermSizing(0.0, "none", {})
    governing = min(candidates, key=lambda k: candidates[k])
    return PermSizing(candidates[governing], governing, candidates)


def stress_matrix(
    sizing_noi: float,
    value: float,
    loan_amount: float,
    max_ltv: float,
    min_dscr: float,
    min_debt_yield: float,
    annual_rate: float,
    amort_years: float,
    rate_bumps_bps: tuple[int, ...] = (0, 100, 200),
    noi_haircuts: tuple[float, ...] = (0.0, 0.05, 0.10),
) -> list[dict]:
    """Rate/NOI stress grid. Each cell reports the DSCR on the EXISTING loan
    (repriced at the stressed rate — the refi-risk question) and the refi
    proceeds a lender would size at the stressed rate and NOI. The stressed
    value scales linearly with NOI (same cap rate)."""
    cells: list[dict] = []
    for bump in rate_bumps_bps:
        stressed_rate = annual_rate + bump / 10000
        for haircut in noi_haircuts:
            stressed_noi = sizing_noi * (1 - haircut)
            stressed_value = value * (1 - haircut)
            constant = annual_loan_constant(stressed_rate, amort_years)
            dscr = (
                stressed_noi / (loan_amount * constant)
                if loan_amount > 0 and constant > 0
                else None
            )
            resized = size_permanent_loan(
                stressed_noi, stressed_value, max_ltv, min_dscr, min_debt_yield,
                stressed_rate, amort_years,
            )
            cells.append(
                {
                    "rateBumpBps": bump,
                    "noiHaircutPct": haircut,
                    "dscr": dscr,
                    "refiProceeds": resized.amount,
                    "governingConstraint": resized.governing_constraint,
                    "refiShortfall": max(0.0, loan_amount - resized.amount),
                }
            )
    return cells


@dataclass(frozen=True)
class ConstructionFinancing:
    draws: list[float]  # loan draw per month (0..construction end)
    equity_funded: list[float]  # equity outflow per month
    interest_capitalized: float  # total capitalized interest
    fee_capitalized: float  # origination fee drawn into the balance
    ending_balance: float  # loan balance at construction end
    balances: list[float]  # end-of-month balance per month


def construction_financing(
    cost_schedule: list[float],
    total_equity: float,
    annual_rate: float,
    origination_fee_pct: float = 0.0,
) -> ConstructionFinancing:
    """Equity-first funding of a monthly cost schedule; loan interest accrues
    on the drawn balance and is capitalized (added to the balance). The
    origination fee is drawn at the first loan draw.

    L5 scoping note (DECISIONS.md): floating-rate debt applies to the
    PERMANENT loan only (acquisition's single loan, or development's
    takeout) — construction-phase financing stays fixed-rate always, a
    deliberate v1 simplification, not an oversight."""
    r = annual_rate / 12
    equity_remaining = total_equity
    balance = 0.0
    fee_total = 0.0

    draws: list[float] = []
    equity_funded: list[float] = []
    balances: list[float] = []
    interest_total = 0.0

    for month, cost in enumerate(cost_schedule):
        equity_used = min(equity_remaining, cost)
        equity_remaining -= equity_used
        draw = cost - equity_used

        if draw > 0 and fee_total == 0.0 and origination_fee_pct > 0:
            # Fee is computed on the eventual commitment; charging it on the
            # first draw against the drawn balance is the simplification here
            # (F2); it capitalizes like interest.
            fee_total = draw * origination_fee_pct
            balance += fee_total

        balance += draw
        # Interest for the month on the average of open/close balance would be
        # more precise; the standard draw model accrues on the ending balance
        # of the prior month plus current draws at mid-month. Keep it simple
        # and defensible: accrue on the post-draw balance for months >= 1,
        # nothing at month 0 (closing).
        interest = balance * r if month >= 1 else 0.0
        balance += interest
        interest_total += interest

        draws.append(draw)
        equity_funded.append(equity_used)
        balances.append(balance)

    return ConstructionFinancing(
        draws=draws,
        equity_funded=equity_funded,
        interest_capitalized=interest_total,
        fee_capitalized=fee_total,
        ending_balance=balance,
        balances=balances,
    )
