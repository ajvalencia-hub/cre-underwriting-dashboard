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
from app.services.sql_like import LIKE_ESCAPE, contains

router = APIRouter(prefix="/api/search", tags=["search"])

GROUP_LIMIT = 8


def _rank_key(text: str | None, q: str) -> tuple[int, str]:
    lowered = (text or "").lower()
    return (0 if lowered.startswith(q) else 1, lowered)


# Facet prefixes restrict the deal-scoped groups (deals, tenants, notes);
# comps are global and unaffected. "acq:foo" / "dev:foo" pick one dealflow;
# "tag:core foo" keeps only deals carrying the tag (case-insensitive). The
# prefixes are parsed in a loop so both can appear ("acq:tag:core foo").
_TYPE_PREFIXES = {"acq:": "acquisition", "dev:": "development"}
_TAG_PREFIX = "tag:"


def _deal_type_of(inputs: dict) -> str | None:
    value = (inputs or {}).get("dealType")
    return value if value in ("acquisition", "development") else None


def _tags_of(deal: Deal) -> list[str]:
    return [t for t in (deal.tags or []) if isinstance(t, str)]


def _parse_facets(q: str) -> tuple[str, str | None, str | None]:
    """Returns (remaining query, type filter, tag filter)."""
    type_filter: str | None = None
    tag_filter: str | None = None
    while True:
        matched = False
        for prefix, facet_type in _TYPE_PREFIXES.items():
            if q.startswith(prefix):
                type_filter = facet_type
                q = q[len(prefix):].strip()
                matched = True
                break
        if q.startswith(_TAG_PREFIX):
            rest = q[len(_TAG_PREFIX):]
            token, _, remainder = rest.partition(" ")
            if token:
                tag_filter = token
            q = remainder.strip()
            matched = True
        if not matched:
            return q, type_filter, tag_filter


def _deal_passes(deal: Deal, type_filter: str | None, tag_filter: str | None) -> bool:
    if type_filter and _deal_type_of(deal.inputs) != type_filter:
        return False
    if tag_filter and tag_filter not in {t.casefold() for t in _tags_of(deal)}:
        return False
    return True


@router.get("")
def search(q: str = "", db: Session = Depends(get_db)):
    q, type_filter, tag_filter = _parse_facets(q.strip().lower())
    if len(q) < 2:
        return {"query": q, "groups": []}
    like = contains(q)  # literal match — `_`/`%` in the query are not wildcards

    deals = db.execute(
        select(Deal).where(
            Deal.archived_at.is_(None),
            or_(
                func.lower(Deal.name).like(like, escape=LIKE_ESCAPE),
                func.lower(func.json_extract(Deal.inputs, "$.address")).like(like, escape=LIKE_ESCAPE),
                func.lower(func.json_extract(Deal.inputs, "$.market")).like(like, escape=LIKE_ESCAPE),
            )
        )
    ).scalars().all()
    deals = [d for d in deals if _deal_passes(d, type_filter, tag_filter)]
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
                "tags": _tags_of(d),
            }
            for d in deals
        ),
        key=lambda item: _rank_key(str(item["title"]), q),
    )[:GROUP_LIMIT]

    comps = db.execute(
        select(SaleComp).where(
            or_(
                func.lower(SaleComp.name).like(like, escape=LIKE_ESCAPE),
                func.lower(SaleComp.address).like(like, escape=LIKE_ESCAPE),
                func.lower(SaleComp.market).like(like, escape=LIKE_ESCAPE),
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
        select(DealNote).where(func.lower(DealNote.body).like(like, escape=LIKE_ESCAPE))
    ).scalars().all()
    note_deals = {
        d.id: d
        for d in db.execute(
            select(Deal).where(Deal.id.in_({n.deal_id for n in notes}))
        ).scalars()
    } if notes else {}
    if type_filter or tag_filter:
        notes = [
            n for n in notes
            if n.deal_id in note_deals
            and _deal_passes(note_deals[n.deal_id], type_filter, tag_filter)
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
    tenant_items: list[dict] = []
    for deal in db.execute(select(Deal).where(Deal.archived_at.is_(None))).scalars():
        deal_type = _deal_type_of(deal.inputs)
        if not _deal_passes(deal, type_filter, tag_filter):
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
            # Comps are global (no deal type, no tags) — a faceted query is
            # explicitly a deal search, so they drop out under acq:/dev:/tag:.
            ("comps", comp_items if not (type_filter or tag_filter) else []),
            ("notes", note_items),
        )
        if items
    ]
    return {
        "query": q,
        "groups": groups,
        "typeFilter": type_filter,
        "tagFilter": tag_filter,
    }
