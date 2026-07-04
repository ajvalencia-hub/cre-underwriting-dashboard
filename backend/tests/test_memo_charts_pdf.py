"""G8: memo charts (image parts present, chartless degradation) and the PDF
variant (real conversion when soffice exists, skip-with-reason otherwise,
409 wiring)."""

import io
import json
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services import memo_charts, memo_service, soffice
from app.services.proforma import engine, hold

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


def _saved_sensitivity() -> dict:
    return {
        "description": "Levered IRR — cap × growth",
        "header": ["cap \\ growth", "2%", "4%"],
        "rows": [["6%", "11%", "12%"], ["7%", "9%", "10%"]],
        "run": {
            "mode": "native",
            "drivers": [
                {"fieldId": "exitCapRatePct", "values": [0.06, 0.07]},
                {"fieldId": "rentGrowthPct", "values": [0.02, 0.04]},
            ],
            "outputFieldIds": ["leveredIrr"],
            "points": [
                {"driverValues": {"exitCapRatePct": c, "rentGrowthPct": g},
                 "outputs": {"leveredIrr": 0.1 + g - c}, "warnings": []}
                for c in (0.06, 0.07) for g in (0.02, 0.04)
            ],
        },
    }


def test_memo_with_all_charts_contains_image_parts(analytic):
    computed = engine.compute(analytic)
    memo_bytes = memo_service.build_memo(
        deal_name="Charted", scenario_name="Base", inputs=analytic,
        outputs=computed["outputs"], debt=computed["debt"],
        sources_and_uses=computed["sourcesAndUses"],
        sensitivity=_saved_sensitivity(),
        statement=computed["statement"],
        hold_sweep=hold.hold_sweep(analytic),
    )
    doc = Document(io.BytesIO(memo_bytes))
    # sources&uses bars + annual CF bars + hold sweep line + heatmap
    assert len(doc.inline_shapes) == 4
    image_parts = [p for p in doc.part.package.parts if p.partname.startswith("/word/media/")]
    assert len(image_parts) == 4
    assert all(part.blob[:8] == b"\x89PNG\r\n\x1a\n" for part in image_parts)


def test_chartless_memo_degrades_cleanly():
    memo_bytes = memo_service.build_memo(
        deal_name="Bare", scenario_name="S", inputs={}, outputs={"equityMultiple": 1.4},
    )
    doc = Document(io.BytesIO(memo_bytes))
    assert len(doc.inline_shapes) == 0


def test_chart_renderers_return_none_on_unusable_data():
    assert memo_charts.sensitivity_heatmap(None) is None
    assert memo_charts.sensitivity_heatmap({"run": {"drivers": [{"fieldId": "x", "values": [1]}]}}) is None
    assert memo_charts.annual_cashflow_bars(None) is None
    assert memo_charts.sources_uses_bars({"uses": [], "sources": []}) is None
    assert memo_charts.hold_sweep_line({"rows": [{"holdYear": 1, "leveredIrr": 0.1}]}) is None


# ------------------------------------------------------------------ PDF

@pytest.fixture
def client():
    sql_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(sql_engine)
    TestSession = sessionmaker(bind=sql_engine)

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db)
    sql_engine.dispose()


def _full_scenario(client, analytic) -> str:
    from app.models import Scenario

    db = next(app.dependency_overrides[get_db]())
    row = Scenario(scenario_name="Base", kind="full", inputs=analytic, outputs={})
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def test_pdf_variant(client, analytic, monkeypatch):
    from app.routers import scenarios as scenarios_router

    monkeypatch.setattr(
        scenarios_router.benchmarks, "build_benchmarks",
        lambda *a, **k: {"location": {}, "flags": [], "unavailable": []},
    )
    scenario_id = _full_scenario(client, analytic)

    if not soffice.is_available():
        resp = client.post(f"/api/scenarios/{scenario_id}/memo?format=pdf", json={})
        assert resp.status_code == 409
        pytest.skip("LibreOffice not installed — 409 contract verified, conversion skipped")

    resp = client.post(f"/api/scenarios/{scenario_id}/memo?format=pdf", json={})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content[:5] == b"%PDF-"
    assert "filename" in resp.headers["content-disposition"]


def test_pdf_409_when_soffice_missing(client, analytic, monkeypatch):
    monkeypatch.setattr(soffice, "LIBREOFFICE_BIN", None)
    scenario_id = _full_scenario(client, analytic)
    resp = client.post(f"/api/scenarios/{scenario_id}/memo?format=pdf", json={})
    assert resp.status_code == 409
    assert "LibreOffice" in resp.json()["detail"]


def test_bad_format_rejected(client, analytic):
    scenario_id = _full_scenario(client, analytic)
    assert client.post(f"/api/scenarios/{scenario_id}/memo?format=rtf", json={}).status_code == 400
