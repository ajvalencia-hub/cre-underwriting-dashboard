"""Native pro-forma engine: schema-shaped inputs dict in, all schema output
ids out. Orchestration only — every formula lives in the sibling modules
(timeline / development / operations / debt / equity / returns), and nothing
outside this package reimplements any of them.
"""

from app.services.proforma import debt, development, equity, input_validation, operations, returns
from app.services.proforma.timeline import (
    ANALYSIS_EPOCH,
    Timeline,
    analysis_calendar,
    build_timeline,
    month_end_dates,
    parse_analysis_start,
)


class InsufficientInputsError(Exception):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"Missing or invalid required inputs: {', '.join(missing)}")


def _num(inputs: dict, field: str, default: float = 0.0) -> float:
    value = inputs.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


_GOVERNING_LABELS = {
    "ltv": "LTV",
    "dscr": "DSCR",
    "debtYield": "Debt yield",
    "manual": "Manual (loan amount input)",
    "none": "None",
}


def _resolve_sizing_noi(inputs: dict, stabilized_noi: float, year1_noi: float) -> float:
    """Sizing-basis convention (see DECISIONS.md): in_place = the inPlaceNoi
    input (falling back to computed year-1), stabilized = the stabilizedNoi
    input (falling back to the engine's computed stabilized NOI),
    underwritten = the engine's computed stabilized NOI regardless of inputs."""
    basis = inputs.get("sizingNoiBasis") or "stabilized"
    if basis == "in_place":
        explicit = _num(inputs, "inPlaceNoi")
        return explicit if explicit > 0 else year1_noi
    if basis == "underwritten":
        return stabilized_noi
    explicit = _num(inputs, "stabilizedNoi")
    return explicit if explicit > 0 else stabilized_noi


