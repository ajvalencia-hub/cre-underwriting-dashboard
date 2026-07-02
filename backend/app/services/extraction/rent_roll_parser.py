"""Deterministic rent-roll parsing: normalize varied column headers to a
canonical schema, parse each row, infer occupancy status, and aggregate into
either a multifamily unit-mix table or a commercial tenant-by-tenant roll —
matching the shapes the app's existing input schema already expects
(unitMix / rentRoll table fields).

This is the "clean structured table" path — it runs first, before any LLM
call, and only falls back to the LLM (in llm_extraction.py) when too few
rows come out matched (see extraction_service.py).
"""

import re
from datetime import date, datetime

from app.services.extraction.excel_extractor import parse_numeric

_FIELD_ALIASES: dict[str, list[str]] = {
    "unit": ["unit", "unit no", "unit number", "suite", "suite no", "suite number", "space"],
    "tenant": ["tenant", "tenant name", "resident", "lessee", "occupant"],
    "sf": ["sf", "square feet", "square footage", "size", "unit sf", "rsf", "sq ft"],
    "unitType": ["unit type", "type", "floor plan", "plan", "bed/bath", "beds/baths", "bd/ba"],
    "inPlaceRentMonthly": [
        "rent", "monthly rent", "in-place rent", "in place rent", "current rent", "actual rent",
    ],
    "marketRentMonthly": ["market rent", "asking rent", "pro forma rent", "proforma rent"],
    "leaseType": ["lease type", "lease structure"],
    "leaseStart": ["lease start", "commencement", "move-in", "move in", "start date", "lease from"],
    "leaseEnd": ["lease end", "lease expiration", "expiration", "expiry", "end date", "lease to"],
    "camRecoveries": ["cam", "cam recoveries", "recoveries", "nnn", "cam/nnn"],
    "status": ["status", "occupancy status", "occupied/vacant"],
}


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _match_headers(headers: list[str]) -> dict[str, int]:
    """canonical field -> column index, best-effort, first match wins."""
    normalized = [_normalize(h) for h in headers]
    matched: dict[str, int] = {}
    for field, aliases in _FIELD_ALIASES.items():
        norm_aliases = [_normalize(a) for a in aliases]
        # exact match first
        for i, h in enumerate(normalized):
            if h in norm_aliases:
                matched[field] = i
                break
        if field in matched:
            continue
        # substring match fallback
        for i, h in enumerate(normalized):
            if h and any(a in h or h in a for a in norm_aliases if len(a) >= 3):
                matched[field] = i
                break
    return matched


