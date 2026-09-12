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
    return sum(cf / (1 + rate) ** ((d - d0).days / 365) for d, cf in zip(dates, amounts, strict=False))


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


def sign_changes(flows: list[float]) -> int:
    """Descartes count: sign flips between consecutive NON-ZERO flows. A
    conventional investment (one outlay, then inflows) has exactly one; a
    series with more may have several IRRs (Run 6 [FIN] diagnostics)."""
    signs = [cf > 0 for cf in flows if cf != 0]
    return sum(1 for a, b in zip(signs, signs[1:], strict=False) if a != b)


# Root-scan band, ANNUAL: -99% .. +300%. Anything outside is not an IRR a
# deal team would act on; the band exists so the scan is finite.
ROOT_SCAN_LOW_ANNUAL = -0.99
ROOT_SCAN_HIGH_ANNUAL = 3.0
_ROOT_SCAN_STEPS = 600


def _scan_roots(f, low: float, high: float, steps: int = _ROOT_SCAN_STEPS) -> list[float]:
    """Every sign change of f on a uniform grid over [low, high], each
    refined by bisection. Ascending. Deliberately walks the WHOLE band —
    Newton finds one root; the diagnostics need all of them."""
    roots: list[float] = []
    prev_x, prev_v = low, f(low)
    for i in range(1, steps + 1):
        x = low + (high - low) * i / steps
        v = f(x)
        if prev_v == 0:
            roots.append(prev_x)
        elif prev_v * v < 0:
            a, fa, b = prev_x, prev_v, x
            for _ in range(100):
                mid = (a + b) / 2
                fm = f(mid)
                if abs(fm) < _TOLERANCE:
                    break
                if fa * fm < 0:
                    b = mid
                else:
                    a, fa = mid, fm
            roots.append((a + b) / 2)
        prev_x, prev_v = x, v
    return roots


def periodic_irr_roots(
    flows: list[float],
    periods_per_year: int = 12,
    low_annual: float = ROOT_SCAN_LOW_ANNUAL,
    high_annual: float = ROOT_SCAN_HIGH_ANNUAL,
) -> list[float]:
    """All annualized IRRs of a periodic series inside the annual band,
    ascending (empty when no root lies in the band)."""
    if not flows:
        return []
    low = (1 + low_annual) ** (1 / periods_per_year) - 1
    high = (1 + high_annual) ** (1 / periods_per_year) - 1
    roots = _scan_roots(lambda r: _npv_periodic(r, flows), low, high)
    return [(1 + r) ** periods_per_year - 1 for r in roots]


def xirr_roots(
    dates: list[date],
    amounts: list[float],
    low_annual: float = ROOT_SCAN_LOW_ANNUAL,
    high_annual: float = ROOT_SCAN_HIGH_ANNUAL,
) -> list[float]:
    """All dated (Excel-convention) IRRs inside the annual band, ascending."""
    if len(dates) != len(amounts) or len(dates) < 2:
        return []
    pairs = sorted(zip(dates, amounts, strict=False), key=lambda p: p[0])
    sorted_dates = [p[0] for p in pairs]
    sorted_amounts = [p[1] for p in pairs]
    return _scan_roots(
        lambda r: _npv_dated(r, sorted_dates, sorted_amounts), low_annual, high_annual
    )


def select_economic_root(roots: list[float], anchor: float | None) -> float:
    """[FIN] Multiple-IRR rule (Run 6): the economic root is the one nearest
    the ANCHOR — the unlevered IRR when the levered series is being solved
    (leverage shifts the return away from the asset's own; the root closest
    to the asset return is the one the capital structure actually produced).
    Without an anchor (the unlevered series itself has several roots) the
    root nearest 0% wins — the conventional root a small-guess Newton search
    lands on. Rejected: the smallest root (an artifact near -100% would win)
    and the root nearest the discount rate (the IRR would then depend on an
    input it should be independent of)."""
    if not roots:
        raise ValueError("select_economic_root needs at least one root")
    target = anchor if anchor is not None else 0.0
    return min(roots, key=lambda r: abs(r - target))


def irr_diagnostics(
    flows: list[float],
    anchor: float | None = None,
    dates: list[date] | None = None,
    periods_per_year: int = 12,
) -> dict | None:
    """Run 6 [FIN]: when a series has MORE THAN ONE sign change, scan the
    band for every IRR. Returns None for a conventional series (exactly one
    sign change — the IRR is untouched, by design) or when at most one root
    exists in the band (the Newton answer is the only candidate). Otherwise
    {"signChanges", "roots" (ascending, annualized), "selected", "otherRoots"}
    with `selected` chosen by select_economic_root()."""
    changes = sign_changes(flows)
    if changes <= 1:
        return None
    if dates is not None:
        roots = xirr_roots(dates, flows)
    else:
        roots = periodic_irr_roots(flows, periods_per_year)
    if len(roots) <= 1:
        return None
    selected = select_economic_root(roots, anchor)
    return {
        "signChanges": changes,
        "roots": roots,
        "selected": selected,
        "otherRoots": [r for r in roots if r != selected],
    }


def xirr(dates: list[date], amounts: list[float]) -> float | None:
    """Excel-convention XIRR: actual/365 exponents from the first date."""
    if len(dates) != len(amounts) or len(dates) < 2:
        return None
    if all(a >= 0 for a in amounts) or all(a <= 0 for a in amounts):
        return None
    pairs = sorted(zip(dates, amounts, strict=False), key=lambda p: p[0])
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
