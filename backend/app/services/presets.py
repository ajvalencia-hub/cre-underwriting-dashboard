"""Assumption presets (H8): seed presets + the capturable field whitelist.

Presets hold RATE/TERM assumptions only — never deal-specific dollars
(purchase price, GPR, taxes) or property facts (unit mix, leases), so a
preset is portable across deals. Applying a preset is always user-confirmed
through a preview diff on the client; nothing here mutates deals.

Seeding runs at startup only when the table is empty, so a user who edits
or deletes the seeds keeps their changes.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AssumptionPreset

# Field ids a preset may carry (subset of the input schema). The client
# offers exactly these at capture time; apply drops anything else.
PRESET_FIELD_IDS = [
    "vacancyPct",
    "creditLossPct",
    "rentGrowthMode",
    "rentGrowthPct",
    "expenseGrowthMode",
    "expenseGrowthPct",
    "managementFeePct",
    "holdPeriodYears",
    "exitCapRatePct",
    "costOfSalePct",
    "discountRatePct",
    "irrConvention",
    "ltvOrLtc",
    "interestRate",
    "amortYears",
    "loanTermYears",
    "ioMonths",
    "originationFeePct",
    "lpSplitPct",
    "gpSplitPct",
    "preferredReturnPct",
    "assessmentRatio",
    "reassessedTaxGrowthPct",
]

SEED_PRESETS = [
    {
        "name": "Conservative",
        "description": "Defensive screen: heavier vacancy, slower rent growth, wider exit cap.",
        "values": {
            "vacancyPct": 0.07,
            "creditLossPct": 0.01,
            "rentGrowthMode": "per_year",
            "rentGrowthPct": 0.02,
            "expenseGrowthMode": "per_year",
            "expenseGrowthPct": 0.03,
            "exitCapRatePct": 0.065,
            "costOfSalePct": 0.02,
            "holdPeriodYears": 5,
            "discountRatePct": 0.10,
        },
    },
    {
        "name": "Base Case",
        "description": "Middle-of-the-road institutional assumptions.",
        "values": {
            "vacancyPct": 0.05,
            "creditLossPct": 0.005,
            "rentGrowthMode": "per_year",
            "rentGrowthPct": 0.03,
            "expenseGrowthMode": "per_year",
            "expenseGrowthPct": 0.025,
            "exitCapRatePct": 0.06,
            "costOfSalePct": 0.02,
            "holdPeriodYears": 5,
            "discountRatePct": 0.10,
        },
    },
    {
        "name": "Aggressive Growth",
        "description": "Best-case screen: tight vacancy, strong rent growth, cap compression.",
        "values": {
            "vacancyPct": 0.04,
            "creditLossPct": 0.005,
            "rentGrowthMode": "per_year",
            "rentGrowthPct": 0.04,
            "expenseGrowthMode": "per_year",
            "expenseGrowthPct": 0.025,
            "exitCapRatePct": 0.055,
            "costOfSalePct": 0.015,
            "holdPeriodYears": 5,
            "discountRatePct": 0.09,
        },
    },
]


def filter_preset_values(values: dict) -> dict:
    """Keep only whitelisted assumption fields — a preset must never smuggle
    in deal-specific dollars or tables."""
    return {k: v for k, v in values.items() if k in PRESET_FIELD_IDS and v is not None}


def seed_presets(db: Session) -> int:
    """Insert the seed presets when the table is empty. Returns the number
    inserted (0 when the table already has rows)."""
    existing = db.execute(select(AssumptionPreset.id).limit(1)).first()
    if existing is not None:
        return 0
    for seed in SEED_PRESETS:
        db.add(
            AssumptionPreset(
                name=seed["name"],
                description=seed["description"],
                values=seed["values"],
                source="seed",
            )
        )
    db.commit()
    return len(SEED_PRESETS)
