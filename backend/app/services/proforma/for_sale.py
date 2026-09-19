"""Build-to-sell homes (roadmap #26): a merchant-builder cash flow — buy
land, build the site, build and close homes at the sales pace, repay the
construction loan from closings. There is no NOI, hold or exit cap; the
return is the sales margin over time. [FIN] conventions (DECISIONS.md):

- Applies to development deals of property type single-family or townhouse
  with "Model as For-Sale" on AND a sale price per home entered (without a
  price the deal keeps computing as a rental, as before this model).
- Month 0: land. Months 1..S (S = constructionMonths): site work — hard
  costs on an S-curve, soft costs straight-line, contingency on the hard
  curve. With S = 0 the site budget lands at close.
- Homes close at absorptionPerMonth from month S + B (B = homeBuildMonths,
  default 6): each home's vertical cost (buildCostPerHome, plus
  contingency) is spent evenly over the B months ending at its closing.
- Price per home grows annually at homePriceGrowthPct from the first
  closing; selling costs (commissions, closing) = costOfSalePct of the price.
- The developer fee is developerFeePct of each month's hard, soft, vertical
  and contingency spend (the development module's base, paid as spent).
- Financing: equity first up to (1 - LTC) of total cost, then a revolving
  construction loan (commitment = LTC x total cost including interest and
  the origination fee, solved by fixed point as for the main development
  loan; the fee is paid at close) funds costs and monthly interest. A
  month's closing proceeds pay that month's costs first, then repay the
  loan; the rest goes to equity. Costs beyond the
  commitment are funded with more equity (warned).
"""

import math

from app.services.proforma import development, equity, returns

FOR_SALE_TYPES = ("single_family", "townhouse")
DEFAULT_BUILD_MONTHS = 6


def _num(inputs: dict, field: str, default: float = 0.0) -> float:
    value = inputs.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def applies(inputs: dict) -> bool:
    return (
        inputs.get("dealType") == "development"
        and inputs.get("propertyType") in FOR_SALE_TYPES
        and inputs.get("isForSale") is not False
        and _num(inputs, "salePricePerHome") > 0
    )


def missing_inputs(inputs: dict) -> list[str]:
    missing = [f for f in ("homeCount", "absorptionPerMonth", "landCost") if _num(inputs, f) <= 0]
    if _num(inputs, "buildCostPerHome") <= 0 and _num(inputs, "hardCosts") <= 0:
        missing.append("buildCostPerHome (or hardCosts for site work)")
    return missing


