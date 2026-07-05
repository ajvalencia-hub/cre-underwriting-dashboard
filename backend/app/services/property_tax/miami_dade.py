"""Miami-Dade Property Appraiser adapter.

Uses the PA public search proxy (the same endpoints the public Property
Search site calls): an address search resolves a folio, then the folio
fetch returns assessment and taxable values. The response schema is parsed
defensively — any missing/renamed field degrades to None, and any network
or parse failure returns dataSource="unavailable" with a note. Millage is
derived as currentTaxes / taxableValue when the API doesn't state it.
"""

import re

import httpx

from app.services.data_sources.source_cache import cached_fetch

COUNTY = "miami_dade"
JURISDICTION = "Miami-Dade County, FL"

_BASE = "https://www.miamidade.gov/Apps/PA/PApublicServiceProxy/PaServicesProxy.ashx"
_TIMEOUT = 15.0

_FOLIO_RE = re.compile(r"^[\d-]{9,17}$")


def _get(params: dict) -> dict:
    with httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": "CRE-Dashboard/1.0"}) as client:
        response = client.get(_BASE, params=params)
        response.raise_for_status()
        return response.json()


def _num(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^0-9.\-]", "", value)
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None
    return None


def _unavailable(note: str) -> dict:
    return {
        "dataSource": "unavailable",
        "folio": None,
        "address": None,
        "assessedValue": None,
        "taxableValue": None,
        "millageRate": None,
        "currentTaxes": None,
        "adValoremTaxes": None,
        "nonAdValorem": None,
        "totalTaxes": None,
        "jurisdiction": JURISDICTION,
        "asOf": None,
        "note": note,
    }


def _parse_non_ad_valorem(detail: dict, taxable_info: dict) -> float | None:
    """Non-ad-valorem assessments (I5): a line-item list where the payload
    provides one, else a scalar field on the taxable info. None (not 0)
    when the split simply isn't in the payload."""
    items = detail.get("NonAdValorem")
    if isinstance(items, dict):
        items = items.get("NonAdValoremInfos")
    if isinstance(items, list) and items:
        total = sum(
            _num(i.get("Amount")) or 0.0 for i in items if isinstance(i, dict)
        )
        if total > 0:
            return total
    scalar = _num(taxable_info.get("NonAdValoremTaxes")) or _num(
        taxable_info.get("NonAdValorem")
    )
    return scalar if scalar else None


def _resolve_folio(query: str) -> tuple[str | None, str | None]:
    """Returns (folio, note). Accepts a folio directly or searches by address."""
    stripped = query.strip()
    if _FOLIO_RE.match(stripped.replace(" ", "")):
        return stripped.replace("-", "").replace(" ", ""), None
    payload = _get(
        {
            "Operation": "GetAddress",
            "clientAppName": "PropertySearch",
            "myAddress": stripped,
            "from": 1,
            "to": 5,
        }
    )
    candidates = payload.get("MinimumPropertyInfos") or []
    if not candidates:
        return None, f"No Miami-Dade parcel matched '{stripped}'."
    strap = candidates[0].get("Strap") or candidates[0].get("FolioNumber")
    if not strap:
        return None, "Miami-Dade PA returned a match without a folio number."
    return str(strap).replace("-", "").replace(" ", ""), None


def _fetch(query: str) -> dict:
    try:
        folio, note = _resolve_folio(query)
        if folio is None:
            return _unavailable(note or "Parcel not found.")
        detail = _get(
            {
                "Operation": "GetPropertySearchByFolio",
                "clientAppName": "PropertySearch",
                "folioNumber": folio,
            }
        )
        prop = detail.get("PropertyInfo") or {}
        assessments = (detail.get("Assessment") or {}).get("AssessmentInfos") or []
        taxable_infos = (detail.get("Taxable") or {}).get("TaxableInfos") or []
        latest_assessment = assessments[0] if assessments else {}
        latest_taxable = taxable_infos[0] if taxable_infos else {}

        assessed = _num(latest_assessment.get("AssessedValue"))
        taxable = _num(latest_taxable.get("CountyTaxableValue")) or _num(
            latest_taxable.get("TaxableValue")
        )
        total_taxes = _num(latest_taxable.get("TotalTaxes")) or _num(
            latest_taxable.get("CountyTaxes")
        )
        non_ad_valorem = _parse_non_ad_valorem(detail, latest_taxable)
        ad_valorem = (
            max(0.0, total_taxes - non_ad_valorem)
            if total_taxes and non_ad_valorem is not None
            else None
        )

        # Millage (I5): ad-valorem taxes / taxable value. When the payload
        # doesn't split out non-ad-valorem, fall back to the old total-based
        # derivation WITH a note — it overstates the true ad-valorem millage.
        millage = None
        note = None
        if taxable and taxable > 0:
            if ad_valorem is not None:
                millage = round(ad_valorem / taxable, 6)
            elif total_taxes:
                millage = round(total_taxes / taxable, 6)
                note = (
                    "Millage derived from TOTAL taxes — the non-ad-valorem "
                    "split wasn't available, so this may overstate the "
                    "ad-valorem millage."
                )

        return {
            "dataSource": COUNTY,
            "folio": folio,
            "address": (detail.get("SiteAddress") or [{}])[0].get("Address")
            or prop.get("PropertyAddress"),
            "assessedValue": assessed,
            "taxableValue": taxable,
            "millageRate": millage,
            "currentTaxes": total_taxes,
            "adValoremTaxes": ad_valorem,
            "nonAdValorem": non_ad_valorem,
            "totalTaxes": total_taxes,
            "jurisdiction": JURISDICTION,
            "asOf": str(latest_assessment.get("Year") or "") or None,
            "note": note,
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return _unavailable(f"Miami-Dade PA lookup failed: {exc}")


def lookup(query: str) -> dict:
    return cached_fetch(f"proptax_miamidade_{query.strip().lower()}", lambda: _fetch(query))
