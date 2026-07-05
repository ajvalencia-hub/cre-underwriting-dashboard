"""H11 parity: the NATIVE-EXPORTED workbook (formula-live, no template)
recalculated by LibreOffice must match the engine within the same
tolerances as the template corpus. Two cases:

- analytic_acquisition: the hand-derivable fixture (pure IO, flat growth) —
  its expected values are pinned in the fixture's comment block, making
  this a three-way check (engine = workbook = hand algebra).
- amortizing_growth: growth clocks, credit loss, other income, multiple
  expense categories, IO -> amortizing debt, app-sized loan — exercises
  every formula the exporter writes.
"""

import json
from pathlib import Path

import openpyxl

from app.services import excel_model_export, recalc_service
from app.services.proforma import engine
from tests.parity.harness import Diff, tolerance_for

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

AMORTIZING_GROWTH_INPUTS = {
    "dealName": "Export Parity — Amortizing Growth",
    "dealType": "acquisition",
    "propertyType": "multifamily",
    "purchasePrice": 10_000_000,
    "closingCostsPct": 0.015,
    "acquisitionFeePct": 0.01,
    "dueDiligenceCosts": 50_000,
    "dayOneCapex": 200_000,
    "grossPotentialRent": 1_200_000,
    "otherIncome": 60_000,
    "vacancyPct": 0.05,
    "creditLossPct": 0.01,
    "rentGrowthMode": "per_year",
    "rentGrowthPct": 0.03,
    "expenseGrowthMode": "per_year",
    "expenseGrowthPct": 0.025,
    "realEstateTaxes": 130_000,
    "insurance": 45_000,
    "utilities": 60_000,
    "repairsMaintenance": 55_000,
    "payroll": 90_000,
    "generalAdmin": 25_000,
    "replacementReserves": 30_000,
    "managementFeePct": 0.03,
    "ltvOrLtc": 0.65,
    "interestRate": 0.062,
    "amortYears": 30,
    "loanTermYears": 10,
    "ioMonths": 24,
    "originationFeePct": 0.01,
    "dscrConstraint": 1.25,
    "debtYieldConstraint": 0.08,
    "holdPeriodYears": 5,
    "exitCapRatePct": 0.0575,
    "costOfSalePct": 0.02,
    "discountRatePct": 0.10,
    "waterfallTiers": [],
}


# I7: expense-line detail + non-ad-valorem — the Expenses block resolves
# per_unit lines against the unit count and carries a separate-growth line.
OPEX_DETAIL_INPUTS = {
    "dealName": "Export Parity — Opex Detail",
    "dealType": "acquisition",
    "propertyType": "multifamily",
    "purchasePrice": 12_000_000,
    "closingCostsPct": 0.01,
    "acquisitionFeePct": 0,
    "dueDiligenceCosts": 40_000,
    "dayOneCapex": 0,
    "unitMix": [
        {"unitType": "1BR", "unitCount": 40, "inPlaceRent": 1_600, "avgSf": 750},
        {"unitType": "2BR", "unitCount": 20, "inPlaceRent": 2_100, "avgSf": 1_050},
    ],
    "otherIncome": 45_000,
    "vacancyPct": 0.05,
    "creditLossPct": 0.01,
    "rentGrowthMode": "per_year",
    "rentGrowthPct": 0.03,
    "expenseGrowthMode": "per_year",
    "expenseGrowthPct": 0.025,
    "opexLineItems": [
        {"category": "taxes", "amount": 140_000, "basis": "annual_total", "recoverable": "yes"},
        {"category": "insurance", "amount": 40_000, "basis": "annual_total", "recoverable": "yes"},
        {"category": "utilities", "amount": 450, "basis": "per_unit", "recoverable": "yes"},
        {"category": "repairs_maintenance", "amount": 35_000, "basis": "annual_total",
         "growthPct": 0.04, "recoverable": "no"},
        {"category": "management_fee", "amount": 0.03, "basis": "pct_of_egi", "recoverable": "no"},
    ],
    "nonAdValoremTaxes": 8_000,
    "nonAdValoremGrowthPct": 0.04,
    "ltvOrLtc": 0.6,
    "interestRate": 0.06,
    "amortYears": 30,
    "loanTermYears": 10,
    "ioMonths": 24,
    "originationFeePct": 0.01,
    "dscrConstraint": 1.25,
    "debtYieldConstraint": 0.08,
    "holdPeriodYears": 5,
    "exitCapRatePct": 0.0575,
    "costOfSalePct": 0.02,
    "discountRatePct": 0.10,
    "waterfallTiers": [],
}

