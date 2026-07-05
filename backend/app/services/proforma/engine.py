"""Native pro-forma engine: schema-shaped inputs dict in, all schema output
ids out. Orchestration only — every formula lives in the sibling modules
(timeline / development / operations / debt / equity / returns), and nothing
outside this package reimplements any of them.
"""

from app.services.proforma import debt, development, equity, operations, returns
from app.services.proforma.timeline import Timeline, build_timeline, month_end_dates


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


def compute(inputs: dict) -> dict:
    """Returns {"outputs": {<schema output id>: float}, "warnings": [str]}.
    Raises InsufficientInputsError naming every missing required field."""
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
    interest_rate = _num(inputs, "interestRate", 0.065)
    amort_years = _num(inputs, "amortYears", 30)
    io_months = int(_num(inputs, "ioMonths"))
    origination_fee_pct = _num(inputs, "originationFeePct")
    dscr_constraint = _num(inputs, "dscrConstraint", 1.25)
    debt_yield_constraint = _num(inputs, "debtYieldConstraint", 0.08)

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

        schedule = debt.amortization_schedule(
            loan_amount, interest_rate, amort_years, io_months, total
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
        # LTC applies to the hard basis (ex financing); interest and fees are
        # loan-funded on top (interest-reserve convention). See DECISIONS.md.
        equity_target = budget.total_ex_financing * (1 - ltc_or_ltv)
        financing = debt.construction_financing(
            cost_schedule, equity_target, interest_rate, origination_fee_pct
        )
        total_cost_basis = (
            budget.total_ex_financing
            + financing.interest_capitalized
            + financing.fee_capitalized
        )
        initial_equity = equity_target

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
        for m in range(timeline.construction_months + 1, takeout_month):
            prior = balance
            balance = max(0.0, balance + balance * r - noi[m - 1])
            if m <= total:
                # The sweep is debt service in statement terms: interest on
                # the prior balance, the remainder principal (negative =
                # further accrual). Matches the engine's zero levered CF.
                stmt_interest[m] = prior * r
                stmt_service[m] = noi[m - 1]
                stmt_principal[m] = noi[m - 1] - prior * r
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
        perm_rate = interest_rate + _num(inputs, "refiRateSpreadPct")
        refi_costs_pct = _num(inputs, "refiCostsPct")

        if takeout_month <= total:
            # Constraint-sized permanent takeout; the delta vs the
            # construction balance is a cash-out to equity (+) or a paydown
            # capital call (-). An all-equity build (LTC = 0) never takes on
            # permanent debt.
            sizing = debt.size_permanent_loan(
                sizing_noi, value_for_ltv, ltc_or_ltv, dscr_constraint,
                debt_yield_constraint, perm_rate, amort_years,
            ) if ltc_or_ltv > 0 else debt.PermSizing(0.0, "none", {})
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
                sizing_noi, value_for_ltv, ltc_or_ltv, dscr_constraint,
                debt_yield_constraint, interest_rate, amort_years,
            )
            for m in range(takeout_month, total + 1):
                prior = balance
                balance = max(0.0, balance + balance * r - noi[m - 1])
                stmt_interest[m] = prior * r
                stmt_service[m] = noi[m - 1]
                stmt_principal[m] = noi[m - 1] - prior * r
                stmt_balance[m] = balance
            perm_loan = balance
            governing_constraint = "none"
            exit_debt_balance = balance
            warnings.append(
                "No permanent takeout occurs before exit — construction debt "
                "is repaid from sale proceeds."
            )

    for m in range(1, total + 1):
        if leasing_capital[m - 1]:
            unlevered[m] -= leasing_capital[m - 1]
            levered[m] -= leasing_capital[m - 1]

    unlevered[total] += gross_sale_net_of_costs
    net_sale_proceeds = gross_sale_net_of_costs - exit_debt_balance
    levered[total] += net_sale_proceeds
    if net_sale_proceeds < 0:
        warnings.append(
            "Sale proceeds do not cover the debt payoff — levered exit flow is negative."
        )

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    outputs: dict[str, float] = {}

    def put(key: str, value):
        if value is not None and isinstance(value, (int, float)):
            outputs[key] = float(value)

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

    yield_on_cost = stabilized_noi / total_cost_basis if total_cost_basis > 0 else None
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
        put("minDscr", min(dscrs))
        put("avgDscr", sum(dscrs) / len(dscrs))
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

    # ------------------------------------------------------------------
    # Debt sizing detail: governing constraint + rate/NOI stress grid.
    # ------------------------------------------------------------------
    debt_block = None
    if perm_loan > 0:
        outputs["governingConstraint"] = _GOVERNING_LABELS.get(
            governing_constraint, governing_constraint
        )
        stress = debt.stress_matrix(
            sizing_noi, value_for_ltv, perm_loan, ltc_or_ltv, dscr_constraint,
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
        "irrConvention": irr_convention,
        "waterfallStyle": waterfall_style,
        "statement": statement,
    }
