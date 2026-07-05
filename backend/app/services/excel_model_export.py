"""Native Excel model export (H11): a formula-live workbook whose cells
mirror the engine's math for the supported deal shape, so the downloaded
file recalculates on its own (change an input cell, the returns move).

Supported shape — acquisitions with GPR-based income, the legacy flat
expense fields, simple debt (IO then level amortization), single-cap exit,
pro-rata equity, periodic-monthly IRR. Anything whose math can't be
mirrored formula-for-formula raises UnsupportedModelFeatures listing the
blockers — a silently wrong model must never escape (see DECISIONS.md).

Two deliberate value-not-formula cells, each flagged in the Notes sheet:
- Loan amount: the engine's constraint-based sizing (min of LTV / DSCR /
  debt-yield proceeds) is written as the sized VALUE.
- Annual GPR / other income: unit-mix or per-SF sections collapse to the
  same annual dollars the engine uses.
"""

from io import BytesIO

import openpyxl

from app.services.proforma import engine, leases, operations
from app.services.proforma.operations import EXPENSE_DOLLAR_FIELDS


class UnsupportedModelFeatures(Exception):
    def __init__(self, features: list[str]):
        self.features = features
        super().__init__(
            "The Excel model export can't mirror these features as formulas: "
            + "; ".join(features)
        )


# Outputs sheet cells the parity harness reads, keyed by schema output id.
OUTPUT_CELLS = {
    "unleveredIrr": "G2",
    "leveredIrr": "G3",
    "equityMultiple": "G4",
    "cashOnCashYear1": "G5",
    "goingInCapRate": "G6",
    "yieldOnCost": "G7",
    "terminalValue": "G8",
    "netSaleProceeds": "G9",
    "totalProfit": "G10",
    "npv": "G11",
    "minDscr": "G12",
    "debtYield": "G13",
    "ltv": "G14",
    "loanConstant": "G15",
}

_EXPENSE_LABELS = {
    "realEstateTaxes": "Real estate taxes",
    "insurance": "Insurance",
    "utilities": "Utilities",
    "repairsMaintenance": "Repairs & maintenance",
    "payroll": "Payroll",
    "generalAdmin": "General & admin",
    "replacementReserves": "Replacement reserves",
}
_EXPENSE_START_ROW = 24  # Inputs!A24.. one row per category


def unsupported_features(inputs: dict) -> list[str]:
    features = []
    if (inputs.get("dealType") or "acquisition") == "development":
        features.append("development deals (construction draws / takeout)")
    if leases.has_leases(inputs):
        features.append("commercial lease-level rent rolls (escalations/recoveries/rollover)")
    if operations.has_opex_detail(inputs):
        features.append("opex line-item detail (per-line basis/growth/recoverable)")
    if inputs.get("waterfallTiers"):
        features.append("promote waterfall tiers")
    if inputs.get("irrConvention") == "xirr":
        features.append("XIRR date-based IRR convention")
    if inputs.get("useReassessedTaxes"):
        features.append("reassessed property taxes (separate tax growth clock)")
    return features


def _num(inputs: dict, key: str, default: float = 0.0) -> float:
    value = inputs.get(key)
    return float(value) if isinstance(value, (int, float)) else default


