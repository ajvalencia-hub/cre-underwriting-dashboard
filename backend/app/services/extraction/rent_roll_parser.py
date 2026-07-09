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

# Mid-table subtotal/summary rows ("Total 1BR/1BA", "Subtotal", "Totals:",
# "Average:") must never become phantom units — they inflate unit counts and
# GPR, and (per the boundary detection below) mark candidate table endings.
_SUBTOTAL_ROW_RE = re.compile(r"^\s*(sub\s*)?totals?\b|^\s*averages?\b", re.IGNORECASE)

# Vacancy marker embedded in the unit label itself ("Unit 7 (Furnished) -
# Vacant"), as distinct from a literal "VACANT" tenant name — brokers often
# leave a boilerplate tenant-type label ("Residential") in the tenant column
# for vacant units, which would otherwise read as occupied.
_VACANT_LABEL_RE = re.compile(r"\bvacant\b", re.IGNORECASE)

_FIELD_ALIASES: dict[str, list[str]] = {
    "unit": ["unit", "unit no", "unit number", "suite", "suite no", "suite number", "space"],
    "tenant": ["tenant", "tenant name", "resident", "lessee", "occupant"],
    "sf": [
        "sf", "square feet", "square footage", "size", "unit sf", "rsf", "sq ft",
        "sf leased", "leased sf", "rba",  # CoStar vocabulary (I9)
    ],
    "unitType": ["unit type", "type", "floor plan", "plan", "bed/bath", "beds/baths", "bd/ba"],
    "inPlaceRentMonthly": [
        "rent", "monthly rent", "in-place rent", "in place rent", "current rent", "actual rent",
    ],
    "marketRentMonthly": ["market rent", "asking rent", "pro forma rent", "proforma rent"],
    # I9: CoStar-style annual figures — converted, never guessed. NOTE: no
    # bare "rent/sf" alias — it normalizes to "rentsf" and would swallow
    # every plain "SF" header through the substring fallback.
    "annualRent": ["annual rent", "total annual rent", "annual base rent", "rent/year"],
    "rentPsfAnnual": [
        "rent/sf/yr", "rent per sf", "rent psf", "annual rent psf", "base rent/sf",
    ],
    "floor": ["floor", "level"],
    "leaseType": ["lease type", "lease structure"],
    "leaseStart": ["lease start", "commencement", "move-in", "move in", "start date", "lease from",
                   "lease commencement"],
    "leaseEnd": ["lease end", "lease expiration", "expiration", "expiry", "end date", "lease to"],
    "camRecoveries": ["cam", "cam recoveries", "recoveries", "nnn", "cam/nnn"],
    "status": ["status", "occupancy status", "occupied/vacant"],
}

# A "Tenant ID"/"Resident ID" column is an identifier, never the tenant's
# actual name — letting it substring-match the "tenant" field (ahead of a
# later "Resident Name" column, since the fallback pass scans left-to-right
# and claims the first hit) previously broke vacancy detection, which
# depends on seeing the literal "VACANT" marker some rent rolls put in the
# name column specifically, not in an ID column. Scoped to "tenant" only —
# an "ID" column is exactly what should satisfy a real identifier field.
_FIELD_SUBSTRING_EXCLUSIONS: dict[str, re.Pattern] = {
    "tenant": re.compile(r"\bid\b", re.IGNORECASE),
}

_MTM_RE = re.compile(r"^\s*(mtm|m-t-m|month\s*-?\s*to\s*-?\s*month)\s*$", re.IGNORECASE)
_MONTH_YEAR_FORMATS = ("%b %Y", "%B %Y", "%m/%Y", "%m-%Y")


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _match_headers(headers: list[str]) -> dict[str, int]:
    """canonical field -> column index, best-effort.

    Two passes with COLUMN RESERVATION (I9): every field tries an exact
    alias match first — exact claims beat any substring claim, so 'Annual
    Rent' belongs to annualRent even though the generic 'rent' alias would
    substring-match it. The substring fallback then fills unmatched fields
    from unclaimed columns only, and the header-inside-alias direction
    requires len(header) >= 4 so a bare 'SF' column can't be swallowed by a
    longer alias that happens to contain 'sf'."""
    normalized = [_normalize(h) for h in headers]
    matched: dict[str, int] = {}
    claimed: set[int] = set()

    for field, aliases in _FIELD_ALIASES.items():
        norm_aliases = [_normalize(a) for a in aliases]
        for i, h in enumerate(normalized):
            if i not in claimed and h in norm_aliases:
                matched[field] = i
                claimed.add(i)
                break

    for field, aliases in _FIELD_ALIASES.items():
        if field in matched:
            continue
        norm_aliases = [_normalize(a) for a in aliases]
        exclusion = _FIELD_SUBSTRING_EXCLUSIONS.get(field)
        for i, h in enumerate(normalized):
            if i in claimed or not h:
                continue
            if exclusion is not None and exclusion.search(headers[i]):
                continue
            if any(
                (len(a) >= 3 and a in h) or (len(h) >= 4 and h in a)
                for a in norm_aliases
            ):
                matched[field] = i
                claimed.add(i)
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