def _operating_break_evens(statement: dict, total: int) -> dict:
    """J9: per CALENDAR YEAR, the economic occupancy at which levered
    operating cash flow is zero holding rents, and the rent level (fraction
    of scheduled) at which it is zero holding occupancy — solved
    ANALYTICALLY on the statement's own annual sums (both are linear given
    the pinned conventions; no engine recomputes).

    Conventions [FIN]: operating flows only — close, sale proceeds, debt
    draws, loan fees, and escrow timing are excluded. The management fee
    scales with EGI at the year's modeled effective rate; other income
    scales with occupancy (mirroring the engine); every other below-NOI
    cash cost (debt service, TI/LC, reno draws, AM fee, junior interest,
    below-NOI reserves) is held at modeled levels — variable-with-occupancy
    opex is NOT re-flexed, which biases the break-evens conservative (high).
    Impossible years return null with a note, never an out-of-range number.
    """
    def _yr(vec: list[float], year: int) -> float:
        return sum(vec[m] for m in range(12 * (year - 1) + 1, min(12 * year, total) + 1))

    zeros = [0.0] * (total + 1)
    years = []
    for year in range(1, (total + 11) // 12 + 1):
        gpr = _yr(statement["gpr"], year)
        notes: list[str] = []
        if gpr <= 0:
            years.append({
                "year": year, "occupancy": None, "rentFactor": None,
                "notes": ["No operating revenue this year (construction)."],
            })
            continue
        vacancy = _yr(statement["vacancyLoss"], year)
        credit = _yr(statement["creditLoss"], year)
        other = _yr(statement["otherIncome"], year)
        egi = _yr(statement["egi"], year)
        mgmt = _yr(statement["managementFee"], year)
        fixed = _yr(statement["opexTotal"], year) - mgmt
        below = (
            _yr(statement["debtService"], year)
            + _yr(statement["leasingCapital"], year)
            + _yr(statement.get("renovationCapex", zeros), year)
            + _yr(statement.get("assetMgmtFee", zeros), year)
            + _yr(statement.get("juniorInterest", zeros), year)
            + _yr(statement.get("replacementReserves", zeros), year)
        )
        mgmt_pct = mgmt / egi if egi > 0 else 0.0
        occupied = gpr - vacancy
        occupancy_now = occupied / gpr
        credit_pct = credit / occupied if occupied > 0 else 0.0
        # EGI needed so that EGI·(1−mgmt%) covers fixed opex + below-NOI cash.
        needed_egi = (fixed + below) / (1 - mgmt_pct) if mgmt_pct < 1 else None

        occupancy_be = rent_be = None
        if needed_egi is not None:
            denom_occ = gpr * (1 - credit_pct) + (
                other / occupancy_now if occupancy_now > 0 else 0.0
            )
            if denom_occ > 0:
                solved = needed_egi / denom_occ
                if solved > 1:
                    notes.append(
                        f"Cannot break even on occupancy — even 100% occupied "
                        f"falls short (needs {solved:.0%})."
                    )
                elif solved < 0:
                    occupancy_be = 0.0
                    notes.append("Positive levered cash flow even at zero occupancy.")
                else:
                    occupancy_be = solved
            denom_rent = gpr - vacancy - credit
            if denom_rent > 0:
                solved = (needed_egi - other) / denom_rent
                if solved > 1:
                    notes.append(
                        f"Cannot break even at scheduled rents — would need "
                        f"{solved:.0%} of scheduled."
                    )
                elif solved < 0:
                    rent_be = 0.0
                    notes.append("Positive levered cash flow even at zero rent.")
                else:
                    rent_be = solved
        else:
            notes.append("Management fee consumes all revenue — no break-even.")
        years.append({
            "year": year, "occupancy": occupancy_be, "rentFactor": rent_be,
            "notes": notes,
        })
    return {"years": years}


def compute(inputs: dict) -> dict:
    """Returns {"outputs": {<schema output id>: float}, "warnings": [str]}.
    Raises InsufficientInputsError naming every missing required field.

    [FIN] Month 0 is the deal's analysisStartDate (closing) when given —
    lease dates, base years and XIRR dates map onto the calendar from there;
    blank keeps the fixed ANALYSIS_EPOCH (2026-01-01)."""
    try:
        start = parse_analysis_start(inputs.get("analysisStartDate"))
        start_warning = None
    except ValueError:
        start = None
        start_warning = (
            f"Analysis start date '{inputs.get('analysisStartDate')}' isn't a date "
            f"(YYYY-MM-DD) — using {ANALYSIS_EPOCH.isoformat()}."
        )
    inputs, input_warnings, input_errors = input_validation.validate_inputs(inputs)
    if input_errors:
        raise InsufficientInputsError(input_errors)
    with analysis_calendar(start):
        result = _compute(inputs)
    result["warnings"][:0] = ([start_warning] if start_warning else []) + input_warnings
    return result


def _compute(inputs: dict) -> dict:
    warnings: list[str] = []

    deal_type = inputs.get("dealType")
    hold_years = _num(inputs, "holdPeriodYears")
    exit_cap = _num(inputs, "exitCapRatePct")

    missing: list[str] = []
    if deal_type not in ("acquisition", "development"):
        missing.append("dealType")
    if hold_years <= 0:
        missing.append("holdPeriodYears")
    if exit_cap <= 0:
        missing.append("exitCapRatePct")

    annual_gpr, _, gpr_source, _ = operations.annual_gpr_and_other_income(inputs)
    if annual_gpr <= 0:
        missing.append("grossPotentialRent (or a unitMix / per-SF rent section)")

    if deal_type == "acquisition" and _num(inputs, "purchasePrice") <= 0:
        missing.append("purchasePrice")
    if deal_type == "development":
        if _num(inputs, "landCost") <= 0:
            missing.append("landCost")
        if _num(inputs, "hardCosts") <= 0:
            missing.append("hardCosts")

    if missing:
        raise InsufficientInputsError(missing)

    timeline, tl_warnings = build_timeline(
        deal_type,
        hold_years,
        construction_months=_num(inputs, "constructionMonths") or None,
        lease_up_months=_num(inputs, "leaseUpMonths") or None,
        stabilization_month=_num(inputs, "stabilizationMonth") or None,
    )
    warnings.extend(tl_warnings)
    total = timeline.total_months

    # Operate 12 months past exit so the terminal value can be capped on
    # FORWARD 12-month NOI (institutional convention).
    extended = Timeline(
        total + 12,
        timeline.construction_months,
        timeline.lease_up_months,
        timeline.stabilization_month,
    )
    ops = operations.build_noi_vector(inputs, extended)
    warnings.extend(ops["warnings"])
    noi = ops["noi"][:total]
    forward_noi_12 = sum(ops["noi"][total : total + 12])
    stabilized_noi = operations.stabilized_annual_noi(inputs)
    in_place_stabilized_noi = stabilized_noi  # before the reserves adjustment

    # J6: replacement reserves — ONE dollar vector; the convention changes
    # only where the line sits. above_noi_underwritten folds it into opex
    # for ALL NOI-derived metrics (exit value, DSCR, sizing) right here,
    # before anything consumes NOI; below_noi (the default) treats it as a
    # capital cost after NOI further down. None at defaults — baseline-safe.
    reserves_full, reserves_annual, reserves_warnings = operations.reserves_vector(
        inputs, extended
    )
    warnings.extend(reserves_warnings)
    reserves_convention = inputs.get("reservesConvention") or "below_noi"
    if reserves_full is not None and reserves_convention == "above_noi_underwritten":
        for i, amount in enumerate(reserves_full):
            ops["noi"][i] -= amount
            ops["opex"][i] += amount
        # Distinct category key — "replacementReserves" is already taken by
        # the legacy flat opex field.
        ops["fixedOpexByCategory"]["reservesUnderwritten"] = reserves_full
        noi = ops["noi"][:total]
        forward_noi_12 = sum(ops["noi"][total : total + 12])
        stabilized_noi -= reserves_annual
    # Leasing capital (TI/LC on commercial rollovers, H1) is a capital cost
    # BELOW NOI: it hits the cash-flow vectors but never DSCR or the exit cap
    # basis. Zeros for non-lease deals.
    leasing_capital = (ops.get("leasingCapital") or [0.0] * total)[:total]

    cost_of_sale = _num(inputs, "costOfSalePct")
    # Component-level exit (H2): when BOTH component caps are provided on a
    # mixed deal, blended value = sum of component forward NOIs at their own
    # caps; otherwise the single-cap behavior is unchanged.
    components = ops.get("components")
    res_exit_cap = _num(inputs, "residentialExitCapPct")
    com_exit_cap = _num(inputs, "commercialExitCapPct")
    if components and res_exit_cap > 0 and com_exit_cap > 0:
        terminal_value = (
            sum(components["residential"]["noi"][total : total + 12]) / res_exit_cap
            + sum(components["commercial"]["noi"][total : total + 12]) / com_exit_cap
        )
    else:
        terminal_value = forward_noi_12 / exit_cap
    gross_sale_net_of_costs = terminal_value * (1 - cost_of_sale)

    ltc_or_ltv = _num(inputs, "ltvOrLtc", 0.65)
    # Development: the permanent takeout can size to its own max LTV (a 60%
    # LTC construction loan often refis into a 65-70% LTV perm). Blank keeps
    # the shared ltvOrLtc. Acquisitions have one loan: always ltvOrLtc.
    perm_ltv = ltc_or_ltv
    if (inputs.get("dealType") or "acquisition") == "development" and inputs.get("permanentLtvPct") not in (None, ""):
        perm_ltv = _num(inputs, "permanentLtvPct", ltc_or_ltv)
    interest_rate = _num(inputs, "interestRate", 0.065)
    amort_years = _num(inputs, "amortYears", 30)
    io_months = int(_num(inputs, "ioMonths"))
    origination_fee_pct = _num(inputs, "originationFeePct")
    dscr_constraint = _num(inputs, "dscrConstraint", 1.25)
    debt_yield_constraint = _num(inputs, "debtYieldConstraint", 0.08)

    # J5: floating-rate senior debt. rate_vec[m-1] is the all-in annual rate
    # for month m; None in fixed mode (the default — reproduces Run 4
    # exactly). Sizing and the reported loan constant use the in-force rate
    # at the loan's funding event ([FIN]: the rate quoted at close/takeout,
    # not a curve average — a lender sizes at today's rate, the curve is the
    # borrower's carry risk).
    rate_vec = debt.floating_rate_vector(inputs, total)
    if rate_vec is not None:
        interest_rate = rate_vec[0]

    year1_noi = sum(noi[: min(12, total)]) * (12 / min(12, total)) if total else 0.0
    sizing_noi = _resolve_sizing_noi(inputs, stabilized_noi, year1_noi)

    # ------------------------------------------------------------------
    # Cost basis, financing, and the two cash-flow vectors (index 0 = close,
    # index `total` = final operating month + exit settlement).
    # ------------------------------------------------------------------
    unlevered = [0.0] * (total + 1)
    levered = [0.0] * (total + 1)
    debt_service: list[debt.DebtServiceMonth | None] = [None] * (total + 1)
    # The rate the PERMANENT loan actually carries — reassigned to the refi
    # rate at a development takeout; acquisitions keep the input rate.
    interest_rate_for_perm = interest_rate

    sources_and_uses: dict = {"uses": [], "sources": []}
    construction_loan: dict | None = None  # development: the solved LTC sizing
    gp_developer_fee = 0.0  # J3: captured in the development branch

    # Statement vectors (index 0 = close), assembled alongside the cash-flow
    # build so the period detail is the SAME numbers, never a recomputation.
    stmt_costs = [0.0] * (total + 1)  # project cash costs (ex loan fees)
    stmt_loan_fees = [0.0] * (total + 1)  # cash loan fees (levered only)
    stmt_equity_funded = [0.0] * (total + 1)
    stmt_debt_draws = [0.0] * (total + 1)  # loan fundings incl. net refi delta
    stmt_interest = [0.0] * (total + 1)
    stmt_principal = [0.0] * (total + 1)
    stmt_service = [0.0] * (total + 1)
    stmt_balance = [0.0] * (total + 1)

    if deal_type == "acquisition":
        purchase_price = _num(inputs, "purchasePrice")
        basis = (
            purchase_price
            + purchase_price * _num(inputs, "closingCostsPct")
            + purchase_price * _num(inputs, "acquisitionFeePct")
            + _num(inputs, "dueDiligenceCosts")
            + _num(inputs, "dayOneCapex")
        )
        # ltvOrLtc = 0 is an explicit all-equity request — the DSCR/debt-yield
        # constraints are caps on proceeds, never a source of them.
        explicit_loan = _num(inputs, "loanAmount")
        sizing = debt.size_permanent_loan(
            sizing_noi, purchase_price, ltc_or_ltv, dscr_constraint,
            debt_yield_constraint, interest_rate, amort_years,
        ) if ltc_or_ltv > 0 or explicit_loan > 0 else debt.PermSizing(0.0, "none", {})
        if explicit_loan > 0:
            loan_amount = explicit_loan
            governing_constraint = "manual"
            if sizing.amount > 0 and explicit_loan > sizing.amount * 1.0001:
                warnings.append(
                    f"Loan amount input (${explicit_loan:,.0f}) exceeds the "
                    f"constraint-sized proceeds (${sizing.amount:,.0f}, governed "
                    f"by {_GOVERNING_LABELS[sizing.governing_constraint]})."
                )
        elif ltc_or_ltv <= 0:
            loan_amount = 0.0
            governing_constraint = "none"
        elif sizing.amount > 0:
            loan_amount = sizing.amount
            governing_constraint = sizing.governing_constraint
        else:
            loan_amount = ltc_or_ltv * purchase_price
            governing_constraint = "ltv"
        loan_fees = loan_amount * origination_fee_pct
        initial_equity = basis - loan_amount + loan_fees
        total_cost_basis = basis + loan_fees

        unlevered[0] = -basis
        levered[0] = -initial_equity

        schedule = (
            debt.amortization_schedule_floating(
                loan_amount, rate_vec, amort_years, io_months, total
            )
            if rate_vec is not None
            else debt.amortization_schedule(
                loan_amount, interest_rate, amort_years, io_months, total
            )
        )
        for m in range(1, total + 1):
            unlevered[m] += noi[m - 1]
            levered[m] += noi[m - 1] - schedule[m - 1].payment
            debt_service[m] = schedule[m - 1]
        exit_debt_balance = schedule[total - 1].balance if schedule else 0.0
        takeout_month = 1
        perm_loan = loan_amount
        value_for_ltv = purchase_price

        stmt_costs[0] = basis
        stmt_loan_fees[0] = loan_fees
        stmt_equity_funded[0] = initial_equity
        stmt_debt_draws[0] = loan_amount
        stmt_balance[0] = loan_amount
        for m in range(1, total + 1):
            entry = schedule[m - 1]
            stmt_interest[m] = entry.interest
            stmt_principal[m] = entry.principal
            stmt_service[m] = entry.payment
            stmt_balance[m] = entry.balance

        sources_and_uses["uses"] = [
            ("Purchase price", purchase_price),
            ("Closing costs", purchase_price * _num(inputs, "closingCostsPct")),
            ("Acquisition fee", purchase_price * _num(inputs, "acquisitionFeePct")),
            ("Due diligence", _num(inputs, "dueDiligenceCosts")),
            ("Day-1 capex", _num(inputs, "dayOneCapex")),
            ("Loan fees", loan_fees),
        ]
        sources_and_uses["sources"] = [
            ("Senior loan", loan_amount),
            ("Equity", initial_equity),
        ]

    else:  # development
        budget = development.build_budget(
            land_cost=_num(inputs, "landCost"),
            hard_costs=_num(inputs, "hardCosts"),
            soft_costs=_num(inputs, "softCosts"),
            contingency_pct=_num(inputs, "contingencyPct", 0.05),
            developer_fee_pct=_num(inputs, "developerFeePct", 0.04),
        )
        cost_schedule = development.monthly_cost_schedule(
            budget, timeline.construction_months
        )
        gp_developer_fee = budget.developer_fee  # J3: a GP fee stream
        # LTC applies to total cost INCLUDING capitalized interest and loan
        # fees (lender convention); solved iteratively. See DECISIONS.md.
        financing, equity_target, construction_commitment = debt.size_construction_loan(
            cost_schedule, budget.total_ex_financing, ltc_or_ltv, interest_rate,
            origination_fee_pct, rate_vector=rate_vec,
        )
        total_cost_basis = (
            budget.total_ex_financing
            + financing.interest_capitalized
            + financing.fee_capitalized
        )
        initial_equity = equity_target
        construction_loan = {
            "commitment": construction_commitment,
            "equity": equity_target,
            "totalCost": total_cost_basis,
            "ltc": construction_commitment / total_cost_basis if total_cost_basis > 0 else None,
        }

        for m, cost in enumerate(cost_schedule):
            if m <= total:
                unlevered[m] -= cost
                levered[m] -= financing.equity_funded[m]
                stmt_costs[m] = cost
                stmt_equity_funded[m] = financing.equity_funded[m]
                stmt_debt_draws[m] = financing.draws[m]
                stmt_balance[m] = financing.balances[m]
                if m >= 1:
                    # Capitalized interest (and the fee at the first draw) is
                    # the balance change beyond the cash draw.
                    stmt_interest[m] = (
                        financing.balances[m] - financing.balances[m - 1] - financing.draws[m]
                    )
        for m in range(1, total + 1):
            unlevered[m] += noi[m - 1]

        # Carry from construction end to perm takeout: interest accrues on the
        # balance; NOI is swept against it (levered CF is zero pre-takeout).
        takeout_month = min(timeline.stabilization_month, total + 1)
        balance = financing.ending_balance
        r = interest_rate / 12

        def _carry_rate(m: int) -> float:
            # J5: carry months accrue at the floating rate when in force.
            if rate_vec is None:
                return r
            return (rate_vec[m - 1] if m - 1 < len(rate_vec) else rate_vec[-1]) / 12

        for m in range(timeline.construction_months + 1, takeout_month):
            prior = balance
            balance = max(0.0, balance + balance * _carry_rate(m) - noi[m - 1])
            if m <= total:
                # The sweep is debt service in statement terms: interest on
                # the prior balance, the remainder principal (negative =
                # further accrual). Matches the engine's zero levered CF.
                stmt_interest[m] = prior * _carry_rate(m)
                stmt_service[m] = noi[m - 1]
                stmt_principal[m] = noi[m - 1] - prior * _carry_rate(m)
                stmt_balance[m] = balance

        value_for_ltv = stabilized_noi / exit_cap if exit_cap > 0 else 0.0

        sources_and_uses["uses"] = [
            ("Land", budget.land),
            ("Hard costs", budget.hard),
            ("Soft costs", budget.soft),
            ("Contingency", budget.contingency),
            ("Developer fee", budget.developer_fee),
            ("Capitalized interest", financing.interest_capitalized),
            ("Loan fees", financing.fee_capitalized),
        ]
        sources_and_uses["sources"] = [
            ("Construction loan (incl. capitalized carry)", financing.ending_balance),
            ("Equity", initial_equity),
        ]

        # The permanent takeout IS the stabilization refinance: it prices at
        # the construction rate plus an explicit spread, with explicit costs
        # (% of the new loan) deducted at takeout. Defaults (0 spread, 0
        # costs) preserve the original at-par behavior exactly.
        refi_spread = _num(inputs, "refiRateSpreadPct")
        perm_rate = interest_rate + refi_spread
        if rate_vec is not None and takeout_month <= total:
            # J5: the floating takeout prices at the in-force rate at the
            # takeout month plus the refi spread, and keeps floating.
            perm_rate = rate_vec[takeout_month - 1] + refi_spread
        refi_costs_pct = _num(inputs, "refiCostsPct")

        if takeout_month <= total:
            # Constraint-sized permanent takeout; the delta vs the
            # construction balance is a cash-out to equity (+) or a paydown
            # capital call (-). An all-equity build (LTC = 0) never takes on
            # permanent debt.
            sizing = debt.size_permanent_loan(
                sizing_noi, value_for_ltv, perm_ltv, dscr_constraint,
                debt_yield_constraint, perm_rate, amort_years,
            ) if perm_ltv > 0 else debt.PermSizing(0.0, "none", {})
            if sizing.amount > 0:
                perm_loan = sizing.amount
                governing_constraint = sizing.governing_constraint
            else:
                perm_loan = balance
                governing_constraint = "none"
            interest_rate_for_perm = perm_rate
            refi_costs = perm_loan * refi_costs_pct
            refi_delta = perm_loan - balance
            levered[takeout_month] += refi_delta - refi_costs
            stmt_debt_draws[takeout_month] += refi_delta
            stmt_loan_fees[takeout_month] += refi_costs
            if refi_delta < 0:
                warnings.append(
                    f"Permanent loan sizes below the construction balance — a "
                    f"${-refi_delta:,.0f} equity paydown is required at takeout "
                    f"(governed by {_GOVERNING_LABELS[governing_constraint]})."
                )
            perm_months = total - takeout_month + 1
            if rate_vec is not None:
                perm_rate_vec = [
                    (rate_vec[m - 1] if m - 1 < len(rate_vec) else rate_vec[-1])
                    + refi_spread
                    for m in range(takeout_month, total + 1)
                ]
                schedule = debt.amortization_schedule_floating(
                    perm_loan, perm_rate_vec, amort_years, io_months, perm_months
                )
            else:
                schedule = debt.amortization_schedule(
                    perm_loan, perm_rate, amort_years, io_months, perm_months
                )
            for m in range(takeout_month, total + 1):
                entry = schedule[m - takeout_month]
                levered[m] += noi[m - 1] - entry.payment
                debt_service[m] = entry
                stmt_interest[m] = entry.interest
                stmt_principal[m] = entry.principal
                stmt_service[m] = entry.payment
                stmt_balance[m] = entry.balance
            exit_debt_balance = schedule[-1].balance if schedule else 0.0
        else:
            # Sold before stabilizing: sweep through exit, pay off then.
            sizing = debt.size_permanent_loan(
                sizing_noi, value_for_ltv, perm_ltv, dscr_constraint,
                debt_yield_constraint, interest_rate, amort_years,
            )
            for m in range(takeout_month, total + 1):
                prior = balance
                balance = max(0.0, balance + balance * _carry_rate(m) - noi[m - 1])
                stmt_interest[m] = prior * _carry_rate(m)
                stmt_service[m] = noi[m - 1]
                stmt_principal[m] = noi[m - 1] - prior * _carry_rate(m)
                stmt_balance[m] = balance
            perm_loan = balance
            governing_constraint = "none"
            exit_debt_balance = balance
            warnings.append(
                "No permanent takeout occurs before exit — construction debt "
                "is repaid from sale proceeds."
            )

    # ------------------------------------------------------------------
    # [FIN] Loan maturity inside the hold (roadmap #11): the balloon is
    # refinanced with a new loan sized by the same constraints on forward
    # NOI / value at maturity, priced at the loan rate + refiRateSpreadPct,
    # with refiCostsPct; the net (cash-out or paydown) goes to equity.
    # loanTermYears blank = no maturity (the pre-#11 behavior).
    # ------------------------------------------------------------------
    maturity_refi = None
    term_years = _num(inputs, "loanTermYears")
    loan_start = takeout_month if deal_type == "development" else 1
    if perm_loan > 0 and term_years > 0 and loan_start <= total:
        maturity = loan_start + int(round(term_years * 12)) - 1
        if maturity < total and debt_service[maturity] is not None:
            balloon = debt_service[maturity].balance
            refi_spread_m = _num(inputs, "refiRateSpreadPct")
            refi_rate = interest_rate_for_perm + (refi_spread_m if deal_type == "acquisition" else 0.0)
            forward = ops["noi"][maturity : maturity + 12]
            fwd_noi = sum(forward) * (12 / len(forward)) if forward else 0.0
            refi_value = fwd_noi / exit_cap if exit_cap > 0 else 0.0
            refi_sizing = debt.size_permanent_loan(
                fwd_noi, refi_value, perm_ltv, dscr_constraint,
                debt_yield_constraint, refi_rate, amort_years,
            )
            new_loan = refi_sizing.amount if refi_sizing.amount > 0 else balloon
            refi_cost = new_loan * _num(inputs, "refiCostsPct")
            delta = new_loan - balloon
            levered[maturity] += delta - refi_cost
            stmt_debt_draws[maturity] += delta
            stmt_loan_fees[maturity] += refi_cost
            remaining = total - maturity
            if rate_vec is not None:
                spread_now = refi_rate - interest_rate_for_perm
                refi_rates = [
                    (rate_vec[m - 1] if m - 1 < len(rate_vec) else rate_vec[-1]) + spread_now
                    for m in range(maturity + 1, total + 1)
                ]
                new_schedule = debt.amortization_schedule_floating(new_loan, refi_rates, amort_years, 0, remaining)
            else:
                new_schedule = debt.amortization_schedule(new_loan, refi_rate, amort_years, 0, remaining)
            for m in range(maturity + 1, total + 1):
                old = debt_service[m]
                entry = new_schedule[m - maturity - 1]
                levered[m] += (old.payment if old is not None else 0.0) - entry.payment
                debt_service[m] = entry
                stmt_interest[m] = entry.interest
                stmt_principal[m] = entry.principal
                stmt_service[m] = entry.payment
                stmt_balance[m] = entry.balance
            exit_debt_balance = new_schedule[-1].balance if new_schedule else 0.0
            maturity_refi = {
                "month": maturity,
                "balloon": balloon,
                "newLoan": new_loan,
                "rate": refi_rate,
                "costs": refi_cost,
                "netToEquity": delta - refi_cost,
                "governingConstraint": _GOVERNING_LABELS.get(
                    refi_sizing.governing_constraint, refi_sizing.governing_constraint
                ),
            }
            warnings.append(
                f"The loan matures in month {maturity} (year {maturity / 12:.1f}), before the exit: "
                f"the ${balloon:,.0f} balloon is refinanced with a ${new_loan:,.0f} loan at "
                f"{refi_rate:.2%} ("
                + (f"${delta - refi_cost:,.0f} cash out to equity" if delta - refi_cost >= 0
                   else f"a ${refi_cost - delta:,.0f} equity paydown")
                + " after costs)."
            )

    # J5: rate-cap premium — a financing cost paid by equity at close.
    # [FIN]: it rides the loanFees statement row (levered only, never
    # unlevered — buying rate protection is a capital-structure choice,
    # like origination fees) and joins the cost basis and uses.
    cap_premium = _num(inputs, "rateCapPremium") if rate_vec is not None else 0.0
    if cap_premium > 0:
        levered[0] -= cap_premium
        initial_equity += cap_premium
        total_cost_basis += cap_premium
        stmt_loan_fees[0] += cap_premium
        stmt_equity_funded[0] += cap_premium
        sources_and_uses["uses"].append(("Rate cap premium", cap_premium))
        sources_and_uses["sources"] = [
            (name, initial_equity if name == "Equity" else amount)
            for name, amount in sources_and_uses["sources"]
        ]

    # J6 (below_noi, the default convention): reserves are a capital cost
    # after NOI, like TI/LC — both cash-flow vectors, never DSCR / sizing /
    # the exit cap basis. The lender-UW view (NOI − reserves) is surfaced as
    # the underwrittenDscr detail output instead.
    reserves_stmt = None
    if reserves_full is not None and reserves_convention == "below_noi":
        reserves_stmt = [0.0] * (total + 1)
        for m in range(1, total + 1):
            amount = reserves_full[m - 1]
            if amount:
                unlevered[m] -= amount
                levered[m] -= amount
                reserves_stmt[m] = amount

    # J6: tax & insurance escrows — PURE cash timing, levered only (a lender
    # requirement; an all-cash buyer posts none): funded at close, released
    # at exit. Never in the cost basis (it comes back) and never in P&L.
    # Sized on the first operating month's modeled taxes + insurance so every
    # tax source (flat, line items, reassessment) is honored.
    escrow_amount = 0.0
    escrow_months = _num(inputs, "monthsOfTaxesAndInsurance")
    if escrow_months > 0:
        om1 = timeline.construction_months  # 0-based index of operating month 1
        monthly_ti = sum(
            (vec[om1] if om1 < len(vec) else 0.0)
            for key, vec in ops["fixedOpexByCategory"].items()
            if key in ("realEstateTaxes", "insurance")
        )
        escrow_amount = monthly_ti * escrow_months
        if escrow_amount > 0:
            levered[0] -= escrow_amount
            levered[total] += escrow_amount
            initial_equity += escrow_amount
            stmt_equity_funded[0] += escrow_amount
            sources_and_uses["uses"].append(("Tax & insurance escrows", escrow_amount))
            sources_and_uses["sources"] = [
                (name, initial_equity if name == "Equity" else amount)
                for name, amount in sources_and_uses["sources"]
            ]
        else:
            warnings.append(
                "monthsOfTaxesAndInsurance is set but the deal models no taxes "
                "or insurance expense — no escrow was funded."
            )

    for m in range(1, total + 1):
        if leasing_capital[m - 1]:
            unlevered[m] -= leasing_capital[m - 1]
            levered[m] -= leasing_capital[m - 1]

    # ------------------------------------------------------------------
    # J1: renovation program cash flows. The budget always joins the cost
    # basis (yield-on-cost denominator). equity_at_close: the full budget
    # is a USE at close funded by equity (escrow view — spend timing is
    # reported, cash leaves at close). operating_cash: capex hits both
    # vectors as incurred, like TI/LC, with a funding warning if cumulative
    # operating cash ever goes negative (never silently re-sequenced).
    # ------------------------------------------------------------------
    reno = ops.get("renovation")
    reno_capex_stmt = [0.0] * (total + 1)
    if reno is not None:
        reno_budget = reno["budget"]
        total_cost_basis += reno_budget
        if reno["fundingSource"] == "equity_at_close":
            unlevered[0] -= reno_budget
            levered[0] -= reno_budget
            initial_equity += reno_budget
            stmt_costs[0] += reno_budget
            stmt_equity_funded[0] += reno_budget
            reno_capex_stmt[0] = reno_budget
            sources_and_uses["uses"].append(("Renovation budget (equity escrow)", reno_budget))
            sources_and_uses["sources"] = [
                (label, amount + reno_budget if label == "Equity" else amount)
                for label, amount in sources_and_uses["sources"]
            ]
        else:  # operating_cash
            running = 0.0
            shortfall_month = None
            for m in range(1, total + 1):
                draw = reno["capex"][m - 1] if m - 1 < len(reno["capex"]) else 0.0
                if draw:
                    unlevered[m] -= draw
                    levered[m] -= draw
                    reno_capex_stmt[m] = draw
                # Exit settlement hasn't been applied yet — levered[1..total]
                # here is pure operating cash after debt service and capital.
                running += levered[m]
                if running < -1e-6 and shortfall_month is None:
                    shortfall_month = m
            if shortfall_month is not None:
                warnings.append(
                    f"Renovation draws exceed cumulative operating cash from month "
                    f"{shortfall_month} — operating_cash funding needs a reserve or "
                    "a slower pace (the program was NOT re-sequenced)."
                )

    unlevered[total] += gross_sale_net_of_costs
    net_sale_proceeds = gross_sale_net_of_costs - exit_debt_balance
    levered[total] += net_sale_proceeds
    if net_sale_proceeds < 0:
        warnings.append(
            "Sale proceeds do not cover the debt payoff — levered exit flow is negative."
        )

    # ------------------------------------------------------------------
    # J4: junior tranche (mezzanine / preferred equity). Funds at the same
    # event as the senior (close for acquisitions, perm takeout for
    # developments); senior sizing is UNAFFECTED. Current-pay interest is a
    # below-NOI financing cost ranking AFTER senior debt service and
    # property capital costs and BEFORE the partnership AM fee and equity;
    # a current-pay shortfall converts to PIK ([FIN] — hard default
    # rejected). Accrued mode compounds monthly at rate/12; the balance is
    # repaid at exit AFTER senior payoff, BEFORE common equity.
    # ------------------------------------------------------------------
    junior_kind = inputs.get("juniorTrancheKind") or "none"
    junior_block = None
    if junior_kind in ("mezz", "pref_equity"):
        junior_rate = _num(inputs, "juniorRatePct")
        junior_fixed = _num(inputs, "juniorAmount")
        junior_fill = _num(inputs, "juniorFillToLtcPct")
        if junior_fixed > 0:
            junior_amount = junior_fixed
        elif junior_fill > 0:
            junior_amount = max(0.0, junior_fill * total_cost_basis - perm_loan)
        else:
            junior_amount = 0.0
        if junior_amount <= 0:
            warnings.append(
                "Junior tranche configured with no amount (set juniorAmount or "
                "juniorFillToLtcPct above the senior) — ignored."
            )
    if junior_kind in ("mezz", "pref_equity") and junior_amount > 0:
        junior_fee = junior_amount * _num(inputs, "juniorOriginationFeePct")
        pay_mode = inputs.get("juniorPayMode") or "current"
        if pay_mode not in ("current", "accrued"):
            warnings.append(f"Unknown juniorPayMode '{pay_mode}' — using current.")
            pay_mode = "current"
        fund_month = 0 if deal_type == "acquisition" else min(takeout_month, total)
        label = "Mezzanine tranche" if junior_kind == "mezz" else "Preferred equity tranche"

        # Funding: reduces common equity by the tranche net of its fee.
        levered[fund_month] += junior_amount - junior_fee
        initial_equity = initial_equity - junior_amount + junior_fee
        stmt_debt_draws[fund_month] += junior_amount
        stmt_loan_fees[fund_month] += junior_fee
        sources_and_uses["uses"].append((f"{label} fee", junior_fee))
        sources_and_uses["sources"] = [
            (name, amount - junior_amount + junior_fee if name == "Equity" else amount)
            for name, amount in sources_and_uses["sources"]
        ]
        sources_and_uses["sources"].append((label, junior_amount))

        junior_interest_paid = [0.0] * (total + 1)
        junior_balance_vec = [0.0] * (total + 1)
        pik_months: list[int] = []
        balance = junior_amount
        junior_balance_vec[fund_month] = balance
        r = junior_rate / 12
        for m in range(fund_month + 1, total + 1):
            interest = balance * r
            if pay_mode == "current":
                available = max(0.0, levered[m])
                paid = min(available, interest)
                shortfall = interest - paid
                if shortfall > 1e-9:
                    balance += shortfall  # shortfall converts to PIK
                    pik_months.append(m)
                levered[m] -= paid
                junior_interest_paid[m] = paid
            else:  # accrued: full PIK
                balance += interest
            junior_balance_vec[m] = balance

        # Exit payoff: after senior (already netted in sale proceeds),
        # before common equity.
        levered[total] -= balance
        junior_payoff_vec = [0.0] * (total + 1)
        junior_payoff_vec[total] = balance
        if levered[total] < 0:
            warnings.append(
                f"{label} payoff (${balance:,.0f}) exceeds the remaining exit "
                "cash — common equity's exit flow is negative."
            )

        junior_block = {
            "kind": junior_kind,
            "amount": junior_amount,
            "fee": junior_fee,
            "payMode": pay_mode,
            "ratePct": junior_rate,
            "fundMonth": fund_month,
            "payoff": balance,
            "pikMonths": pik_months,
            "interestPaid": junior_interest_paid,
            "balance": junior_balance_vec,
            "payoffVector": junior_payoff_vec,
        }

    # ------------------------------------------------------------------
    # J3: asset management fee — a PARTNERSHIP expense below property NOI.
    # It reduces LEVERED cash flow (and therefore every levered metric and
    # the waterfall), but never NOI, DSCR, unlevered flows, or lender
    # metrics ([FIN], DECISIONS.md — treating it as opex was rejected).
    # ------------------------------------------------------------------
    am_fee_pct = _num(inputs, "assetMgmtFeePct")
    am_fee_vec = [0.0] * (total + 1)
    if am_fee_pct > 0:
        am_basis = inputs.get("assetMgmtFeeBasis") or "egi"
        if am_basis not in ("egi", "committed_equity"):
            warnings.append(f"Unknown assetMgmtFeeBasis '{am_basis}' — using egi.")
            am_basis = "egi"
        for m in range(1, total + 1):
            if am_basis == "egi":
                fee = am_fee_pct * ops["egi"][m - 1]
            else:  # committed_equity: annual pct on the equity at close
                fee = am_fee_pct / 12 * initial_equity
            am_fee_vec[m] = fee
            levered[m] -= fee

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    outputs: dict[str, float] = {}

    def put(key: str, value):
        if value is not None and isinstance(value, (int, float)):
            outputs[key] = float(value)

    if junior_block is not None:
        # J4: combined leverage detail (senior + tranche). The senior-only
        # lender metrics (ltv/ltc) stay untouched; pref equity differs from
        # mezz in labeling only here.
        if value_for_ltv > 0:
            put("combinedLtv", (perm_loan + junior_block["amount"]) / value_for_ltv)
        if total_cost_basis > 0:
            put("combinedLtc", (perm_loan + junior_block["amount"]) / total_cost_basis)

    # IRR convention (G1): periodic_monthly (default, Run-1 behavior) computes
    # a monthly IRR annualized as (1+i)^12-1; xirr dates every flow at the
    # engine's month-end calendar and solves actual/365 (Excel convention).
    irr_convention = inputs.get("irrConvention") or "periodic_monthly"
    if irr_convention == "xirr":
        flow_dates = month_end_dates(total + 1)

        def irr_of(flows: list[float]):
            return returns.xirr(flow_dates, flows)
    else:
        irr_convention = "periodic_monthly"
        irr_of = returns.periodic_irr

    put("unleveredIrr", irr_of(unlevered))
    levered_irr = irr_of(levered)
    put("leveredIrr", levered_irr)
    for label, flows in (("Unlevered", unlevered), ("Levered", levered)):
        if returns.sign_changes(flows) < 2:
            continue  # one sign change: exactly one IRR (Descartes)
        roots = returns.periodic_irr_roots(flows)
        if len(roots) > 1:
            shown = ", ".join(f"{r:.2%}" for r in roots[:4])
            warnings.append(
                f"{label} cash flows change sign more than once and have {len(roots)} IRRs "
                f"({shown}) — the IRR shown is only one of them. Judge this deal on NPV "
                "and equity multiple instead."
            )

    em = returns.equity_multiple(levered)
    put("equityMultiple", em)
    put("unleveredEquityMultiple", returns.equity_multiple(unlevered))
    put("moic", em)
    if em is not None and hold_years > 0:
        put("annualizedReturn", em ** (1 / hold_years) - 1)
    put("paybackPeriodYears", returns.payback_period_years(levered))

    total_equity_in = -sum(cf for cf in levered if cf < 0)
    if total_equity_in > 0:
        # Operating-only cash flows (exclude the exit settlement).
        operating = [levered[m] for m in range(1, total + 1)]
        if total >= 1:
            operating[-1] -= net_sale_proceeds
        year1_window = operating[: min(12, len(operating))]
        if year1_window:
            annualized_y1 = sum(year1_window) * (12 / len(year1_window))
            put("cashOnCashYear1", annualized_y1 / total_equity_in)
        full_years = len(operating) // 12
        if full_years > 0:
            yearly = [sum(operating[y * 12 : (y + 1) * 12]) for y in range(full_years)]
            put("avgCashOnCash", (sum(yearly) / full_years) / total_equity_in)
        stab_start = timeline.stabilization_month - 1  # 0-based into operating
        stab_window = operating[stab_start : stab_start + 12]
        if stab_window:
            annualized_stab = sum(stab_window) * (12 / len(stab_window))
            put("stabilizedCashOnCash", annualized_stab / total_equity_in)

    discount_rate = _num(inputs, "discountRatePct", 0.10)
    put("npv", returns.npv(discount_rate, levered))
    put("profitabilityIndex", returns.profitability_index(discount_rate, levered))

    put("terminalValue", terminal_value)
    put("netSaleProceeds", net_sale_proceeds)
    put("totalProfit", sum(levered))

    # [FIN] Value-add: the basis carries the full renovation budget, so the
    # numerator is the untrended NOI once the program is complete (it used to
    # be in-place NOI, so a renovation LOWERED yield on cost). Same reserves
    # deduction as stabilized_noi. Debt sizing stays in-place (J1).
    yoc_noi = stabilized_noi
    post_reno_noi, post_reno_warning = operations.post_renovation_stabilized_noi(inputs)
    if post_reno_warning:
        warnings.append(post_reno_warning)
    if post_reno_noi is not None:
        yoc_noi = post_reno_noi - (in_place_stabilized_noi - stabilized_noi)
    yield_on_cost = yoc_noi / total_cost_basis if total_cost_basis > 0 else None
    put("yieldOnCost", yield_on_cost)
    # Per-component yield on cost (H2): basis allocated pro-rata to component
    # value at the component caps (blended cap when unset). See DECISIONS.md.
    if components and total_cost_basis > 0 and total >= 1:
        window = min(12, total)
        stab_res = sum(components["residential"]["noi"][:window]) * (12 / window)
        stab_com = sum(components["commercial"]["noi"][:window]) * (12 / window)
        cap_r = res_exit_cap if res_exit_cap > 0 else exit_cap
        cap_c = com_exit_cap if com_exit_cap > 0 else exit_cap
        value_r = stab_res / cap_r if cap_r > 0 else 0.0
        value_c = stab_com / cap_c if cap_c > 0 else 0.0
        if value_r > 0 and value_c > 0:
            basis_r = total_cost_basis * value_r / (value_r + value_c)
            basis_c = total_cost_basis - basis_r
            put("residentialYieldOnCost", stab_res / basis_r)
            put("commercialYieldOnCost", stab_com / basis_c)
    if deal_type == "acquisition":
        in_place_noi = _num(inputs, "inPlaceNoi")
        year1_noi = sum(noi[: min(12, total)]) * (12 / min(12, total)) if total else 0.0
        going_in_noi = in_place_noi if in_place_noi > 0 else year1_noi
        purchase_price = _num(inputs, "purchasePrice")
        if purchase_price > 0:
            put("goingInCapRate", going_in_noi / purchase_price)
        if perm_loan > 0:
            # debtYield uses stabilized NOI (the sizing view); lenders also
            # quote going-in debt yield on in-place / year-1 NOI.
            put("goingInDebtYield", going_in_noi / perm_loan)
    else:
        put("goingInCapRate", yield_on_cost)
    if yield_on_cost is not None:
        put("developmentSpreadBps", yield_on_cost - exit_cap)

    # Debt metrics — only meaningful with debt outstanding.
    service_months = [
        (noi[m - 1], debt_service[m])
        for m in range(1, total + 1)
        if debt_service[m] is not None and debt_service[m].payment > 0
    ]
    if perm_loan > 0 and service_months:
        dscrs = [n / s.payment for n, s in service_months]
        # [FIN] Lenders test DSCR on loan years (12 months of NOI over 12
        # months of debt service), not single months: one downtime month
        # used to set the headline. The monthly minimum stays available.
        service_month_ids = [
            m for m in range(1, total + 1)
            if debt_service[m] is not None and debt_service[m].payment > 0
        ]
        windows = debt.annual_dscr_windows(service_month_ids[0], service_month_ids[-1])

        def _annual_min(noi_of) -> float:
            return min(
                sum(noi_of(m) for m in range(a, b + 1))
                / sum(debt_service[m].payment for m in range(a, b + 1) if debt_service[m] is not None)
                for a, b in windows
            )

        put("minDscr", _annual_min(lambda m: noi[m - 1]))
        put("minMonthlyDscr", min(dscrs))
        put("avgDscr", sum(dscrs) / len(dscrs))
        if reserves_stmt is not None:
            # J6: lender-UW DSCR on NOI − reserves — a DETAIL row; the
            # deal's own DSCR stays on NOI (below_noi convention).
            put("underwrittenDscr", _annual_min(lambda m: noi[m - 1] - reserves_stmt[m]))
        annual_service = 12 * debt.monthly_payment(perm_loan, interest_rate_for_perm, amort_years)
        if io_months >= total - takeout_month + 1:
            annual_service = perm_loan * interest_rate_for_perm  # never leaves IO
        put("loanConstant", annual_service / perm_loan)
        put("debtYield", stabilized_noi / perm_loan)
        year1_interest = sum(
            s.interest for _, s in service_months[:12]
        ) * (12 / min(12, len(service_months)))
        if year1_interest > 0:
            put("interestCoverageRatio", stabilized_noi / year1_interest)
        if value_for_ltv > 0:
            put("ltv", perm_loan / value_for_ltv)
        if total_cost_basis > 0:
            put("ltc", perm_loan / total_cost_basis)

        gpr_annual, other_annual, _, _ = operations.annual_gpr_and_other_income(inputs)
        # Lease-modeled deals embed vacancy as downtime — the general
        # vacancyPct input never applies to them (H1, DECISIONS.md).
        occupancy = (
            1.0 if gpr_source == "commercialLeases"
            else max(0.0, 1 - _num(inputs, "vacancyPct", 0.05))
        )
        credit_loss = _num(inputs, "creditLossPct")
        stabilized_egi = gpr_annual * occupancy * (1 - credit_loss) + other_annual
        stabilized_opex = stabilized_egi - stabilized_noi
        gross_revenue = gpr_annual + other_annual
        if gross_revenue > 0:
            # Break-even ratio: (opex + debt service) / gross potential revenue.
            put("breakEvenRatio", (stabilized_opex + annual_service) / gross_revenue)
        if gpr_annual > 0:
            # Occupancy at which collections cover opex + debt service.
            put(
                "breakEvenOccupancy",
                (stabilized_opex + annual_service - other_annual)
                / (gpr_annual * (1 - credit_loss)),
            )

    # ------------------------------------------------------------------
    # LP/GP waterfall on the levered equity flows.
    # ------------------------------------------------------------------
    waterfall_style = inputs.get("waterfallStyle") or "european"
    if waterfall_style not in ("european", "american"):
        warnings.append(f"Unknown waterfallStyle '{waterfall_style}' — using european.")
        waterfall_style = "european"
    catch_up_pct = inputs.get("catchUpPct")
    waterfall = equity.run_waterfall(
        levered,
        lp_share=_num(inputs, "lpSplitPct", 0.9),
        gp_share=_num(inputs, "gpSplitPct", 0.1),
        preferred_return=_num(inputs, "preferredReturnPct", 0.08),
        tiers=inputs.get("waterfallTiers") or [],
        style=waterfall_style,
        catch_up_pct=float(catch_up_pct) if isinstance(catch_up_pct, (int, float)) else None,
    )
    warnings.extend(waterfall["warnings"])
    # LP/GP IRRs honor the selected convention (the waterfall's own fields are
    # always periodic — hurdle math is periodic in both styles).
    put("lpIrr", irr_of(waterfall["lpFlows"]))
    put("gpIrr", irr_of(waterfall["gpFlows"]))
    put("lpEquityMultiple", waterfall["lpMultiple"])

    # J3: GP total compensation — fees + promote + pro-rata. All three fee
    # streams are paid TO the GP; the waterfall stays on contributed-capital
    # promote math. Conditional block: only when a fee stream exists, so
    # fee-free deals keep their Run-4 payload exactly.
    gp_acquisition_fee = (
        _num(inputs, "purchasePrice") * _num(inputs, "acquisitionFeePct")
        if deal_type == "acquisition" else 0.0
    )
    gp_developer_fee_total = gp_developer_fee if deal_type == "development" else 0.0
    am_fees_total = sum(am_fee_vec)
    gp_economics = None
    # Gate: the AM fee (new input) or an acquisition fee activates the block.
    # The developer fee alone does NOT — its pre-J3 engine default (0.04)
    # would put this block on every Run-4 development deal, breaking the
    # baseline; it reports inside the block once another stream fires.
    if gp_acquisition_fee > 0 or am_fees_total > 0:
        gp_distributions_net = sum(waterfall["gpFlows"])
        fees_total = gp_acquisition_fee + gp_developer_fee_total + am_fees_total
        gp_economics = {
            "acquisitionFee": gp_acquisition_fee,
            "developerFee": gp_developer_fee_total,
            "assetMgmtFees": am_fees_total,
            "feesTotal": fees_total,
            "promote": waterfall["promotePaid"],
            "gpDistributionsNet": gp_distributions_net,
            "proRataNet": gp_distributions_net - waterfall["promotePaid"],
            "totalCompensation": fees_total + gp_distributions_net,
        }
        put("gpFeesTotal", fees_total)
        put("gpTotalCompensation", gp_economics["totalCompensation"])

    # ------------------------------------------------------------------
    # Debt sizing detail: governing constraint + rate/NOI stress grid.
    # ------------------------------------------------------------------
    debt_block = None
    if perm_loan > 0:
        outputs["governingConstraint"] = _GOVERNING_LABELS.get(
            governing_constraint, governing_constraint
        )
        stress = debt.stress_matrix(
            sizing_noi, value_for_ltv, perm_loan, perm_ltv, dscr_constraint,
            debt_yield_constraint, interest_rate_for_perm, amort_years,
        )
        worst = next(
            (c for c in stress if c["rateBumpBps"] == 200 and c["noiHaircutPct"] == 0.10),
            None,
        )
        if worst and worst["dscr"] is not None:
            put("stressedDscr", worst["dscr"])
        debt_block = {
            "loanAmount": perm_loan,
            "sizedLoanAmount": sizing.amount,
            "governingConstraint": _GOVERNING_LABELS.get(
                governing_constraint, governing_constraint
            ),
            "candidates": sizing.candidates,
            "sizingNoi": sizing_noi,
            "value": value_for_ltv,
            "stress": stress,
        }
        if rate_vec is not None:
            # J5: floating-rate detail — conditional, fixed deals unchanged.
            strike = _num(inputs, "rateCapStrikePct")
            cap_term = int(_num(inputs, "rateCapTermMonths"))
            spread = _num(inputs, "spreadBps") / 10_000
            rate_info: dict = {
                "mode": "floating",
                "index": "SOFR",
                "spreadBps": _num(inputs, "spreadBps"),
                "initialRatePct": interest_rate_for_perm,
                "monthlyRatePct": rate_vec,
            }
            floor_raw = inputs.get("floorPct")
            if isinstance(floor_raw, (int, float)) and not isinstance(floor_raw, bool):
                rate_info["floorPct"] = float(floor_raw)
            if strike > 0 and cap_term > 0:
                # DSCR if the loan reprices AT the cap strike — the relevant
                # stress for a capped floater (the +200bps row is a fiction
                # the borrower already paid to escape while the cap runs).
                strike_all_in = strike + spread
                constant = debt.annual_loan_constant(strike_all_in, amort_years)
                if io_months >= total - takeout_month + 1:
                    constant = strike_all_in  # never leaves IO
                dscr_at_strike = (
                    sizing_noi / (perm_loan * constant) if constant > 0 else None
                )
                rate_info["cap"] = {
                    "strikePct": strike,
                    "strikeAllInPct": strike_all_in,
                    "termMonths": cap_term,
                    "premium": _num(inputs, "rateCapPremium"),
                    "dscrAtStrike": dscr_at_strike,
                }
                if dscr_at_strike is not None:
                    put("dscrAtCapStrike", dscr_at_strike)
            debt_block["rate"] = rate_info

    # ------------------------------------------------------------------
    # Period-level statement (G2): the vectors above, packaged. Index 0 =
    # close. Identities hold by construction:
    #   egi = gpr - vacancyLoss - creditLoss + otherIncome
    #   noi = egi - opexTotal
    #   levered = noi - debtService + debtDraws - costs - loanFees
    #             - leasingCapital + saleProceedsNet
    # ------------------------------------------------------------------
    def _padded(key: str) -> list[float]:
        return [0.0] + ops[key][:total]

    sale_net_vec = [0.0] * (total + 1)
    sale_net_vec[total] = net_sale_proceeds
    sale_gross_vec = [0.0] * (total + 1)
    sale_gross_vec[total] = gross_sale_net_of_costs

    statement = {
        "months": list(range(total + 1)),
        "phases": ["close"] + [timeline.phase(m) for m in range(1, total + 1)],
        "constructionMonths": timeline.construction_months,
        "stabilizationMonth": timeline.stabilization_month,
        "exitMonth": total,
        "gpr": _padded("gpr"),
        "vacancyLoss": _padded("vacancyLoss"),
        "creditLoss": _padded("creditLoss"),
        "otherIncome": _padded("otherIncome"),
        "egi": _padded("egi"),
        "fixedOpexByCategory": {
            category: [0.0] + vec[:total]
            for category, vec in ops["fixedOpexByCategory"].items()
        },
        "managementFee": _padded("managementFee"),
        "opexTotal": _padded("opex"),
        "noi": [0.0] + noi,
        "occupancy": _padded("occupancy"),
        "costs": stmt_costs,
        "loanFees": stmt_loan_fees,
        "equityFunded": stmt_equity_funded,
        "debtDraws": stmt_debt_draws,
        "interest": stmt_interest,
        "principal": stmt_principal,
        "debtService": stmt_service,
        "loanBalance": stmt_balance,
        "saleProceedsNet": sale_net_vec,
        "saleProceedsGross": sale_gross_vec,
        "recoveries": [0.0] + (ops.get("recoveries") or [0.0] * total)[:total],
        "leasingCapital": [0.0] + leasing_capital,
        "unlevered": unlevered,
        "levered": levered,
        "lpDistributions": waterfall["lpFlows"],
        "gpDistributions": waterfall["gpFlows"],
    }
    if reno is not None:
        # J1: conditional keys (baseline-safe — absent without a program).
        statement["renovationCapex"] = reno_capex_stmt
        statement["renovation"] = {
            "unitsComplete": [0.0] + reno["unitsComplete"][:total],
            "unitsInProgress": [0.0] + reno["unitsInProgress"][:total],
            "unitsRemaining": [0.0] + reno["unitsRemaining"][:total],
            "spendSchedule": [0.0] + reno["capex"][:total],
            "budget": reno["budget"],
            "fundingSource": reno["fundingSource"],
        }
        put("postRenoAvgRent", reno["postRenoAvgRent"])
    if reserves_stmt is not None:
        # J6: conditional below-NOI reserves row (both vectors).
        statement["replacementReserves"] = reserves_stmt
    if escrow_amount > 0:
        # J6: conditional escrow timing row: −E at close, +E at exit.
        escrow_vec = [0.0] * (total + 1)
        escrow_vec[0] = -escrow_amount
        escrow_vec[total] += escrow_amount
        statement["escrowFlows"] = escrow_vec
    if am_fees_total > 0:
        # J3: conditional partnership-expense row (below NOI, levered only).
        statement["assetMgmtFee"] = am_fee_vec
    if junior_block is not None:
        # J4: conditional tranche rows — paid interest, running balance, and
        # the exit payoff (levered = ... − juniorInterest − juniorPayoff for
        # tranche deals).
        statement["juniorInterest"] = junior_block["interestPaid"]
        statement["juniorBalance"] = junior_block["balance"]
        statement["juniorPayoff"] = junior_block["payoffVector"]
    # J9: per-calendar-year operating break-evens on the statement's own
    # vectors (analytic; no recomputes). Year-1 values join the sidebar.
    statement["breakEvens"] = _operating_break_evens(statement, total)
    if statement["breakEvens"]["years"]:
        year1_be = statement["breakEvens"]["years"][0]
        put("breakEvenOccupancyYear1", year1_be["occupancy"])
        put("breakEvenRentYear1", year1_be["rentFactor"])

    ltl = ops.get("lossToLease")
    if ltl is not None:
        # J2: conditional display block — GPR at market, less loss-to-lease,
        # = scheduled rent (the statement identity stays on scheduled GPR).
        statement["lossToLease"] = {
            "marketGpr": [0.0] + ltl["marketGpr"][:total],
            "lossToLease": [0.0] + ltl["lossToLease"][:total],
        }
        year1 = sum(ltl["lossToLease"][: min(12, total)])
        put("year1LossToLease", year1)
    # Insurance stress (H3): categorical stress exists only in expense-detail
    # mode; each scenario is a full engine re-compute with the insurance
    # line(s) bumped, so recoveries/mgmt-fee knock-ons are exact.
    if (
        debt_block is not None
        and operations.has_opex_detail(inputs)
        and not inputs.get("_skipCategoricalStress")
    ):
        insurance_present = any(
            isinstance(r, dict) and r.get("category") == "insurance" and _num(r, "amount") > 0
            for r in inputs.get("opexLineItems") or []
        )
        if insurance_present:
            def _avg_annual_operating_cf(stmt: dict) -> float:
                months = stmt["exitMonth"]
                operating = sum(stmt["levered"][1 : months + 1]) - stmt["saleProceedsNet"][months]
                return operating / (months / 12) if months else 0.0

            base_cf = _avg_annual_operating_cf(statement)
            insurance_rows = []
            for bump in (0.25, 0.50):
                bumped_lines = [
                    {**r, "amount": _num(r, "amount") * (1 + bump)}
                    if isinstance(r, dict) and r.get("category") == "insurance"
                    else r
                    for r in inputs.get("opexLineItems") or []
                ]
                sub = compute(
                    {**inputs, "opexLineItems": bumped_lines, "_skipCategoricalStress": True}
                )
                insurance_rows.append(
                    {
                        "bumpPct": bump,
                        "minDscr": sub["outputs"].get("minDscr"),
                        "leveredCfDeltaAnnual": _avg_annual_operating_cf(sub["statement"]) - base_cf,
                    }
                )
            debt_block["insuranceStress"] = insurance_rows

    if ops.get("leaseDetail"):
        lease_detail = dict(ops["leaseDetail"])
        # I8: per-lease drill-down slices — trim the extended forward window
        # off the vectors so they align with the statement's hold horizon.
        slice_keys = ("scheduledRent", "freeRent", "downtimeLoss", "recoveries", "leasingCapital")
        lease_detail["perLease"] = [
            {
                **entry,
                **{key: entry[key][:total] for key in slice_keys},
                "rolloverEvents": [
                    e for e in entry.get("rolloverEvents", []) if e["expiryMonth"] <= total
                ],
            }
            for entry in lease_detail.get("perLease", [])
        ]
        statement["leases"] = lease_detail
    if components:
        statement["components"] = {
            name: {key: [0.0] + vec[:total] for key, vec in comp.items()}
            for name, comp in components.items()
        }

    return {
        "outputs": outputs,
        "warnings": warnings,
        "gprSource": gpr_source,
        "debt": debt_block,
        "sourcesAndUses": sources_and_uses,
        "constructionLoan": construction_loan,
        "maturityRefinance": maturity_refi,
        "irrConvention": irr_convention,
        "waterfallStyle": waterfall_style,
        "gpEconomics": gp_economics,
        "juniorTranche": (
            {k: v for k, v in junior_block.items()
             if k not in ("interestPaid", "balance", "payoffVector")}
            if junior_block is not None else None
        ),
        "statement": statement,
    }
