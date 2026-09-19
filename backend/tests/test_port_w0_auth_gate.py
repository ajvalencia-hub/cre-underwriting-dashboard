"""Run 6 port (Wave 0): the optional CRE_API_TOKEN gate and the X-Request-ID
sanitization. Uses the shared `client` fixture from conftest.py."""

from app import auth, config


def test_no_token_configured_means_no_gate(client, monkeypatch):
    monkeypatch.setattr(config, "CRE_API_TOKEN", "")
    assert client.get("/api/deals").status_code == 200
    status = client.get("/api/auth/status").json()
    assert status == {"required": False, "authenticated": True}
    # Login is a harmless no-op when no token is configured.
    assert client.post("/api/auth/login", json={"token": "anything"}).json() == {
        "authenticated": True,
        "required": False,
    }


def test_token_gate_blocks_and_accepts_header_and_cookie(client, monkeypatch):
    monkeypatch.setattr(config, "CRE_API_TOKEN", "s3cret-token")
    # Public routes stay open.
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/status").json() == {"required": True, "authenticated": False}
    # Everything else is a 401 with a challenge.
    blocked = client.get("/api/deals")
    assert blocked.status_code == 401
    assert blocked.headers["www-authenticate"] == "Bearer"
    assert client.post("/api/deals", json={"name": "x"}).status_code == 401

    # Bearer header and X-API-Token both work; wrong values do not.
    assert client.get("/api/deals", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
    assert client.get("/api/deals", headers={"X-API-Token": "s3cret-token"}).status_code == 200
    assert client.get("/api/deals", headers={"Authorization": "Bearer nope"}).status_code == 401

    # Login sets an HttpOnly session cookie that carries an HMAC, never the token.
    bad = client.post("/api/auth/login", json={"token": "wrong"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/login", json={"token": "s3cret-token"})
    assert ok.status_code == 200
    cookie = client.cookies.get(auth.SESSION_COOKIE)
    assert cookie and "s3cret-token" not in cookie
    assert "httponly" in ok.headers["set-cookie"].lower()
    assert client.get("/api/deals").status_code == 200
    assert client.get("/api/auth/status").json()["authenticated"] is True

    # Rotating the token invalidates the old cookie; logout clears it.
    monkeypatch.setattr(config, "CRE_API_TOKEN", "rotated")
    assert client.get("/api/deals").status_code == 401
    monkeypatch.setattr(config, "CRE_API_TOKEN", "s3cret-token")
    assert client.get("/api/deals").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/deals").status_code == 401


def test_non_api_paths_are_never_gated(client, monkeypatch):
    monkeypatch.setattr(config, "CRE_API_TOKEN", "tok")
    # The SPA (or a 404 for it in tests) must not turn into a 401.
    assert client.get("/").status_code != 401


def test_a_401_still_carries_a_request_id(client, monkeypatch):
    """The token gate runs inside the request-id middleware, so a rejected
    request is logged and echoed with its id like any other."""
    monkeypatch.setattr(config, "CRE_API_TOKEN", "tok")
    blocked = client.get("/api/deals", headers={"X-Request-ID": "abc-123"})
    assert blocked.status_code == 401
    assert blocked.headers["x-request-id"] == "abc-123"
    assert blocked.headers["x-content-type-options"] == "nosniff"


def test_request_id_is_sanitized_and_bounded(client):
    forged = client.get("/api/health", headers={"X-Request-ID": "ok id\tINFO fake line"})
    assert forged.headers["x-request-id"] == "okidINFOfakeline"
    long_id = client.get("/api/health", headers={"X-Request-ID": "a" * 200})
    assert long_id.headers["x-request-id"] == "a" * 64
    kept = client.get("/api/health", headers={"X-Request-ID": "Abc.def_1-2"})
    assert kept.headers["x-request-id"] == "Abc.def_1-2"
    # Nothing usable left -> a generated id instead of an empty header.
    generated = client.get("/api/health", headers={"X-Request-ID": "!!!"})
    assert len(generated.headers["x-request-id"]) == 12


def test_cors_exposes_etag_and_retry_after(client):
    resp = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    exposed = {h.strip().lower() for h in resp.headers["access-control-expose-headers"].split(",")}
    assert {"etag", "retry-after"} <= exposed