def _parse_end_date(value) -> tuple[str | None, bool, bool]:
    """Lease-END dates (I9): returns (iso, is_mtm, was_month_year).
    Month-year-only values ('Jun 2027', '06/2028') read as the LAST day of
    that month — a lease expiring 'Jun 2027' runs through June. MTM terms
    parse as no end date (the engine treats them as running through the
    analysis) and are flagged so the proposal can warn."""
    if value is None or value == "":
        return None, False, False
    text = str(value).strip()
    if _MTM_RE.match(text):
        return None, True, False
    for fmt in _MONTH_YEAR_FORMATS:
        try:
            first = datetime.strptime(text, fmt)
            import calendar as _calendar

            last_day = _calendar.monthrange(first.year, first.month)[1]
            return first.replace(day=last_day).strftime("%Y-%m-%d"), False, True
        except ValueError:
            continue
    return _parse_date(value), False, False


def _infer_status(tenant, rent_monthly, explicit_status: str | None, unit=None) -> str:
    if explicit_status:
        norm = explicit_status.strip().lower()
        if "vacant" in norm:
            return "vacant"
        if "occupied" in norm or "leased" in norm:
            return "occupied"
    # The unit label itself is a common vacancy marker ("Unit 7 (Furnished) -
    # Vacant") that would otherwise be masked by a boilerplate tenant-type
    # value ("Residential") sitting in the tenant column for every row.
    unit_text = "" if unit is None else str(unit).strip()
    if _VACANT_LABEL_RE.search(unit_text):
        return "vacant"
    # Yardi-style rolls put the literal word "VACANT" in the resident column —
    # that's a vacancy marker, not a tenant named Vacant.
    tenant_text = "" if tenant is None else str(tenant).strip()
    if tenant_text.lower() in ("vacant", "vacant unit", "-- vacant --"):
        return "vacant"
    rent_zero = rent_monthly in (None, 0, 0.0)
    if tenant_text == "" and rent_zero:
        return "vacant"
    if tenant_text != "":
        return "occupied"
    return "unknown"