def build_model_workbook(inputs: dict) -> tuple[bytes, list[str]]:
    """Returns (xlsx bytes, warnings). Raises UnsupportedModelFeatures or
    engine.InsufficientInputsError."""
    blockers = unsupported_features(inputs)
    if blockers:
        raise UnsupportedModelFeatures(blockers)

    # One engine compute for the sized loan (and to fail early on bad inputs).
    result = engine.compute(inputs)
    debt_block = result.get("debt") or {}
    loan_amount = float(debt_block.get("loanAmount") or 0.0)

    annual_gpr, annual_other, gpr_source, _ = operations.annual_gpr_and_other_income(inputs)
    warnings: list[str] = []
    if gpr_source != "grossPotentialRent":
        warnings.append(
            f"Income comes from a {gpr_source} section — collapsed to annual dollars "
            "(the rows themselves are not formula-modeled)."
        )
    if loan_amount > 0:
        warnings.append(
            f"Loan amount ${loan_amount:,.0f} is the app's constraint-based sizing "
            f"(governed by {debt_block.get('governingConstraint', 'ltv')}) written as a value."
        )

    hold_months = int(round(_num(inputs, "holdPeriodYears", 5) * 12))
    total_rows = hold_months + 12  # 12 forward months for the exit cap window
    rent_growth = (
        _num(inputs, "rentGrowthPct") if inputs.get("rentGrowthMode") != "flat" else 0.0
    )
    expense_growth = (
        _num(inputs, "expenseGrowthPct") if inputs.get("expenseGrowthMode") != "flat" else 0.0
    )

    wb = openpyxl.Workbook()

    # ---- Inputs sheet -----------------------------------------------------
    ws = wb.active
    ws.title = "Inputs"
    input_rows = [
        ("Purchase price", _num(inputs, "purchasePrice")),
        ("Closing costs %", _num(inputs, "closingCostsPct")),
        ("Acquisition fee %", _num(inputs, "acquisitionFeePct")),
        ("Due diligence", _num(inputs, "dueDiligenceCosts")),
        ("Day-1 capex", _num(inputs, "dayOneCapex")),
        ("Annual GPR", annual_gpr),
        ("Annual other income", annual_other),
        ("Vacancy %", _num(inputs, "vacancyPct", 0.05)),
        ("Credit loss %", _num(inputs, "creditLossPct")),
        ("Rent growth %/yr", rent_growth),
        ("Mgmt fee % of EGI", _num(inputs, "managementFeePct")),
        ("Loan amount (sized by app)", loan_amount),
        ("Interest rate", _num(inputs, "interestRate", 0.065)),
        ("Amortization (yrs)", _num(inputs, "amortYears", 30)),
        ("IO months", int(_num(inputs, "ioMonths"))),
        ("Origination fee %", _num(inputs, "originationFeePct")),
        ("Hold (months)", hold_months),
        ("Exit cap rate", _num(inputs, "exitCapRatePct")),
        ("Cost of sale %", _num(inputs, "costOfSalePct")),
        ("Discount rate", _num(inputs, "discountRatePct", 0.10)),
        ("In-place NOI (0 = use year 1)", _num(inputs, "inPlaceNoi")),
    ]
    for i, (label, value) in enumerate(input_rows, start=1):
        ws.cell(row=i, column=1, value=label)
        ws.cell(row=i, column=2, value=value)

    ws.cell(row=_EXPENSE_START_ROW - 1, column=1, value="Operating expenses (annual)")
    ws.cell(row=_EXPENSE_START_ROW - 1, column=3, value="Growth %/yr")
    for offset, field in enumerate(EXPENSE_DOLLAR_FIELDS):
        row = _EXPENSE_START_ROW + offset
        ws.cell(row=row, column=1, value=_EXPENSE_LABELS.get(field, field))
        ws.cell(row=row, column=2, value=_num(inputs, field))
        ws.cell(row=row, column=3, value=expense_growth)
    exp_first = _EXPENSE_START_ROW
    exp_last = _EXPENSE_START_ROW + len(EXPENSE_DOLLAR_FIELDS) - 1

    # ---- Model sheet: rows 2..total_rows+1 = months 1..total_rows ---------
    model = wb.create_sheet("Model")
    headers = [
        "Month", "GPR", "Vacancy loss", "Credit loss", "Other income", "EGI",
        "Fixed opex", "Mgmt fee", "NOI", "Begin balance", "Interest",
        "Principal", "End balance", "Debt service", "DSCR",
        "Unlevered CF", "Levered CF",
    ]
    for col, header in enumerate(headers, start=1):
        model.cell(row=1, column=col, value=header)

    growth_exp = "INT(($A{r}-1)/12)"
    for m in range(1, total_rows + 1):
        r = m + 1
        g = growth_exp.format(r=r)
        model.cell(row=r, column=1, value=m)
        model.cell(row=r, column=2, value=f"=Inputs!$B$6/12*(1+Inputs!$B$10)^{g}")
        model.cell(row=r, column=3, value=f"=B{r}*Inputs!$B$8")
        model.cell(row=r, column=4, value=f"=B{r}*(1-Inputs!$B$8)*Inputs!$B$9")
        model.cell(row=r, column=5, value=f"=Inputs!$B$7/12*(1+Inputs!$B$10)^{g}")
        model.cell(row=r, column=6, value=f"=B{r}-C{r}-D{r}+E{r}")
        model.cell(
            row=r, column=7,
            value=(
                f"=SUMPRODUCT(Inputs!$B${exp_first}:$B${exp_last}/12,"
                f"(1+Inputs!$C${exp_first}:$C${exp_last})^{g})"
            ),
        )
        model.cell(row=r, column=8, value=f"=F{r}*Inputs!$B$11")
        model.cell(row=r, column=9, value=f"=F{r}-G{r}-H{r}")
        if m > hold_months:
            continue  # forward window: income only, no debt or cash flows
        begin = "Inputs!$B$12" if m == 1 else f"M{r - 1}"
        model.cell(row=r, column=10, value=f"={begin}")
        model.cell(row=r, column=11, value=f"=J{r}*Inputs!$B$13/12")
        model.cell(
            row=r, column=12,
            value=f"=IF($A{r}<=Inputs!$B$15,0,MAX(0,MIN(Outputs!$B$1-K{r},J{r})))",
        )
        model.cell(row=r, column=13, value=f"=J{r}-L{r}")
        model.cell(row=r, column=14, value=f"=K{r}+L{r}")
        model.cell(row=r, column=15, value=f'=IF(N{r}>0,I{r}/N{r},"")')
        exit_bump_u = f"+IF($A{r}=Inputs!$B$17,Outputs!$B$6,0)"
        exit_bump_l = f"+IF($A{r}=Inputs!$B$17,Outputs!$B$6-M{r},0)"
        model.cell(row=r, column=16, value=f"=I{r}{exit_bump_u}")
        model.cell(row=r, column=17, value=f"=I{r}-N{r}{exit_bump_l}")

    hold_row = hold_months + 1  # Model row of the exit month
    fwd_first, fwd_last = hold_row + 1, hold_row + 12

    # ---- Outputs sheet ----------------------------------------------------
    out = wb.create_sheet("Outputs")
    helper_rows = [
        ("Monthly payment (PMT)",
         "=IF(Inputs!$B$12<=0,0,IF(Inputs!$B$13=0,"
         "Inputs!$B$12/ROUND(Inputs!$B$14*12,0),"
         "Inputs!$B$12*Inputs!$B$13/12/(1-(1+Inputs!$B$13/12)^-ROUND(Inputs!$B$14*12,0))))"),
        ("Total basis (ex loan fees)",
         "=Inputs!$B$1*(1+Inputs!$B$2+Inputs!$B$3)+Inputs!$B$4+Inputs!$B$5"),
        ("Loan fees", "=Inputs!$B$12*Inputs!$B$16"),
        ("Initial equity", "=B2-Inputs!$B$12+B3"),
        ("Terminal value (fwd-12 NOI / cap)",
         f"=SUM(Model!$I${fwd_first}:$I${fwd_last})/Inputs!$B$18"),
        ("Gross sale net of costs", "=B5*(1-Inputs!$B$19)"),
        ("Exit loan balance", f"=Model!$M${hold_row}"),
        ("Net sale proceeds", "=B6-B7"),
        ("Stabilized EGI (today's rents)",
         "=Inputs!$B$6*(1-Inputs!$B$8)*(1-Inputs!$B$9)+Inputs!$B$7"),
        ("Stabilized NOI",
         f"=B9-SUM(Inputs!$B${exp_first}:$B${exp_last})-B9*Inputs!$B$11"),
    ]
    for i, (label, formula) in enumerate(helper_rows, start=1):
        out.cell(row=i, column=1, value=label)
        out.cell(row=i, column=2, value=formula)

    # Cash-flow vectors: D = levered, E = unlevered; row 1 = close (t0).
    out["D1"] = "=-B4"
    out["E1"] = "=-B2"
    for m in range(1, hold_months + 1):
        out.cell(row=m + 1, column=4, value=f"=Model!Q{m + 1}")
        out.cell(row=m + 1, column=5, value=f"=Model!P{m + 1}")
    flow_last = hold_months + 1
    lev = f"$D$1:$D${flow_last}"
    unlev = f"$E$1:$E${flow_last}"

    coc_exit_adj = "-B8" if hold_months == 12 else ""
    metrics = {
        "unleveredIrr": f"=(1+IRR({unlev},0.005))^12-1",
        "leveredIrr": f"=(1+IRR({lev},0.005))^12-1",
        "equityMultiple": f'=SUMIF({lev},">0")/-SUMIF({lev},"<0")',
        "cashOnCashYear1": f'=(SUM(Model!$Q$2:$Q$13){coc_exit_adj})/-SUMIF({lev},"<0")',
        "goingInCapRate":
            "=IF(Inputs!$B$21>0,Inputs!$B$21,SUM(Model!$I$2:$I$13))/Inputs!$B$1",
        "yieldOnCost": "=B10/(B2+B3)",
        "terminalValue": "=B5",
        "netSaleProceeds": "=B8",
        "totalProfit": f"=SUM({lev})",
        "npv": f"=D1+NPV((1+Inputs!$B$20)^(1/12)-1,$D$2:$D${flow_last})",
        "minDscr": f"=MIN(Model!$O$2:$O${hold_row})",
        "debtYield": "=B10/Inputs!$B$12",
        "ltv": "=Inputs!$B$12/Inputs!$B$1",
        "loanConstant":
            "=IF(Inputs!$B$15>=Inputs!$B$17,Inputs!$B$13,12*B1/Inputs!$B$12)",
    }
    for i, (output_id, formula) in enumerate(metrics.items(), start=2):
        out.cell(row=i, column=6, value=output_id)
        assert OUTPUT_CELLS[output_id] == f"G{i}"
        out.cell(row=i, column=7, value=formula)

    # ---- Notes sheet ------------------------------------------------------
    notes = wb.create_sheet("Notes")
    notes["A1"] = "Exported by CRE Underwriting Dashboard — formula-live model"
    note_lines = warnings + [
        "Conventions: monthly periods, growth steps annually (anniversary), "
        "credit loss applies to occupied revenue, terminal value caps the "
        "FORWARD 12-month NOI, IRR is monthly annualized as (1+i)^12-1.",
    ]
    for i, line in enumerate(note_lines, start=3):
        notes.cell(row=i, column=1, value=line)

    wb.calculation.fullCalcOnLoad = True
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue(), warnings
