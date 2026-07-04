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


def _num(inputs: dict, field: str, default: float = 0.0) -> float:
    value = inputs.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def annual_gpr_and_other_income(inputs: dict) -> tuple[float, float, str, list[str]]:
    """Returns (annual GPR, annual other income, source, warnings)."""
    warnings: list[str] = []

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


def build_noi_vector(inputs: dict, timeline: Timeline) -> dict:
    """Returns monthly vectors for months 1..total_months:
    {"noi", "egi", "gpr", "opex", "occupancy", "gprSource", "warnings"} plus
    the statement components ("vacancyLoss", "creditLoss", "otherIncome",
    "managementFee", "fixedOpexByCategory") — identities hold by
    construction: egi = gpr - vacancyLoss - creditLoss + otherIncome and
    noi = egi - opex."""
    annual_gpr, annual_other, source, warnings = annual_gpr_and_other_income(inputs)

    rent_growth = (
        _num(inputs, "rentGrowthPct") if inputs.get("rentGrowthMode") != "flat" else 0.0
    )
    expense_growth = (
        _num(inputs, "expenseGrowthPct") if inputs.get("expenseGrowthMode") != "flat" else 0.0
    )
    vacancy_pct = _num(inputs, "vacancyPct", 0.05)
    credit_loss_pct = _num(inputs, "creditLossPct")
    management_fee_pct = _num(inputs, "managementFeePct")
    stabilized_occupancy = max(0.0, 1 - vacancy_pct)

    category_bases = {f: _num(inputs, f) for f in EXPENSE_DOLLAR_FIELDS}
    annual_expense_base = sum(category_bases.values())
    active_categories = [f for f, v in category_bases.items() if v > 0]

    gpr_vec: list[float] = []
    egi_vec: list[float] = []
    opex_vec: list[float] = []
    noi_vec: list[float] = []
    occupancy_vec: list[float] = []
    vacancy_vec: list[float] = []
    credit_vec: list[float] = []
    other_vec: list[float] = []
    mgmt_fee_vec: list[float] = []
    fixed_by_category: dict[str, list[float]] = {f: [] for f in active_categories}

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
            for f in active_categories:
                fixed_by_category[f].append(0.0)
            continue

        if phase == "lease_up":
            ramp_months = max(1, timeline.stabilization_month - timeline.construction_months - 1)
            progress = (month - timeline.construction_months) / ramp_months
            occupancy = stabilized_occupancy * min(1.0, progress)
        else:
            occupancy = stabilized_occupancy

        rent_mult = _growth_multiplier(rent_growth, operating_month)
        expense_mult = _growth_multiplier(expense_growth, operating_month)

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

        fixed_expenses_month = (annual_expense_base / 12) * expense_mult
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
        for f in active_categories:
            fixed_by_category[f].append((category_bases[f] / 12) * expense_mult)

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
    month x 12 of build_noi_vector's math."""
    annual_gpr, annual_other, _, _ = annual_gpr_and_other_income(inputs)
    vacancy_pct = _num(inputs, "vacancyPct", 0.05)
    credit_loss_pct = _num(inputs, "creditLossPct")
    management_fee_pct = _num(inputs, "managementFeePct")
    occupancy = max(0.0, 1 - vacancy_pct)
    egi = annual_gpr * occupancy * (1 - credit_loss_pct) + annual_other
    expenses = sum(_num(inputs, f) for f in EXPENSE_DOLLAR_FIELDS) + egi * management_fee_pct
    return egi - expenses
