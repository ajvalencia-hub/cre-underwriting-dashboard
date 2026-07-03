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
    origination fee is drawn at the first loan draw."""
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
