"""K3: agent tool surface — read tools wrap existing services correctly,
write tools validate + preview without ever touching the DB, and the
privilege split (no db/Session param on any write tool) is structurally
enforced here, not just documented in a docstring."""

import inspect
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Deal, SaleComp, Scenario
from app.services.agent.tools import read_tools, write_tools
from app.services.agent.tools.registry import ALL_TOOLS, to_tool_specs

FIXTURES = Path(__file__).parent / "fixtures"


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


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


# ---------------------------------------------------------------------------
# Structural privilege-split enforcement — the actual guarantee
# ---------------------------------------------------------------------------

def test_write_tools_never_accept_a_db_session():
    write_defs = [t for t in ALL_TOOLS.values() if t.privilege == "write"]
    assert write_defs, "expected at least one write tool to be registered"
    for tool in write_defs:
        sig = inspect.signature(tool.fn)
        for name, param in sig.parameters.items():
            assert name != "db", f"{tool.name} must not accept a db/Session parameter"
            assert param.annotation is not Session, f"{tool.name} must not accept a Session-typed parameter"


def test_read_tools_all_accept_db_first():
    for tool in ALL_TOOLS.values():
        if tool.privilege != "read":
            continue
        params = list(inspect.signature(tool.fn).parameters)
        assert params[0] == "db", f"{tool.name} should take db as its first parameter"


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

def test_get_deal_happy_path_and_missing(db, analytic):
    deal = Deal(name="Test Deal", inputs=analytic)
    db.add(deal)
    db.commit()

    out = read_tools.get_deal(db, deal.id)
    assert out["name"] == "Test Deal"
    assert out["inputs"]["purchasePrice"] == 1000000

    missing = read_tools.get_deal(db, "not-a-real-id")
    assert "error" in missing


def test_list_and_get_scenario(db, analytic):
    deal = Deal(name="Test Deal", inputs=analytic)
    db.add(deal)
    db.commit()
    scenario = Scenario(
        scenario_name="Base Case", kind="full", deal_id=deal.id,
        inputs=analytic, outputs={"leveredIrr": 0.1},
    )
    db.add(scenario)
    db.commit()

    listing = read_tools.list_scenarios(db, deal.id)
    assert listing["scenarios"][0]["scenarioName"] == "Base Case"

    detail = read_tools.get_scenario(db, scenario.id)
    assert detail["outputs"]["leveredIrr"] == 0.1

    missing = read_tools.get_scenario(db, "nope")
    assert "error" in missing


def test_compute_tool_happy_path_and_insufficient(db, analytic):
    out = read_tools.compute(db, analytic)
    assert "leveredIrr" in out["outputs"]

    bad = read_tools.compute(db, {"dealType": "acquisition"})
    assert "error" in bad
    assert "missing" in bad


def test_solve_tool_happy_path_and_error(db, analytic):
    from app.services.proforma import engine as engine_mod

    target = engine_mod.compute(analytic)["outputs"]["leveredIrr"]
    out = read_tools.solve(
        db, analytic, targetField="exitCapRatePct", targetMetric="leveredIrr",
        targetValue=target, lowerBound=0.05, upperBound=0.12, tolerance=1e-6,
    )
    assert out["fieldValue"] == pytest.approx(0.08, abs=1e-4)

    bad = read_tools.solve(
        db, analytic, targetField="exitCapRatePct", targetMetric="leveredIrr",
        targetValue=1.0, lowerBound=0.05, upperBound=0.12,
    )
    assert "error" in bad


def test_run_tornado_tool(db, analytic):
    out = read_tools.run_tornado(db, analytic, "leveredIrr")
    assert len(out["bars"]) == 6


def test_run_sensitivity_tool(db, analytic):
    out = read_tools.run_sensitivity(
        db, analytic, [{"fieldId": "exitCapRatePct", "values": [0.07, 0.08, 0.09]}], ["leveredIrr"]
    )
    assert len(out["points"]) == 3


def test_list_comps_tool(db):
    db.add(SaleComp(name="123 Main St", market="Seattle", price=1000000, units=10, cap_rate_pct=0.05))
    db.commit()
    out = read_tools.list_comps(db, "sale", "Seattle")
    assert out["count"] == 1
    assert out["comps"][0]["name"] == "123 Main St"

    empty = read_tools.list_comps(db, "sale", "Nowhere")
    assert empty["count"] == 0

    bad = read_tools.list_comps(db, "bogus")
    assert "error" in bad


def test_get_schema_tool(db):
    out = read_tools.get_schema(db)
    ids = {f["id"] for f in out["fields"]}
    assert "purchasePrice" in ids
    assert "leveredIrr" in ids  # outputs included


# ---------------------------------------------------------------------------
# Write tools — validation, preview, no DB access at all
# ---------------------------------------------------------------------------

def test_propose_input_changes_happy_path(analytic):
    proposal = write_tools.propose_input_changes(
        analytic, {"exitCapRatePct": 0.075}, "Lower exit cap given recent comps."
    )
    assert proposal.kind == "input_changes"
    assert proposal.changes == {"exitCapRatePct": 0.075}
    assert proposal.warnings == []
    assert proposal.preview is not None
    assert "leveredIrr" in proposal.preview["outputs"]


def test_propose_input_changes_drops_unknown_field(analytic):
    proposal = write_tools.propose_input_changes(
        analytic, {"notARealField": 123, "exitCapRatePct": 0.075}, "test"
    )
    assert "notARealField" not in proposal.changes
    assert "exitCapRatePct" in proposal.changes
    assert any("notARealField" in w for w in proposal.warnings)


def test_propose_input_changes_drops_wrong_type(analytic):
    proposal = write_tools.propose_input_changes(analytic, {"exitCapRatePct": "not a number"}, "test")
    assert "exitCapRatePct" not in proposal.changes
    assert any("exitCapRatePct" in w for w in proposal.warnings)


def test_propose_input_changes_rejects_bad_enum_value(analytic):
    proposal = write_tools.propose_input_changes(analytic, {"dealType": "not_a_real_type"}, "test")
    assert "dealType" not in proposal.changes
    assert any("dealType" in w for w in proposal.warnings)


def test_propose_input_changes_preview_reflects_insufficient_inputs():
    proposal = write_tools.propose_input_changes({}, {"purchasePrice": 500000}, "test")
    assert proposal.preview is None
    assert any("missing inputs" in w for w in proposal.warnings)


def test_propose_scenario_happy_path(analytic):
    proposal = write_tools.propose_scenario(
        "Downside Case", analytic, {"exitCapRatePct": 0.09}, "Stress test a wider exit cap."
    )
    assert proposal.kind == "scenario"
    assert proposal.scenarioName == "Downside Case"
    assert proposal.changes == {"exitCapRatePct": 0.09}


# ---------------------------------------------------------------------------
# Registry / tool-spec generation
# ---------------------------------------------------------------------------

def test_registry_has_expected_read_and_write_tools():
    names = set(ALL_TOOLS)
    assert {"get_deal", "compute", "solve", "propose_input_changes", "propose_scenario"} <= names
    privileges = {t.name: t.privilege for t in ALL_TOOLS.values()}
    assert privileges["propose_input_changes"] == "write"
    assert privileges["propose_scenario"] == "write"
    assert privileges["get_deal"] == "read"


def test_to_tool_specs_all_and_subset():
    all_specs = to_tool_specs()
    assert len(all_specs) == len(ALL_TOOLS)

    subset = to_tool_specs(["get_deal", "compute"])
    assert {s.name for s in subset} == {"get_deal", "compute"}
