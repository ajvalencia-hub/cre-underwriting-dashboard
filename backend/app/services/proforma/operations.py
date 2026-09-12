"""Monthly operating pro-forma: GPR -> EGI -> NOI vectors.

Conventions (see DECISIONS.md):
- GPR source precedence: multifamily unit-mix table (units x in-place rent,
  falling back to market rent per row) > per-SF shapes (rentableSf x rentPsf,
  office equivalents) > the flat grossPotentialRent input. Whichever source
  wins, the others are ignored (never summed) — mixed-use granularity beyond
  one primary source is out of scope for the native engine and warned about.
- Growth: annual step-ups on operating-year anniversaries — month m (1-based
  from operations start) gets (1+g)^((m-1)//12). 'flat' mode = 0 growth.
- Vacancy and credit loss are percentages of GPR. Development lease-up ramps
  occupancy linearly from 0 to the stabilized level (1 - vacancyPct), then
  holds; the vacancy input is interpreted as the stabilized economic vacancy.
- Management fee is a % of EGI. All other expense lines are annual dollars
  grown at the expense growth rate. Replacement reserves are treated as an
  operating deduction (above the NOI line here, consistent with the lender
  convention of underwriting NOI net of reserves).
"""

from app.services.proforma import leases
from app.services.proforma.timeline import Timeline

EXPENSE_DOLLAR_FIELDS = [
    "realEstateTaxes",
    "insurance",
    "utilities",
    "repairsMaintenance",
    "payroll",
    "generalAdmin",
    "replacementReserves",
]

# H1 default recoverable set for NNN / base-year-stop recoveries: every fixed
# category EXCEPT replacement reserves (capital-natured, not customarily
# recovered) and the management fee (%-based and contested). H3's per-line
# recoverable flags override this. See DECISIONS.md.
RECOVERABLE_EXPENSE_FIELDS = [
    "realEstateTaxes",
    "insurance",
    "utilities",
    "repairsMaintenance",
    "payroll",
    "generalAdmin",
]

# Run 6 (B7) opt-in: when True, annual_gpr_and_other_income builds the
# year-1 recovery pool for lease deals in expense-DETAIL mode from the
# per-line recoverable vector (the same basis the NOI build uses) instead
# of the flat recoverable fields. This is a genuine bug fix, but flipping it
# changes the Run-4 baseline VALUE of commercial_rollover.outputs.
# breakEvenRatio (0.8428964912579363 -> 0.8777284581419397; breakEven-
# Occupancy is algebraically invariant), so it ships OFF pending the
# baseline decision. Flip to True and regenerate the baseline to adopt.
DETAIL_MODE_YEAR1_RECOVERIES = False


def _num(inputs: dict, field: str, default: float = 0.0) -> float:
    value = inputs.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def has_residential(inputs: dict) -> bool:
    unit_mix = inputs.get("unitMix")
    return isinstance(unit_mix, list) and any(
        isinstance(r, dict) and r.get("unitCount") for r in unit_mix
    )


def annual_gpr_and_other_income(inputs: dict) -> tuple[float, float, str, list[str]]:
    """Returns (annual GPR, annual other income, source, warnings)."""
    warnings: list[str] = []

    # Lease-level commercial rent roll (H1); alongside a unit mix it becomes
    # a mixed-use composition (H2). Year-1 scheduled base rent; recoveries
    # ride in "other".
    if leases.has_leases(inputs):
        if has_opex_detail(inputs) and DETAIL_MODE_YEAR1_RECOVERIES:
            # Run 6 (B7): in expense-detail mode the year-1 recovery pool is
            # the SAME per-line recoverable vector the NOI build uses, so the
            # legacy break-even ratio's EGI and NOI sit on one basis. Flat
            # mode keeps the flat-field pool byte-for-byte.
            recoverable_monthly = _fixed_expense_vectors(inputs, Timeline(12, 0, 0, 1))[
                "recoverable"
            ]
        else:
            recoverable_base = sum(_num(inputs, f) for f in RECOVERABLE_EXPENSE_FIELDS)
            recoverable_monthly = [recoverable_base / 12] * 12
        income = leases.build_lease_income(
            inputs, 12, recoverable_monthly, _num(inputs, "expenseGrowthPct", 0.025)
        )
        gpr = sum(income["scheduledBaseRent"])
        other = sum(income["recoveries"]) + _num(inputs, "otherIncome")
        if has_residential(inputs):
            res_gpr, res_other, _, _ = annual_gpr_and_other_income(
                {**inputs, "commercialLeases": []}
            )
            return gpr + res_gpr, other + res_other - _num(inputs, "otherIncome"), "mixed", warnings
        return gpr, other, "commercialLeases", warnings

    unit_mix = inputs.get("unitMix")
    if isinstance(unit_mix, list) and any(
        isinstance(r, dict) and r.get("unitCount") for r in unit_mix
    ):
        monthly = 0.0
        for row in unit_mix:
            if not isinstance(row, dict):
                continue
            count = row.get("unitCount") or 0
            rent = row.get("inPlaceRent") or row.get("marketRent") or 0
            monthly += float(count) * float(rent)
        gpr = monthly * 12
        loss_to_lease = _num(inputs, "lossToLeasePct")
        concessions = _num(inputs, "concessionsPct")
        gpr *= max(0.0, 1 - loss_to_lease - concessions)
        other = (
            _num(inputs, "parkingIncome")
            + _num(inputs, "rubsIncome")
            + _num(inputs, "otherFeeIncome")
            + _num(inputs, "otherIncome")
        )
        return gpr, other, "unitMix", warnings

    rentable_sf = _num(inputs, "rentableSf") or _num(inputs, "officeRentableSf")
    rent_psf = _num(inputs, "rentPsf") or _num(inputs, "officeRentPsf")
    if rentable_sf > 0 and rent_psf > 0:
        gpr = rentable_sf * rent_psf
        other = (
            _num(inputs, "nnnRecoveriesPsf") * rentable_sf
            + _num(inputs, "parkingIncomeOffice")
            + _num(inputs, "otherIncome")
        )
        return gpr, other, "perSf", warnings

    gpr = _num(inputs, "grossPotentialRent")
    other = _num(inputs, "otherIncome")
    return gpr, other, "grossPotentialRent", warnings


