"""Comps CRUD + CSV import (H5). Import is two-phase: no mapping -> preview
only (nothing written); mapping submitted -> rows inserted. Comps are global
(not deal-scoped) and filtered by market at query time."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import RentComp, SaleComp
from app.services import comps as comps_service

router = APIRouter(prefix="/api/comps", tags=["comps"])

MAX_CSV_BYTES = 5 * 1024 * 1024
PREVIEW_ROWS = 8

_KIND_MODELS = {"sale": SaleComp, "rent": RentComp}

# JSON field <-> column attribute per kind (shared by create/update/serialize)
_SALE_ATTRS = {
    "name": "name", "address": "address", "market": "market", "submarket": "submarket",
    "propertyType": "property_type", "saleDate": "sale_date", "price": "price",
    "units": "units", "sf": "sf", "capRatePct": "cap_rate_pct",
    "yearBuilt": "year_built", "source": "source", "notes": "notes",
}
_RENT_ATTRS = {
    "name": "name", "address": "address", "market": "market", "submarket": "submarket",
    "propertyType": "property_type", "asOf": "as_of", "unitType": "unit_type",
    "avgRent": "avg_rent", "avgSf": "avg_sf", "occupancyPct": "occupancy_pct",
    "yearBuilt": "year_built", "source": "source", "notes": "notes",
}
_KIND_ATTRS = {"sale": _SALE_ATTRS, "rent": _RENT_ATTRS}


class CompIn(BaseModel):
    """Permissive comp payload — the per-kind attribute map picks what applies."""

    name: str
    address: str = ""
    market: str = ""
    submarket: str = ""
    propertyType: str = ""
    saleDate: str = ""
    asOf: str = ""
    unitType: str = ""
    price: float | None = None
    units: float | None = None
    sf: float | None = None
    capRatePct: float | None = None
    avgRent: float | None = None
    avgSf: float | None = None
    occupancyPct: float | None = None
    yearBuilt: float | None = None
    source: str = "manual"
    notes: str = ""


def _model_for(kind: str):
    model = _KIND_MODELS.get(kind)
    if model is None:
        raise HTTPException(400, f"Unknown comp kind '{kind}' — use 'sale' or 'rent'.")
    return model


def _to_out(comp, kind: str) -> dict:
    out = {"id": comp.id, "kind": kind, "createdAt": comp.created_at}
    for json_field, attr in _KIND_ATTRS[kind].items():
        out[json_field] = getattr(comp, attr)
    if kind == "sale":
        out["pricePerUnit"] = comp.price / comp.units if comp.price and comp.units else None
        out["pricePerSf"] = comp.price / comp.sf if comp.price and comp.sf else None
    return out


def _apply(comp, payload: dict, kind: str):
    for json_field, attr in _KIND_ATTRS[kind].items():
        if json_field in payload and payload[json_field] is not None:
            setattr(comp, attr, payload[json_field])


class ImportRequest(BaseModel):
    kind: str
    csvText: str
    mapping: dict[str, str] | None = Field(
        default=None,
        description="{fieldId: csvHeader}. Omit for a preview — nothing is written.",
    )
    defaultMarket: str = ""
    # I11: row indexes (0-based over the parsed rows) the user chose to skip
    # after seeing the duplicate flags in the preview.
    skipRows: list[int] = []


# NOTE: static /import routes must be declared before the /{kind} routes or
# FastAPI matches them as kind="import".
@router.post("/import")
def import_csv(payload: ImportRequest, db: Session = Depends(get_db)):
    _model_for(payload.kind)  # validates kind
    if len(payload.csvText.encode("utf-8", errors="ignore")) > MAX_CSV_BYTES:
        raise HTTPException(413, "CSV exceeds the 5 MB import limit.")
    headers, rows = comps_service.parse_csv_text(payload.csvText)
    if not headers or not rows:
        raise HTTPException(400, "Could not parse any rows from the CSV.")

    if payload.mapping is None:
        # I11: duplicate detection rides the preview, coerced through the
        # SUGGESTED mapping (best effort — the user hasn't confirmed one yet).
        suggested = comps_service.suggest_mapping(headers, payload.kind)
        candidates = [
            comps_service.coerce_row(row, suggested, payload.kind)[0] or {}
            for row in rows
        ]
        return {
            "phase": "preview",
            "columns": headers,
            "suggestedMapping": suggested,
            "rowCount": len(rows),
            "sampleRows": rows[:PREVIEW_ROWS],
            "duplicates": comps_service.find_duplicates(db, payload.kind, candidates),
            "imported": 0,
            "warnings": [],
        }

    unknown = [h for h in payload.mapping.values() if h not in headers]
    if unknown:
        raise HTTPException(400, f"Mapping references missing column(s): {', '.join(unknown)}")

    model = _KIND_MODELS[payload.kind]
    warnings: list[str] = []
    imported = 0
    skip = set(payload.skipRows)
    skipped_duplicates = 0
    for index, row in enumerate(rows):
        if index in skip:
            skipped_duplicates += 1
            continue
        comp_fields, warning = comps_service.coerce_row(row, payload.mapping, payload.kind)
        if warning:
            warnings.append(warning)
        if comp_fields is None:
            continue
        comp_fields.setdefault("market", payload.defaultMarket)
        comp = model(name=comp_fields["name"], source="yardi_csv")
        _apply(comp, comp_fields, payload.kind)
        comp.source = "yardi_csv"
        db.add(comp)
        imported += 1
    db.commit()
    if skipped_duplicates:
        warnings.append(f"{skipped_duplicates} row(s) skipped as duplicates (kept the existing comps).")
    return {"phase": "imported", "imported": imported, "warnings": warnings}


@router.get("/{kind}/map")
def comps_map(kind: str, market: str = "", db: Session = Depends(get_db)):
    """I11: geocoded points for the filtered comp set. Comps whose address
    can't be geocoded are SKIPPED with a warning naming them — a map with
    silently missing pins would misrepresent the set."""
    from app.services.data_sources import geocode
    from app.services.data_sources.source_cache import cached_fetch

    model = _model_for(kind)
    query = select(model).order_by(model.created_at.desc())
    if market.strip():
        query = query.where(model.market.ilike(f"%{market.strip()}%"))
    points: list[dict] = []
    warnings: list[str] = []
    for comp in db.execute(query).scalars():
        if not comp.address:
            warnings.append(f"{comp.name}: no address — not mapped.")
            continue
        try:
            location = cached_fetch(
                f"geo_comp_{comp.address.strip().lower()}",
                lambda c=comp: {
                    **geocode.geocode(c.market, "", c.address),
                    "dataSource": "geocode",
                },
            )
        except Exception as exc:  # noqa: BLE001 — one bad geocode must not kill the map
            warnings.append(f"{comp.name}: geocoding failed ({exc}).")
            continue
        if not location.get("resolved") or location.get("lat") is None:
            warnings.append(f"{comp.name}: address didn't geocode — not mapped.")
            continue
        points.append({
            "id": comp.id,
            "name": comp.name,
            "lat": location["lat"],
            "lon": location["lon"],
        })
    return {"points": points, "warnings": warnings}


@router.post("/import/file")
async def import_csv_file(
    kind: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Multipart convenience wrapper: reads the file and returns the same
    preview payload as /import without a mapping, plus the decoded text so
    the client can re-submit /import with a mapping."""
    raw = await file.read()
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(413, "CSV exceeds the 5 MB import limit.")
    text = raw.decode("utf-8-sig", errors="replace")
    preview = import_csv(ImportRequest(kind=kind, csvText=text), db)
    return {**preview, "csvText": text}