# I7: development — S-curve draws, equity-first funding, capitalized
# interest + fee, NOI sweep to takeout, constraint-sized perm, IO->amort.
DEVELOPMENT_SCURVE_INPUTS = {
    "dealName": "Export Parity — Development S-curve",
    "dealType": "development",
    "propertyType": "multifamily",
    "landCost": 2_000_000,
    "hardCosts": 10_000_000,
    "softCosts": 2_000_000,
    "contingencyPct": 0.05,
    "developerFeePct": 0.04,
    "constructionMonths": 12,
    "leaseUpMonths": 6,
    "grossPotentialRent": 1_800_000,
    "otherIncome": 50_000,
    "vacancyPct": 0.05,
    "creditLossPct": 0.01,
    "rentGrowthMode": "per_year",
    "rentGrowthPct": 0.03,
    "expenseGrowthMode": "per_year",
    "expenseGrowthPct": 0.025,
    "realEstateTaxes": 150_000,
    "insurance": 50_000,
    "utilities": 60_000,
    "repairsMaintenance": 40_000,
    "payroll": 80_000,
    "generalAdmin": 20_000,
    "replacementReserves": 25_000,
    "managementFeePct": 0.03,
    "ltvOrLtc": 0.65,
    "interestRate": 0.075,
    "refiRateSpreadPct": 0.005,
    "refiCostsPct": 0.01,
    "amortYears": 30,
    "loanTermYears": 10,
    "ioMonths": 12,
    "originationFeePct": 0.01,
    "dscrConstraint": 1.25,
    "debtYieldConstraint": 0.08,
    "holdPeriodYears": 5,
    "exitCapRatePct": 0.055,
    "costOfSalePct": 0.02,
    "discountRatePct": 0.10,
    "lpSplitPct": 0.9,
    "gpSplitPct": 0.1,
    "preferredReturnPct": 0.08,
    "waterfallTiers": [],
}


def _load_cases() -> list[tuple[str, dict]]:
    analytic = json.loads((_FIXTURES / "analytic_acquisition.json").read_text())
    return [
        ("export_analytic_acquisition", analytic),
        ("export_amortizing_growth", AMORTIZING_GROWTH_INPUTS),
        ("export_opex_detail", OPEX_DETAIL_INPUTS),
        ("export_development_scurve", DEVELOPMENT_SCURVE_INPUTS),
    ]


def run_export_parity(workdir: Path) -> list[tuple[str, list[Diff] | None, str | None]]:
    """Returns [(case_name, diffs | None, skip_reason | None)]."""
    results = []
    for name, inputs in _load_cases():
        content, _warnings = excel_model_export.build_model_workbook(inputs)
        path = workdir / f"{name}.xlsx"
        path.write_bytes(content)

        native = engine.compute(inputs)["outputs"]
        compared = [
            oid for oid in excel_model_export.OUTPUT_CELLS
            if isinstance(native.get(oid), (int, float))
        ]

        if not recalc_service.is_available():
            results.append((name, None, "LibreOffice not installed — export parity skipped"))
            continue

        recalc_service.recalc_with_libreoffice(path)
        wb = openpyxl.load_workbook(path, data_only=True)
        out = wb["Outputs"]
        diffs = []
        for oid in compared:
            excel_value = out[excel_model_export.OUTPUT_CELLS[oid]].value
            diffs.append(
                Diff(
                    field=oid,
                    native=float(native[oid]),
                    excel=float(excel_value) if isinstance(excel_value, (int, float)) else None,
                    tolerance=tolerance_for(oid),
                )
            )
        wb.close()
        results.append((name, diffs, None))
    return results
