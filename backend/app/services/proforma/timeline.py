"""Monthly timeline: phase boundaries from hold-period inputs.

Month indexing convention used across the engine:
- Month 0 is the closing/acquisition date. Equity and day-one costs land here.
- Operating months are 1..total_months; the exit (sale) settles at the END of
  month total_months, in the same period as that month's operating flow.
- Development: construction occupies months 1..construction_months, lease-up
  the next lease_up_months, and the property is stabilized from
  stabilization_month onward (inclusive).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Timeline:
    total_months: int
    construction_months: int
    lease_up_months: int
    stabilization_month: int  # first stabilized month index (1-based)

    def phase(self, month: int) -> str:
        """'construction' | 'lease_up' | 'stabilized' for month 1..total."""
        if month <= self.construction_months:
            return "construction"
        if month < self.stabilization_month:
            return "lease_up"
        return "stabilized"


def build_timeline(
    deal_type: str,
    hold_period_years: float,
    construction_months: int | None = None,
    lease_up_months: int | None = None,
    stabilization_month: int | None = None,
) -> tuple[Timeline, list[str]]:
    """Returns (timeline, warnings). Lease-up longer than the hold is a
    warning, never a crash — the exit simply happens mid-lease-up."""
    warnings: list[str] = []
    total_months = max(1, round(hold_period_years * 12))

    if deal_type != "development":
        return Timeline(total_months, 0, 0, 1), warnings

    construction = int(construction_months or 0)
    lease_up = int(lease_up_months or 0)
    # An explicit stabilization month wins; otherwise construction + lease-up.
    stabilization = (
        int(stabilization_month)
        if stabilization_month
        else construction + lease_up + 1
    )
    stabilization = max(stabilization, construction + 1)

    if stabilization > total_months:
        warnings.append(
            f"Stabilization (month {stabilization}) falls after the exit "
            f"(month {total_months}) — the deal is sold before stabilizing, "
            "so the forward 12-month NOI behind the exit value is partly "
            "un-stabilized."
        )
    if construction >= total_months:
        warnings.append(
            f"Construction ({construction} mo) covers the whole hold "
            f"({total_months} mo) — no operating period exists."
        )

    return Timeline(total_months, construction, lease_up, stabilization), warnings
