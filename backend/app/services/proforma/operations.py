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
        recoverable_base = sum(_num(inputs, f) for f in RECOVERABLE_EXPENSE_FIELDS)
        income = leases.build_lease_income(
            inputs, 12, [recoverable_base / 12] * 12, _num(inputs, "expenseGrowthPct", 0.025)
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

    if has_opex_detail(inputs):
        lines = []
        egi_pct_total = 0.0
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
            key = _DETAIL_CATEGORY_KEYS.get(raw.get("category") or "other", "otherOpex")
            recoverable_flag = raw.get("recoverable") in (True, "yes", "true", 1)
            lines.append({"key": key, "annual": annual, "growth": growth,
                          "recoverable": recoverable_flag})

        by_category: dict[str, list[float]] = {}
        recoverable = [0.0] * total
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
        return {
            "byCategory": by_category,
            "recoverable": recoverable,
            "expenseGrowth": expense_growth,
            "egiPctTotal": egi_pct_total,
            "detailMode": True,
            "warnings": warnings,
        }

    category_bases = {f: _num(inputs, f) for f in EXPENSE_DOLLAR_FIELDS}
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
        month_recoverable = 0.0
        for f in active:
            amount = (category_bases[f] / 12) * mult
            by_category[f].append(amount)
            if f in RECOVERABLE_EXPENSE_FIELDS:
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


def _build_lease_noi_vector(
    inputs: dict, timeline: Timeline, recoverable_scale: float = 1.0
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
    recoverable = [v * recoverable_scale for v in expenses["recoverable"]]
    income = leases.build_lease_income(
        inputs, total, recoverable, expenses["expenseGrowth"]
    )
    warnings.extend(income["warnings"])

    if timeline.construction_months > 0:
        warnings.append(
            "Commercial leases are modeled from the analysis start — lease income "
            "during the construction period is zeroed."
        )

    credit_loss_pct = _num(inputs, "creditLossPct")
    management_fee_pct = expenses["egiPctTotal"]
    rent_growth = (
        _num(inputs, "rentGrowthPct") if inputs.get("rentGrowthMode") != "flat" else 0.0
    )
    other_annual = _num(inputs, "otherIncome")

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


def _build_mixed_noi_vector(inputs: dict, timeline: Timeline) -> dict:
    """Mixed-use composition (H2): the residential path (unit mix, vacancy,
    occupancy ramp) and the commercial lease path run side by side and SUM.
    Fixed opex exists exactly once (carried by the commercial run);
    management fee is EGI-based and therefore splits linearly. For component
    REPORTING, shared fixed opex is allocated pro-rata to monthly component
    EGI. Blended NOI = residential NOI + commercial NOI by construction."""
    com_share = _commercial_income_share(inputs)
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
        share_r = egi_r / egi_total if egi_total > 0 else 0.5
        occupancy.append(
            residential["occupancy"][m] * share_r + commercial["occupancy"][m] * (1 - share_r)
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
        "warnings": residential["warnings"] + commercial["warnings"],
    }


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
        # Credit loss applies to collected (occupied) revenue.
        vacancy_loss_month = gpr_month * (1 - occupancy)
        credit_loss_month = gpr_month * occupancy * credit_loss_pct
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

    return {
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
    expenses = sum(_num(inputs, f) for f in EXPENSE_DOLLAR_FIELDS) + egi * management_fee_pct
    return egi - expenses
