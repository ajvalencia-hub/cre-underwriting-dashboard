"""Commercial lease-level income: escalations, recoveries, free rent, and
probability-weighted rollover. Every convention is logged in DECISIONS.md
([FIN] H1 block); the load-bearing ones, in brief:

- Calendar: lease dates map onto the analysis calendar anchored at
  timeline.ANALYSIS_EPOCH — operating month m spans the calendar month at
  offset m-1 from the epoch. Leases straddling the start are in place at
  month 1 with escalations counted from their TRUE start date.
- Escalations: applied on lease-start anniversaries every escalationMonths
  months (default 12). fixed_pct compounds (rent *= 1+v per interval);
  fixed_step adds (rent += v $psf/yr per interval); none = flat.
- Free rent: abates BASE RENT only for the first freeRentMonths of the
  contract term; recoveries are unabated (NNN tenants pay expenses during
  abatement).
- Recoveries: NNN = pro-rata SF share of recoverable opex; gross = none;
  base_year_stop = share of recoverable opex ABOVE the base-year annual
  amount (base year = lease-start calendar year), floored at zero;
  fixed_psf = stated $psf/yr, flat.
- Rollover (expected-value single timeline — the standard ARGUS-style
  simplification, no path explosion): at each expiry, with p =
  renewalProbability, the following downtimeMonths collect p x market rent
  (the renewal path has no downtime; the re-let path is vacant), then full
  market rent. Speculative terms run newTermYears, escalate annually at
  marketRentGrowthPct, inherit the expiring lease's recovery structure
  (base-year stops reset to the new start year), carry no free rent, and
  roll again through the horizon.
- Rollover capital, charged in the month AFTER expiry: TI = [p x
  tiRenewalPsf + (1-p) x tiNewPsf] x SF; LC = [p x lcRenewalPct + (1-p) x
  lcNewPct] x (starting annual rent x newTermYears). Leasing capital is
  below NOI (a capital cost, like capex).
- Market rent: marketRentPsf grows in annual steps (1+g)^((m-1)//12) from
  the analysis start; when marketRentPsf is unset, each lease's own
  escalated in-place rent at expiry is used as its market rent (avoids
  silent zero-rent rollovers).
"""

from datetime import date, datetime

from app.services.proforma.timeline import ANALYSIS_EPOCH


def _num(source: dict, field: str, default: float = 0.0) -> float:
    value = source.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _parse_date(value) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def month_index_of(d: date, epoch: date = ANALYSIS_EPOCH) -> int:
    """1-based operating month whose calendar month contains `d`
    (month 1 = the epoch's own calendar month)."""
    return (d.year - epoch.year) * 12 + (d.month - epoch.month) + 1


ROLLOVER_DEFAULTS = {
    "renewalProbability": 0.70,
    "downtimeMonths": 6,
    "marketRentGrowthPct": 0.03,
    "newTermYears": 5,
    "tiNewPsf": 0.0,
    "tiRenewalPsf": 0.0,
    "lcNewPct": 0.0,
    "lcRenewalPct": 0.0,
}


def _rollover_assumptions(inputs: dict) -> dict:
    return {
        "renewalProbability": min(1.0, max(0.0, _num(inputs, "renewalProbability", ROLLOVER_DEFAULTS["renewalProbability"]))),
        "downtimeMonths": int(_num(inputs, "downtimeMonths", ROLLOVER_DEFAULTS["downtimeMonths"])),
        "marketRentPsf": _num(inputs, "marketRentPsf") or None,
        "marketRentGrowthPct": _num(inputs, "marketRentGrowthPct", ROLLOVER_DEFAULTS["marketRentGrowthPct"]),
        "newTermYears": max(1, int(_num(inputs, "newTermYears", ROLLOVER_DEFAULTS["newTermYears"]))),
        "tiNewPsf": _num(inputs, "tiNewPsf"),
        "tiRenewalPsf": _num(inputs, "tiRenewalPsf"),
        "lcNewPct": _num(inputs, "lcNewPct"),
        "lcRenewalPct": _num(inputs, "lcRenewalPct"),
    }


