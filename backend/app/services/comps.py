"""Comps database services (H5): CSV import (Yardi Matrix style) with
column-mapping heuristics, and comps-derived benchmark flags.

Import flow mirrors the extraction human-review gate: without a mapping the
endpoint returns a PREVIEW (detected columns + suggested mapping + sample
rows) and writes nothing; rows are only inserted once the user submits a
mapping. Unparseable rows are skipped with a warning, never guessed.
"""

import csv
import io
import re
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RentComp, SaleComp

# --- CSV parsing -----------------------------------------------------------

# Importable fields per comp kind, with header synonyms (normalized to
# lowercase alphanumerics) covering Yardi Matrix export naming.
SALE_FIELDS: dict[str, list[str]] = {
    "name": ["propertyname", "property", "name"],
    "address": ["address", "propertyaddress", "streetaddress"],
    "market": ["market", "metro"],
    "submarket": ["submarket"],
    "propertyType": ["propertytype", "assettype", "type"],
    "saleDate": ["saledate", "dateofsale", "closingdate", "date"],
    "price": ["saleprice", "price", "totalprice"],
    "units": ["units", "numberofunits", "unitcount", "noofunits"],
    "sf": ["rba", "sf", "buildingsf", "grosssf", "nra", "squarefeet", "totalsf"],
    "capRatePct": ["caprate", "capratepct", "cap"],
    "yearBuilt": ["yearbuilt", "built", "yoc"],
    "notes": ["notes", "comments"],
}

RENT_FIELDS: dict[str, list[str]] = {
    "name": ["propertyname", "property", "name"],
    "address": ["address", "propertyaddress", "streetaddress"],
    "market": ["market", "metro"],
    "submarket": ["submarket"],
    "propertyType": ["propertytype", "assettype", "type"],
    "asOf": ["asof", "asofdate", "surveydate", "date"],
    "unitType": ["unittype", "bedstype", "floorplan", "beds"],
    "avgRent": ["avgrent", "averagerent", "effectiverent", "askingrent", "rent", "avgeffectiverent"],
    "avgSf": ["avgsf", "averagesf", "unitsf", "avgunitsf"],
    "occupancyPct": ["occupancy", "occupancypct", "occ", "occupancyrate"],
    "yearBuilt": ["yearbuilt", "built"],
    "notes": ["notes", "comments"],
}

_NUMERIC_FIELDS = {"price", "units", "sf", "capRatePct", "yearBuilt", "avgRent", "avgSf", "occupancyPct"}
_PERCENT_FIELDS = {"capRatePct", "occupancyPct"}
_DATE_FIELDS = {"saleDate", "asOf"}

_DATE_PATTERNS = [
    (re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})"), lambda m: (m[1], m[2], m[3])),
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})"), lambda m: (m[3], m[1], m[2])),
    (re.compile(r"^(\d{1,2})/(\d{4})$"), lambda m: (m[2], m[1], "1")),
]


