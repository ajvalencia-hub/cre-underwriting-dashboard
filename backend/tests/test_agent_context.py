"""K8: the compact deal-context seed — a summary string, not a source of
truth (the model still must call a tool before stating a number from it)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Deal
from app.services.agent import context


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()
    engine.dispose()


def test_missing_deal_returns_empty_string(db):
    assert context.build_context_seed(db, "not-a-real-id") == ""


def test_seed_includes_name_status_type_market_and_key_inputs(db):
    deal = Deal(
        name="648 NE 80th St",
        status="underwriting",
        inputs={
            "dealType": "acquisition",
            "propertyType": "multifamily",
            "market": "Seattle",
            "purchasePrice": 1000000,
            "holdPeriodYears": 5,
        },
    )
    db.add(deal)
    db.commit()

    seed = context.build_context_seed(db, deal.id)

    assert "648 NE 80th St" in seed
    assert "underwriting" in seed
    assert "acquisition" in seed
    assert "multifamily" in seed
    assert "Seattle" in seed
    assert "purchasePrice" in seed


def test_seed_degrades_gracefully_for_a_bare_deal(db):
    deal = Deal(name="Untitled Deal", inputs={})
    db.add(deal)
    db.commit()

    seed = context.build_context_seed(db, deal.id)

    assert "Untitled Deal" in seed
    assert "screening" in seed  # default status
