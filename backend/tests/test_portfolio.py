"""J15: portfolio roll-up — aggregation, equity-weighted blends, stale
(uncomputable) exclusion, and empty states. Pure-function tests on
build_portfolio plus a thin endpoint check."""

import json
from pathlib import Path

import pytest

from app.services import compute_cache, portfolio
from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"


def analytic(**overrides) -> dict:
    deal = json.loads((FIXTURES / "analytic_acquisition.json").read_text())
    deal.update(overrides)
    return deal


def _deal(id_, name, status, inputs):
    return {"id": id_, "name": name, "status": status, "inputs": inputs}


def test_empty_portfolio():
    roll = portfolio.build_portfolio([])
    assert roll["dealCount"] == 0
    assert roll["blendedLeveredIrr"] is None
    assert roll["totals"]["equity"] == 0
    assert roll["deals"] == [] and roll["excluded"] == []


def test_dead_deals_are_dropped_entirely():
    roll = portfolio.build_portfolio([
        _deal("d1", "Live", "underwriting", analytic(market="Austin")),
        _deal("d2", "Dead", "dead", analytic(market="Austin")),
    ])
    assert roll["dealCount"] == 1
    assert [d["name"] for d in roll["deals"]] == ["Live"]


def test_totals_and_equity_weighted_blend():
    """Two computable deals. The analytic deal has 400,000 equity and a known
    levered IRR; a second deal at double scale (2x price/rent/loan/equity)
    has the SAME IRR but 800,000 equity. Equity-weighted blend = that IRR."""
    base = engine.compute(analytic())
    base_irr = base["outputs"]["leveredIrr"]
    base_mult = base["outputs"]["equityMultiple"]

    doubled = analytic(
        purchasePrice=2_000_000, grossPotentialRent=200_000, loanAmount=1_200_000,
        realEstateTaxes=20_000, totalEquity=800_000,
    )
    roll = portfolio.build_portfolio([
        _deal("d1", "Base", "underwriting", analytic(market="Austin")),
        _deal("d2", "Double", "loi", doubled | {"market": "Dallas"}),
    ])

    assert roll["dealCount"] == 2
    # Equity committed = 400k + 800k.
    assert roll["totals"]["equity"] == pytest.approx(1_200_000, rel=1e-6)
    # Same IRR on both -> blend equals it regardless of weights.
    assert roll["blendedLeveredIrr"] == pytest.approx(base_irr, rel=1e-6)
    assert roll["blendedEquityMultiple"] == pytest.approx(base_mult, rel=1e-6)
    # Exposure + concentration by market.
    markets = {r["market"]: r["equity"] for r in roll["exposureByMarket"]}
    assert markets["Dallas"] == pytest.approx(800_000, rel=1e-6)
    assert roll["concentration"][0]["market"] == "Dallas"
    assert roll["concentration"][0]["sharePct"] == pytest.approx(800_000 / 1_200_000, rel=1e-6)


def test_blend_is_actually_equity_weighted():
    """Different IRRs -> the blend must lean toward the larger-equity deal.
    Deal A: 400k equity. Deal B: bigger equity, lower IRR. Blend must sit
    between the two and closer to B."""
    a = analytic(market="A")
    # B: a development-scale acquisition with more equity and a weaker exit.
    b = analytic(purchasePrice=5_000_000, grossPotentialRent=400_000,
                 loanAmount=2_000_000, realEstateTaxes=60_000,
                 exitCapRatePct=0.09, market="B")
    roll = portfolio.build_portfolio([
        _deal("a", "A", "underwriting", a), _deal("b", "B", "underwriting", b),
    ])
    irr_a = engine.compute(a)["outputs"]["leveredIrr"]
    irr_b = engine.compute(b)["outputs"]["leveredIrr"]
    eq_a = -engine.compute(a)["statement"]["levered"][0]
    eq_b = -engine.compute(b)["statement"]["levered"][0]
    expected = (eq_a * irr_a + eq_b * irr_b) / (eq_a + eq_b)
    assert roll["blendedLeveredIrr"] == pytest.approx(expected, rel=1e-6)
    assert min(irr_a, irr_b) < roll["blendedLeveredIrr"] < max(irr_a, irr_b)


def test_uncomputable_deals_are_excluded_and_listed():
    roll = portfolio.build_portfolio([
        _deal("d1", "Good", "underwriting", analytic()),
        _deal("d2", "Half-entered", "screening", {"dealName": "WIP", "dealType": "acquisition"}),
    ])
    assert roll["dealCount"] == 1
    assert roll["excludedCount"] == 1
    assert roll["excluded"][0]["name"] == "Half-entered"
    assert "missing inputs" in roll["excluded"][0]["reason"]
    # The excluded deal contributes to NO total.
    assert roll["totals"]["equity"] == pytest.approx(400_000, rel=1e-6)


def test_by_deal_type_aggregation():
    """Typed deals bucket by dealflow; a deal without a type lands in
    'untyped' rather than being guessed."""
    dev = analytic()
    dev.pop("purchasePrice")
    dev.update({
        "dealType": "development", "landCost": 300_000, "hardCosts": 500_000,
        "softCosts": 100_000, "constructionMonths": 12, "market": "Austin",
    })
    untyped = analytic()
    untyped.pop("dealType")
    roll = portfolio.build_portfolio([
        _deal("a", "Acq", "underwriting", analytic()),
        _deal("b", "Dev", "construction", dev),
        _deal("c", "Old", "screening", untyped),
    ])
    # The untyped deal can't compute (engine requires dealType) -> excluded,
    # so byDealType only carries the two real flows.
    by_type = {row["dealType"]: row for row in roll["byDealType"]}
    assert by_type["acquisition"]["count"] == 1
    assert by_type["development"]["count"] == 1
    assert by_type["acquisition"]["equity"] == pytest.approx(400_000, rel=1e-6)
    assert roll["excludedCount"] == 1
    # Each computed deal row names its flow.
    assert {d["dealType"] for d in roll["deals"]} == {"acquisition", "development"}


def test_units_and_sf_aggregate():
    mf = analytic(unitMix=[{"unitType": "1BR", "unitCount": 50, "avgSf": 800,
                            "inPlaceRent": 1500, "marketRent": 1500}])
    roll = portfolio.build_portfolio([_deal("d1", "MF", "underwriting", mf)])
    assert roll["totals"]["units"] == pytest.approx(50)
    assert roll["totals"]["sf"] == pytest.approx(50 * 800)


def test_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database import Base, get_db
    from app.main import app

    db_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(db_engine)
    TestSession = sessionmaker(bind=db_engine)

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    compute_cache.clear()
    client = TestClient(app)
    deal = client.post("/api/deals", json={"name": "Endpoint Deal"}).json()
    client.put(f"/api/deals/{deal['id']}", json={"inputs": analytic(market="Miami")})

    roll = client.get("/api/portfolio").json()
    assert roll["dealCount"] == 1
    assert roll["blendedLeveredIrr"] is not None

    csv_text = client.get("/api/portfolio/export.csv").text
    assert "PORTFOLIO" in csv_text and "Endpoint Deal" in csv_text
    app.dependency_overrides.pop(get_db)
    db_engine.dispose()