def _row_looks_like_unit(row: list, field_cols: dict) -> bool:
    """True if `row` still plausibly belongs to the unit table — has a unit
    or tenant identifier that ISN'T itself a summary label, plus a real SF
    figure. Used to tell a mid-table subtotal (more units follow) apart from
    the table's actual end (everything below is a different section)."""

    def get(field):
        col = field_cols.get(field)
        return row[col] if col is not None and col < len(row) else None

    unit = get("unit")
    tenant = get("tenant")
    sf = parse_numeric(get("sf"))
    if unit is not None and _SUBTOTAL_ROW_RE.match(str(unit)):
        return False
    if tenant is not None and _SUBTOTAL_ROW_RE.match(str(tenant)):
        return False
    return (unit is not None or tenant is not None) and sf is not None


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
        # Labeled subtotal/total/average rows carry aggregate numbers, not a
        # unit. Once we've collected at least one real unit, treat such a row
        # as the possible end of the table: if the NEXT row doesn't itself
        # look like a continuing unit row (a mid-table "Total 1BR/1BA" style
        # subtotal is normally followed by more units; a grand "TOTAL:" row
        # is normally followed by unrelated narrative/summary content),
        # stop parsing entirely rather than let that content leak in as
        # phantom units (real-world case: a combined rent-roll + income-
        # statement sheet, where dozens of expense/summary rows below the
        # roll each have SOMETHING in the unit/tenant/sf columns).
        is_summary_row = (unit is not None and _SUBTOTAL_ROW_RE.match(str(unit))) or (
            tenant is not None and _SUBTOTAL_ROW_RE.match(str(tenant))
        )
        if is_summary_row:
            if parsed_rows:
                next_row = data_rows[row_idx + 1] if row_idx + 1 < len(data_rows) else None
                if next_row is None or not _row_looks_like_unit(next_row, field_cols):
                    break
            continue

        # I9: CoStar-style annual figures derive the monthly rent when no
        # monthly column exists. The derivation is recorded, never silent.
        annual_rent = parse_numeric(get("annualRent")) if "annualRent" in field_cols else None
        rent_psf = parse_numeric(get("rentPsfAnnual")) if "rentPsfAnnual" in field_cols else None
        derived_from = None
        if in_place is None:
            if annual_rent:
                in_place = round(annual_rent / 12, 2)
                derived_from = "annualRent"
            elif rent_psf and sf:
                in_place = round(rent_psf * sf / 12, 2)
                derived_from = "rentPsfAnnual"

        status = _infer_status(tenant, in_place, get("status"), unit)
        lease_end, is_mtm, month_year_end = _parse_end_date(get("leaseEnd"))

        parsed = {
            "unit": str(unit).strip() if unit is not None else None,
            "tenant": str(tenant).strip() if tenant is not None else None,
            "sf": sf,
            "unitType": str(get("unitType")).strip() if get("unitType") is not None else None,
            "status": status,
            "leaseType": str(get("leaseType")).strip() if get("leaseType") is not None else None,
            "inPlaceRentMonthly": in_place,
            "marketRentMonthly": market,
            "leaseStart": _parse_date(get("leaseStart")),
            "leaseEnd": lease_end,
            "camRecoveries": parse_numeric(get("camRecoveries")),
            "sourceRef": {"doc": source_doc, "sheet": sheet, "row": row_idx, "page": None, "cell": None},
        }
        # New keys appear only when their source exists, so pre-I9 fixtures
        # produce byte-identical goldens.
        if "floor" in field_cols and get("floor") is not None:
            parsed["floor"] = str(get("floor")).strip()
        if annual_rent is not None:
            parsed["annualRent"] = annual_rent
        if rent_psf is not None:
            parsed["rentPsfAnnual"] = rent_psf
        if derived_from:
            parsed["rentDerivedFrom"] = derived_from
        if is_mtm:
            parsed["mtm"] = True
        if month_year_end:
            parsed["monthYearEndDate"] = True
        parsed_rows.append(parsed)

    # confidence: how many of the load-bearing fields (unit/tenant, sf, rent)
    # we actually found columns for — a proxy for "did header matching work".
    load_bearing = ["unit", "sf", "inPlaceRentMonthly"]
    confidence = sum(1 for f in load_bearing if f in field_cols) / len(load_bearing)

    return {"rows": parsed_rows, "matchedFields": list(field_cols.keys()), "confidence": round(confidence, 2)}


# --------------------------------------------------------------- unit mix

_STUDIO_RE = re.compile(r"studio|\beff", re.IGNORECASE)
_COMPACT_BED_BATH_RE = re.compile(r"^\s*(\d+)\s*[x/]\s*(\d+(?:\.\d+)?)\s*$")
_BED_BATH_RE = re.compile(
    r"(\d+)\s*(?:bd|br|bed)[a-z]*\s*[/x\- ]?\s*(?:(\d+(?:\.\d+)?)\s*(?:ba|bath))?",
    re.IGNORECASE,
)


def _bed_bath_key(label) -> tuple[int, float | None] | None:
    """'1BR/1BA' -> (1, 1.0); '2x2' -> (2, 2.0); 'Studio' -> (0, 1.0);
    'A1' (an opaque floorplan code) -> None."""
    if not label:
        return None
    text = str(label)
    if _STUDIO_RE.search(text):
        return (0, 1.0)
    compact = _COMPACT_BED_BATH_RE.match(text)
    if compact:
        return (int(compact.group(1)), float(compact.group(2)))
    match = _BED_BATH_RE.search(text)
    if match:
        baths = float(match.group(2)) if match.group(2) else None
        return (int(match.group(1)), baths)
    return None


def _bed_bath_label(key: tuple[int, float | None]) -> str:
    beds, baths = key
    if beds == 0:
        return "Studio"
    if baths is None:
        return f"{beds} BR"
    return f"{beds} BR / {baths:g} BA"


