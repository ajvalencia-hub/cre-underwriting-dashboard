"""Run 6 (API wave 2): `GET /api/deals?fields=summary` — the pipeline's
slim list shape (no inputs blob; dealType/dealName/address/market lifted
into `summary`). Opt-in; the default response is unchanged."""


def test_summary_shape_and_default_unchanged(client):
    full = client.post("/api/deals", json={"name": "Slim", "inputs": {
        "dealType": "acquisition", "dealName": "Slim", "address": "1 Main St",
        "market": "Austin", "purchasePrice": 1_000_000, "unitMix": [{"beds": 1}] * 50,
    }}).json()
    client.put(f"/api/deals/{full['id']}", json={"tags": ["core"], "status": "loi"})
    bare = client.post("/api/deals", json={"name": "Bare"}).json()

    rows = client.get("/api/deals?fields=summary").json()
    by_id = {r["id"]: r for r in rows}
    slim = by_id[full["id"]]
    assert "inputs" not in slim
    assert slim["summary"] == {
        "dealType": "acquisition", "dealName": "Slim", "address": "1 Main St", "market": "Austin",
    }
    assert slim["tags"] == ["core"] and slim["status"] == "loi" and slim["name"] == "Slim"
    assert {"id", "activeTemplateId", "activeMappingProfileId", "archivedAt", "createdAt", "updatedAt"} <= set(slim)
    assert by_id[bare["id"]]["summary"] == {
        "dealType": None, "dealName": None, "address": None, "market": None,
    }

    # Default and fields=full keep the blob.
    default_rows = {r["id"]: r for r in client.get("/api/deals").json()}
    assert default_rows[full["id"]]["inputs"]["purchasePrice"] == 1_000_000
    assert "summary" not in default_rows[full["id"]]
    assert "inputs" in client.get("/api/deals?fields=full").json()[0]
    assert client.get("/api/deals?fields=bogus").status_code == 422


def test_summary_combines_with_tag_and_archived_filters(client):
    a = client.post("/api/deals", json={"name": "A", "inputs": {"market": "Denver"}}).json()
    b = client.post("/api/deals", json={"name": "B"}).json()
    client.put(f"/api/deals/{a['id']}", json={"tags": ["Core"]})
    client.post(f"/api/deals/{b['id']}/archive")

    rows = client.get("/api/deals?fields=summary&tag=core").json()
    assert [r["id"] for r in rows] == [a["id"]]
    assert rows[0]["summary"]["market"] == "Denver"
    everything = client.get("/api/deals?fields=summary&includeArchived=true").json()
    assert {r["id"] for r in everything} == {a["id"], b["id"]}
    assert all("inputs" not in r for r in everything)