def _market_growth_multiplier(annual_growth: float, month_1_based: int) -> float:
    return (1 + annual_growth) ** ((month_1_based - 1) // 12)


def _escalated_rent_psf(lease: dict, start_index: int, month: int) -> float:
    """Contractual base rent $psf/yr in operating month `month` for a lease
    whose term started at operating-month index start_index (may be <= 0)."""
    base = _num(lease, "baseRentPsfAnnual")
    esc_type = lease.get("escalationType") or "none"
    interval = int(_num(lease, "escalationMonths", 12)) or 12
    elapsed_intervals = max(0, (month - start_index)) // interval
    value = _num(lease, "escalationValue")
    if esc_type == "fixed_pct":
        return base * (1 + value) ** elapsed_intervals
    if esc_type == "fixed_step":
        return base + value * elapsed_intervals
    return base


def _annual_recoverable_by_calendar_year(
    recoverable_monthly: list[float], expense_growth: float
) -> dict[int, float]:
    """Annual recoverable opex per calendar year over the vector, with
    partial years annualized. Pre-epoch years extrapolate backward by
    de-growing year 1 at the expense growth rate."""
    by_year: dict[int, list[float]] = {}
    for m, amount in enumerate(recoverable_monthly, start=1):
        year = ANALYSIS_EPOCH.year + (ANALYSIS_EPOCH.month - 1 + m - 1) // 12
        by_year.setdefault(year, []).append(amount)
    annuals = {
        year: sum(values) * (12 / len(values)) for year, values in by_year.items()
    }
    first_year = min(annuals) if annuals else ANALYSIS_EPOCH.year
    first_amount = annuals.get(first_year, 0.0)
    for back in range(1, 31):  # pre-epoch base years, extrapolated backward
        year = first_year - back
        annuals[year] = first_amount / ((1 + expense_growth) ** back)
    return annuals


def build_lease_income(
    inputs: dict,
    months: int,
    recoverable_opex_monthly: list[float],
    expense_growth: float,
) -> dict:
    """Property-level monthly vectors for operating months 1..months.

    Returns {"scheduledBaseRent", "collectedBaseRent", "downtimeLoss",
    "freeRentLoss", "recoveries", "leasingCapital", "occupiedSf" (vectors),
    "totalSf", "walt", "occupancyYear1", "occupancyStabilized",
    "expirationSchedule", "warnings"}.

    scheduledBaseRent is the full contractual/market rent as if always
    collected; collected = scheduled - downtimeLoss - freeRentLoss. The
    caller maps scheduled to the GPR line and the losses to vacancy so the
    statement identities hold unchanged.
    """
    warnings: list[str] = []
    leases = [
        l for l in (inputs.get("commercialLeases") or [])
        if isinstance(l, dict) and _num(l, "sf") > 0 and _num(l, "baseRentPsfAnnual") > 0
    ]
    rollover = _rollover_assumptions(inputs)

    scheduled = [0.0] * months
    collected = [0.0] * months
    downtime_loss = [0.0] * months
    free_rent_loss = [0.0] * months
    recoveries = [0.0] * months
    leasing_capital = [0.0] * months
    occupied_sf = [0.0] * months

    total_sf = sum(_num(l, "sf") for l in leases)
    annual_recoverable = _annual_recoverable_by_calendar_year(
        recoverable_opex_monthly, expense_growth
    )

    def calendar_year_of(month: int) -> int:
        return ANALYSIS_EPOCH.year + (ANALYSIS_EPOCH.month - 1 + month - 1) // 12

    def recovery_for(lease: dict, month: int, share: float, base_year: int) -> float:
        recovery_type = lease.get("recoveryType") or "gross"
        if recovery_type == "NNN":
            return share * (recoverable_opex_monthly[month - 1] if month <= len(recoverable_opex_monthly) else 0.0)
        if recovery_type == "base_year_stop":
            current = annual_recoverable.get(calendar_year_of(month))
            if current is None:
                current = annual_recoverable[max(annual_recoverable)]
            base_amount = annual_recoverable.get(base_year, 0.0)
            return share * max(0.0, current - base_amount) / 12
        if recovery_type == "fixed_psf":
            return _num(lease, "recoveryValue") * _num(lease, "sf") / 12
        return 0.0  # gross

    p = rollover["renewalProbability"]
    downtime = rollover["downtimeMonths"]
    new_term_months = rollover["newTermYears"] * 12
    expected_ti_psf = p * rollover["tiRenewalPsf"] + (1 - p) * rollover["tiNewPsf"]
    expected_lc_pct = p * rollover["lcRenewalPct"] + (1 - p) * rollover["lcNewPct"]

    total_annual_in_place = 0.0
    expiration_by_year: dict[int, dict] = {}
    walt_weighted = 0.0

    for lease in leases:
        sf = _num(lease, "sf")
        share = sf / total_sf if total_sf > 0 else 0.0
        start_date = _parse_date(lease.get("startDate"))
        end_date = _parse_date(lease.get("endDate"))
        if end_date is None:
            warnings.append(
                f"Lease '{lease.get('tenant') or lease.get('suiteId') or '?'}' has no "
                "end date — treated as running through the whole analysis."
            )
        start_index = month_index_of(start_date) if start_date else 1
        end_index = month_index_of(end_date) if end_date else months + 1
        free_months = int(_num(lease, "freeRentMonths"))
        base_year = (start_date or ANALYSIS_EPOCH).year

        # WALT + expiration schedule from the ORIGINAL contract only. WALT is
        # SF-weighted remaining term in years from the analysis start
        # (no-end-date leases count the full analysis horizon, with a warning).
        remaining_years = max(0, end_index) / 12 if end_date else months / 12
        walt_weighted += sf * remaining_years
        in_place_annual = _num(lease, "baseRentPsfAnnual") * sf
        total_annual_in_place += in_place_annual
        if end_date is not None:
            bucket = expiration_by_year.setdefault(
                end_date.year, {"sfExpiring": 0.0, "annualRent": 0.0}
            )
            bucket["sfExpiring"] += sf
            bucket["annualRent"] += in_place_annual

        # ---- contract term ------------------------------------------------
        for m in range(max(1, start_index), min(end_index, months) + 1):
            rent = _escalated_rent_psf(lease, start_index, m) * sf / 12
            scheduled[m - 1] += rent
            in_free_period = (m - start_index) < free_months
            if in_free_period:
                free_rent_loss[m - 1] += rent
            else:
                collected[m - 1] += rent
            recoveries[m - 1] += recovery_for(lease, m, share, base_year)
            occupied_sf[m - 1] += sf

        # ---- speculative rollover generations -----------------------------
        if end_date is None:
            continue
        generation_start = end_index + 1
        market_base = rollover["marketRentPsf"]
        if market_base is None:
            # Fallback: the lease's own escalated rent at expiry is its market.
            market_base = _escalated_rent_psf(lease, start_index, end_index)
            market_at = lambda m, base=market_base, g0=generation_start: base * _market_growth_multiplier(  # noqa: E731
                rollover["marketRentGrowthPct"], m
            ) / _market_growth_multiplier(rollover["marketRentGrowthPct"], g0)
        else:
            market_at = lambda m: rollover["marketRentPsf"] * _market_growth_multiplier(  # noqa: E731
                rollover["marketRentGrowthPct"], m
            )

        while generation_start <= months:
            start_rent_psf = market_at(generation_start)
            # Rollover capital in the month after expiry.
            if 1 <= generation_start <= months:
                ti = expected_ti_psf * sf
                lc = expected_lc_pct * start_rent_psf * sf * rollover["newTermYears"]
                leasing_capital[generation_start - 1] += ti + lc
            gen_base_year = calendar_year_of(min(generation_start, months))
            gen_end = generation_start + new_term_months - 1
            for m in range(max(1, generation_start), min(gen_end, months) + 1):
                # Speculative terms escalate annually at market growth from
                # the generation start.
                years_in = (m - generation_start) // 12
                rent = start_rent_psf * (1 + rollover["marketRentGrowthPct"]) ** years_in * sf / 12
                scheduled[m - 1] += rent
                in_downtime = (m - generation_start) < downtime
                if in_downtime:
                    collected[m - 1] += rent * p
                    downtime_loss[m - 1] += rent * (1 - p)
                    recoveries[m - 1] += recovery_for(lease, m, share, gen_base_year) * p
                    occupied_sf[m - 1] += sf * p
                else:
                    collected[m - 1] += rent
                    recoveries[m - 1] += recovery_for(lease, m, share, gen_base_year)
                    occupied_sf[m - 1] += sf
            generation_start = gen_end + 1

    walt = walt_weighted / total_sf if total_sf > 0 else 0.0
    occupancy = [
        (occupied_sf[m] / total_sf if total_sf > 0 else 0.0) for m in range(months)
    ]
    year1 = occupancy[: min(12, months)]
    occupancy_year1 = sum(year1) / len(year1) if year1 else 0.0
    last12 = occupancy[max(0, months - 12) : months]
    occupancy_stabilized = sum(last12) / len(last12) if last12 else 0.0

    expiration_schedule = [
        {
            "year": year,
            "sfExpiring": bucket["sfExpiring"],
            "pctOfSf": bucket["sfExpiring"] / total_sf if total_sf > 0 else 0.0,
            "pctOfRent": (
                bucket["annualRent"] / total_annual_in_place
                if total_annual_in_place > 0
                else 0.0
            ),
        }
        for year, bucket in sorted(expiration_by_year.items())
    ]

    return {
        "scheduledBaseRent": scheduled,
        "collectedBaseRent": collected,
        "downtimeLoss": downtime_loss,
        "freeRentLoss": free_rent_loss,
        "recoveries": recoveries,
        "leasingCapital": leasing_capital,
        "occupiedSf": occupied_sf,
        "occupancy": occupancy,
        "totalSf": total_sf,
        "walt": round(walt, 2),
        "occupancyYear1": round(occupancy_year1, 4),
        "occupancyStabilized": round(occupancy_stabilized, 4),
        "expirationSchedule": expiration_schedule,
        "warnings": warnings,
    }


def has_leases(inputs: dict) -> bool:
    return any(
        isinstance(l, dict) and _num(l, "sf") > 0 and _num(l, "baseRentPsfAnnual") > 0
        for l in (inputs.get("commercialLeases") or [])
    )