def propose_unit_mix(rows: list[dict]) -> dict:
    """Group parsed rent-roll rows into a proposed unit-mix table.

    Grouping key: the unit-type label — UNLESS two different labels parse to
    the same bed/bath pair (e.g. '1BR/1BA', '1x1', '1 Bed 1 Bath' in one
    roll), in which case grouping falls back to the parsed bed/bath key with
    a warning, so inconsistent vocabulary can't split one physical unit type
    into several rows.

    Returns {"rows": [{unitType, unitCount, avgSf, inPlaceRent, marketRent,
    occupiedCount, occupancyPct, sourceRowCount}], "groupedBy":
    "label"|"bedBath", "warnings": [...]}."""
    warnings: list[str] = []

    key_to_labels: dict[tuple, set[str]] = {}
    for r in rows:
        label = r.get("unitType")
        key = _bed_bath_key(label)
        if key is not None and label:
            key_to_labels.setdefault(key, set()).add(str(label).strip())
    inconsistent = any(len(labels) > 1 for labels in key_to_labels.values())

    has_any_unit_type = any(r.get("unitType") for r in rows)

    if inconsistent:
        grouped_by = "bedBath"
        examples = next(sorted(labels) for labels in key_to_labels.values() if len(labels) > 1)
        warnings.append(
            "Unit-type labels are inconsistent (e.g. "
            + " vs ".join(f"'{e}'" for e in examples[:3])
            + " describe the same bed/bath) — grouped by parsed bed/bath instead of the raw label."
        )

        def group_key(r):
            key = _bed_bath_key(r.get("unitType"))
            if key is not None:
                return _bed_bath_label(key)
            return str(r.get("unitType") or "Unspecified").strip()
    elif not has_any_unit_type:
        # No Unit Type / Floor Plan column at all (common on small, simple
        # rolls) — grouping everyone into one "Unspecified" bucket loses
        # real unit-mix variation. SF is the next-best proxy: distinct SF
        # values on a residential roll almost always correspond to distinct
        # floor plans, even when the broker never labeled them.
        grouped_by = "sf"
        warnings.append(
            "No unit-type/floor-plan column found — grouped by square footage instead "
            "(each distinct SF value treated as one unit type)."
        )

        def group_key(r):
            sf = r.get("sf")
            return f"{round(sf)} SF" if sf is not None else "Unspecified"
    else:
        grouped_by = "label"

        def group_key(r):
            return str(r.get("unitType") or "Unspecified").strip()

    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(group_key(r), []).append(r)

    mix_rows = []
    for unit_type, group in groups.items():
        sfs = [r["sf"] for r in group if r.get("sf") is not None]
        in_place = [
            r["inPlaceRentMonthly"]
            for r in group
            if r.get("status") == "occupied" and r.get("inPlaceRentMonthly")
        ]
        market = [r["marketRentMonthly"] for r in group if r.get("marketRentMonthly")]
        occupied = sum(1 for r in group if r.get("status") == "occupied")
        mix_rows.append(
            {
                "unitType": unit_type,
                "unitCount": len(group),
                "avgSf": round(sum(sfs) / len(sfs)) if sfs else None,
                "inPlaceRent": round(sum(in_place) / len(in_place)) if in_place else None,
                "marketRent": round(sum(market) / len(market)) if market else None,
                "occupiedCount": occupied,
                "occupancyPct": round(occupied / len(group), 4) if group else None,
                "sourceRowCount": len(group),
            }
        )

    return {"rows": mix_rows, "groupedBy": grouped_by, "warnings": warnings}


def aggregate_multifamily(rows: list[dict]) -> dict:
    # The unit-mix grouping has ONE implementation: propose_unit_mix. The
    # legacy unitMix field keeps its original shape (schema columns only).
    proposal = propose_unit_mix(rows)
    unit_mix = [
        {
            "unitType": row["unitType"],
            "unitCount": row["unitCount"],
            "avgSf": row["avgSf"],
            "inPlaceRent": row["inPlaceRent"],
            "marketRent": row["marketRent"],
        }
        for row in proposal["rows"]
    ]
    return {"unitMix": unit_mix, **_occupancy_summary(rows)}


_LEASE_TYPE_TO_RECOVERY = {
    # modified gross maps to a base-year stop as the nearest standard
    # structure; unknown/absent maps to gross (the income-conservative
    # reading). See DECISIONS.md (H1). I9 adds the CoStar vocabulary.
    "nnn": "NNN",
    "net": "NNN",
    "triple net": "NNN",
    "gross": "gross",
    "full service": "gross",
    "full service gross": "gross",
    "fs": "gross",
    "modified_gross": "base_year_stop",
    "modified gross": "base_year_stop",
    "mg": "base_year_stop",
}

