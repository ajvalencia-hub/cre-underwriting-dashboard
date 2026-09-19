"""Seed a demo workspace: three acquisition deals and two development deals
with realistic, engine-computable inputs, six sale comps, six rent comps, and
one note per deal. Stages are spread across both dealflow registries
(app/data/input_schema.json `dealStages`) so the Deals boards, Portfolio
roll-up and comps benchmarks all have something to show.

Usage (from backend/):

    python scripts/seed_demo.py                       # the configured DB
    CRE_DB_PATH=/tmp/demo.sqlite3 python scripts/seed_demo.py
    python scripts/seed_demo.py --replace             # re-seed: drop the
                                                      # previously seeded rows first
    python scripts/seed_demo.py --dry-run             # compute only, write nothing

The database is whatever app.config resolves: CRE_DB_PATH if set, otherwise
<CRE_STORAGE_ROOT or backend/storage>/db/app.sqlite3. Every deal's inputs are
run through the engine's input validation (no errors AND no warnings — a
seed never relies on coercion or an out-of-range value) and the native
pro-forma engine BEFORE anything is written, so a seed that would not
compute never reaches the database. The database is opened the way the app
starts: refuse a newer schema, back up before migrating, migrate. Refuses to run twice
(seeded rows are tagged) unless --replace is given.
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# app.config reads the environment at import time — everything below must
# come after any CRE_* variable the caller exported.
from app.database import (  # noqa: E402
    Base,
    SessionLocal,
    engine,
    prepare_migrations,
    run_migrations,
)
from app.models import Deal, DealNote, RentComp, SaleComp  # noqa: E402
from app.schemas import DEAL_STAGES_BY_TYPE  # noqa: E402
from app.services import deal_history  # noqa: E402
from app.services.proforma import engine as proforma  # noqa: E402
from app.services.proforma import input_validation  # noqa: E402

SEED_TAG = "seed_demo"  # comps.source and the note marker that make re-seeding safe
NOTE_MARKER = f"[{SEED_TAG}]"

# ---------------------------------------------------------------------------
# Deal inputs. Shapes mirror tests/fixtures/*.json and
# tests/regression/fixtures/*.json (the engine's own analytic cases); numbers
# are re-scaled to read like real deals.
# ---------------------------------------------------------------------------

_CAPITAL_STACK_COMMON = {
    "amortYears": 30,
    "loanTermYears": 10,
    "originationFeePct": 0.01,
    "dscrConstraint": 1.25,
    "debtYieldConstraint": 0.08,
    "lpSplitPct": 0.9,
    "gpSplitPct": 0.1,
    "preferredReturnPct": 0.08,
    "waterfallTiers": [
        {"tierName": "Tier 1", "irrHurdle": 0.12, "lpSplitAboveHurdle": 0.8, "gpSplitAboveHurdle": 0.2},
        {"tierName": "Tier 2", "irrHurdle": 0.18, "lpSplitAboveHurdle": 0.7, "gpSplitAboveHurdle": 0.3},
    ],
}

DEALS: list[dict] = [
    {
        "name": "Maple Court Apartments",
        "status": "underwriting",
        "note": "Value-add: 60% of units at classic finish, ~$200/mo premium on renovated "
        "comps. Seller wants a 45-day DD. Tax reassessment at sale is the swing factor.",
        "inputs": {
            "dealType": "acquisition",
            "propertyType": "multifamily",
            "address": "4100 Maple Ct",
            "market": "Austin",
            "submarket": "East Riverside",
            "purchasePrice": 18_000_000,
            "closingCostsPct": 0.01,
            "acquisitionFeePct": 0.01,
            "dueDiligenceCosts": 50_000,
            "dayOneCapex": 250_000,
            "unitMix": [
                {"unitType": "1BR", "unitCount": 60, "avgSf": 750, "inPlaceRent": 1_400, "marketRent": 1_600},
                {"unitType": "2BR", "unitCount": 40, "avgSf": 1_050, "inPlaceRent": 1_800, "marketRent": 2_050},
            ],
            "otherIncome": 120_000,
            "vacancyPct": 0.06,
            "creditLossPct": 0.01,
            "realEstateTaxes": 220_000,
            "insurance": 90_000,
            "utilities": 130_000,
            "repairsMaintenance": 110_000,
            "payroll": 160_000,
            "generalAdmin": 40_000,
            "replacementReserves": 25_000,
            "managementFeePct": 0.03,
            "rentGrowthMode": "per_year",
            "rentGrowthPct": 0.03,
            "expenseGrowthMode": "per_year",
            "expenseGrowthPct": 0.025,
            "holdPeriodYears": 5,
            "exitCapRatePct": 0.055,
            "costOfSalePct": 0.02,
            "discountRatePct": 0.10,
            "ltvOrLtc": 0.65,
            "interestRate": 0.0625,
            "ioMonths": 24,
            **_CAPITAL_STACK_COMMON,
        },
    },
    {
        "name": "Riverside Office Center",
        "status": "loi",
        "note": "Two-tenant suburban office. Alpha LLC rolls in 2028 — the renewal "
        "probability drives the deal. LOI countersigned; PSA draft due Friday.",
        "inputs": {
            "dealType": "acquisition",
            "propertyType": "office",
            "address": "900 Riverside Pkwy",
            "market": "Dallas",
            "submarket": "Las Colinas",
            "purchasePrice": 4_200_000,
            "closingCostsPct": 0.01,
            "acquisitionFeePct": 0,
            "dueDiligenceCosts": 25_000,
            "dayOneCapex": 0,
            "commercialLeases": [
                {
                    "tenant": "Alpha LLC", "suiteId": "100", "sf": 6_000,
                    "startDate": "2025-03-01", "endDate": "2028-06-30",
                    "baseRentPsfAnnual": 34, "escalationType": "fixed_pct",
                    "escalationValue": 0.03, "escalationMonths": 12,
                    "recoveryType": "NNN", "recoveryValue": 0, "freeRentMonths": 0,
                },
                {
                    "tenant": "Beta Corp", "suiteId": "200", "sf": 4_000,
                    "startDate": "2024-07-01", "endDate": "2031-12-31",
                    "baseRentPsfAnnual": 31, "escalationType": "fixed_pct",
                    "escalationValue": 0.025, "escalationMonths": 12,
                    "recoveryType": "NNN", "recoveryValue": 0, "freeRentMonths": 0,
                },
            ],
            "renewalProbability": 0.65,
            "downtimeMonths": 5,
            "marketRentPsf": 36,
            "marketRentGrowthPct": 0.03,
            "newTermYears": 5,
            "tiNewPsf": 40,
            "tiRenewalPsf": 10,
            "lcNewPct": 0.06,
            "lcRenewalPct": 0.03,
            "opexLineItems": [
                {"category": "taxes", "amount": 90_000, "basis": "annual_total", "recoverable": "yes"},
                {"category": "insurance", "amount": 30_000, "basis": "annual_total", "recoverable": "yes"},
                {"category": "utilities", "amount": 24_000, "basis": "annual_total", "recoverable": "yes"},
                {"category": "management_fee", "amount": 0.03, "basis": "pct_of_egi", "recoverable": "no"},
                {"category": "other", "amount": 12_000, "basis": "annual_total", "recoverable": "no"},
            ],
            "creditLossPct": 0.01,
            "otherIncome": 0,
            "rentGrowthMode": "per_year",
            "rentGrowthPct": 0.03,
            "expenseGrowthMode": "per_year",
            "expenseGrowthPct": 0.025,
            "holdPeriodYears": 5,
            "exitCapRatePct": 0.07,
            "costOfSalePct": 0.02,
            "discountRatePct": 0.10,
            "ltvOrLtc": 0.6,
            "interestRate": 0.065,
            "ioMonths": 12,
            **_CAPITAL_STACK_COMMON,
        },
    },
    {
        "name": "Harbor Point Shops",
        "status": "screening",
        "note": "Grocery-anchored strip off the broker's OM. Anchor at $18 NNN through 2034; "
        "in-line rents look 10% under market. Screening only — no site visit yet.",
        "inputs": {
            "dealType": "acquisition",
            "propertyType": "retail",
            "address": "2200 Harbor Point Blvd",
            "market": "Miami",
            "submarket": "Coral Way",
            "purchasePrice": 8_200_000,
            "closingCostsPct": 0.015,
            "acquisitionFeePct": 0.01,
            "dueDiligenceCosts": 40_000,
            "dayOneCapex": 150_000,
            "commercialLeases": [
                {
                    "tenant": "Fresh Market Grocery", "suiteId": "A", "sf": 22_000,
                    "startDate": "2019-01-01", "endDate": "2034-12-31",
                    "baseRentPsfAnnual": 18, "escalationType": "fixed_pct",
                    "escalationValue": 0.02, "escalationMonths": 60,
                    "recoveryType": "NNN", "recoveryValue": 0, "freeRentMonths": 0,
                },
                {
                    "tenant": "Harbor Nails & Spa", "suiteId": "B1", "sf": 1_800,
                    "startDate": "2023-04-01", "endDate": "2028-03-31",
                    "baseRentPsfAnnual": 30, "escalationType": "fixed_pct",
                    "escalationValue": 0.03, "escalationMonths": 12,
                    "recoveryType": "NNN", "recoveryValue": 0, "freeRentMonths": 0,
                },
                {
                    "tenant": "Cafe Marina", "suiteId": "B2", "sf": 2_400,
                    "startDate": "2022-09-01", "endDate": "2027-08-31",
                    "baseRentPsfAnnual": 34, "escalationType": "fixed_pct",
                    "escalationValue": 0.03, "escalationMonths": 12,
                    "recoveryType": "NNN", "recoveryValue": 0, "freeRentMonths": 1,
                },
                {
                    "tenant": "Pointe Pharmacy", "suiteId": "C", "sf": 3_600,
                    "startDate": "2021-06-01", "endDate": "2031-05-31",
                    "baseRentPsfAnnual": 27, "escalationType": "fixed_pct",
                    "escalationValue": 0.025, "escalationMonths": 12,
                    "recoveryType": "NNN", "recoveryValue": 0, "freeRentMonths": 0,
                },
            ],
            "renewalProbability": 0.7,
            "downtimeMonths": 6,
            "marketRentPsf": 32,
            "marketRentGrowthPct": 0.025,
            "newTermYears": 5,
            "tiNewPsf": 25,
            "tiRenewalPsf": 5,
            "lcNewPct": 0.06,
            "lcRenewalPct": 0.03,
            "opexLineItems": [
                {"category": "taxes", "amount": 135_000, "basis": "annual_total", "recoverable": "yes"},
                {"category": "insurance", "amount": 70_000, "basis": "annual_total", "recoverable": "yes"},
                {"category": "utilities", "amount": 18_000, "basis": "annual_total", "recoverable": "yes"},
                {"category": "repairs_maintenance", "amount": 45_000, "basis": "annual_total", "recoverable": "yes"},
                {"category": "management_fee", "amount": 0.03, "basis": "pct_of_egi", "recoverable": "no"},
                {"category": "other", "amount": 15_000, "basis": "annual_total", "recoverable": "no"},
            ],
            "creditLossPct": 0.01,
            "otherIncome": 12_000,
            "rentGrowthMode": "per_year",
            "rentGrowthPct": 0.025,
            "expenseGrowthMode": "per_year",
            "expenseGrowthPct": 0.03,
            "holdPeriodYears": 7,
            "exitCapRatePct": 0.065,
            "costOfSalePct": 0.02,
            "discountRatePct": 0.09,
            "ltvOrLtc": 0.6,
            "interestRate": 0.0675,
            "ioMonths": 36,
            **_CAPITAL_STACK_COMMON,
        },
    },
    {
        "name": "Eastside Flats Development",
        "status": "entitlements",
        "note": "220-unit garden deal on the rezoning docket for October. GMP bid came in "
        "4% over budget — contingency covers it. Perm takeout sized at stabilization.",
        "inputs": {
            "dealType": "development",
            "propertyType": "multifamily",
            "address": "1800 E 7th St",
            "market": "Austin",
            "submarket": "East Austin",
            "landCost": 5_500_000,
            "hardCosts": 38_000_000,
            "softCosts": 6_500_000,
            "contingencyPct": 0.05,
            "developerFeePct": 0.04,
            "constructionMonths": 20,
            "leaseUpMonths": 12,
            "grossPotentialRent": 5_280_000,
            "vacancyPct": 0.05,
            "creditLossPct": 0.01,
            "otherIncome": 264_000,
            "realEstateTaxes": 620_000,
            "insurance": 150_000,
            "utilities": 220_000,
            "repairsMaintenance": 180_000,
            "payroll": 330_000,
            "generalAdmin": 110_000,
            "managementFeePct": 0.03,
            "replacementReserves": 55_000,
            "rentGrowthMode": "per_year",
            "rentGrowthPct": 0.03,
            "expenseGrowthMode": "per_year",
            "expenseGrowthPct": 0.025,
            "holdPeriodYears": 7,
            "exitCapRatePct": 0.0525,
            "costOfSalePct": 0.02,
            "discountRatePct": 0.11,
            "ltvOrLtc": 0.6,
            "interestRate": 0.07,
            "ioMonths": 24,
            **_CAPITAL_STACK_COMMON,
        },
    },
    {
        "name": "Gateway Logistics Park",
        "status": "construction",
        "note": "Two-building 420k SF cross-dock spec industrial. Steel up on Building A; "
        "pre-leasing 35% to a 3PL at $7.25 NNN. Vertical complete Q2.",
        "inputs": {
            "dealType": "development",
            "propertyType": "industrial",
            "address": "12500 Gateway Industrial Dr",
            "market": "Dallas",
            "submarket": "South Dallas",
            "landCost": 4_500_000,
            "hardCosts": 25_000_000,
            "softCosts": 3_200_000,
            "contingencyPct": 0.05,
            "developerFeePct": 0.035,
            "constructionMonths": 14,
            "leaseUpMonths": 10,
            # 420k SF at ~$8.10 NNN; the flat opex lines are the landlord's
            # net (non-recovered) share, so NOI reads like a net-lease asset.
            "grossPotentialRent": 3_400_000,
            "vacancyPct": 0.05,
            "creditLossPct": 0.005,
            "otherIncome": 40_000,
            "realEstateTaxes": 120_000,
            "insurance": 40_000,
            "utilities": 15_000,
            "repairsMaintenance": 60_000,
            "payroll": 0,
            "generalAdmin": 35_000,
            "managementFeePct": 0.02,
            "replacementReserves": 42_000,
            "rentGrowthMode": "per_year",
            "rentGrowthPct": 0.035,
            "expenseGrowthMode": "per_year",
            "expenseGrowthPct": 0.025,
            "holdPeriodYears": 5,
            "exitCapRatePct": 0.06,
            "costOfSalePct": 0.015,
            "discountRatePct": 0.11,
            "ltvOrLtc": 0.6,
            "interestRate": 0.0725,
            "ioMonths": 18,
            **_CAPITAL_STACK_COMMON,
        },
    },
]

SALE_COMPS: list[dict] = [
    {"name": "The Grove at Riverside", "address": "2900 S Lakeshore Blvd", "market": "Austin",
     "submarket": "East Riverside", "property_type": "multifamily", "sale_date": "2026-03-14",
     "price": 21_500_000, "units": 118, "sf": 104_000, "cap_rate_pct": 0.0535, "year_built": 1998},
    {"name": "Oltorf Commons", "address": "1600 E Oltorf St", "market": "Austin",
     "submarket": "East Riverside", "property_type": "multifamily", "sale_date": "2025-11-02",
     "price": 16_200_000, "units": 96, "sf": 82_500, "cap_rate_pct": 0.0550, "year_built": 1985},
    {"name": "Pleasant Valley Lofts", "address": "4400 Pleasant Valley Rd", "market": "Austin",
     "submarket": "East Austin", "property_type": "multifamily", "sale_date": "2026-05-20",
     "price": 27_800_000, "units": 140, "sf": 121_000, "cap_rate_pct": 0.0515, "year_built": 2008},
    {"name": "Las Colinas Tower II", "address": "5050 N O'Connor Blvd", "market": "Dallas",
     "submarket": "Las Colinas", "property_type": "office", "sale_date": "2026-01-28",
     "price": 14_400_000, "units": None, "sf": 62_000, "cap_rate_pct": 0.0790, "year_built": 2001},
    {"name": "Inwood Distribution Center", "address": "3300 Inwood Rd", "market": "Dallas",
     "submarket": "South Dallas", "property_type": "industrial", "sale_date": "2026-04-09",
     "price": 33_600_000, "units": None, "sf": 380_000, "cap_rate_pct": 0.0585, "year_built": 2019},
    {"name": "Coral Way Plaza", "address": "3000 Coral Way", "market": "Miami",
     "submarket": "Coral Way", "property_type": "retail", "sale_date": "2025-12-16",
     "price": 11_250_000, "units": None, "sf": 34_000, "cap_rate_pct": 0.0650, "year_built": 1996},
]

RENT_COMPS: list[dict] = [
    {"name": "The Grove at Riverside", "address": "2900 S Lakeshore Blvd", "market": "Austin",
     "submarket": "East Riverside", "property_type": "multifamily", "as_of": "2026-06-01",
     "unit_type": "1BR", "avg_rent": 1_575, "avg_sf": 740, "occupancy_pct": 0.94, "year_built": 1998},
    {"name": "The Grove at Riverside", "address": "2900 S Lakeshore Blvd", "market": "Austin",
     "submarket": "East Riverside", "property_type": "multifamily", "as_of": "2026-06-01",
     "unit_type": "2BR", "avg_rent": 2_010, "avg_sf": 1_040, "occupancy_pct": 0.94, "year_built": 1998},
    {"name": "Oltorf Commons", "address": "1600 E Oltorf St", "market": "Austin",
     "submarket": "East Riverside", "property_type": "multifamily", "as_of": "2026-06-01",
     "unit_type": "1BR", "avg_rent": 1_520, "avg_sf": 720, "occupancy_pct": 0.95, "year_built": 1985},
    {"name": "Pleasant Valley Lofts", "address": "4400 Pleasant Valley Rd", "market": "Austin",
     "submarket": "East Austin", "property_type": "multifamily", "as_of": "2026-06-01",
     "unit_type": "2BR", "avg_rent": 2_140, "avg_sf": 1_080, "occupancy_pct": 0.93, "year_built": 2008},
    {"name": "Trinity Mills Station", "address": "3900 Trinity Mills Rd", "market": "Dallas",
     "submarket": "Carrollton", "property_type": "multifamily", "as_of": "2026-05-01",
     "unit_type": "1BR", "avg_rent": 1_390, "avg_sf": 700, "occupancy_pct": 0.92, "year_built": 2005},
    {"name": "Cedar Springs Place", "address": "4100 Cedar Springs Rd", "market": "Dallas",
     "submarket": "Oak Lawn", "property_type": "multifamily", "as_of": "2026-05-01",
     "unit_type": "2BR", "avg_rent": 2_260, "avg_sf": 1_100, "occupancy_pct": 0.95, "year_built": 2014},
]


# ---------------------------------------------------------------------------


def _validate_stages() -> None:
    for deal in DEALS:
        deal_type = deal["inputs"]["dealType"]
        allowed = DEAL_STAGES_BY_TYPE[deal_type]
        if deal["status"] not in allowed:
            raise SystemExit(
                f"{deal['name']}: status {deal['status']!r} is not a {deal_type} stage {allowed}"
            )


def _validate_inputs() -> None:
    """The engine's own schema check (type + range). Errors would stop the
    compute; warnings mean a value is text or out of the schema's range —
    neither belongs in demo data."""
    for deal in DEALS:
        inputs = dict(deal["inputs"], dealName=deal["name"])
        _, warnings, errors = input_validation.validate_inputs(inputs)
        if errors or warnings:
            raise SystemExit(f"{deal['name']}: input validation failed: {[*errors, *warnings]}")


def _compute_all() -> dict[str, dict]:
    """Run every deal through the native engine; any InsufficientInputsError
    or exception aborts the seed before a row is written."""
    results: dict[str, dict] = {}
    for deal in DEALS:
        inputs = dict(deal["inputs"], dealName=deal["name"])
        computed = proforma.compute(copy.deepcopy(inputs))
        results[deal["name"]] = computed["outputs"]
    return results


def _fmt(value, kind: str) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    if kind == "pct":
        return f"{value * 100:.2f}%"
    if kind == "x":
        return f"{value:.2f}x"
    return f"${value:,.0f}"


def _print_summary(outputs: dict[str, dict]) -> None:
    print(f"{'deal':<30}{'type':<13}{'stage':<15}{'lev IRR':>9}{'EM':>7}{'YoC':>8}{'DSCR':>7}")
    for deal in DEALS:
        o = outputs[deal["name"]]
        print(
            f"{deal['name']:<30}{deal['inputs']['dealType']:<13}{deal['status']:<15}"
            f"{_fmt(o.get('leveredIrr'), 'pct'):>9}{_fmt(o.get('equityMultiple'), 'x'):>7}"
            f"{_fmt(o.get('yieldOnCost'), 'pct'):>8}{_fmt(o.get('minDscr'), 'x'):>7}"
        )


def _existing_seed(db) -> list[Deal]:
    names = [d["name"] for d in DEALS]
    return db.query(Deal).filter(Deal.name.in_(names)).all()


def _remove_previous_seed(db) -> None:
    for deal in _existing_seed(db):
        db.query(DealNote).filter(DealNote.deal_id == deal.id).delete()
        # Scenarios / snapshots / attachments a user may have added to a
        # seeded deal ride along with the deal row via the API's own delete;
        # the seed only ever created the deal + note, so those are what go.
        db.delete(deal)
    db.query(SaleComp).filter(SaleComp.source == SEED_TAG).delete()
    db.query(RentComp).filter(RentComp.source == SEED_TAG).delete()
    db.flush()


def seed(db, outputs: dict[str, dict]) -> None:
    for spec in DEALS:
        inputs = dict(spec["inputs"], dealName=spec["name"])
        deal = Deal(name=spec["name"], inputs={}, status=spec["status"])
        db.add(deal)
        db.flush()
        # Record the inputs the way an autosave would, so the history drawer
        # has a first checkpoint instead of an empty timeline.
        deal_history.record_snapshot(db, deal, inputs, kind="autosave")
        deal.inputs = inputs
        db.add(DealNote(deal_id=deal.id, body=f"{spec['note']} {NOTE_MARKER}"))
    for comp in SALE_COMPS:
        db.add(SaleComp(source=SEED_TAG, notes="Demo comp seeded by scripts/seed_demo.py", **comp))
    for comp in RENT_COMPS:
        db.add(RentComp(source=SEED_TAG, notes="Demo comp seeded by scripts/seed_demo.py", **comp))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--replace", action="store_true", help="delete rows from a previous seed first")
    parser.add_argument("--dry-run", action="store_true", help="compute the deals and print, write nothing")
    args = parser.parse_args(argv)

    _validate_stages()
    _validate_inputs()
    outputs = _compute_all()
    _print_summary(outputs)
    if args.dry_run:
        print("dry run - nothing written.")
        return 0

    prepare_migrations()  # refuse a newer database; back up before migrating
    Base.metadata.create_all(bind=engine)
    run_migrations()
    with SessionLocal() as db:
        existing = _existing_seed(db)
        if existing and not args.replace:
            print(
                f"\nRefusing: {len(existing)} seeded deal(s) already exist "
                f"({', '.join(d.name for d in existing)}). Re-run with --replace.",
                file=sys.stderr,
            )
            return 1
        if existing:
            _remove_previous_seed(db)
        seed(db, outputs)
        db.commit()

    db_path = os.environ.get("CRE_DB_PATH") or str(engine.url).removeprefix("sqlite:///")
    print(
        f"\nSeeded {len(DEALS)} deals, {len(SALE_COMPS)} sale comps, {len(RENT_COMPS)} rent comps, "
        f"{len(DEALS)} notes into {db_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
