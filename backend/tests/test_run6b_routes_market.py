"""Run 6b: HTTP coverage for the rent-comp CRUD + multipart CSV import, and
the market routes (FRED rates, benchmarks, market context, demographics).
Every external source is monkeypatched at the module boundary — no test
here may reach the network."""

import httpx
import pytest

from app.services import benchmarks, market_context
from app.services.data_sources import fred

RENT_CSV = (
    "Property Name,Address,Market,Unit Type,Avg Rent,Avg SF,Occupancy,As Of\n"
    "Palm Court,100 Palm Ave,Miami,2BR,\"$2,100\",950,95%,2026-06-01\n"
    "Bayview Flats,200 Ocean St,Miami,1BR,1750,700,0.92,06/15/2026\n"
    "No Rent Here,300 Empty Rd,Miami,Studio,,500,90%,2026-06-01\n"
)


# ----------------------------------------------------------------- rent comps


def test_rent_comp_crud(client):
    assert client.get("/api/comps/rent").json() == []
    created = client.post(
        "/api/comps/rent",
        json={
            "name": "Palm Court", "market": "Miami", "submarket": "Brickell",
            "propertyType": "multifamily", "unitType": "2BR", "avgRent": 2100,
            "avgSf": 950, "occupancyPct": 0.95, "asOf": "2026-06-01",
        },
    )
    assert created.status_code == 200, created.text
    comp = created.json()
    assert comp["kind"] == "rent" and comp["name"] == "Palm Court"
    assert comp["avgRent"] == 2100 and comp["unitType"] == "2BR"
    assert comp["source"] == "manual"
    assert "pricePerUnit" not in comp  # sale-only derived fields stay off rent comps

    listed = client.get("/api/comps/rent", params={"market": "miami"}).json()
    assert [c["id"] for c in listed] == [comp["id"]]
    assert client.get("/api/comps/rent", params={"market": "Austin"}).json() == []

    updated = client.put(
        f"/api/comps/rent/{comp['id']}", json={"name": "Palm Court", "avgRent": 2250}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["avgRent"] == 2250
    assert updated.json()["unitType"] == "2BR"  # partial update keeps the rest

    assert client.delete(f"/api/comps/rent/{comp['id']}").json() == {"deleted": True}
    assert client.get("/api/comps/rent").json() == []


def test_create_comp_strips_surrounding_whitespace_from_name(client):
    # Regression: create_comp built the row with a stripped name and then
    # _apply() wrote the padded original back over it; text fields are now
    # trimmed inside _apply so create and update agree.
    created = client.post("/api/comps/rent", json={"name": "  Palm Court ", "avgRent": 1})
    assert created.status_code == 200
    assert created.json()["name"] == "Palm Court"


def test_rent_comp_error_paths(client):
    assert client.post("/api/comps/rent", json={"name": "   "}).status_code == 400
    assert client.post("/api/comps/lease", json={"name": "X"}).status_code == 400
    assert client.get("/api/comps/lease").status_code == 400
    assert client.put("/api/comps/rent/nope", json={"name": "X"}).status_code == 404
    assert client.delete("/api/comps/rent/nope").status_code == 404
    assert client.post("/api/comps/rent", json={"avgRent": 1}).status_code == 422


def test_rent_import_file_preview_then_import(client):
    preview = client.post(
        "/api/comps/import/file",
        data={"kind": "rent"},
        files={"file": ("rents.csv", RENT_CSV.encode("utf-8-sig"), "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["phase"] == "preview" and body["imported"] == 0
    assert body["rowCount"] == 3
    assert body["columns"][0] == "Property Name"  # BOM stripped
    assert body["suggestedMapping"]["avgRent"] == "Avg Rent"
    assert body["suggestedMapping"]["occupancyPct"] == "Occupancy"
    assert body["suggestedMapping"]["asOf"] == "As Of"
    assert body["csvText"].startswith("Property Name")
    assert body["duplicates"] == []
    assert client.get("/api/comps/rent").json() == []  # preview writes nothing

    imported = client.post(
        "/api/comps/import",
        json={"kind": "rent", "csvText": body["csvText"], "mapping": body["suggestedMapping"]},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["phase"] == "imported"
    assert imported.json()["imported"] == 2
    assert any("No Rent Here" in w for w in imported.json()["warnings"])

    by_name = {c["name"]: c for c in client.get("/api/comps/rent").json()}
    assert by_name["Palm Court"]["avgRent"] == pytest.approx(2100)
    assert by_name["Palm Court"]["occupancyPct"] == pytest.approx(0.95)
    assert by_name["Bayview Flats"]["asOf"] == "2026-06-15"
    assert by_name["Bayview Flats"]["source"] == "yardi_csv"


def test_rent_import_file_rejects_bad_kind_and_empty_csv(client):
    bad_kind = client.post(
        "/api/comps/import/file", data={"kind": "lease"},
        files={"file": ("rents.csv", RENT_CSV.encode(), "text/csv")},
    )
    assert bad_kind.status_code == 400
    empty = client.post(
        "/api/comps/import/file", data={"kind": "rent"},
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert empty.status_code == 400
    assert client.post("/api/comps/import/file", data={"kind": "rent"}).status_code == 422


# ------------------------------------------------------------------- market


class _FredResponse:
    def __init__(self, value: str):
        self._value = value

    def raise_for_status(self):
        pass

    def json(self):
        return {"observations": [{"value": self._value, "date": "2026-08-01"}]}


def test_market_rates_via_stubbed_fred(client, tmp_path, monkeypatch):
    monkeypatch.setattr(fred, "_cache_path", lambda: tmp_path / "market_rates.json")
    monkeypatch.setattr(fred, "FRED_API_KEY", "test-key")
    requested: list[str] = []

    def fake_get(url, params=None, timeout=None):
        requested.append(params["series_id"])
        return _FredResponse("4.35")

    monkeypatch.setattr(fred.httpx, "get", fake_get)
    response = client.get("/api/market/rates")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dataSource"] == "fred"
    assert body["rates"]["sofr"] == pytest.approx(0.0435)
    assert body["asOf"]["treasury10yrPct"] == "2026-08-01"
    assert set(requested) == {"SOFR", "DGS5", "DGS10", "MORTGAGE30US"}


def test_market_rates_degrade_without_key(client, tmp_path, monkeypatch):
    monkeypatch.setattr(fred, "_cache_path", lambda: tmp_path / "market_rates.json")
    monkeypatch.setattr(fred, "FRED_API_KEY", "")

    def explode(*args, **kwargs):
        raise AssertionError("no key -> no network call")

    monkeypatch.setattr(fred.httpx, "get", explode)
    body = client.get("/api/market/rates").json()
    assert body["dataSource"] == "unavailable"
    assert all(v is None for v in body["rates"].values())


@pytest.fixture
def stubbed_benchmark_sources(monkeypatch):
    monkeypatch.setattr(benchmarks, "cached_fetch", lambda key, fetch, ttl_seconds=0: fetch())
    monkeypatch.setattr(
        benchmarks.geocode, "geocode",
        lambda market, submarket="", address="": {
            "resolved": True, "lat": 30.2, "lon": -97.7,
            "stateFips": "48", "countyFips": "453", "countyName": "Travis",
            "tractCode": "001100", "cbsaCode": "12420", "cbsaName": "Austin",
        },
    )
    monkeypatch.setattr(
        benchmarks.census_acs, "get_demographics",
        lambda s, c: {"dataSource": "census_acs", "acsYear": "2022",
                      "medianGrossRent": 1500.0, "medianHouseholdIncome": 85000.0,
                      "population": 1300000},
    )
    monkeypatch.setattr(
        benchmarks.hud, "get_fair_market_rents",
        lambda s, c: {"dataSource": "hud", "fmrStudio": 1100, "fmr1BR": 1250,
                      "fmr2BR": 1350, "fmr3BR": 1750, "year": "2026"},
    )
    monkeypatch.setattr(
        benchmarks.fhfa, "get_home_price_appreciation",
        lambda cbsa: {"dataSource": "fhfa", "hpiYoYAppreciation": 0.03,
                      "metroName": "Austin", "asOf": "2026 Q1"},
    )
    monkeypatch.setattr(
        benchmarks.bls, "get_employment_trend",
        lambda s, c: {"dataSource": "bls", "employmentYoYGrowth": 0.02, "asOf": "May 2026"},
    )
    monkeypatch.setattr(
        benchmarks.fema, "get_flood_zone",
        lambda lat, lon: {"dataSource": "fema", "floodZone": "X", "description": "Minimal"},
    )


def test_market_benchmarks_endpoint_merges_public_and_comp_flags(client, stubbed_benchmark_sources):
    # Three Miami-free rent comps in Austin at ~1,450 so the comps-DB flag
    # fires alongside the public-source flags.
    for name, rent in (("A", 1400), ("B", 1450), ("C", 1500)):
        client.post(
            "/api/comps/rent",
            json={"name": name, "market": "Austin", "propertyType": "multifamily",
                  "unitType": "1BR", "avgRent": rent, "asOf": "2026-06-01"},
        )
    response = client.post(
        "/api/market/benchmarks",
        json={
            "address": "701 Congress Ave", "market": "Austin", "assetClass": "multifamily",
            "subject": {"avgRentMonthly": 1450, "rentGrowthPct": 0.03,
                        "expenseRatioPct": 0.45,
                        "bedroomMix": [{"bedrooms": 1, "count": 100}]},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    metrics = {f["metric"]: f for f in body["flags"]}
    assert {"rent_vs_market", "rent_growth_vs_hpa", "expense_ratio", "flood_zone",
            "employment_trend"} <= set(metrics)
    assert "rent_vs_comps" in metrics  # the comps-DB flag rides alongside
    assert body["unavailable"] == []
    assert all(f["source"] for f in body["flags"])


def test_market_benchmarks_empty_payload_is_still_200(client, stubbed_benchmark_sources):
    response = client.post("/api/market/benchmarks", json={})
    assert response.status_code == 200, response.text
    assert isinstance(response.json()["flags"], list)


@pytest.fixture
def stubbed_market_context(monkeypatch):
    monkeypatch.setattr(
        market_context.geocode, "geocode",
        lambda market, submarket="", address="": {
            "resolved": True, "lat": 30.2, "lon": -97.7, "stateFips": "48",
            "countyFips": "453", "cbsaCode": "12420",
        },
    )
    monkeypatch.setattr(
        market_context.census_acs, "get_demographics",
        lambda s, c: {"dataSource": "census_acs", "population": 1_300_000},
    )
    monkeypatch.setattr(
        market_context.bls, "get_unemployment_rate",
        lambda s, c: {"dataSource": "bls", "unemploymentRatePct": 0.035},
    )
    monkeypatch.setattr(
        market_context.bea, "get_income_growth",
        lambda s, c: {"dataSource": "bea", "incomeGrowthYoY": 0.04},
    )
    monkeypatch.setattr(
        market_context.fhfa, "get_home_price_appreciation",
        lambda cbsa: {"dataSource": "fhfa", "hpiYoYAppreciation": 0.03},
    )
    monkeypatch.setattr(
        market_context.hud, "get_fair_market_rents",
        lambda s, c: {"dataSource": "hud", "fmr2BR": 1350},
    )
    monkeypatch.setattr(
        market_context.fred, "get_macro_rates",
        lambda: {"dataSource": "fred", "sofr": 0.0435},
    )
    monkeypatch.setattr(
        market_context.fema, "get_flood_zone",
        lambda lat, lon: {"dataSource": "fema", "floodZone": "X"},
    )


def test_market_context_endpoint(client, stubbed_market_context):
    response = client.get(
        "/api/market-context",
        params={"market": "Austin", "submarket": "Downtown", "asset_class": "multifamily"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["market"] == "Austin" and body["assetClass"] == "multifamily"
    assert body["location"]["stateFips"] == "48"
    assert len(body["comps"]) == 4  # illustrative placeholder comps
    assert body["pricingTrends"]["capRateLow"] <= body["pricingTrends"]["capRateHigh"]
    assert body["demographics"]["dataSource"] == "census_acs"
    # BEA income merges onto the BLS labor block; HUD merges onto FHFA housing.
    assert body["laborMarket"]["unemploymentRatePct"] == pytest.approx(0.035)
    assert body["laborMarket"]["incomeGrowthYoY"] == pytest.approx(0.04)
    assert body["housing"]["hpiYoYAppreciation"] == pytest.approx(0.03)
    assert body["housing"]["fmr2BR"] == 1350
    assert body["macro"]["sofr"] == pytest.approx(0.0435)
    assert body["siteRisk"]["floodZone"] == "X"
    assert body["meta"]["dataSource"] == "mixed"

    # Deterministic placeholder pricing: same inputs -> same comps.
    again = client.get("/api/market-context", params={"market": "Austin", "submarket": "Downtown",
                                                      "asset_class": "multifamily"}).json()
    assert again["comps"] == body["comps"]


def test_market_context_requires_market(client, stubbed_market_context):
    assert client.get("/api/market-context").status_code == 422  # query param missing
    blank = client.get("/api/market-context", params={"market": "   "})
    assert blank.status_code == 400
    assert "market is required" in blank.json()["detail"]


# --------------------------------------------------------------- demographics


def test_demographics_requires_market_or_address(client):
    assert client.get("/api/demographics").status_code == 400
    assert client.get("/api/demographics", params={"market": "  "}).status_code == 400


def test_demographics_endpoint_with_stubbed_sources(client, monkeypatch):
    from app.services import demographics

    monkeypatch.setattr(demographics, "cached_fetch", lambda key, fetch, ttl_seconds=0: fetch())
    monkeypatch.setattr(
        demographics.geocode, "geocode",
        lambda market, submarket, address: {
            "resolved": True, "stateFips": "12", "countyFips": "086", "cbsaCode": "33100",
        },
    )
    monkeypatch.setattr(
        demographics.census_acs, "get_population_trend",
        lambda s, c: {"dataSource": "census_acs", "population": [{"period": "2022", "value": 1}]},
    )
    monkeypatch.setattr(
        demographics.bls, "get_employment_series",
        lambda s, c: {"dataSource": "unavailable", "note": "stubbed"},
    )
    monkeypatch.setattr(
        demographics.fhfa, "get_hpi_series",
        lambda c: {"dataSource": "fhfa", "hpiIndex": [{"period": "2025 Q1", "value": 400.0}]},
    )
    monkeypatch.setattr(
        demographics.bea, "get_income_series",
        lambda s, c: {"dataSource": "bea", "perCapitaPersonalIncome": []},
    )

    def no_network(*args, **kwargs):
        raise AssertionError("demographics must not hit the network")

    monkeypatch.setattr(httpx, "get", no_network)
    monkeypatch.setattr(httpx, "post", no_network)

    response = client.get("/api/demographics", params={"address": "1 Biscayne Blvd, Miami"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["population"]["dataSource"] == "census_acs"
    assert body["employment"]["dataSource"] == "unavailable"
    assert body["homePrices"]["hpiIndex"][0]["value"] == 400.0
    assert body["income"]["dataSource"] == "bea"