# I9: a "monthly" rent whose implied annual $/SF is beyond this is almost
# certainly an ANNUAL figure sitting in a monthly-labeled column (the mixed-
# magnitude column hostile case). Reinterpreted WITH a warning, never silently.
_ANNUAL_MISREAD_PSF = 250.0

_SUITE_RANGE_RE = re.compile(r"\d+\s*[-–]\s*\d+")


def propose_commercial_leases(rows: list[dict]) -> dict:
    """Map parsed commercial rent-roll rows onto the schema's lease-level
    commercialLeases shape (H1). Escalations and free rent aren't reliably
    extractable from a rent roll — they propose as none/zero for the user to
    edit. Vacant/no-SF rows are skipped with a warning naming them; occupied
    rows WITHOUT a rent (stacking plans, I9) propose at $0 with a warning so
    the review grid can be filled in rather than losing the tenancy.

    Returns {"rows": [...], "warnings": [...]}."""
    warnings: list[str] = []
    proposed: list[dict] = []
    skipped: list[str] = []
    zero_rent: list[str] = []
    reinterpreted: list[str] = []
    mtm_rows: list[str] = []
    ranged: list[str] = []

    for r in rows:
        sf = r.get("sf")
        rent_monthly = r.get("inPlaceRentMonthly") or r.get("marketRentMonthly")
        label = r.get("tenant") or r.get("unit") or "?"
        if not sf or r.get("status") == "vacant":
            skipped.append(str(label))
            continue

        if r.get("rentPsfAnnual"):
            base_psf = round(float(r["rentPsfAnnual"]), 2)
        elif rent_monthly:
            base_psf = round(rent_monthly * 12 / sf, 2)
            if base_psf > _ANNUAL_MISREAD_PSF:
                # Magnitude heuristic: this "monthly" number is annual.
                base_psf = round(rent_monthly / sf, 2)
                reinterpreted.append(f"{label} (${rent_monthly:,.0f} read as annual)")
        else:
            base_psf = 0.0
            zero_rent.append(str(label))

        if r.get("mtm"):
            mtm_rows.append(str(label))
        suite = str(r.get("unit") or "")
        if _SUITE_RANGE_RE.search(suite):
            ranged.append(suite)

        lease_type = str(r.get("leaseType") or "").strip().lower()
        proposed.append(
            {
                "tenant": r.get("tenant") or "",
                "suiteId": suite,
                "sf": sf,
                "startDate": r.get("leaseStart"),
                "endDate": r.get("leaseEnd"),
                "baseRentPsfAnnual": base_psf,
                "escalationType": "none",
                "escalationValue": 0,
                "escalationMonths": 12,
                "recoveryType": _LEASE_TYPE_TO_RECOVERY.get(lease_type, "gross"),
                "recoveryValue": 0,
                "freeRentMonths": 0,
            }
        )

    if skipped:
        warnings.append(
            f"{len(skipped)} rent-roll row(s) were vacant or missing SF/rent and "
            f"were not proposed as leases: {', '.join(skipped[:5])}"
            + ("…" if len(skipped) > 5 else "")
        )
    if zero_rent:
        warnings.append(
            f"{len(zero_rent)} row(s) have SF but NO stated rent (stacking-plan "
            f"style) — proposed at $0/SF; fill the rent in before applying: "
            + ", ".join(zero_rent[:5]) + ("…" if len(zero_rent) > 5 else "")
        )
    if reinterpreted:
        warnings.append(
            "Rent magnitude check: "
            + "; ".join(reinterpreted[:5])
            + (";…" if len(reinterpreted) > 5 else "")
            + f" — read as monthly these imply > ${_ANNUAL_MISREAD_PSF:,.0f}/SF/yr. "
            "Verify against the source document."
        )
    if mtm_rows:
        warnings.append(
            f"{len(mtm_rows)} month-to-month lease(s) ({', '.join(mtm_rows[:5])}) — "
            "no expiry proposed; the engine treats them as running through the "
            "analysis. Consider setting a near-term expiry with rollover "
            "assumptions instead."
        )
    if ranged:
        warnings.append(
            f"Combined suite range(s) kept as ONE lease each: {', '.join(ranged[:5])} "
            "— split them manually if the spaces have different terms."
        )
    missing_dates = sum(1 for p in proposed if not p["endDate"])
    if missing_dates:
        warnings.append(
            f"{missing_dates} proposed lease(s) have no expiry date — the engine "
            "treats them as running through the whole analysis until you set one."
        )
    return {"rows": proposed, "warnings": warnings}


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
