"""Run 6 (API wave 2): optimistic concurrency on deals — ETag on every
single-deal response, If-Match on PUT (412 + current deal when stale,
last-writer-wins when absent, `*` always passes)."""


def _create(client, name="Concurrency Court"):
    resp = client.post("/api/deals", json={"name": name, "inputs": {"x": 1}})
    assert resp.status_code == 200
    return resp.json(), resp.headers["etag"]


def test_single_deal_responses_carry_a_quoted_etag(client):
    deal, etag = _create(client)
    assert etag.startswith('"') and etag.endswith('"') and len(etag) > 2
    # The tag is derived from updatedAt and stable across reads.
    got = client.get(f"/api/deals/{deal['id']}")
    assert got.headers["etag"] == etag
    assert client.get(f"/api/deals/{deal['id']}").headers["etag"] == etag

    for route in ("archive", "unarchive", "clone"):
        resp = client.post(f"/api/deals/{deal['id']}/{route}")
        assert resp.status_code == 200, route
        assert resp.headers.get("etag", "").startswith('"'), route

    # The list endpoint is unaffected (no ETag, same body shape as before).
    listing = client.get("/api/deals")
    assert listing.status_code == 200
    assert "etag" not in listing.headers
    assert all("inputs" in d for d in listing.json())


def test_stale_if_match_is_412_with_current_deal_and_writes_nothing(client):
    deal, stale = _create(client)
    first = client.put(f"/api/deals/{deal['id']}", json={"inputs": {"x": 2}})
    assert first.status_code == 200
    fresh = first.headers["etag"]
    assert fresh != stale

    stale_write = client.put(
        f"/api/deals/{deal['id']}", json={"inputs": {"x": 3}}, headers={"If-Match": stale}
    )
    assert stale_write.status_code == 412
    body = stale_write.json()
    assert body["detail"] == "Deal was modified elsewhere"
    assert body["current"]["id"] == deal["id"]
    assert body["current"]["inputs"] == {"x": 2}  # the winning write, untouched
    assert stale_write.headers["etag"] == fresh
    assert client.get(f"/api/deals/{deal['id']}").json()["inputs"] == {"x": 2}


def test_matching_if_match_succeeds_and_returns_a_new_etag(client):
    deal, etag = _create(client)
    ok = client.put(
        f"/api/deals/{deal['id']}", json={"inputs": {"x": 9}}, headers={"If-Match": etag}
    )
    assert ok.status_code == 200
    assert ok.json()["inputs"] == {"x": 9}
    assert ok.headers["etag"] != etag
    # Weak-validator prefix and a list are tolerated.
    weak = client.put(
        f"/api/deals/{deal['id']}", json={"name": "Renamed"},
        headers={"If-Match": f'W/{ok.headers["etag"]}'},
    )
    assert weak.status_code == 200


def test_absent_if_match_is_last_writer_wins_and_star_always_passes(client):
    deal, _ = _create(client)
    client.put(f"/api/deals/{deal['id']}", json={"inputs": {"x": 2}})
    plain = client.put(f"/api/deals/{deal['id']}", json={"inputs": {"x": 3}})
    assert plain.status_code == 200
    star = client.put(
        f"/api/deals/{deal['id']}", json={"inputs": {"x": 4}}, headers={"If-Match": "*"}
    )
    assert star.status_code == 200
    assert client.get(f"/api/deals/{deal['id']}").json()["inputs"] == {"x": 4}


def test_etag_is_cors_exposed():
    from app.main import app

    for middleware in app.user_middleware:
        if "expose_headers" in middleware.kwargs:
            exposed = {h.lower() for h in middleware.kwargs["expose_headers"]}
            assert {"etag", "retry-after"} <= exposed
            return
    raise AssertionError("CORS middleware not found")