def compute(inputs: dict) -> dict:
    warnings: list[str] = []
    homes = int(round(_num(inputs, "homeCount")))
    pace = _num(inputs, "absorptionPerMonth")
    price = _num(inputs, "salePricePerHome")
    price_growth = _num(inputs, "homePriceGrowthPct")
    build_per_home = _num(inputs, "buildCostPerHome")
    build_months = max(1, int(round(_num(inputs, "homeBuildMonths", DEFAULT_BUILD_MONTHS))))
    site_months = max(0, int(round(_num(inputs, "constructionMonths"))))
    contingency_pct = _num(inputs, "contingencyPct")
    fee_pct = _num(inputs, "developerFeePct")
    selling_pct = _num(inputs, "costOfSalePct")
    ltc = min(1.0, max(0.0, _num(inputs, "ltvOrLtc")))
    rate = _num(inputs, "interestRate")
    origination_pct = _num(inputs, "originationFeePct")
    if homes != _num(inputs, "homeCount"):
        warnings.append(f"# Homes rounded to {homes}.")

    # ---- closing schedule: `pace` a month from S + B until sold out --------
    first_close = site_months + build_months
    closings_by_month: dict[int, float] = {}
    remaining, month = float(homes), first_close
    while remaining > 1e-9:
        sold = min(pace, remaining)
        closings_by_month[month] = sold
        remaining -= sold
        month += 1
    total = max(closings_by_month) if closings_by_month else first_close
    sellout_months = total - first_close + 1

    # ---- costs by month ------------------------------------------------------
    site = development.build_budget(
        _num(inputs, "landCost"), _num(inputs, "hardCosts"), _num(inputs, "softCosts"), contingency_pct, 0.0
    )
    site_schedule = development.monthly_cost_schedule(site, site_months)  # land at 0, site work 1..S
    land = [0.0] * (total + 1)
    site_work = [0.0] * (total + 1)
    land[0] = site.land
    for m, amount in enumerate(site_schedule):
        if m == 0:
            site_work[0] += amount - site.land
        elif m <= total:
            site_work[m] += amount
    vertical = [0.0] * (total + 1)
    per_home_month = build_per_home * (1 + contingency_pct) / build_months
    for close_month, count in closings_by_month.items():
        for m in range(close_month - build_months + 1, close_month + 1):
            vertical[max(m, 0)] += count * per_home_month
    fee = [fee_pct * (site_work[m] + vertical[m]) for m in range(total + 1)]
    costs = [land[m] + site_work[m] + vertical[m] + fee[m] for m in range(total + 1)]

    # ---- sales ---------------------------------------------------------------
    gross_sales = [0.0] * (total + 1)
    for close_month, count in closings_by_month.items():
        gross_sales[close_month] = count * price * (1 + price_growth) ** ((close_month - first_close) // 12)
    selling_costs = [selling_pct * g for g in gross_sales]
    net_sales = [g - c for g, c in zip(gross_sales, selling_costs, strict=True)]

    # ---- financing: equity first, revolving loan, closings repay the loan ---
    # LTC is on total cost including interest and fees, as for the main
    # development loan (engine audit fix): solve the commitment by fixed point.
    budget = sum(costs)
    total_cost = budget
    for _ in range(100):
        commitment = ltc * total_cost
        plan = _finance(costs, net_sales, commitment, total_cost - commitment, origination_pct, rate)
        solved = budget + plan["loanFee"] + sum(plan["interest"])
        if abs(solved - total_cost) < 0.01:
            break
        total_cost = solved
    commitment = ltc * total_cost
    plan = _finance(costs, net_sales, commitment, total_cost - commitment, origination_pct, rate)
    loan_fee = plan["loanFee"]
    equity_in, draws, interest = plan["equityIn"], plan["draws"], plan["interest"]
    repayments, balance_vec, distributions = plan["repayments"], plan["balance"], plan["distributions"]
    balance = plan["unpaid"]
    if balance > 0.5:
        warnings.append(f"Sales leave ${balance:,.0f} of the construction loan unpaid at sellout; equity repays it.")
    if plan["overCommitment"] > 0.5:
        warnings.append(
            f"Costs and interest exceed the loan commitment by ${plan['overCommitment']:,.0f}; more equity funds it."
        )

    levered = [distributions[m] - equity_in[m] for m in range(total + 1)]
    unlevered = [net_sales[m] - costs[m] for m in range(total + 1)]

    # ---- returns ---------------------------------------------------------------
    outputs: dict[str, float] = {}

    def put(key: str, value) -> None:
        if isinstance(value, (int, float)) and math.isfinite(value):
            outputs[key] = float(value)

    lp_share, gp_share = _num(inputs, "lpSplitPct", 0.9), _num(inputs, "gpSplitPct", 0.1)
    waterfall = equity.run_waterfall(
        levered, lp_share, gp_share, _num(inputs, "preferredReturnPct"),
        inputs.get("waterfallTiers") or [], inputs.get("waterfallStyle") or "european",
    )
    warnings.extend(waterfall["warnings"])
    revenue = sum(net_sales)
    total_interest = sum(interest)
    profit_before_financing = revenue - budget
    put("leveredIrr", returns.periodic_irr(levered))
    put("unleveredIrr", returns.periodic_irr(unlevered))
    put("equityMultiple", returns.equity_multiple(levered))
    put("moic", returns.equity_multiple(levered))
    put("unleveredEquityMultiple", returns.equity_multiple(unlevered))
    put("lpIrr", waterfall["lpIrr"])
    put("gpIrr", waterfall["gpIrr"])
    put("lpEquityMultiple", waterfall["lpMultiple"])
    put("totalProfit", sum(levered))
    put("netSaleProceeds", revenue)
    put("npv", returns.npv(_num(inputs, "discountRatePct", 0.10), levered))
    put("profitabilityIndex", returns.profitability_index(_num(inputs, "discountRatePct", 0.10), levered))
    put("paybackPeriodYears", returns.payback_period_years(levered))
    if total_cost > 0:
        put("ltc", commitment / total_cost)
    if revenue > 0:
        # Merchant-builder margin: profit before financing over net revenue.
        put("grossMarginPct", profit_before_financing / revenue)
    peak = 0.0
    running = 0.0
    for flow in levered:
        running += flow
        peak = max(peak, -running)
    put("peakEquity", peak)
    put("selloutYears", sellout_months / 12)

    zeros = [0.0] * (total + 1)
    statement = {
        "months": list(range(total + 1)),
        "phases": ["close"] + [
            "construction" if m <= site_months else ("lease_up" if m < first_close else "stabilized")
            for m in range(1, total + 1)
        ],
        "constructionMonths": site_months,
        "stabilizationMonth": first_close,
        "exitMonth": total,
        **{key: list(zeros) for key in (
            "gpr", "vacancyLoss", "creditLoss", "otherIncome", "egi", "managementFee",
            "opexTotal", "noi", "occupancy", "recoveries", "leasingCapital",
        )},
        "fixedOpexByCategory": {},
        "costs": costs,
        "loanFees": [loan_fee] + [0.0] * total,
        # The usual identity holds: levered = noi - debtService + debtDraws
        # - costs - loanFees - leasingCapital + saleProceedsNet, with debt
        # service = interest + loan repaid from closings.
        "equityFunded": equity_in,
        "debtDraws": draws,
        "interest": interest,
        "principal": repayments,
        "debtService": [interest[m] + repayments[m] for m in range(total + 1)],
        "loanBalance": balance_vec,
        "saleProceedsNet": net_sales,
        "saleProceedsGross": gross_sales,
        "unlevered": unlevered,
        "levered": levered,
        "lpDistributions": waterfall["lpFlows"],
        "gpDistributions": waterfall["gpFlows"],
        "forSale": {
            "homes": homes,
            "closings": [closings_by_month.get(m, 0.0) for m in range(total + 1)],
            "grossSales": gross_sales,
            "sellingCosts": selling_costs,
            "netSales": net_sales,
            "land": land,
            "siteWork": site_work,
            "vertical": vertical,
            "developerFee": fee,
            "loanRepayments": repayments,
        },
    }
    uses = [
        ["Land", site.land],
        ["Site work (hard, soft, contingency)", sum(site_work)],
        ["Home construction (incl. contingency)", sum(vertical)],
        ["Developer fee", sum(fee)],
        ["Construction interest", total_interest],
        ["Loan fees", loan_fee],
    ]
    sources = [
        ["Construction loan draws (revolving)", sum(draws)],
        ["Closing proceeds reinvested in construction", sum(plan["reinvested"])],
        ["Equity", sum(equity_in) - (balance if balance > 0.5 else 0.0)],
    ]
    return {
        "outputs": outputs,
        "warnings": warnings,
        "gprSource": "forSale",
        "debt": {"loanAmount": commitment, "governingConstraint": "ltc", "peakBalance": max(balance_vec)},
        "sourcesAndUses": {"uses": uses, "sources": sources},
        "constructionLoan": None,
        "maturityRefinance": None,
        "irrConvention": "periodic_monthly",
        "waterfallStyle": inputs.get("waterfallStyle") or "european",
        "gpEconomics": None,
        "juniorTranche": None,
        "statement": statement,
    }


def _finance(
    costs: list[float],
    net_sales: list[float],
    commitment: float,
    equity_commitment: float,
    origination_pct: float,
    rate: float,
) -> dict:
    """One pass of the funding waterfall for a given loan and equity
    commitment: equity first up to its share, then loan draws (costs and
    interest), closings repaying the loan before anything reaches equity."""
    total = len(costs) - 1
    loan_fee = origination_pct * commitment
    equity_in = [0.0] * (total + 1)
    draws = [0.0] * (total + 1)
    interest = [0.0] * (total + 1)
    repayments = [0.0] * (total + 1)
    balance_vec = [0.0] * (total + 1)
    distributions = [0.0] * (total + 1)
    reinvested = [0.0] * (total + 1)
    equity_used = balance = over_commitment = 0.0
    for m in range(total + 1):
        interest[m] = balance * rate / 12
        need = costs[m] + (loan_fee if m == 0 else 0.0) + interest[m]
        # A month's closings pay that month's costs first (a builder funds
        # the next starts from the last closings), then repay the loan.
        available = net_sales[m]
        from_sales = min(available, need)
        reinvested[m] = from_sales
        available -= from_sales
        need -= from_sales
        from_equity = min(need, max(0.0, equity_commitment - equity_used))
        from_loan = min(need - from_equity, max(0.0, commitment - balance))
        extra_equity = need - from_equity - from_loan
        over_commitment += extra_equity
        equity_used += from_equity
        equity_in[m] = from_equity + extra_equity
        draws[m] = from_loan
        balance += from_loan
        repay = min(balance, available)
        repayments[m] = repay
        balance -= repay
        distributions[m] = available - repay
        balance_vec[m] = balance
    unpaid = balance
    if unpaid > 0.5:
        # Equity repays what sales couldn't.
        equity_in[total] += unpaid
        repayments[total] += unpaid
        balance_vec[total] = 0.0
    return {
        "loanFee": loan_fee,
        "equityIn": equity_in,
        "draws": draws,
        "interest": interest,
        "repayments": repayments,
        "balance": balance_vec,
        "distributions": distributions,
        "reinvested": reinvested,
        "unpaid": unpaid,
        "overCommitment": over_commitment,
    }
