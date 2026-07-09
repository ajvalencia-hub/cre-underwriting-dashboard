"""Return metrics: IRR (periodic and dated/XIRR), multiples, NPV, payback.

Pure functions, no third-party numerics (no scipy/numpy): Newton's method with
a guaranteed bisection fallback. Conventions (see DECISIONS.md):
- Engine-level IRRs are computed on the monthly cash-flow vector as a periodic
  monthly IRR, annualized as (1 + i_m)^12 - 1. This keeps results exactly
  reproducible by hand (no day-count noise from calendar month lengths).
- xirr() exists for dated flows and follows Excel's convention: discount
  exponent = days/365 (actual/365), verified against Excel's documented
  reference example.
"""

from datetime import date

_MAX_ITERATIONS = 100
_TOLERANCE = 1e-10


def _npv_periodic(rate: float, flows: list[float]) -> float:
    return sum(cf / (1 + rate) ** t for t, cf in enumerate(flows))


def _npv_dated(rate: float, dates: list[date], amounts: list[float]) -> float:
    d0 = dates[0]
    return sum(cf / (1 + rate) ** ((d - d0).days / 365) for d, cf in zip(dates, amounts, strict=True))


def _solve_rate(f, low: float = -0.9999, high: float = 10.0, guess: float = 0.1) -> float | None:
    """Root of f (an NPV function of rate): Newton first, bisection fallback.
    Returns None when no sign change exists in [low, high] (no IRR)."""
    # Newton with numeric derivative.
    rate = guess
    for _ in range(_MAX_ITERATIONS):
        value = f(rate)
        if abs(value) < _TOLERANCE:
            return rate
        step = 1e-7
        derivative = (f(rate + step) - value) / step
        if derivative == 0:
            break
        next_rate = rate - value / derivative
        if next_rate <= -1:
            break  # left the domain — hand over to bisection
        if abs(next_rate - rate) < _TOLERANCE:
            return next_rate
        rate = next_rate

    # Bisection: guaranteed if a sign change exists.
    f_low, f_high = f(low), f(high)
    if f_low == 0:
        return low
    if f_high == 0:
        return high
    if f_low * f_high > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2
        f_mid = f(mid)
        if abs(f_mid) < _TOLERANCE:
            return mid
        if f_low * f_mid < 0:
            high = mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


def periodic_irr(flows: list[float], periods_per_year: int = 12) -> float | None:
    """Annualized IRR of evenly spaced periodic flows (flows[0] at t=0).
    Returns None when undefined (all same sign, or no root)."""
    if not flows or all(cf >= 0 for cf in flows) or all(cf <= 0 for cf in flows):
        return None
    rate = _solve_rate(lambda r: _npv_periodic(r, flows), guess=0.01)
    if rate is None:
        return None
    return (1 + rate) ** periods_per_year - 1


def xirr(dates: list[date], amounts: list[float]) -> float | None:
    """Excel-convention XIRR: actual/365 exponents from the first date."""
    if len(dates) != len(amounts) or len(dates) < 2:
        return None
    if all(a >= 0 for a in amounts) or all(a <= 0 for a in amounts):
        return None
    pairs = sorted(zip(dates, amounts, strict=True), key=lambda p: p[0])
    sorted_dates = [p[0] for p in pairs]
    sorted_amounts = [p[1] for p in pairs]
    return _solve_rate(lambda r: _npv_dated(r, sorted_dates, sorted_amounts), guess=0.1)


def npv(annual_rate: float, monthly_flows: list[float]) -> float:
    """NPV of monthly flows (flows[0] at t=0) at an annual discount rate,
    de-annualized to monthly as (1+r)^(1/12)-1."""
    monthly_rate = (1 + annual_rate) ** (1 / 12) - 1
    return _npv_periodic(monthly_rate, monthly_flows)


def equity_multiple(flows: list[float]) -> float | None:
    """Total distributions / total contributions (absolute)."""
    contributions = -sum(cf for cf in flows if cf < 0)
    distributions = sum(cf for cf in flows if cf > 0)
    if contributions <= 0:
        return None
    return distributions / contributions


def payback_period_years(flows: list[float], periods_per_year: int = 12) -> float | None:
    """First period where cumulative flow turns non-negative, in years,
    with linear interpolation inside the crossing period."""
    cumulative = 0.0
    for t, cf in enumerate(flows):
        previous = cumulative
        cumulative += cf
        if cumulative >= 0 and t > 0:
            fraction = -previous / cf if cf > 0 else 0.0
            return (t - 1 + fraction) / periods_per_year
    return None


def profitability_index(annual_rate: float, monthly_flows: list[float]) -> float | None:
    """PV(positive flows) / |PV(negative flows)| at the discount rate."""
    monthly_rate = (1 + annual_rate) ** (1 / 12) - 1
    pv_in = sum(cf / (1 + monthly_rate) ** t for t, cf in enumerate(monthly_flows) if cf > 0)
    pv_out = sum(cf / (1 + monthly_rate) ** t for t, cf in enumerate(monthly_flows) if cf < 0)
    if pv_out == 0:
        return None
    return pv_in / abs(pv_out)
