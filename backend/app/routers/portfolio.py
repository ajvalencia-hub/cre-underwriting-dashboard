"""J15: portfolio roll-up endpoint + CSV export."""

import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Deal
from app.services import portfolio

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _deal_dicts(db: Session) -> list[dict]:
    return [
        {"id": d.id, "name": d.name, "status": d.status or "screening", "inputs": d.inputs or {}}
        for d in db.execute(select(Deal)).scalars()
    ]


@router.get("")
def get_portfolio(db: Session = Depends(get_db)):
    return portfolio.build_portfolio(_deal_dicts(db))


@router.get("/export.csv")
def export_portfolio_csv(db: Session = Depends(get_db)):
    """One row per computed deal + a totals footer; the excluded deals are
    appended so the CSV is honest about what the blend left out."""
    roll = portfolio.build_portfolio(_deal_dicts(db))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Deal", "Status", "Market", "Asset class", "Equity",
                     "Levered IRR", "Equity multiple"])
    for d in roll["deals"]:
        writer.writerow([
            d["name"], d["status"], d["market"], d["assetClass"],
            round(d["equity"]),
            "" if d["leveredIrr"] is None else round(d["leveredIrr"], 6),
            "" if d["equityMultiple"] is None else round(d["equityMultiple"], 4),
        ])
    writer.writerow([])
    writer.writerow(["PORTFOLIO", "", "", "", round(roll["totals"]["equity"]),
                     "" if roll["blendedLeveredIrr"] is None else round(roll["blendedLeveredIrr"], 6),
                     "" if roll["blendedEquityMultiple"] is None else round(roll["blendedEquityMultiple"], 4)])
    for d in roll["excluded"]:
        writer.writerow([d["name"], "EXCLUDED", d["reason"], "", "", "", ""])

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="portfolio.csv"'},
    )
