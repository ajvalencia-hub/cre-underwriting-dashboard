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
    # Renewal rent spread (I2): renewal-path rent = discount x market. A
    # missing/zero value means 1.0 (no spread) — 0 would silently zero the
    # renewal rent.
    discount = _num(inputs, "renewalRentPsfDiscountPct", 1.0)
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
        "renewalRentDiscount": discount if discount > 0 else 1.0,
        # I2 timing refinement is OPT-IN: at defaults the re-let TI/LC stays
        # at expiry+1 with the renewal side (Run-3 behavior), because moving
        # it changes cash timing whenever downtime > 0 and the compatibility
        # rule is absolute.
        "reletCapitalAtCommencement": bool(inputs.get("reletCapitalAtCommencement")),
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


def _occupancy_projection(
    lease_rows: list[dict], rollover: dict, months: int, total_sf: float
) -> list[float]:
    """Occupancy vector from lease terms only (contract months full,
    downtime months at renewal probability, speculative terms full) — the
    same accumulation the main loop performs, extracted for the gross-up
    (I3), which needs occupancy BEFORE recoveries exist. A drift-guard test
    asserts this matches build_lease_income()['occupancy'] exactly."""
    occupied = [0.0] * months
    p = rollover["renewalProbability"]
    downtime = rollover["downtimeMonths"]
    term_months = rollover["newTermYears"] * 12
    for lease in lease_rows:
        sf = _num(lease, "sf")
        start_date = _parse_date(lease.get("startDate"))
        end_date = _parse_date(lease.get("endDate"))
        start_index = month_index_of(start_date) if start_date else 1
        end_index = month_index_of(end_date) if end_date else months + 1
        for m in range(max(1, start_index), min(end_index, months) + 1):
            occupied[m - 1] += sf
        if end_date is None:
            continue
        generation_start = end_index + 1
        while generation_start <= months:
            gen_end = generation_start + term_months - 1
            for m in range(max(1, generation_start), min(gen_end, months) + 1):
                in_downtime = (m - generation_start) < downtime
                occupied[m - 1] += sf * p if in_downtime else sf
            generation_start = gen_end + 1
    return [o / total_sf if total_sf > 0 else 0.0 for o in occupied]


def _grossed_up_pool(
    pool: list[float],
    variable: list[float],
    occupancy: list[float],
    gross_up_to: float,
) -> list[float]:
    """I3: R_adj(m) = fixed(m) + variable(m) x max(1, grossUpTo / occ(y)) —
    occupancy averaged per calendar year, ratio floored at 1 (never gross
    DOWN below actuals). Pre-epoch base years reuse year 1's occupancy."""
    months = len(pool)
    occ_by_year: dict[int, float] = {}
    samples: dict[int, list[float]] = {}
    for m in range(1, months + 1):
        year = ANALYSIS_EPOCH.year + (ANALYSIS_EPOCH.month - 1 + m - 1) // 12
        samples.setdefault(year, []).append(occupancy[m - 1])
    for year, values in samples.items():
        occ_by_year[year] = sum(values) / len(values)

    adjusted = []
    for m in range(1, months + 1):
        year = ANALYSIS_EPOCH.year + (ANALYSIS_EPOCH.month - 1 + m - 1) // 12
        occ = occ_by_year.get(year, 1.0)
        ratio = max(1.0, gross_up_to / occ) if occ > 0 else 1.0
        fixed_part = pool[m - 1] - variable[m - 1]
        adjusted.append(fixed_part + variable[m - 1] * ratio)
    return adjusted


