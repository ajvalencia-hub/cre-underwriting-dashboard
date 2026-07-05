"""H10: read-only HTML deal share — self-containment, pass-through numbers,
annual aggregation as sums of the engine's own vectors, escaping, and
graceful degradation for incomputable deals."""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services.proforma import engine as proforma_engine
from app.services.share_html import _annual_sums

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    TestSession = sessionmaker(bind=eng)

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db)
    eng.dispose()


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


def test_share_page_is_self_contained_and_passes_numbers_through(client, analytic):
    deal = client.post("/api/deals", json={"name": "Analytic", "inputs": analytic}).json()
    response = client.get(f"/api/deals/{deal['id']}/share.html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    page = response.text

    # Self-contained: no scripts, no external fetches of any kind.
    assert "<script" not in page.lower()
    assert "http://" not in page.replace("http://www.w3.org", "")
    assert "https://" not in page
    assert "url(" not in page

    # Pass-through numbers match a direct engine compute.
    result = proforma_engine.compute(analytic)
    levered_irr = result["outputs"]["leveredIrr"]
    assert f"{levered_irr * 100:.2f}%" in page
    # Year-1 NOI = sum of the engine's own monthly vector.
    noi_y1 = sum(result["statement"]["noi"][1:13])
    assert f"${noi_y1:,.0f}" in page
    assert "Read-only" in page


def test_share_page_escapes_hostile_deal_names(client, analytic):
    deal = client.post(
        "/api/deals",
        json={"name": "<script>alert(1)</script> & Sons", "inputs": analytic},
    ).json()
    response = client.get(f"/api/deals/{deal['id']}/share.html")
    page = response.text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    # Content-Disposition stripped to a safe filename.
    assert re.search(r'filename="[A-Za-z0-9 _.-]+-share\.html"', response.headers["content-disposition"])


def test_incomputable_deal_renders_an_error_page_not_a_500(client):
    deal = client.post("/api/deals", json={"name": "Empty", "inputs": {}}).json()
    response = client.get(f"/api/deals/{deal['id']}/share.html")
    assert response.status_code == 200
    assert "missing inputs" in response.text

    assert client.get("/api/deals/nope/share.html").status_code == 404


def test_annual_sums_bucket_operating_months_only():
    series = [999.0] + [100.0] * 18  # close month + 18 operating months
    sums = _annual_sums(series, 18)
    assert sums == [1200.0, 600.0]  # close month excluded, partial year 2
