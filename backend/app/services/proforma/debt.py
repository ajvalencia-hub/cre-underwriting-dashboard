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


def floating_rate_vector(inputs: dict, months: int) -> list[float] | None:
    """J5: the loan's annual rate per month 1..months, or None for fixed
    mode. rate(m) = max(index(m), floor) + spread, capped at strike + spread
    while the cap is in force. The forward curve is a STEP function ([FIN]:
    no smoothing — curve points are the user's assumption, not samples of a
    smooth process); before the first point the index is currentIndexPct."""
    if inputs.get("rateMode") != "floating":
        return None

    def _n(key: str, default: float = 0.0) -> float:
        value = inputs.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return float(value)

    current = _n("currentIndexPct")
    spread = _n("spreadBps") / 10_000
    floor_raw = inputs.get("floorPct")
    floor = (
        float(floor_raw)
        if isinstance(floor_raw, (int, float)) and not isinstance(floor_raw, bool)
        else None
    )
    points = sorted(
        (
            (int(row["month"]), float(row["indexPct"]))
            for row in (inputs.get("forwardCurve") or [])
            if isinstance(row, dict)
            and isinstance(row.get("month"), (int, float))
            and isinstance(row.get("indexPct"), (int, float))
        ),
        key=lambda p: p[0],
    )
    strike = _n("rateCapStrikePct")
    cap_term = int(_n("rateCapTermMonths"))
    cap_active = strike > 0 and cap_term > 0

    rates: list[float] = []
    for m in range(1, months + 1):
        index = current
        for point_month, point_index in points:
            if point_month <= m:
                index = point_index
            else:
                break
        if floor is not None:
            index = max(index, floor)
        rate = index + spread
        if cap_active and m <= cap_term:
            rate = min(rate, strike + spread)
        rates.append(rate)
    return rates


def amortization_schedule_floating(
    principal: float,
    rate_vector: list[float],
    amort_years: float,
    io_months: int,
    months: int,
) -> list[DebtServiceMonth]:
    """J5: ARM-style floating amortization — each amortizing month's payment
    is recomputed at that month's rate over the REMAINING amortization
    ([FIN]: reprices like an ARM; freezing the payment at the initial rate
    was rejected — it silently un-floats the principal path)."""
    schedule: list[DebtServiceMonth] = []
    if principal <= 0 or months <= 0:
        return [DebtServiceMonth(0.0, 0.0, 0.0) for _ in range(max(0, months))]

    balance = principal
    total_amort_months = round(amort_years * 12)
    for month in range(1, months + 1):
        rate = rate_vector[month - 1] if month - 1 < len(rate_vector) else rate_vector[-1]
        r = rate / 12
        interest = balance * r
        if month <= io_months or total_amort_months <= 0:
            principal_paid = 0.0
        else:
            remaining = max(1, total_amort_months - (month - io_months - 1))
            if r == 0:
                payment = balance / remaining
            else:
                payment = balance * r / (1 - (1 + r) ** -remaining)
            principal_paid = min(max(payment - interest, 0.0), balance)
        balance -= principal_paid
        schedule.append(DebtServiceMonth(interest, principal_paid, balance))
    return schedule


def amortization_schedule(
    principal: float,
    annual_rate: float,
    amort_years: float,
    io_months: int,
    months: int,
) -> list[DebtServiceMonth]:
    """Monthly schedule for `months` periods: IO for io_months, then level
    amortizing payments on the full amortization curve."""
    schedule: list[DebtServiceMonth] = []
    if principal <= 0 or months <= 0:
        return [DebtServiceMonth(0.0, 0.0, 0.0) for _ in range(max(0, months))]

    r = annual_rate / 12
    balance = principal
    payment = monthly_payment(principal, annual_rate, amort_years)

    for month in range(1, months + 1):
        interest = balance * r
        if month <= io_months:
            principal_paid = 0.0
        else:
            principal_paid = min(payment - interest, balance)
            principal_paid = max(principal_paid, 0.0)
        balance -= principal_paid
        schedule.append(DebtServiceMonth(interest, principal_paid, balance))
    return schedule


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


def size_construction_loan(
    cost_schedule: list[float],
    budget_ex_financing: float,
    ltc: float,
    annual_rate: float,
    origination_fee_pct: float = 0.0,
    rate_vector: list[float] | None = None,
) -> tuple[ConstructionFinancing, float, float]:
    """LTC on TOTAL cost, financing included (lender convention: the interest
    reserve and loan fees sit inside the cost the LTC is measured on).

    Circular — interest depends on the loan, the loan on total cost — so
    solve by fixed-point iteration: equity = (1 - LTC) x total cost, loan
    commitment = LTC x total cost. It contracts (each pass changes financing
    cost by ~LTC x rate x time of the previous change) and converges in a
    handful of passes. Returns (financing, equity, commitment); the ending
    construction balance equals the commitment.
    """
    total = budget_ex_financing
    financing = None
    for _ in range(200):
        commitment = ltc * total
        equity = total - commitment
        financing = construction_financing(
            cost_schedule, equity, annual_rate, origination_fee_pct,
            rate_vector=rate_vector, commitment=commitment,
        )
        new_total = budget_ex_financing + financing.interest_capitalized + financing.fee_capitalized
        if abs(new_total - total) < 1e-7:
            total = new_total
            break
        total = new_total
    commitment = ltc * total
    equity = total - commitment
    financing = construction_financing(
        cost_schedule, equity, annual_rate, origination_fee_pct,
        rate_vector=rate_vector, commitment=commitment,
    )
    return financing, equity, commitment


def construction_financing(
    cost_schedule: list[float],
    total_equity: float,
    annual_rate: float,
    origination_fee_pct: float = 0.0,
    rate_vector: list[float] | None = None,
    commitment: float | None = None,
) -> ConstructionFinancing:
    """Equity-first funding of a monthly cost schedule; loan interest accrues
    on the drawn balance and is capitalized (added to the balance). The
    origination fee is charged on the loan commitment and capitalized at the
    first loan draw (without a commitment — direct callers only — on that
    draw). J5: when rate_vector is given (annual rate per deal month 1..n),
    construction interest accrues at that month's floating rate instead of
    the fixed annual_rate."""
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
            # Lenders charge the fee on the whole commitment at closing of the
            # loan; it capitalizes like interest. (It used to be charged on
            # the first draw only — about a tenth of the real fee.)
            fee_total = (commitment if commitment is not None else draw) * origination_fee_pct
            balance += fee_total

        balance += draw
        # Interest for the month on the average of open/close balance would be
        # more precise; the standard draw model accrues on the ending balance
        # of the prior month plus current draws at mid-month. Keep it simple
        # and defensible: accrue on the post-draw balance for months >= 1,
        # nothing at month 0 (closing).
        if rate_vector is not None and month >= 1:
            month_rate = (
                rate_vector[month - 1] if month - 1 < len(rate_vector) else rate_vector[-1]
            )
            interest = balance * month_rate / 12
        else:
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