def _growth_multiplier(annual_growth: float, month_1_based: int) -> float:
    return (1 + annual_growth) ** ((month_1_based - 1) // 12)


# Detail-mode (H3) category ids -> the statement's legacy category keys, so
# the Cash Flow view labels stay consistent across modes.
_DETAIL_CATEGORY_KEYS = {
    "taxes": "realEstateTaxes",
    "insurance": "insurance",
    "utilities": "utilities",
    "repairs_maintenance": "repairsMaintenance",
    "payroll": "payroll",
    "management_fee": "managementFeeFixed",
    "ga": "generalAdmin",
    "other": "otherOpex",
}

# I3: which detail categories move with occupancy by default (the gross-up
# split). Utilities and R&M scale with tenants in the building; taxes,
# insurance, payroll, G&A, and management do not. Per-line override via the
# variableWithOccupancy column ("yes"/"no", blank = this default).
_VARIABLE_CATEGORY_DEFAULTS = {"utilities", "repairs_maintenance"}


def has_opex_detail(inputs: dict) -> bool:
    return any(
        isinstance(r, dict) and isinstance(r.get("amount"), (int, float)) and r["amount"] > 0
        for r in (inputs.get("opexLineItems") or [])
    )


def _detail_line_annual(inputs: dict, line: dict) -> tuple[float, str | None]:
    """Resolve a detail line's annual dollar base per its basis. Returns
    (annual, warning-or-None). pct_of_egi lines return 0 here — they're
    EGI-multiplied in the loops."""
    amount = _num(line, "amount")
    basis = line.get("basis") or "annual_total"
    if basis == "per_unit":
        units = sum(
            r.get("unitCount") or 0
            for r in (inputs.get("unitMix") or [])
            if isinstance(r, dict)
        )
        if units <= 0:
            return amount, (
                f"Opex line '{line.get('category')}' uses per_unit basis but the "
                "deal has no unit mix — treated as an annual total."
            )
        return amount * units, None
    if basis == "psf":
        sf = (
            sum(_num(l, "sf") for l in (inputs.get("commercialLeases") or []) if isinstance(l, dict))
            or _num(inputs, "rentableSf")
            or _num(inputs, "officeRentableSf")
        )
        if sf <= 0:
            return amount, (
                f"Opex line '{line.get('category')}' uses psf basis but no SF is "
                "known — treated as an annual total."
            )
        return amount * sf, None
    return amount, None  # annual_total (and pct_of_egi callers never get here)


DEFAULT_ASSESSMENT_RATIO = 0.85


def projected_reassessed_taxes(
    purchase_price: float, assessment_ratio: float, millage_rate: float
) -> float:
    """Post-sale reassessment projection (H4): the taxable value resets to
    assessment_ratio x purchase price and the full millage applies. Pure —
    also served to the UI via the property-tax router for display."""
    return purchase_price * assessment_ratio * millage_rate


def _reassessed_tax_annual(inputs: dict) -> tuple[float | None, str | None]:
    """Returns (annual-projected-taxes, warning). None when the toggle is off
    or required inputs are missing (with a warning in the latter case)."""
    if not inputs.get("useReassessedTaxes"):
        return None, None
    price = _num(inputs, "purchasePrice")
    if price <= 0:  # development: reassess on all-in cost
        price = (
            _num(inputs, "landCost") + _num(inputs, "hardCosts") + _num(inputs, "softCosts")
        )
    millage = _num(inputs, "millageRatePct")
    if price <= 0 or millage <= 0:
        return None, (
            "Reassessed taxes are enabled but purchase price or millage rate "
            "is missing — modeled taxes left unchanged."
        )
    ratio = _num(inputs, "assessmentRatio") or DEFAULT_ASSESSMENT_RATIO
    return projected_reassessed_taxes(price, ratio, millage), None


def _fixed_expense_vectors(inputs: dict, timeline: Timeline) -> dict:
    """The single expense model both income paths consume.

    Legacy mode (no opexLineItems): per-category vectors from the flat dollar
    fields, egiPctTotal = managementFeePct, recoverable per the H1 default
    set. Detail mode (H3): per-line categories with basis resolution
    (annual_total | per_unit | psf), per-line growth (falling back to the
    deal's expense growth), explicit recoverable flags, and pct_of_egi lines
    aggregated into egiPctTotal (EGI-based lines are never recoverable —
    see DECISIONS.md)."""
    expense_growth = (
        _num(inputs, "expenseGrowthPct") if inputs.get("expenseGrowthMode") != "flat" else 0.0
    )
    warnings: list[str] = []
    total = timeline.total_months

    reassessed_taxes, reassess_warning = _reassessed_tax_annual(inputs)
    if reassess_warning:
        warnings.append(reassess_warning)
    elif reassessed_taxes is not None:
        warnings.append(
            f"Reassessed property taxes modeled: ${reassessed_taxes:,.0f}/yr "
            "(assessed value x millage) replaces the input real estate taxes."
        )
    tax_growth = (
        _num(inputs, "reassessedTaxGrowthPct")
        if inputs.get("reassessedTaxGrowthPct") is not None
        else expense_growth
    )

    # Non-ad-valorem assessments (I5): a separate fixed line with its own
    # growth clock, NEVER reset by reassessment (special assessments don't
    # reprice at sale), recoverable by default (they bill like taxes).
    non_ad_valorem = _num(inputs, "nonAdValoremTaxes")
    nav_growth = (
        _num(inputs, "nonAdValoremGrowthPct")
        if inputs.get("nonAdValoremGrowthPct") is not None
        else expense_growth
    )
    nav_raw_flag = inputs.get("nonAdValoremRecoverable")
    nav_recoverable = True if nav_raw_flag is None else bool(nav_raw_flag)

    if has_opex_detail(inputs):
        lines = []
        egi_pct_total = 0.0
        tax_lines_recoverable = False
        for raw in inputs.get("opexLineItems") or []:
            if not (isinstance(raw, dict) and _num(raw, "amount") > 0):
                continue
            if (raw.get("basis") or "annual_total") == "pct_of_egi":
                egi_pct_total += _num(raw, "amount")
                continue
            annual, warning = _detail_line_annual(inputs, raw)
            if warning:
                warnings.append(warning)
            growth = _num(raw, "growthPct", expense_growth) if raw.get("growthPct") is not None else expense_growth
            category = raw.get("category") or "other"
            key = _DETAIL_CATEGORY_KEYS.get(category, "otherOpex")
            recoverable_flag = raw.get("recoverable") in (True, "yes", "true", 1)
            variable_override = raw.get("variableWithOccupancy")
            variable_flag = (
                variable_override in (True, "yes", "true", 1)
                if variable_override not in (None, "")
                else category in _VARIABLE_CATEGORY_DEFAULTS
            )
            if reassessed_taxes is not None and key == "realEstateTaxes":
                # reassessment replaces every modeled tax line (H4)
                tax_lines_recoverable = tax_lines_recoverable or recoverable_flag
                continue
            lines.append({"key": key, "annual": annual, "growth": growth,
                          "recoverable": recoverable_flag, "variable": variable_flag})
        if reassessed_taxes is not None:
            lines.append({
                "key": "realEstateTaxes",
                "annual": reassessed_taxes,
                "growth": tax_growth,
                "recoverable": tax_lines_recoverable,
                "variable": False,  # taxes never move with occupancy
            })
        if non_ad_valorem > 0:
            lines.append({
                "key": "nonAdValorem",
                "annual": non_ad_valorem,
                "growth": nav_growth,
                "recoverable": nav_recoverable,
                "variable": False,
            })

        by_category: dict[str, list[float]] = {}
        recoverable = [0.0] * total
        recoverable_variable = [0.0] * total
        for month in range(1, total + 1):
            operating_month = month - timeline.construction_months
            for line in lines:
                vec = by_category.setdefault(line["key"], [0.0] * total)
                if operating_month < 1:
                    continue
                amount = (line["annual"] / 12) * _growth_multiplier(line["growth"], operating_month)
                vec[month - 1] += amount
                if line["recoverable"]:
                    recoverable[month - 1] += amount
                    if line["variable"]:
                        recoverable_variable[month - 1] += amount
        return {
            "byCategory": by_category,
            "recoverable": recoverable,
            "recoverableVariable": recoverable_variable,
            "expenseGrowth": expense_growth,
            "egiPctTotal": egi_pct_total,
            "detailMode": True,
            "warnings": warnings,
        }

    category_bases = {f: _num(inputs, f) for f in EXPENSE_DOLLAR_FIELDS}
    if reassessed_taxes is not None:
        category_bases["realEstateTaxes"] = reassessed_taxes
    if non_ad_valorem > 0:
        category_bases["nonAdValorem"] = non_ad_valorem
    active = [f for f, v in category_bases.items() if v > 0]
    by_category = {f: [] for f in active}
    recoverable = []
    for month in range(1, total + 1):
        operating_month = month - timeline.construction_months
        if operating_month < 1:
            for f in active:
                by_category[f].append(0.0)
            recoverable.append(0.0)
            continue
        mult = _growth_multiplier(expense_growth, operating_month)
        special_mults = {}
        if reassessed_taxes is not None:
            special_mults["realEstateTaxes"] = _growth_multiplier(tax_growth, operating_month)
        if non_ad_valorem > 0:
            special_mults["nonAdValorem"] = _growth_multiplier(nav_growth, operating_month)
        month_recoverable = 0.0
        for f in active:
            amount = (category_bases[f] / 12) * special_mults.get(f, mult)
            by_category[f].append(amount)
            if f in RECOVERABLE_EXPENSE_FIELDS or (f == "nonAdValorem" and nav_recoverable):
                month_recoverable += amount
        recoverable.append(month_recoverable)
    return {
        "byCategory": by_category,
        "recoverable": recoverable,
        "expenseGrowth": expense_growth,
        "egiPctTotal": _num(inputs, "managementFeePct"),
        "detailMode": False,
        "warnings": warnings,
    }


def _scale_at(scale, index: int) -> float:
    """recoverable_scale may be a scalar (Run-3) or a per-month vector (I4's
    revenue_share_annual basis)."""
    if isinstance(scale, list):
        return scale[index] if index < len(scale) else (scale[-1] if scale else 1.0)
    return scale


def _build_lease_noi_vector(
    inputs: dict, timeline: Timeline, recoverable_scale=1.0
) -> dict:
    """Lease-driven income path (H1): commercial leases produce the revenue
    stack; the statement identities hold via the mapping
    gpr := scheduled base rent, vacancyLoss := downtime + free rent,
    otherIncome := recoveries + the otherIncome input. The general vacancyPct
    input is NOT applied (downtime IS the vacancy); credit loss applies to
    collected revenue. Leasing capital (TI/LC) is returned separately and
    lands BELOW NOI. recoverable_scale < 1 is the mixed-use case (H2):
    commercial tenants recover only the commercial share of property opex."""
    warnings: list[str] = []
    total = timeline.total_months
    expenses = _fixed_expense_vectors(inputs, timeline)
    warnings.extend(expenses["warnings"])
    recoverable = [
        v * _scale_at(recoverable_scale, i) for i, v in enumerate(expenses["recoverable"])
    ]

    credit_loss_pct = _num(inputs, "creditLossPct")
    management_fee_pct = expenses["egiPctTotal"]
    rent_growth = (
        _num(inputs, "rentGrowthPct") if inputs.get("rentGrowthMode") != "flat" else 0.0
    )
    other_annual = _num(inputs, "otherIncome")

    # Management-fee recoverability (I1, default OFF). The fee is EGI-based
    # and EGI includes recoveries, so a naive pool contribution is circular.
    # Chosen convention [FIN]: the dollars that JOIN THE POOL are the fee on
    # PRE-RECOVERY EGI (collected base rent net of credit loss + other
    # income) — deterministic, one pass; the fee EXPENSE itself stays on
    # full EGI as before. The optional cap is % of the same pre-recovery
    # EGI. The augmented pool feeds base-year stops identically, so a lease
    # signed under the flag sees no spurious step.
    if inputs.get("mgmtFeeRecoverable") and management_fee_pct > 0:
        pre = leases.build_lease_income(inputs, total, [0.0] * total, expenses["expenseGrowth"])
        cap_pct = inputs.get("mgmtRecoveryCapPct")
        cap_pct = float(cap_pct) if isinstance(cap_pct, (int, float)) else None
        for m in range(1, total + 1):
            operating_month = m - timeline.construction_months
            if operating_month < 1:
                continue
            other_inc = (other_annual / 12) * _growth_multiplier(rent_growth, operating_month)
            pre_egi = pre["collectedBaseRent"][m - 1] * (1 - credit_loss_pct) + other_inc
            contribution = management_fee_pct * pre_egi
            if cap_pct is not None:
                contribution = min(contribution, cap_pct * pre_egi)
            recoverable[m - 1] += max(0.0, contribution)

    # Base-year gross-up (I3): needs the variable/fixed split, which only
    # exists in expense-detail mode. Occupancy basis is the COMMERCIAL
    # occupied-SF share in both pure and mixed deals — residential vacancy
    # must not gross up commercial CAM (see DECISIONS.md).
    gross_up_raw = inputs.get("grossUpToPct")
    gross_up = float(gross_up_raw) if isinstance(gross_up_raw, (int, float)) and gross_up_raw > 0 else None
    variable_recoverable = None
    if gross_up is not None:
        if expenses["detailMode"]:
            variable_recoverable = [
                v * _scale_at(recoverable_scale, i)
                for i, v in enumerate(expenses["recoverableVariable"])
            ]
        else:
            warnings.append(
                "Base-year gross-up requires expense line detail (the variable/"
                "fixed split) — grossUpToPct is ignored in simple-expense mode."
            )
            gross_up = None

    income = leases.build_lease_income(
        inputs, total, recoverable, expenses["expenseGrowth"],
        variable_recoverable_monthly=variable_recoverable,
        gross_up_to=gross_up,
    )
    warnings.extend(income["warnings"])

    if timeline.construction_months > 0:
        warnings.append(
            "Commercial leases are modeled from the analysis start — lease income "
            "during the construction period is zeroed."
        )

    gpr_vec, vacancy_vec, credit_vec, other_vec = [], [], [], []
    egi_vec, mgmt_vec, opex_vec, noi_vec, occupancy_vec = [], [], [], [], []
    leasing_capital = [0.0] * total

    for month in range(1, total + 1):
        under_construction = month <= timeline.construction_months
        if under_construction:
            for vec in (gpr_vec, vacancy_vec, credit_vec, other_vec, egi_vec,
                        mgmt_vec, opex_vec, noi_vec, occupancy_vec):
                vec.append(0.0)
            continue
        i = month - 1
        scheduled = income["scheduledBaseRent"][i]
        collected = income["collectedBaseRent"][i]
        recoveries = income["recoveries"][i]
        # otherIncome input rides alongside, grown at the rent-growth clock;
        # not occupancy-scaled in lease mode (see DECISIONS.md).
        operating_month = month - timeline.construction_months
        other_inc = (other_annual / 12) * _growth_multiplier(rent_growth, operating_month)
        credit = (collected + recoveries) * credit_loss_pct
        egi = collected + recoveries + other_inc - credit

        fixed = sum(vec[i] for vec in expenses["byCategory"].values())
        mgmt = egi * management_fee_pct
        opex = fixed + mgmt

        gpr_vec.append(scheduled)
        vacancy_vec.append(income["downtimeLoss"][i] + income["freeRentLoss"][i])
        credit_vec.append(credit)
        other_vec.append(recoveries + other_inc)
        egi_vec.append(egi)
        mgmt_vec.append(mgmt)
        opex_vec.append(opex)
        noi_vec.append(egi - opex)
        occupancy_vec.append(income["occupancy"][i])
        leasing_capital[i] = income["leasingCapital"][i]

    return {
        "noi": noi_vec,
        "egi": egi_vec,
        "gpr": gpr_vec,
        "opex": opex_vec,
        "occupancy": occupancy_vec,
        "vacancyLoss": vacancy_vec,
        "creditLoss": credit_vec,
        "otherIncome": other_vec,
        "managementFee": mgmt_vec,
        "fixedOpexByCategory": expenses["byCategory"],
        "recoveries": income["recoveries"],
        "leasingCapital": leasing_capital,
        "leaseDetail": {
            "walt": income["walt"],
            "totalSf": income["totalSf"],
            "occupancyYear1": income["occupancyYear1"],
            "occupancyStabilized": income["occupancyStabilized"],
            "expirationSchedule": income["expirationSchedule"],
            "perLease": income["perLease"],
        },
        "gprSource": "commercialLeases",
        "warnings": warnings,
    }


_INCOME_KEYS = ("gpr", "vacancyLoss", "creditLoss", "otherIncome", "egi")


def _commercial_income_share(inputs: dict) -> float:
    """Stabilized commercial share of property revenue (year-1 scheduled
    commercial rent vs residential GPR) — the pro-rata basis for how much of
    the property's recoverable opex commercial tenants can recover in a
    mixed-use deal (H2, DECISIONS.md)."""
    com_income = leases.build_lease_income(inputs, 12, [0.0] * 12, 0.0)
    com_rent = sum(com_income["scheduledBaseRent"])
    res_gpr, _, _, _ = annual_gpr_and_other_income({**inputs, "commercialLeases": []})
    total = com_rent + res_gpr
    return com_rent / total if total > 0 else 1.0


def _allocation_shares(inputs: dict, total: int):
    """I4: the commercial share of shared property opex per the chosen
    basis. Returns (pool_scale: float | list[float],
    reporting_share_c: list[float] | None, warnings).

    - revenue_share_y1 (default, Run-3): frozen year-1 scheduled-revenue
      share for the pool; reporting keeps the legacy monthly-EGI split
      (reporting_share_c None).
    - sf: commercial SF / (commercial SF + residential unit-mix SF); one
      scalar drives BOTH pool and reporting. Falls back to the default with
      a warning when either side's SF is unknown.
    - revenue_share_annual: the y1 ratio recomputed per calendar year (a
      per-month vector), driving BOTH pool and reporting.
    """
    basis = inputs.get("opexAllocationBasis") or "revenue_share_y1"
    warnings: list[str] = []

    if basis == "sf":
        com_sf = sum(
            _num(l, "sf") for l in (inputs.get("commercialLeases") or [])
            if isinstance(l, dict)
        )
        res_sf = sum(
            _num(r, "unitCount") * _num(r, "avgSf")
            for r in (inputs.get("unitMix") or [])
            if isinstance(r, dict)
        )
        if com_sf > 0 and res_sf > 0:
            share = com_sf / (com_sf + res_sf)
            return share, [share] * total, warnings
        warnings.append(
            "opexAllocationBasis 'sf' needs SF on both sides (lease SF and "
            "unit-mix Avg SF) — falling back to the year-1 revenue share."
        )
        basis = "revenue_share_y1"

    if basis == "revenue_share_annual":
        com_sched = leases.build_lease_income(
            inputs, total, [0.0] * total, 0.0
        )["scheduledBaseRent"]
        res_gpr_annual, _, _, _ = annual_gpr_and_other_income(
            {**inputs, "commercialLeases": []}
        )
        rent_growth = (
            _num(inputs, "rentGrowthPct")
            if inputs.get("rentGrowthMode") != "flat" else 0.0
        )
        res_gpr = [
            (res_gpr_annual / 12) * _growth_multiplier(rent_growth, m)
            for m in range(1, total + 1)
        ]
        # Group by calendar year (epoch-anchored, same mapping as leases.py).
        year_of = [
            leases.ANALYSIS_EPOCH.year
            + (leases.ANALYSIS_EPOCH.month - 1 + m) // 12
            for m in range(total)
        ]
        share_by_year: dict[int, float] = {}
        for year in set(year_of):
            months_in = [m for m in range(total) if year_of[m] == year]
            com_y = sum(com_sched[m] for m in months_in)
            res_y = sum(res_gpr[m] for m in months_in)
            share_by_year[year] = com_y / (com_y + res_y) if com_y + res_y > 0 else 1.0
        vector = [share_by_year[year_of[m]] for m in range(total)]
        return vector, vector, warnings

    return _commercial_income_share(inputs), None, warnings


def _build_mixed_noi_vector(inputs: dict, timeline: Timeline) -> dict:
    """Mixed-use composition (H2): the residential path (unit mix, vacancy,
    occupancy ramp) and the commercial lease path run side by side and SUM.
    Fixed opex exists exactly once (carried by the commercial run);
    management fee is EGI-based and therefore splits linearly. For component
    REPORTING, shared fixed opex is allocated pro-rata to monthly component
    EGI under the default basis, or by the chosen I4 basis. Blended NOI =
    residential NOI + commercial NOI by construction under every basis."""
    total_months = timeline.total_months
    com_share, reporting_share_c, alloc_warnings = _allocation_shares(inputs, total_months)
    commercial = _build_lease_noi_vector(
        {**inputs, "unitMix": [], "otherIncome": 0}, timeline,
        recoverable_scale=com_share,
    )
    # Residential run carries NO fixed dollar expenses (they'd double count);
    # its management fee on its own EGI is the correct linear share.
    res_inputs = {**inputs, "commercialLeases": [], "opexLineItems": []}
    for field in EXPENSE_DOLLAR_FIELDS:
        res_inputs[field] = 0
    # Detail mode: keep the res side's EGI-based lines (mgmt fee) by carrying
    # them over as legacy managementFeePct so the linear split still works.
    if has_opex_detail(inputs):
        res_inputs["managementFeePct"] = sum(
            _num(r, "amount")
            for r in (inputs.get("opexLineItems") or [])
            if isinstance(r, dict) and (r.get("basis") or "annual_total") == "pct_of_egi"
        )
    residential = build_noi_vector(res_inputs, timeline)

    total = timeline.total_months
    blended = {key: [residential[key][m] + commercial[key][m] for m in range(total)]
               for key in _INCOME_KEYS}
    mgmt = [residential["managementFee"][m] + commercial["managementFee"][m] for m in range(total)]
    fixed_by_category = commercial["fixedOpexByCategory"]
    fixed_total = [
        sum(vec[m] for vec in fixed_by_category.values()) for m in range(total)
    ]
    opex = [fixed_total[m] + mgmt[m] for m in range(total)]
    noi = [blended["egi"][m] - opex[m] for m in range(total)]

    # EGI-weighted blended occupancy; component fixed-opex allocation for
    # reporting only (the blend is exact regardless).
    occupancy = []
    components = {
        "residential": {k: [] for k in (*_INCOME_KEYS, "opex", "noi")},
        "commercial": {k: [] for k in (*_INCOME_KEYS, "opex", "noi")},
    }
    for m in range(total):
        egi_r, egi_c = residential["egi"][m], commercial["egi"][m]
        egi_total = egi_r + egi_c
        egi_share_r = egi_r / egi_total if egi_total > 0 else 0.5
        # Reporting opex split: legacy monthly-EGI share under the default
        # basis; the chosen I4 basis otherwise (so pool and reporting agree).
        share_r = (
            1 - reporting_share_c[m] if reporting_share_c is not None else egi_share_r
        )
        occupancy.append(
            residential["occupancy"][m] * egi_share_r
            + commercial["occupancy"][m] * (1 - egi_share_r)
        )
        for key in _INCOME_KEYS:
            components["residential"][key].append(residential[key][m])
            components["commercial"][key].append(commercial[key][m])
        opex_r = fixed_total[m] * share_r + residential["managementFee"][m]
        opex_c = fixed_total[m] * (1 - share_r) + commercial["managementFee"][m]
        components["residential"]["opex"].append(opex_r)
        components["commercial"]["opex"].append(opex_c)
        components["residential"]["noi"].append(egi_r - opex_r)
        components["commercial"]["noi"].append(egi_c - opex_c)

    return {
        "noi": noi,
        "egi": blended["egi"],
        "gpr": blended["gpr"],
        "opex": opex,
        "occupancy": occupancy,
        "vacancyLoss": blended["vacancyLoss"],
        "creditLoss": blended["creditLoss"],
        "otherIncome": blended["otherIncome"],
        "managementFee": mgmt,
        "fixedOpexByCategory": fixed_by_category,
        "recoveries": commercial["recoveries"],
        "leasingCapital": commercial["leasingCapital"],
        "leaseDetail": commercial["leaseDetail"],
        "components": components,
        "gprSource": "mixed",
        "warnings": alloc_warnings + residential["warnings"] + commercial["warnings"],
    }


def has_renovation_program(inputs: dict) -> bool:
    return any(
        isinstance(r, dict) and _num(r, "unitsToReno") > 0
        for r in (inputs.get("renovationProgram") or [])
    )


def _renovation_vectors(
    inputs: dict, timeline: Timeline, rent_growth: float
) -> tuple[dict | None, list[str]]:
    """J1: value-add renovation program. Sequences units through the program
    at the stated pace; returns monthly vectors on the OPERATING clock
    (index 0 = operating month 1):

    {offlineRent, premiumRent, capex, unitsComplete, unitsInProgress,
     unitsRemaining, budget, fundingSource, postRenoAvgRent, warnings}

    Conventions ([FIN], DECISIONS.md): a unit in reno earns ZERO rent for
    its downtime months, IN ADDITION to the general vacancy on the rest of
    the pool (no overlap credit); the premium joins the rent basis and
    grows on the SAME deal anniversary clock as rent; capex lands per unit
    in its start month."""
    if not has_renovation_program(inputs):
        return None, []
    warnings: list[str] = []
    total = timeline.total_months
    operating_months = total - timeline.construction_months
    units_by_type = {
        str(r.get("unitType") or ""): (_num(r, "unitCount"), _num(r, "inPlaceRent") or _num(r, "marketRent"))
        for r in (inputs.get("unitMix") or [])
        if isinstance(r, dict)
    }

    offline_rent = [0.0] * operating_months
    premium_rent = [0.0] * operating_months
    capex = [0.0] * operating_months
    complete = [0.0] * operating_months
    in_progress = [0.0] * operating_months
    remaining_vec = [0.0] * operating_months
    budget = 0.0
    total_program_units = 0.0
    post_reno_rent_total = 0.0
    post_reno_units = 0.0

    for program in inputs.get("renovationProgram") or []:
        if not (isinstance(program, dict) and _num(program, "unitsToReno") > 0):
            continue
        unit_type = str(program.get("unitType") or "")
        unit_count, base_rent = units_by_type.get(unit_type, (0.0, 0.0))
        units = _num(program, "unitsToReno")
        if unit_count and units > unit_count:
            warnings.append(
                f"Renovation program for '{unit_type}': {units:.0f} units exceeds "
                f"the {unit_count:.0f} in the mix — capped."
            )
            units = unit_count
        if base_rent <= 0:
            warnings.append(
                f"Renovation program for '{unit_type}' matches no unit-mix row "
                "with a rent — skipped."
            )
            continue
        cost = _num(program, "costPerUnit")
        premium = _num(program, "premiumPerMonth")
        downtime = max(0, int(_num(program, "downtimeMonthsPerUnit")))
        pace = max(1, int(_num(program, "unitsPerMonth", 1)))
        start = max(1, int(_num(program, "startMonth", 1)))
        if start > operating_months:
            warnings.append(
                f"Renovation program for '{unit_type}' starts in operating month "
                f"{start}, after the exit — it never runs."
            )
            continue

        budget += units * cost
        total_program_units += units
        post_reno_rent_total += units * (base_rent + premium)
        post_reno_units += units

        cohorts: list[tuple[int, float]] = []  # (start operating month, units)
        left = units
        month = start
        while left > 0 and month <= operating_months:
            n = min(pace, left)
            cohorts.append((month, n))
            capex[month - 1] += n * cost
            left -= n
            month += 1
        if left > 0:
            warnings.append(
                f"Renovation program for '{unit_type}': {left:.0f} unit(s) never "
                "start before the exit at this pace."
            )

        for om in range(1, operating_months + 1):
            mult = _growth_multiplier(rent_growth, om)
            offline = sum(n for s, n in cohorts if s <= om < s + downtime)
            delivered = sum(n for s, n in cohorts if om >= s + downtime)
            started = sum(n for s, n in cohorts if s <= om)
            offline_rent[om - 1] += offline * base_rent * mult
            premium_rent[om - 1] += delivered * premium * mult
            complete[om - 1] += delivered
            in_progress[om - 1] += started - delivered
            remaining_vec[om - 1] += units - started

    if budget <= 0 and total_program_units <= 0:
        return None, warnings  # nothing runs, but the reasons still surface
    funding = inputs.get("renoFundingSource") or "equity_at_close"
    if funding not in ("equity_at_close", "operating_cash"):
        warnings.append(f"Unknown renoFundingSource '{funding}' — using equity_at_close.")
        funding = "equity_at_close"
    return {
        "offlineRent": offline_rent,
        "premiumRent": premium_rent,
        "capex": capex,
        "unitsComplete": complete,
        "unitsInProgress": in_progress,
        "unitsRemaining": remaining_vec,
        "budget": budget,
        "fundingSource": funding,
        "postRenoAvgRent": (post_reno_rent_total / post_reno_units) if post_reno_units else 0.0,
    }, warnings


def _loss_to_lease_vectors(
    inputs: dict, timeline: Timeline, rent_growth: float, reno: dict | None
) -> dict | None:
    """J2: loss-to-lease burn-off — analytic expected-value blend, no
    per-unit simulation. Active per unit type only when BOTH rents are
    present AND annualTurnoverPct is set (default null = off; Run-4
    behavior effectively prices in-place from day one).

    Per type, month om: the in-place share s = (1 − turnover/12)^(om−1)
    (month 1 is fully in-place), turned units re-let at
    in-place + capture × gap, and — because in-place and market grow on the
    SAME clock — the blend is closed-form. Renovated units EXIT the pool at
    reno start; delivered units re-base to MARKET (+ premium via J1) —
    [FIN]: reno supersedes LTL.

    Returns {upliftScheduled, marketGpr} on the operating clock, or None."""
    capture_raw = inputs.get("lossToLeaseCapturePct")
    capture = float(capture_raw) if isinstance(capture_raw, (int, float)) else 1.0
    capture = min(1.0, max(0.0, capture))

    active_types = []
    for row in inputs.get("unitMix") or []:
        if not isinstance(row, dict):
            continue
        turnover = _num(row, "annualTurnoverPct")
        in_place = _num(row, "inPlaceRent")
        market = _num(row, "marketRent")
        if turnover > 0 and in_place > 0 and market > 0:
            active_types.append({
                "unitType": str(row.get("unitType") or ""),
                "count": _num(row, "unitCount"),
                "inPlace": in_place,
                "market": market,
                "monthlyTurnover": min(1.0, turnover / 12),
            })
    if not active_types:
        return None

    operating_months = timeline.total_months - timeline.construction_months
    uplift = [0.0] * operating_months
    market_gpr = [0.0] * operating_months
    loss = [0.0] * operating_months

    # Reno interaction: per-type started/delivered counts from J1 cohorts.
    reno_by_type: dict[str, dict] = {}
    if reno is not None:
        for program in inputs.get("renovationProgram") or []:
            if isinstance(program, dict) and _num(program, "unitsToReno") > 0:
                reno_by_type[str(program.get("unitType") or "")] = program

    for t in active_types:
        gap = t["market"] - t["inPlace"]
        program = reno_by_type.get(t["unitType"])
        # Rebuild this type's started/delivered schedule (cheap, mirrors J1).
        started_at: list[tuple[int, float]] = []
        downtime = 0
        if program is not None:
            pace = max(1, int(_num(program, "unitsPerMonth", 1)))
            start = max(1, int(_num(program, "startMonth", 1)))
            downtime = max(0, int(_num(program, "downtimeMonthsPerUnit")))
            left = min(_num(program, "unitsToReno"), t["count"])
            month = start
            while left > 0 and month <= operating_months:
                n = min(pace, left)
                started_at.append((month, n))
                left -= n
                month += 1

        premium = _num(program, "premiumPerMonth") if program is not None else 0.0
        f = t["monthlyTurnover"]
        for om in range(1, operating_months + 1):
            mult = _growth_multiplier(rent_growth, om)
            started = sum(n for s0, n in started_at if s0 <= om)
            delivered = sum(n for s0, n in started_at if om >= s0 + downtime)
            offline = started - delivered
            pool = max(0.0, t["count"] - started)
            in_place_share = (1 - f) ** (om - 1)
            uplift[om - 1] += (
                pool * (1 - in_place_share) * capture * gap
                + delivered * gap  # post-reno basis is FULL market
            ) * mult
            # Display build: GPR at market (delivered premiums are potential
            # above market) less loss-to-lease = scheduled rent.
            market_gpr[om - 1] += (t["count"] * t["market"] + delivered * premium) * mult
            loss[om - 1] += gap * (
                pool * (1 - (1 - in_place_share) * capture) + offline
            ) * mult

    return {"upliftScheduled": uplift, "marketGpr": market_gpr, "lossToLease": loss}


def build_noi_vector(inputs: dict, timeline: Timeline) -> dict:
    """Returns monthly vectors for months 1..total_months:
    {"noi", "egi", "gpr", "opex", "occupancy", "gprSource", "warnings"} plus
    the statement components ("vacancyLoss", "creditLoss", "otherIncome",
    "managementFee", "fixedOpexByCategory") — identities hold by
    construction: egi = gpr - vacancyLoss - creditLoss + otherIncome and
    noi = egi - opex. Lease-level commercial rent rolls route through
    _build_lease_noi_vector (extra keys: recoveries, leasingCapital,
    leaseDetail)."""
    if leases.has_leases(inputs) and has_residential(inputs):
        return _build_mixed_noi_vector(inputs, timeline)
    if leases.has_leases(inputs):
        return _build_lease_noi_vector(inputs, timeline)

    annual_gpr, annual_other, source, warnings = annual_gpr_and_other_income(inputs)

    rent_growth = (
        _num(inputs, "rentGrowthPct") if inputs.get("rentGrowthMode") != "flat" else 0.0
    )
    vacancy_pct = _num(inputs, "vacancyPct", 0.05)
    credit_loss_pct = _num(inputs, "creditLossPct")
    stabilized_occupancy = max(0.0, 1 - vacancy_pct)

    expenses = _fixed_expense_vectors(inputs, timeline)
    warnings.extend(expenses["warnings"])
    management_fee_pct = expenses["egiPctTotal"]
    fixed_by_category = expenses["byCategory"]

    # J1: renovation program (None at defaults — the loop math is untouched).
    reno, reno_warnings = _renovation_vectors(inputs, timeline, rent_growth)
    warnings.extend(reno_warnings)
    # J2: loss-to-lease burn-off (None at defaults).
    ltl = _loss_to_lease_vectors(inputs, timeline, rent_growth, reno)

    gpr_vec: list[float] = []
    egi_vec: list[float] = []
    opex_vec: list[float] = []
    noi_vec: list[float] = []
    occupancy_vec: list[float] = []
    vacancy_vec: list[float] = []
    credit_vec: list[float] = []
    other_vec: list[float] = []
    mgmt_fee_vec: list[float] = []

    for month in range(1, timeline.total_months + 1):
        phase = timeline.phase(month)
        # Growth clocks run from the start of OPERATIONS (post-construction),
        # so a 24-month build doesn't silently bank two years of rent growth.
        operating_month = month - timeline.construction_months
        if operating_month < 1:
            for vec in (
                gpr_vec, egi_vec, opex_vec, noi_vec, occupancy_vec,
                vacancy_vec, credit_vec, other_vec, mgmt_fee_vec,
            ):
                vec.append(0.0)
            continue

        if phase == "lease_up":
            ramp_months = max(1, timeline.stabilization_month - timeline.construction_months - 1)
            progress = (month - timeline.construction_months) / ramp_months
            occupancy = stabilized_occupancy * min(1.0, progress)
        else:
            occupancy = stabilized_occupancy

        rent_mult = _growth_multiplier(rent_growth, operating_month)

        gpr_month = (annual_gpr / 12) * rent_mult
        other_month = (annual_other / 12) * rent_mult
        if ltl is not None:
            # J2: turned units' captured gap joins scheduled rent.
            om_ltl = operating_month - 1
            if om_ltl < len(ltl["upliftScheduled"]):
                gpr_month += ltl["upliftScheduled"][om_ltl]
        if reno is not None:
            # J1: delivered premiums join GPR; offline units lose 100% of
            # their rent IN ADDITION to the general vacancy on the rest of
            # the pool (no overlap credit — [FIN], DECISIONS.md).
            om_index = operating_month - 1
            premium = reno["premiumRent"][om_index] if om_index < len(reno["premiumRent"]) else 0.0
            offline = reno["offlineRent"][om_index] if om_index < len(reno["offlineRent"]) else 0.0
            gpr_month += premium
            vacancy_loss_month = (gpr_month - offline) * (1 - occupancy) + offline
        else:
            vacancy_loss_month = gpr_month * (1 - occupancy)
        # Credit loss applies to collected (occupied) revenue.
        credit_loss_month = (gpr_month - vacancy_loss_month) * credit_loss_pct
        collected_rent = gpr_month - vacancy_loss_month - credit_loss_month
        # Ancillary income scales with occupancy too — an empty building
        # collects no parking/RUBS.
        occupancy_share = occupancy / stabilized_occupancy if stabilized_occupancy > 0 else 0.0
        other_income_month = other_month * occupancy_share
        egi_month = collected_rent + other_income_month

        fixed_expenses_month = sum(vec[month - 1] for vec in fixed_by_category.values())
        management_fee_month = egi_month * management_fee_pct
        opex_month = fixed_expenses_month + management_fee_month

        gpr_vec.append(gpr_month)
        egi_vec.append(egi_month)
        opex_vec.append(opex_month)
        noi_vec.append(egi_month - opex_month)
        occupancy_vec.append(occupancy)
        vacancy_vec.append(vacancy_loss_month)
        credit_vec.append(credit_loss_month)
        other_vec.append(other_income_month)
        mgmt_fee_vec.append(management_fee_month)

    result = {
        "noi": noi_vec,
        "egi": egi_vec,
        "gpr": gpr_vec,
        "opex": opex_vec,
        "occupancy": occupancy_vec,
        "vacancyLoss": vacancy_vec,
        "creditLoss": credit_vec,
        "otherIncome": other_vec,
        "managementFee": mgmt_fee_vec,
        "fixedOpexByCategory": fixed_by_category,
        "gprSource": source,
        "warnings": warnings,
    }

    if reno is not None:
        cm = timeline.construction_months
        pad = [0.0] * cm

        def _month_indexed(vec: list[float]) -> list[float]:
            return (pad + list(vec))[: timeline.total_months]

        result["renovation"] = {
            "capex": _month_indexed(reno["capex"]),
            "unitsComplete": _month_indexed(reno["unitsComplete"]),
            "unitsInProgress": _month_indexed(reno["unitsInProgress"]),
            "unitsRemaining": _month_indexed(reno["unitsRemaining"]),
            "budget": reno["budget"],
            "fundingSource": reno["fundingSource"],
            "postRenoAvgRent": reno["postRenoAvgRent"],
        }
    if ltl is not None:
        cm2 = timeline.construction_months
        pad2 = [0.0] * cm2
        result["lossToLease"] = {
            "marketGpr": (pad2 + list(ltl["marketGpr"]))[: timeline.total_months],
            "lossToLease": (pad2 + list(ltl["lossToLease"]))[: timeline.total_months],
        }
    return result


def reserves_vector(
    inputs: dict, timeline: Timeline
) -> tuple[list[float] | None, float, list[str]]:
    """J6: replacement reserves as ONE monthly dollar vector on the
    expense-growth clock (operating months only). Returns (vector indexed
    0..total_months-1, year-1 annual base, warnings), or (None, 0.0,
    warnings) when the inputs are absent or inert. The reservesConvention
    toggle changes only WHERE the engine places these dollars ([FIN],
    DECISIONS.md), never how many there are.

    Bases: $/unit/yr x the unit-mix count; $/SF/yr x commercial SF (lease
    roll SF, else rentableSf). Both may coexist on a mixed-use deal. The
    pre-existing flat `replacementReserves` opex field is untouched."""
    per_unit = _num(inputs, "replacementReservesPerUnit")
    per_sf = _num(inputs, "replacementReservesPsf")
    warnings: list[str] = []
    if per_unit <= 0 and per_sf <= 0:
        return None, 0.0, warnings

    units = sum(
        _num(r, "unitCount") for r in (inputs.get("unitMix") or []) if isinstance(r, dict)
    )
    commercial_sf = sum(
        _num(r, "sf") for r in (inputs.get("commercialLeases") or []) if isinstance(r, dict)
    )
    if commercial_sf <= 0:
        commercial_sf = _num(inputs, "rentableSf")

    annual = 0.0
    if per_unit > 0:
        if units > 0:
            annual += per_unit * units
        else:
            warnings.append(
                "replacementReservesPerUnit is set but the deal has no unit mix — "
                "the per-unit reserve contributes nothing."
            )
    if per_sf > 0:
        if commercial_sf > 0:
            annual += per_sf * commercial_sf
        else:
            warnings.append(
                "replacementReservesPsf is set but the deal has no commercial SF "
                "(lease roll or rentableSf) — the PSF reserve contributes nothing."
            )
    if annual <= 0:
        return None, 0.0, warnings

    expense_growth = (
        _num(inputs, "expenseGrowthPct") if inputs.get("expenseGrowthMode") != "flat" else 0.0
    )
    vec: list[float] = []
    for month in range(1, timeline.total_months + 1):
        operating_month = month - timeline.construction_months
        if operating_month < 1:
            vec.append(0.0)
        else:
            vec.append(annual / 12 * _growth_multiplier(expense_growth, operating_month))
    return vec, annual, warnings


def stabilized_annual_noi(inputs: dict) -> float:
    """Stabilized-year NOI at today's rents (no growth): the sizing/exit basis
    when the deal's own vectors haven't stabilized. Mirrors one stabilized
    month x 12 of build_noi_vector's math. Lease deals use the first
    12 months of the lease-driven NOI (in-place, before rollover) — see
    DECISIONS.md."""
    if leases.has_leases(inputs):
        if has_residential(inputs):
            return sum(_build_mixed_noi_vector(inputs, Timeline(12, 0, 0, 1))["noi"])
        window = _build_lease_noi_vector(inputs, Timeline(12, 0, 0, 1))
        return sum(window["noi"])
    if has_opex_detail(inputs):
        # Detail mode: mirror the vector math over a 12-month in-place window.
        return sum(build_noi_vector(inputs, Timeline(12, 0, 0, 1))["noi"])

    annual_gpr, annual_other, _, _ = annual_gpr_and_other_income(inputs)
    vacancy_pct = _num(inputs, "vacancyPct", 0.05)
    credit_loss_pct = _num(inputs, "creditLossPct")
    management_fee_pct = _num(inputs, "managementFeePct")
    occupancy = max(0.0, 1 - vacancy_pct)
    egi = annual_gpr * occupancy * (1 - credit_loss_pct) + annual_other
    category_bases = {f: _num(inputs, f) for f in EXPENSE_DOLLAR_FIELDS}
    # Run 6 (B2): the reassessment substitution (H4) applies to the legacy
    # stabilized figure exactly as it does to the expense vectors, so sizing
    # NOI / debt yield / YoC / break-evens move with useReassessedTaxes.
    reassessed_taxes, _ = _reassessed_tax_annual(inputs)
    if reassessed_taxes is not None:
        category_bases["realEstateTaxes"] = reassessed_taxes
    expenses = (
        sum(category_bases.values())
        + _num(inputs, "nonAdValoremTaxes")  # I5: separate fixed line
        + egi * management_fee_pct
    )
    return egi - expenses