def _parse_date(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %Y", "%B %Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _infer_status(tenant, rent_monthly, explicit_status: str | None) -> str:
    if explicit_status:
        norm = explicit_status.strip().lower()
        if "vacant" in norm:
            return "vacant"
        if "occupied" in norm or "leased" in norm:
            return "occupied"
    tenant_blank = tenant is None or str(tenant).strip() == ""
    rent_zero = rent_monthly in (None, 0, 0.0)
    if tenant_blank and rent_zero:
        return "vacant"
    if not tenant_blank:
        return "occupied"
    return "unknown"


def parse_rows(headers: list[str], data_rows: list[list], source_doc: str, sheet: str) -> dict:
    """Returns {"rows": [RentRollRow,...], "matchedFields": [...], "confidence": float}."""
    field_cols = _match_headers(headers)
    parsed_rows = []

    for row_idx, row in enumerate(data_rows):

        def get(field):
            col = field_cols.get(field)
            return row[col] if col is not None and col < len(row) else None

        unit = get("unit")
        tenant = get("tenant")
        sf = parse_numeric(get("sf"))
        in_place = parse_numeric(get("inPlaceRentMonthly"))
        market = parse_numeric(get("marketRentMonthly"))

        # A row with neither a unit id nor a tenant nor SF is almost certainly
        # a blank/subtotal row, not real rent-roll data — skip it.
        if unit is None and tenant is None and sf is None:
            continue

        status = _infer_status(tenant, in_place, get("status"))

        parsed_rows.append(
            {
                "unit": str(unit).strip() if unit is not None else None,
                "tenant": str(tenant).strip() if tenant is not None else None,
                "sf": sf,
                "unitType": str(get("unitType")).strip() if get("unitType") is not None else None,
                "status": status,
                "leaseType": str(get("leaseType")).strip() if get("leaseType") is not None else None,
                "inPlaceRentMonthly": in_place,
                "marketRentMonthly": market,
                "leaseStart": _parse_date(get("leaseStart")),
                "leaseEnd": _parse_date(get("leaseEnd")),
                "camRecoveries": parse_numeric(get("camRecoveries")),
                "sourceRef": {"doc": source_doc, "sheet": sheet, "row": row_idx, "page": None, "cell": None},
            }
        )

    # confidence: how many of the load-bearing fields (unit/tenant, sf, rent)
    # we actually found columns for — a proxy for "did header matching work".
    load_bearing = ["unit", "sf", "inPlaceRentMonthly"]
    confidence = sum(1 for f in load_bearing if f in field_cols) / len(load_bearing)

    return {"rows": parsed_rows, "matchedFields": list(field_cols.keys()), "confidence": round(confidence, 2)}


def aggregate_multifamily(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        key = r["unitType"] or "Unspecified"
        groups.setdefault(key, []).append(r)

    unit_mix = []
    for unit_type, group in groups.items():
        sfs = [r["sf"] for r in group if r["sf"] is not None]
        in_place = [r["inPlaceRentMonthly"] for r in group if r["status"] == "occupied" and r["inPlaceRentMonthly"]]
        market = [r["marketRentMonthly"] for r in group if r["marketRentMonthly"]]
        unit_mix.append(
            {
                "unitType": unit_type,
                "unitCount": len(group),
                "avgSf": round(sum(sfs) / len(sfs)) if sfs else None,
                "inPlaceRent": round(sum(in_place) / len(in_place)) if in_place else None,
                "marketRent": round(sum(market) / len(market)) if market else None,
            }
        )

    return {"unitMix": unit_mix, **_occupancy_summary(rows)}


def aggregate_commercial(rows: list[dict], as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    weighted_years, walt_sf = 0.0, 0.0
    for r in rows:
        if r["status"] != "occupied" or not r["sf"] or not r["leaseEnd"]:
            continue
        try:
            end = datetime.strptime(r["leaseEnd"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if end <= as_of:
            continue
        years_remaining = (end - as_of).days / 365.25
        weighted_years += years_remaining * r["sf"]
        walt_sf += r["sf"]

    return {
        "rentRoll": rows,
        "waltYears": round(weighted_years / walt_sf, 2) if walt_sf else None,
        **_occupancy_summary(rows),
    }


def _occupancy_summary(rows: list[dict]) -> dict:
    total_units = len(rows)
    occupied = [r for r in rows if r["status"] == "occupied"]
    total_sf = sum(r["sf"] for r in rows if r["sf"])
    occupied_sf = sum(r["sf"] for r in occupied if r["sf"])

    in_place_total = sum(r["inPlaceRentMonthly"] for r in occupied if r["inPlaceRentMonthly"])
    market_total = sum(r["marketRentMonthly"] for r in occupied if r["marketRentMonthly"])

    return {
        "totalUnits": total_units,
        "occupiedUnits": len(occupied),
        "occupancyPctByUnit": round(len(occupied) / total_units, 4) if total_units else None,
        "occupancyPctBySf": round(occupied_sf / total_sf, 4) if total_sf else None,
        "grossPotentialRentMonthly": round(
            sum(r["marketRentMonthly"] or r["inPlaceRentMonthly"] or 0 for r in rows), 2
        ),
        "lossToLeasePct": round((market_total - in_place_total) / market_total, 4) if market_total else None,
    }