def _norm_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def parse_csv_text(text: str) -> tuple[list[str], list[dict]]:
    """Returns (headers, rows). Sniffs comma/semicolon/tab delimiters."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [h.strip() for h in (reader.fieldnames or []) if h and h.strip()]
    rows = [
        {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        for row in reader
    ]
    return headers, rows


def suggest_mapping(headers: list[str], kind: str) -> dict[str, str]:
    """Best-guess {fieldId: csvHeader} by normalized-synonym match. First
    synonym hit wins per field; each header maps at most once."""
    synonyms = SALE_FIELDS if kind == "sale" else RENT_FIELDS
    normalized = {_norm_header(h): h for h in headers}
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for field, names in synonyms.items():
        for name in names:
            header = normalized.get(name)
            if header and header not in used:
                mapping[field] = header
                used.add(header)
                break
    return mapping


def _parse_number(raw: str) -> float | None:
    cleaned = re.sub(r"[^0-9.\-]", "", raw)
    if cleaned in ("", "-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(raw: str) -> str | None:
    for pattern, extract in _DATE_PATTERNS:
        match = pattern.match(raw.strip())
        if match:
            year, month, day = extract(match)
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return None


def coerce_row(row: dict, mapping: dict[str, str], kind: str) -> tuple[dict | None, str | None]:
    """Row dict + {fieldId: header} -> (comp fields, warning) — comp is None
    when the row lacks the minimum to be a usable comp."""
    comp: dict = {}
    for field, header in mapping.items():
        raw = (row.get(header) or "").strip()
        if not raw:
            continue
        if field in _NUMERIC_FIELDS:
            value = _parse_number(raw)
            if value is None:
                continue
            if field in _PERCENT_FIELDS and value > 1:
                value /= 100  # "5.25" or "5.25%" -> 0.0525
            comp[field] = value
        elif field in _DATE_FIELDS:
            parsed = _parse_date(raw)
            if parsed:
                comp[field] = parsed
        else:
            comp[field] = raw

    name = comp.get("name")
    if not name:
        return None, "Row skipped: no property name."
    if kind == "sale" and comp.get("price") is None and comp.get("capRatePct") is None:
        return None, f"Row '{name}' skipped: neither sale price nor cap rate parsed."
    if kind == "rent" and comp.get("avgRent") is None:
        return None, f"Row '{name}' skipped: no average rent parsed."
    return comp, None


# --- benchmark hooks (H5) ----------------------------------------------------

MIN_COMPS_FOR_FLAG = 3
RENT_VS_COMPS_CAUTION = 0.10  # subject rent above comps median by >10% / >20%
RENT_VS_COMPS_WARNING = 0.20
EXIT_CAP_CAUTION_BPS = 0.005  # subject exit cap below comps median by >50/>100bps
EXIT_CAP_WARNING_BPS = 0.010


def _market_filter(query, model, market: str):
    return query.where(model.market.ilike(f"%{market.strip()}%")) if market.strip() else query


def _type_ok(comp_type: str, asset_class: str) -> bool:
    """Soft property-type filter: untyped comps and blank asset classes
    always pass; otherwise substring match either way ('mixed_use' vs
    'Mixed Use')."""
    if not asset_class or not comp_type:
        return True
    a = asset_class.replace("_", " ").lower()
    c = comp_type.replace("_", " ").lower()
    return a in c or c in a


# I6: rent comparison tiers. Each tier needs MIN_COMPS_FOR_FLAG comps to be
# usable; comparison falls through tier by tier and states which one fired.
_BEDROOM_RE = re.compile(r"(\d)\s*(bd|br|bed)", re.IGNORECASE)


def _bedrooms_of(unit_type: str | None) -> int | None:
    if not unit_type:
        return None
    match = _BEDROOM_RE.search(unit_type)
    if match:
        return min(3, int(match.group(1)))
    return 0 if re.search(r"studio|eff", unit_type, re.IGNORECASE) else None


def weighted_type_median(
    comp_rows: list, bedroom_mix: list[dict]
) -> tuple[float, int] | None:
    """Tier 1: median rent per bedroom class, weighted by the SUBJECT's
    unit-type distribution. Usable only when EVERY weighted subject class
    has >= MIN_COMPS_FOR_FLAG typed comps (a half-covered mix would silently
    skew the blend). Returns (weighted median, comps used) or None."""
    by_class: dict[int, list[float]] = {}
    for comp in comp_rows:
        bedrooms = _bedrooms_of(comp.unit_type)
        if bedrooms is not None and comp.avg_rent:
            by_class.setdefault(bedrooms, []).append(comp.avg_rent)

    total_weight, blended, used = 0.0, 0.0, 0
    for entry in bedroom_mix:
        count = entry.get("count") or 0
        if count <= 0:
            continue
        rents = by_class.get(entry.get("bedrooms"))
        if not rents or len(rents) < MIN_COMPS_FOR_FLAG:
            return None
        blended += count * median(rents)
        total_weight += count
        used += len(rents)
    if total_weight <= 0:
        return None
    return blended / total_weight, used


def _rent_comparison(comp_rows: list, subject: dict):
    """Returns (subject_value, benchmark_value, count, basis_label,
    low_confidence) for the best usable tier, or None."""
    subject_rent = subject.get("avgRentMonthly")
    if not isinstance(subject_rent, (int, float)) or subject_rent <= 0:
        return None

    # Tier 1: unit-type weighted (typed comps covering the subject's mix).
    mix = subject.get("bedroomMix") or []
    if mix:
        typed = weighted_type_median(comp_rows, mix)
        if typed is not None:
            blended, used = typed
            return subject_rent, blended, used, "unit-type weighted median", False

    # Tier 2: $/SF (subject and comp SF both known).
    subject_sf = subject.get("avgUnitSf")
    if isinstance(subject_sf, (int, float)) and subject_sf > 0:
        psf = [c.avg_rent / c.avg_sf for c in comp_rows if c.avg_rent and c.avg_sf]
        if len(psf) >= MIN_COMPS_FOR_FLAG:
            return (
                subject_rent / subject_sf, median(psf), len(psf),
                "$/SF median", False,
            )

    # Tier 3: raw pooled median — flagged as low confidence.
    rents = [c.avg_rent for c in comp_rows if c.avg_rent]
    if len(rents) >= MIN_COMPS_FOR_FLAG:
        return subject_rent, median(rents), len(rents), "pooled median", True
    return None


def _sale_basis_note(sale_rows: list, asset_class: str) -> str:
    """I6: the sale-comp basis appropriate to the asset class, as context in
    the flag explanation — $/unit for multifamily, $/SF otherwise."""
    prefer_unit = "multifamily" in (asset_class or "").lower() or "mixed" in (asset_class or "").lower()
    if prefer_unit:
        per_unit = [c.price / c.units for c in sale_rows if c.price and c.units]
        if len(per_unit) >= MIN_COMPS_FOR_FLAG:
            return f" Median ${median(per_unit):,.0f}/unit across {len(per_unit)} priced comps."
    per_sf = [c.price / c.sf for c in sale_rows if c.price and c.sf]
    if len(per_sf) >= MIN_COMPS_FOR_FLAG:
        return f" Median ${median(per_sf):,.0f}/SF across {len(per_sf)} priced comps."
    return ""


def benchmark_flags(db: Session, market: str, asset_class: str, subject: dict) -> list[dict]:
    """Comps-DB flags in the benchmarks.py flag shape. The minimum-comps
    rule applies PER COMPARISON TIER (I6) — two comps are an anecdote at
    every tier."""
    flags: list[dict] = []

    rent_rows = [
        c
        for c in db.execute(_market_filter(select(RentComp), RentComp, market)).scalars()
        if _type_ok(c.property_type, asset_class)
    ]
    comparison = _rent_comparison(rent_rows, subject)
    if comparison is not None:
        subject_value, benchmark_value, count, basis, low_confidence = comparison
        premium = subject_value / benchmark_value - 1
        verdict = (
            "warning" if premium > RENT_VS_COMPS_WARNING
            else "caution" if premium > RENT_VS_COMPS_CAUTION
            else "ok"
        )
        unit = "/SF/mo" if "$/SF" in basis else "/mo"
        explanation = (
            f"Subject rent ${subject_value:,.2f}{unit} vs ${benchmark_value:,.2f} "
            f"({basis}, {count} rent comps, {premium:+.0%})."
        )
        if low_confidence:
            explanation += (
                " Low-confidence comparison: pooled across unit types — add typed"
                " or $/SF comps to tighten it."
            )
        flags.append({
            "metric": "rent_vs_comps",
            "subjectValue": subject_value,
            "benchmarkValue": benchmark_value,
            "source": "comps_db",
            "asOf": "",
            "verdict": verdict,
            "explanation": explanation,
            "relatedFieldIds": ["unitMix", "grossPotentialRent"],
        })

    exit_cap = subject.get("exitCapRatePct")
    if isinstance(exit_cap, (int, float)) and exit_cap > 0:
        sale_rows = [
            c
            for c in db.execute(_market_filter(select(SaleComp), SaleComp, market)).scalars()
            if _type_ok(c.property_type, asset_class)
        ]
        caps = [c.cap_rate_pct for c in sale_rows if c.cap_rate_pct]
        if len(caps) >= MIN_COMPS_FOR_FLAG:
            comps_median = median(caps)
            compression = comps_median - exit_cap  # positive = exit below today's comps
            verdict = (
                "warning" if compression > EXIT_CAP_WARNING_BPS
                else "caution" if compression > EXIT_CAP_CAUTION_BPS
                else "ok"
            )
            flags.append({
                "metric": "exit_cap_vs_comps",
                "subjectValue": exit_cap,
                "benchmarkValue": comps_median,
                "source": "comps_db",
                "asOf": "",
                "verdict": verdict,
                "explanation": (
                    f"Exit cap {exit_cap * 100:.2f}% vs {comps_median * 100:.2f}% median of "
                    f"{len(caps)} sale comps — "
                    + (
                        f"{compression * 10000:.0f}bps of assumed compression."
                        if compression > 0
                        else "no compression assumed."
                    )
                    + _sale_basis_note(sale_rows, asset_class)
                ),
                "relatedFieldIds": ["exitCapRatePct"],
            })

    return flags
