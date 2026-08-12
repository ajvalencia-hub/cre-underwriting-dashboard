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


# Dealflow facet prefixes: "acq:foo" / "dev:foo" restrict deal-scoped groups
# (deals, tenants, notes) to one dealflow; comps are global and unaffected.
_TYPE_PREFIXES = {"acq:": "acquisition", "dev:": "development"}


def _deal_type_of(inputs: dict) -> str | None:
    value = (inputs or {}).get("dealType")
    return value if value in ("acquisition", "development") else None


@router.get("")
def search(q: str = "", db: Session = Depends(get_db)):
    q = q.strip().lower()
    type_filter = None
    for prefix, deal_type in _TYPE_PREFIXES.items():
        if q.startswith(prefix):
            type_filter = deal_type
            q = q[len(prefix):].strip()
            break
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
    if type_filter:
        deals = [d for d in deals if _deal_type_of(d.inputs) == type_filter]
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
                "dealType": _deal_type_of(d.inputs),
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
    note_deals = {
        d.id: d
        for d in db.execute(
            select(Deal).where(Deal.id.in_({n.deal_id for n in notes}))
        ).scalars()
    } if notes else {}
    if type_filter:
        notes = [
            n for n in notes
            if n.deal_id in note_deals
            and _deal_type_of(note_deals[n.deal_id].inputs) == type_filter
        ]
    note_items = sorted(
        (
            {
                "id": n.id,
                "title": (n.body[:80] + ("…" if len(n.body) > 80 else "")),
                "subtitle": note_deals[n.deal_id].name if n.deal_id in note_deals else "",
                "dealId": n.deal_id,
                "dealType": _deal_type_of(note_deals[n.deal_id].inputs)
                if n.deal_id in note_deals else None,
            }
            for n in notes
        ),
        key=lambda item: _rank_key(item["title"], q),
    )[:GROUP_LIMIT]

    # Tenants across deals: JSON arrays, Python scan (see module docstring).
    tenant_items = []
    for deal in db.execute(select(Deal)).scalars():
        deal_type = _deal_type_of(deal.inputs)
        if type_filter and deal_type != type_filter:
            continue
        for row in (deal.inputs or {}).get("commercialLeases") or []:
            tenant = row.get("tenant") if isinstance(row, dict) else None
            if isinstance(tenant, str) and q in tenant.lower():
                tenant_items.append(
                    {
                        "id": f"{deal.id}:{tenant}",
                        "title": tenant,
                        "subtitle": deal.name,
                        "dealId": deal.id,
                        "dealType": deal_type,
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
            # Comps are global (no deal type) — a faceted query is explicitly
            # a dealflow search, so they drop out under acq:/dev:.
            ("comps", comp_items if not type_filter else []),
            ("notes", note_items),
        )
        if items
    ]
    return {"query": q, "groups": groups, "typeFilter": type_filter}