def build_lease_income(
    inputs: dict,
    months: int,
    recoverable_opex_monthly: list[float],
    expense_growth: float,
    variable_recoverable_monthly: list[float] | None = None,
    gross_up_to: float | None = None,
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
    # Base-year gross-up (I3, base_year_stop only): both the base year and
    # every comparison year come from the ADJUSTED pool; NNN keeps billing
    # the raw pool (actual expenses are what they are).
    annual_recoverable_stop = annual_recoverable
    if gross_up_to is not None and gross_up_to > 0 and variable_recoverable_monthly:
        projected_occupancy = _occupancy_projection(leases, rollover, months, total_sf)
        adjusted_pool = _grossed_up_pool(
            recoverable_opex_monthly, variable_recoverable_monthly,
            projected_occupancy, gross_up_to,
        )
        annual_recoverable_stop = _annual_recoverable_by_calendar_year(
            adjusted_pool, expense_growth
        )

    def calendar_year_of(month: int) -> int:
        return ANALYSIS_EPOCH.year + (ANALYSIS_EPOCH.month - 1 + month - 1) // 12

    # CAM admin fee (I1): a billing markup on pool-based recoveries. Applies
    # to NNN and base-year-stop only — fixed_psf is a stated contract amount
    # and gross recovers nothing, so neither can carry a markup.
    admin_markup = 1 + _num(inputs, "adminFeePct")

    def recovery_for(lease: dict, month: int, share: float, base_year: int) -> float:
        recovery_type = lease.get("recoveryType") or "gross"
        if recovery_type == "NNN":
            pool = recoverable_opex_monthly[month - 1] if month <= len(recoverable_opex_monthly) else 0.0
            return share * pool * admin_markup
        if recovery_type == "base_year_stop":
            current = annual_recoverable_stop.get(calendar_year_of(month))
            if current is None:
                current = annual_recoverable_stop[max(annual_recoverable_stop)]
            base_amount = annual_recoverable_stop.get(base_year, 0.0)
            # The base-year comparison happens on RAW pool amounts; the
            # markup applies to the billed delta only.
            return share * max(0.0, current - base_amount) / 12 * admin_markup
        if recovery_type == "fixed_psf":
            return _num(lease, "recoveryValue") * _num(lease, "sf") / 12
        return 0.0  # gross

    p = rollover["renewalProbability"]
    downtime = rollover["downtimeMonths"]
    new_term_months = rollover["newTermYears"] * 12

    total_annual_in_place = 0.0
    expiration_by_year: dict[int, dict] = {}
    walt_weighted = 0.0
    per_lease: list[dict] = []  # I8: drill-down slices, one per rent-roll row

    for lease_index, lease in enumerate(leases):
        sf = _num(lease, "sf")
        share = sf / total_sf if total_sf > 0 else 0.0
        slice_scheduled = [0.0] * months
        slice_free = [0.0] * months
        slice_downtime = [0.0] * months
        slice_recoveries = [0.0] * months
        slice_capital = [0.0] * months
        rollover_events: list[dict] = []
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
            slice_scheduled[m - 1] += rent
            in_free_period = (m - start_index) < free_months
            if in_free_period:
                free_rent_loss[m - 1] += rent
                slice_free[m - 1] += rent
            else:
                collected[m - 1] += rent
            rec = recovery_for(lease, m, share, base_year)
            recoveries[m - 1] += rec
            slice_recoveries[m - 1] += rec
            occupied_sf[m - 1] += sf

        def _finish_lease(events: list[dict]):
            per_lease.append({
                "suiteId": str(lease.get("suiteId") or lease.get("tenant") or f"lease-{lease_index + 1}"),
                "tenant": lease.get("tenant") or "",
                "sf": sf,
                "recoveryType": lease.get("recoveryType") or "gross",
                "endDate": str(lease.get("endDate") or ""),
                "scheduledRent": slice_scheduled,
                "freeRent": slice_free,
                "downtimeLoss": slice_downtime,
                "recoveries": slice_recoveries,
                "leasingCapital": slice_capital,
                "rolloverEvents": events,
            })

        # ---- speculative rollover generations -----------------------------
        if end_date is None:
            _finish_lease([])
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

        discount = rollover["renewalRentDiscount"]
        while generation_start <= months:
            start_rent_psf = market_at(generation_start)
            # The spread applies AT EACH renewal event against that
            # generation's market rent — it never compounds through prior
            # generations, because every generation re-derives from the
            # market track, not from the previous generation's realized rent.
            renewal_start_psf = discount * start_rent_psf

            # Rollover capital (I2). Renewal side: month after expiry.
            # Re-let side: with the opt-in timing refinement it lands at
            # commencement (expiry + downtime + 1) and is simply not
            # incurred when commencement falls past the analysis end;
            # legacy (default) timing charges both sides at expiry+1.
            # LC bases: renewal uses the spread-adjusted rent, re-let the
            # market rent.
            renewal_capital = (
                p * rollover["tiRenewalPsf"] * sf
                + p * rollover["lcRenewalPct"] * renewal_start_psf * sf * rollover["newTermYears"]
            )
            relet_capital = (
                (1 - p) * rollover["tiNewPsf"] * sf
                + (1 - p) * rollover["lcNewPct"] * start_rent_psf * sf * rollover["newTermYears"]
            )
            if rollover["reletCapitalAtCommencement"]:
                if 1 <= generation_start <= months:
                    leasing_capital[generation_start - 1] += renewal_capital
                    slice_capital[generation_start - 1] += renewal_capital
                commencement = generation_start + downtime
                if 1 <= commencement <= months:
                    leasing_capital[commencement - 1] += relet_capital
                    slice_capital[commencement - 1] += relet_capital
            else:
                if 1 <= generation_start <= months:
                    leasing_capital[generation_start - 1] += renewal_capital + relet_capital
                    slice_capital[generation_start - 1] += renewal_capital + relet_capital

            if generation_start <= months:
                rollover_events.append({
                    "expiryMonth": generation_start - 1,
                    "commencementMonth": min(generation_start + downtime, months),
                    "startRentPsf": round(start_rent_psf, 2),
                    "renewalProbability": p,
                    "downtimeMonths": downtime,
                })

            gen_base_year = calendar_year_of(min(generation_start, months))
            gen_end = generation_start + new_term_months - 1
            for m in range(max(1, generation_start), min(gen_end, months) + 1):
                # Speculative terms escalate annually at market growth from
                # the generation start.
                years_in = (m - generation_start) // 12
                market_rent = start_rent_psf * (1 + rollover["marketRentGrowthPct"]) ** years_in * sf / 12
                renewal_rent = discount * market_rent
                blended_rent = p * renewal_rent + (1 - p) * market_rent
                scheduled[m - 1] += blended_rent
                slice_scheduled[m - 1] += blended_rent
                in_downtime = (m - generation_start) < downtime
                if in_downtime:
                    # Renewal path pays (no downtime); re-let path is vacant.
                    collected[m - 1] += p * renewal_rent
                    downtime_loss[m - 1] += (1 - p) * market_rent
                    slice_downtime[m - 1] += (1 - p) * market_rent
                    rec = recovery_for(lease, m, share, gen_base_year) * p
                    recoveries[m - 1] += rec
                    slice_recoveries[m - 1] += rec
                    occupied_sf[m - 1] += sf * p
                else:
                    collected[m - 1] += blended_rent
                    rec = recovery_for(lease, m, share, gen_base_year)
                    recoveries[m - 1] += rec
                    slice_recoveries[m - 1] += rec
                    occupied_sf[m - 1] += sf
            generation_start = gen_end + 1

        _finish_lease(rollover_events)

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
        "perLease": per_lease,
        "warnings": warnings,
    }


def has_leases(inputs: dict) -> bool:
    return any(
        isinstance(l, dict) and _num(l, "sf") > 0 and _num(l, "baseRentPsfAnnual") > 0
        for l in (inputs.get("commercialLeases") or [])
    )
