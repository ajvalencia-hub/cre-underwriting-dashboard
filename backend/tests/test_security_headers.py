"""Browser-side hardening for content the app serves from its own origin."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.routers import file_cabinet


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(file_cabinet, "DOCUMENTS_DIR", tmp_path)
    db_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db_engine)
    TestSession = sessionmaker(bind=db_engine)

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db)
    db_engine.dispose()


def test_every_response_forbids_type_sniffing(client):
    assert client.get("/api/health").headers["X-Content-Type-Options"] == "nosniff"


def test_an_uploaded_svg_opens_sandboxed(client):
    deal = client.post("/api/deals", json={"name": "SVG"}).json()["id"]
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    att = client.post(f"/api/deals/{deal}/attachments", files={"file": ("x.svg", svg, "image/svg+xml")}).json()
    response = client.get(f"/api/deals/{deal}/attachments/{att['id']}/download?inline=true")
    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"].startswith("sandbox;")


def test_share_page_allows_no_scripts(client):
    deal = client.post("/api/deals", json={"name": "Share"}).json()["id"]
    response = client.get(f"/api/deals/{deal}/share.html")
    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"].startswith("default-src 'none'")


def test_compose_publishes_on_this_machine_only():
    from pathlib import Path

    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    assert '"127.0.0.1:8000:8000"' in compose and '- "8000:8000"' not in compose
