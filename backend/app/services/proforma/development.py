"""Development budget and spend timing.

Conventions (see DECISIONS.md):
- Contingency = contingencyPct x (hard + soft).
- Developer fee = developerFeePct x (hard + soft + contingency) — the fee
  base excludes land and financing costs.
- Land is spent at month 0 (closing); hard costs follow an S-curve across the
  construction months; soft costs and the developer fee are spread pro-rata
  (straight-line) across construction; contingency follows the hard-cost
  curve (it exists to absorb hard-cost variance).
- Construction interest on the drawn balance is capitalized into basis by
  debt.construction_financing, not here.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class DevelopmentBudget:
    land: float
    hard: float
    soft: float
    contingency: float
    developer_fee: float

    @property
    def total_ex_financing(self) -> float:
        return self.land + self.hard + self.soft + self.contingency + self.developer_fee


def build_budget(
    land_cost: float,
    hard_costs: float,
    soft_costs: float,
    contingency_pct: float,
    developer_fee_pct: float,
) -> DevelopmentBudget:
    contingency = (hard_costs + soft_costs) * contingency_pct
    developer_fee = (hard_costs + soft_costs + contingency) * developer_fee_pct
    return DevelopmentBudget(land_cost, hard_costs, soft_costs, contingency, developer_fee)


def s_curve_weights(months: int) -> list[float]:
    """Normalized S-curve spend weights over `months` periods: the classic
    cosine ogive — cumulative share s(t) = (1 - cos(pi * t/T)) / 2 — sliced
    into per-month increments. Sums to 1.0 exactly."""
    if months <= 0:
        return []
    if months == 1:
        return [1.0]
    cumulative = [(1 - math.cos(math.pi * t / months)) / 2 for t in range(months + 1)]
    return [cumulative[t + 1] - cumulative[t] for t in range(months)]


def straight_line_weights(months: int) -> list[float]:
    if months <= 0:
        return []
    return [1.0 / months] * months


def monthly_cost_schedule(
    budget: DevelopmentBudget,
    construction_months: int,
    hard_cost_curve=None,
) -> list[float]:
    """Cost outflows by month, index 0..construction_months. Month 0 carries
    land; months 1..N carry hard/soft/contingency/fee per their curves.
    `hard_cost_curve` is injectable: months -> list of weights summing to 1."""
    curve_fn = hard_cost_curve or s_curve_weights
    if construction_months <= 0:
        # Nothing to build — everything lands at close.
        return [budget.total_ex_financing]

    hard_weights = curve_fn(construction_months)
    line_weights = straight_line_weights(construction_months)

    schedule = [budget.land]
    for m in range(construction_months):
        schedule.append(
            (budget.hard + budget.contingency) * hard_weights[m]
            + (budget.soft + budget.developer_fee) * line_weights[m]
        )
    return schedule


def custom_cost_schedule(
    budget: DevelopmentBudget, construction_months: int, draws: list
) -> tuple[list[float] | None, list[str]]:
    """Roadmap #12: the user's monthly draw schedule shapes when the non-land
    budget is spent (months 1..N; land stays at close). Amounts are used as
    WEIGHTS: the schedule always spends exactly the budget, so a draw table
    that doesn't add up can't silently change total cost — it's scaled, with
    a warning. Returns (None, []) when there are no usable rows."""
    warnings: list[str] = []
    if construction_months <= 0:
        return None, []
    by_month = [0.0] * construction_months
    for row in draws or []:
        if not isinstance(row, dict):
            continue
        month, amount = row.get("month"), row.get("drawAmount")
        if not isinstance(month, (int, float)) or not isinstance(amount, (int, float)) or amount <= 0:
            continue
        index = int(month)
        if index < 1 or index > construction_months:
            warnings.append(
                f"Draw schedule month {index} is outside the {construction_months}-month build — "
                "counted in the nearest build month."
            )
            index = min(max(index, 1), construction_months)
        by_month[index - 1] += float(amount)
    total_drawn = sum(by_month)
    if total_drawn <= 0:
        return None, warnings
    spend = budget.total_ex_financing - budget.land
    if abs(total_drawn - spend) > 0.01 * max(spend, 1.0):
        warnings.append(
            f"The draw schedule totals ${total_drawn:,.0f} but the non-land budget is "
            f"${spend:,.0f} — its monthly shape is used, scaled to the budget."
        )
    return [budget.land] + [spend * amount / total_drawn for amount in by_month], warnings
