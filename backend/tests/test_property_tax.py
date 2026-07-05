"""H4: property-tax module — Miami-Dade adapter (mocked PA API), the lookup
router, and reassessment modeling in the engine (default OFF)."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import property_tax
from app.services.property_tax import miami_dade
from app.services.proforma import engine, operations
from app.services.proforma.timeline import Timeline

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    """Bypass the 24h on-disk cache so every test exercises the fetch path."""
    monkeypatch.setattr(miami_dade, "cached_fetch", lambda key, fetch, ttl_seconds=0: fetch())


ADDRESS_PAYLOAD = {
    "MinimumPropertyInfos": [
        {"Strap": "01-3125-045-0090", "SiteAddress": "100 Test Ave"},
        {"Strap": "01-3125-045-0091", "SiteAddress": "100 Test Ave Unit 2"},
    ]
}

FOLIO_PAYLOAD = {
    "PropertyInfo": {"PropertyAddress": "100 TEST AVE"},
    "SiteAddress": [{"Address": "100 TEST AVE, MIAMI FL"}],
    "Assessment": {"AssessmentInfos": [{"Year": 2025, "AssessedValue": "8,500,000"}]},
    "Taxable": {
        "TaxableInfos": [
            {"CountyTaxableValue": 8_000_000, "TotalTaxes": "157,600"}
        ]
    },
}


def _mock_get(monkeypatch, handler):
    monkeypatch.setattr(miami_dade, "_get", handler)


def test_address_lookup_parses_pa_payload(monkeypatch):
    def handler(params):
        if params["Operation"] == "GetAddress":
            return ADDRESS_PAYLOAD
        assert params["folioNumber"] == "0131250450090"
        return FOLIO_PAYLOAD

    _mock_get(monkeypatch, handler)
    result = miami_dade.lookup("100 Test Ave, Miami")
    assert result["dataSource"] == "miami_dade"
    assert result["folio"] == "0131250450090"
    assert result["assessedValue"] == pytest.approx(8_500_000)
    assert result["taxableValue"] == pytest.approx(8_000_000)
    assert result["currentTaxes"] == pytest.approx(157_600)
    # millage derived = taxes / taxable = 1.97%
    assert result["millageRate"] == pytest.approx(0.0197)
    assert result["asOf"] == "2025"


def test_folio_query_skips_address_search(monkeypatch):
    calls = []

    def handler(params):
        calls.append(params["Operation"])
        return FOLIO_PAYLOAD

    _mock_get(monkeypatch, handler)
    result = miami_dade.lookup("01-3125-045-0090")
    assert calls == ["GetPropertySearchByFolio"]
    assert result["dataSource"] == "miami_dade"


def test_address_not_found(monkeypatch):
    _mock_get(monkeypatch, lambda params: {"MinimumPropertyInfos": []})
    result = miami_dade.lookup("nowhere land")
    assert result["dataSource"] == "unavailable"
    assert "No Miami-Dade parcel" in result["note"]


def test_network_failure_degrades(monkeypatch):
    def handler(params):
        raise httpx.ConnectError("boom")

    _mock_get(monkeypatch, handler)
    result = miami_dade.lookup("100 Test Ave")
    assert result["dataSource"] == "unavailable"
    assert "failed" in result["note"]


def test_malformed_payload_degrades_to_nones(monkeypatch):
    def handler(params):
        if params["Operation"] == "GetAddress":
            return ADDRESS_PAYLOAD
        return {"unexpected": "shape"}

    _mock_get(monkeypatch, handler)
    result = miami_dade.lookup("100 Test Ave")
    assert result["dataSource"] == "miami_dade"
    assert result["assessedValue"] is None
    assert result["millageRate"] is None


def test_lookup_router_returns_projection(monkeypatch):
    monkeypatch.setattr(
        property_tax,
        "lookup",
        lambda query, county=None: {
            "dataSource": "miami_dade",
            "millageRate": 0.02,
            "jurisdiction": "Miami-Dade County, FL",
        },
    )
    client = TestClient(app)
    response = client.post(
        "/api/property-tax/lookup",
        json={"query": "100 Test Ave", "purchasePrice": 10_000_000, "assessmentRatio": 0.85},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["projection"]["projectedAssessedValue"] == pytest.approx(8_500_000)
    assert body["projection"]["projectedAnnualTaxes"] == pytest.approx(170_000)

    # No price -> no projection, lookup result still passes through.
    body = client.post("/api/property-tax/lookup", json={"query": "x"}).json()
    assert body["projection"] is None


# --- reassessment modeling (engine) ---


def test_reassessment_default_off_is_a_no_op(analytic):
    base = engine.compute(analytic)
    with_fields = engine.compute({**analytic, "useReassessedTaxes": False,
                                  "millageRatePct": 0.02, "assessmentRatio": 0.85})
    assert with_fields["outputs"] == base["outputs"]


def test_reassessment_replaces_taxes_legacy_mode(analytic):
    price = analytic["purchasePrice"]
    result = engine.compute({
        **analytic,
        "useReassessedTaxes": True,
        "millageRatePct": 0.02,
        "assessmentRatio": 0.85,
    })
    projected = price * 0.85 * 0.02
    # statement index 0 = close; month 1 is the first operating month
    taxes = result["statement"]["fixedOpexByCategory"]["realEstateTaxes"]
    assert taxes[1] == pytest.approx(projected / 12)
    assert any("Reassessed property taxes" in w for w in result["warnings"])


def test_reassessment_replaces_detail_tax_lines_and_keeps_recoverable():
    """Both modeled tax lines are replaced by the single projection; the
    recoverable flag survives, so a NNN tenant recovers the projected taxes."""
    inputs = {
        "purchasePrice": 1_000_000,
        "commercialLeases": [{
            "tenant": "T", "suiteId": "1", "sf": 5_000,
            "startDate": "2026-01-01", "endDate": "2033-12-31",
            "baseRentPsfAnnual": 20, "escalationType": "none",
            "recoveryType": "NNN", "freeRentMonths": 0,
        }],
        "creditLossPct": 0, "rentGrowthMode": "flat", "expenseGrowthMode": "flat",
        "opexLineItems": [
            {"category": "taxes", "amount": 30_000, "basis": "annual_total", "recoverable": "yes"},
            {"category": "taxes", "amount": 10_000, "basis": "annual_total", "recoverable": "no"},
        ],
        "useReassessedTaxes": True,
        "millageRatePct": 0.018,
        "assessmentRatio": 1.0,
    }
    ops = operations.build_noi_vector(inputs, Timeline(12, 0, 0, 1))
    projected_monthly = 1_000_000 * 1.0 * 0.018 / 12  # 1,500/mo
    assert ops["fixedOpexByCategory"]["realEstateTaxes"][0] == pytest.approx(projected_monthly)
    assert ops["recoveries"][0] == pytest.approx(projected_monthly)


def test_reassessment_missing_millage_warns_and_leaves_taxes(analytic):
    result = engine.compute({**analytic, "useReassessedTaxes": True})
    base = engine.compute(analytic)
    assert (
        result["statement"]["fixedOpexByCategory"]["realEstateTaxes"][0]
        == base["statement"]["fixedOpexByCategory"]["realEstateTaxes"][0]
    )
    assert any("millage" in w for w in result["warnings"])


# --- non-ad-valorem assessments (I5) ---


FOLIO_PAYLOAD_WITH_NAV = {
    **FOLIO_PAYLOAD,
    "NonAdValorem": [{"Amount": 5_000}, {"Amount": 2_600}],
}


def test_non_ad_valorem_split_drives_millage(monkeypatch):
    _mock_get(monkeypatch, lambda params: FOLIO_PAYLOAD_WITH_NAV)
    result = miami_dade.lookup("01-3125-045-0090")
    assert result["nonAdValorem"] == pytest.approx(7_600)
    assert result["adValoremTaxes"] == pytest.approx(150_000)  # 157,600 - 7,600
    # Millage from AD-VALOREM taxes: 150,000 / 8,000,000 = 1.875%.
    assert result["millageRate"] == pytest.approx(0.01875)
    assert result["note"] is None


def test_millage_falls_back_to_total_with_a_note(monkeypatch):
    _mock_get(monkeypatch, lambda params: FOLIO_PAYLOAD)  # no split in payload
    result = miami_dade.lookup("01-3125-045-0090")
    assert result["nonAdValorem"] is None
    assert result["adValoremTaxes"] is None
    assert result["millageRate"] == pytest.approx(0.0197)  # old total-based derivation
    assert "TOTAL taxes" in result["note"]


def test_projection_carries_non_ad_valorem(monkeypatch):
    monkeypatch.setattr(
        property_tax,
        "lookup",
        lambda query, county=None: {
            "dataSource": "miami_dade",
            "millageRate": 0.02,
            "nonAdValorem": 7_600,
            "jurisdiction": "Miami-Dade County, FL",
        },
    )
    client = TestClient(app)
    body = client.post(
        "/api/property-tax/lookup",
        json={"query": "x", "purchasePrice": 10_000_000, "assessmentRatio": 0.85},
    ).json()
    assert body["projection"]["projectedAdValorem"] == pytest.approx(170_000)
    assert body["projection"]["carriedNonAdValorem"] == pytest.approx(7_600)
    assert body["projection"]["projectedAnnualTaxes"] == pytest.approx(177_600)


def test_engine_non_ad_valorem_line(analytic):
    result = engine.compute({
        **analytic,
        "expenseGrowthMode": "per_year", "expenseGrowthPct": 0.02,
        "nonAdValoremTaxes": 12_000,
        "nonAdValoremGrowthPct": 0.05,
    })
    by_cat = result["statement"]["fixedOpexByCategory"]
    nav = by_cat["nonAdValorem"]
    assert nav[1] == pytest.approx(1_000)
    assert nav[13] == pytest.approx(1_050)  # its OWN 5% clock
    taxes = by_cat["realEstateTaxes"]
    assert taxes[13] == pytest.approx(taxes[1] * 1.02)  # deal growth untouched


def test_reassessment_leaves_non_ad_valorem_untouched(analytic):
    result = engine.compute({
        **analytic,
        "nonAdValoremTaxes": 12_000,
        "useReassessedTaxes": True,
        "millageRatePct": 0.02, "assessmentRatio": 0.85,
    })
    by_cat = result["statement"]["fixedOpexByCategory"]
    assert by_cat["realEstateTaxes"][1] == pytest.approx(1_000_000 * 0.85 * 0.02 / 12)
    assert by_cat["nonAdValorem"][1] == pytest.approx(1_000)  # not reset


def test_non_ad_valorem_recoverable_default_feeds_nnn():
    lease_deal = {
        "commercialLeases": [{
            "tenant": "T", "suiteId": "1", "sf": 5_000,
            "startDate": "2026-01-01", "endDate": "2033-12-31",
            "baseRentPsfAnnual": 20, "escalationType": "none",
            "recoveryType": "NNN", "freeRentMonths": 0,
        }],
        "creditLossPct": 0, "rentGrowthMode": "flat", "expenseGrowthMode": "flat",
        "realEstateTaxes": 36_000,
        "nonAdValoremTaxes": 6_000,
    }
    from app.services.proforma.timeline import Timeline

    ops = operations.build_noi_vector(lease_deal, Timeline(12, 0, 0, 1))
    assert ops["recoveries"][0] == pytest.approx(3_000 + 500)  # default: recoverable

    ops_off = operations.build_noi_vector(
        {**lease_deal, "nonAdValoremRecoverable": False}, Timeline(12, 0, 0, 1)
    )
    assert ops_off["recoveries"][0] == pytest.approx(3_000)


def test_reassessed_tax_growth_override(analytic):
    """Taxes grow at their own rate while other categories keep the deal's
    expense growth."""
    result = engine.compute({
        **analytic,
        "utilities": 6_000,
        "expenseGrowthMode": "per_year", "expenseGrowthPct": 0.02,
        "useReassessedTaxes": True,
        "millageRatePct": 0.02, "assessmentRatio": 0.85,
        "reassessedTaxGrowthPct": 0.05,
    })
    by_cat = result["statement"]["fixedOpexByCategory"]
    taxes = by_cat["realEstateTaxes"]
    assert taxes[13] == pytest.approx(taxes[1] * 1.05)
    other = by_cat["utilities"]
    assert other[13] == pytest.approx(other[1] * 1.02)
