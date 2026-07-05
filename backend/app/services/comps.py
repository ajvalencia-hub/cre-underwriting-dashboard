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


def benchmark_flags(db: Session, market: str, asset_class: str, subject: dict) -> list[dict]:
    """Comps-DB flags in the benchmarks.py flag shape. Only fires with at
    least MIN_COMPS_FOR_FLAG comps in the deal's market — two comps are an
    anecdote, not a benchmark."""
    flags: list[dict] = []

    subject_rent = subject.get("avgRentMonthly")
    if isinstance(subject_rent, (int, float)) and subject_rent > 0:
        rents = [
            c.avg_rent
            for c in db.execute(_market_filter(select(RentComp), RentComp, market)).scalars()
            if c.avg_rent and _type_ok(c.property_type, asset_class)
        ]
        if len(rents) >= MIN_COMPS_FOR_FLAG:
            comps_median = median(rents)
            premium = subject_rent / comps_median - 1
            verdict = (
                "warning" if premium > RENT_VS_COMPS_WARNING
                else "caution" if premium > RENT_VS_COMPS_CAUTION
                else "ok"
            )
            flags.append({
                "metric": "rent_vs_comps",
                "subjectValue": subject_rent,
                "benchmarkValue": comps_median,
                "source": "comps_db",
                "asOf": "",
                "verdict": verdict,
                "explanation": (
                    f"Subject rent ${subject_rent:,.0f}/mo vs ${comps_median:,.0f} median of "
                    f"{len(rents)} rent comps ({premium:+.0%})."
                ),
                "relatedFieldIds": ["unitMix", "grossPotentialRent"],
            })

    exit_cap = subject.get("exitCapRatePct")
    if isinstance(exit_cap, (int, float)) and exit_cap > 0:
        caps = [
            c.cap_rate_pct
            for c in db.execute(_market_filter(select(SaleComp), SaleComp, market)).scalars()
            if c.cap_rate_pct and _type_ok(c.property_type, asset_class)
        ]
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
                ),
                "relatedFieldIds": ["exitCapRatePct"],
            })

    return flags
