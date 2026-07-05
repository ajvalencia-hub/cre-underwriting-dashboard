"""H6: demographics trend panel — series builders over mocked source APIs,
graceful degradation, and the composing service/router."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import demographics
from app.services.data_sources import bls, census_acs, fhfa


def test_bls_employment_series_parses_and_sorts(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        emp_id = json["seriesid"][0]
        unemp_id = json["seriesid"][1]
        body = {
            "Results": {
                "series": [
                    {
                        "seriesID": emp_id,
                        "data": [
                            {"year": "2026", "period": "M02", "value": "105000"},
                            {"year": "2026", "period": "M01", "value": "104000"},
                            {"year": "2025", "period": "M13", "value": "999999"},  # annual avg — skipped
                            {"year": "2025", "period": "M12", "value": "103000"},
                        ],
                    },
                    {
                        "seriesID": unemp_id,
                        "data": [{"year": "2026", "period": "M02", "value": "3.4"}],
                    },
                ]
            }
        }
        request = httpx.Request("POST", url)
        return httpx.Response(200, json=body, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)
    result = bls.get_employment_series("12", "086")
    assert result["dataSource"] == "bls"
    periods = [p["period"] for p in result["employmentLevel"]]
    assert periods == ["2025-12", "2026-01", "2026-02"]  # ascending, M13 dropped
    assert result["unemploymentRatePct"][0]["value"] == pytest.approx(0.034)


def test_bls_series_network_failure_degrades(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", fake_post)
    result = bls.get_employment_series("12", "086")
    assert result["dataSource"] == "unavailable"


def test_fhfa_hpi_series(monkeypatch):
    rows = [
        ["Miami-Fort Lauderdale, FL", "33100", "2024", "4", "410.2", "1.0"],
        ["Miami-Fort Lauderdale, FL", "33100", "2025", "1", "415.9", "1.0"],
        ["Miami-Fort Lauderdale, FL", "33100", "2025", "2", "-", "1.0"],  # missing point
        ["Somewhere Else", "99999", "2025", "1", "200.0", "1.0"],
    ]
    monkeypatch.setattr(fhfa, "_load_rows", lambda: rows)
    result = fhfa.get_hpi_series("33100")
    assert result["dataSource"] == "fhfa"
    assert [p["value"] for p in result["hpiIndex"]] == [410.2, 415.9]
    assert result["hpiIndex"][0]["period"] == "2024 Q4"

    assert fhfa.get_hpi_series("00000")["dataSource"] == "unavailable"
    assert fhfa.get_hpi_series(None)["dataSource"] == "unavailable"


def test_acs_population_trend_skips_failed_vintages(monkeypatch):
    monkeypatch.setattr(census_acs, "CENSUS_API_KEY", "test-key")

    def fake_get(url, params=None, timeout=None):
        year = int(url.split("/data/")[1].split("/")[0])
        request = httpx.Request("GET", url)
        if year == 2020:  # one vintage fails
            return httpx.Response(500, request=request)
        body = [["B01003_001E", "B19013_001E", "state", "county"],
                [str(2_600_000 + year), str(60_000 + year), "12", "086"]]
        return httpx.Response(200, json=body, request=request)

    monkeypatch.setattr(httpx, "get", fake_get)
    result = census_acs.get_population_trend("12", "086")
    assert result["dataSource"] == "census_acs"
    assert len(result["population"]) == 4  # 5 vintages minus the failed one
    assert result["population"][0]["period"] < result["population"][-1]["period"]


def test_service_composes_and_survives_source_failures(monkeypatch):
    monkeypatch.setattr(
        demographics,
        "cached_fetch",
        lambda key, fetch, ttl_seconds=0: fetch(),
    )
    monkeypatch.setattr(
        demographics.geocode,
        "geocode",
        lambda market, submarket, address: {
            "resolved": True, "stateFips": "12", "countyFips": "086", "cbsaCode": "33100",
        },
    )
    monkeypatch.setattr(
        demographics.census_acs,
        "get_population_trend",
        lambda s, c: {"dataSource": "census_acs", "population": [{"period": "2022", "value": 1}]},
    )
    monkeypatch.setattr(
        demographics.bls,
        "get_employment_series",
        lambda s, c: (_ for _ in ()).throw(RuntimeError("bug")),  # source BUG, not just failure
    )
    monkeypatch.setattr(
        demographics.fhfa, "get_hpi_series", lambda c: {"dataSource": "unavailable", "note": "x"}
    )
    monkeypatch.setattr(
        demographics.bea,
        "get_income_series",
        lambda s, c: {"dataSource": "bea", "perCapitaPersonalIncome": []},
    )
    result = demographics.get_demographic_trends("Miami", "", "")
    assert result["population"]["dataSource"] == "census_acs"
    assert result["employment"]["dataSource"] == "unavailable"  # bug -> note, not a crash
    assert result["homePrices"]["dataSource"] == "unavailable"
    assert result["income"]["dataSource"] == "bea"


def test_router_requires_market_or_address():
    client = TestClient(app)
    assert client.get("/api/demographics").status_code == 400
