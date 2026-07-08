"""J13: global search for the Cmd+K palette.

SQLite LIKE over indexed columns (deals.name, sale_comps.address/market —
indexes added by migration) plus json_extract for the deal blob's
address/market. Tenants are matched by a Python scan over deal lease rolls —
tenant names live inside JSON arrays where no useful index exists, and the
deal count in a local tool is small (documented trade-off).

Ranking: within each group, prefix matches rank above substring matches,
then alphabetical; groups cap at 8 items each.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Deal, DealNote, SaleComp

router = APIRouter(prefix="/api/search", tags=["search"])

GROUP_LIMIT = 8


def _rank_key(text: str, q: str) -> tuple[int, str]:
    lowered = (text or "").lower()
    return (0 if lowered.startswith(q) else 1, lowered)


@router.get("")
def search(q: str = "", db: Session = Depends(get_db)):
    q = q.strip().lower()
    if len(q) < 2:
        return {"query": q, "groups": []}
    like = f"%{q}%"

    deals = db.execute(
        select(Deal).where(
            or_(
                func.lower(Deal.name).like(like),
                func.lower(func.json_extract(Deal.inputs, "$.address")).like(like),
                func.lower(func.json_extract(Deal.inputs, "$.market")).like(like),
            )
        )
    ).scalars().all()
    deal_items = sorted(
        (
            {
                "id": d.id,
                "title": d.name,
                "subtitle": " · ".join(
                    str(v) for v in (d.inputs.get("address"), d.inputs.get("market"))
                    if isinstance(v, str) and v
                ),
                "dealId": d.id,
            }
            for d in deals
        ),
        key=lambda item: _rank_key(item["title"], q),
    )[:GROUP_LIMIT]

    comps = db.execute(
        select(SaleComp).where(
            or_(
                func.lower(SaleComp.name).like(like),
                func.lower(SaleComp.address).like(like),
                func.lower(SaleComp.market).like(like),
            )
        )
    ).scalars().all()
    comp_items = sorted(
        (
            {
                "id": c.id,
                "title": c.name,
                "subtitle": " · ".join(v for v in (c.address, c.market) if v),
            }
            for c in comps
        ),
        key=lambda item: _rank_key(item["title"], q),
    )[:GROUP_LIMIT]

    notes = db.execute(
        select(DealNote).where(func.lower(DealNote.body).like(like))
    ).scalars().all()
    deal_names = {
        d.id: d.name
        for d in db.execute(
            select(Deal).where(Deal.id.in_({n.deal_id for n in notes}))
        ).scalars()
    } if notes else {}
    note_items = sorted(
        (
            {
                "id": n.id,
                "title": (n.body[:80] + ("…" if len(n.body) > 80 else "")),
                "subtitle": deal_names.get(n.deal_id, ""),
                "dealId": n.deal_id,
            }
            for n in notes
        ),
        key=lambda item: _rank_key(item["title"], q),
    )[:GROUP_LIMIT]

    # Tenants across deals: JSON arrays, Python scan (see module docstring).
    tenant_items = []
    for deal in db.execute(select(Deal)).scalars():
        for row in (deal.inputs or {}).get("commercialLeases") or []:
            tenant = row.get("tenant") if isinstance(row, dict) else None
            if isinstance(tenant, str) and q in tenant.lower():
                tenant_items.append(
                    {
                        "id": f"{deal.id}:{tenant}",
                        "title": tenant,
                        "subtitle": deal.name,
                        "dealId": deal.id,
                    }
                )
    tenant_items = sorted(
        tenant_items, key=lambda item: _rank_key(item["title"], q)
    )[:GROUP_LIMIT]

    groups = [
        {"kind": kind, "items": items}
        for kind, items in (
            ("deals", deal_items),
            ("tenants", tenant_items),
            ("comps", comp_items),
            ("notes", note_items),
        )
        if items
    ]
    return {"query": q, "groups": groups}