@router.get("/{kind}")
def list_comps(kind: str, market: str = "", db: Session = Depends(get_db)):
    model = _model_for(kind)
    query = select(model).order_by(model.created_at.desc())
    if market.strip():
        query = query.where(model.market.ilike(f"%{market.strip()}%"))
    return [_to_out(c, kind) for c in db.execute(query).scalars()]


@router.post("/{kind}")
def create_comp(kind: str, payload: CompIn, db: Session = Depends(get_db)):
    model = _model_for(kind)
    if not payload.name.strip():
        raise HTTPException(400, "Comp name cannot be empty")
    comp = model(name=payload.name.strip())
    _apply(comp, payload.model_dump(), kind)
    db.add(comp)
    db.commit()
    db.refresh(comp)
    return _to_out(comp, kind)


@router.put("/{kind}/{comp_id}")
def update_comp(kind: str, comp_id: str, payload: CompIn, db: Session = Depends(get_db)):
    model = _model_for(kind)
    comp = db.get(model, comp_id)
    if comp is None:
        raise HTTPException(404, "Comp not found")
    # Partial-update semantics: only fields present in the body are applied
    # (same convention as the deals router).
    _apply(comp, payload.model_dump(exclude_unset=True), kind)
    db.commit()
    db.refresh(comp)
    return _to_out(comp, kind)


@router.delete("/{kind}/{comp_id}")
def delete_comp(kind: str, comp_id: str, db: Session = Depends(get_db)):
    model = _model_for(kind)
    comp = db.get(model, comp_id)
    if comp is None:
        raise HTTPException(404, "Comp not found")
    db.delete(comp)
    db.commit()
    return {"deleted": True}
