"""Run 6 (API wave 2): deal tags — column + migration, normalization on
write, list filter, bulk add/remove, the search `tag:` facet, export/import
round-trip and clone."""

from sqlalchemy import create_engine, inspect, text

from app.database import run_migrations
from app.models import SaleComp


def _deal(client, name, tags=None, inputs=None):
    deal = client.post("/api/deals", json={"name": name, "inputs": inputs or {}}).json()
    assert deal["tags"] == []
    if tags is not None:
        deal = client.put(f"/api/deals/{deal['id']}", json={"tags": tags}).json()
    return deal


# --- PUT + normalization -----------------------------------------------------

def test_put_tags_normalizes_and_is_partial(client):
    deal = _deal(client, "Tagged", inputs={"x": 1})
    out = client.put(
        f"/api/deals/{deal['id']}",
        json={"tags": ["  Core ", "core", "CORE", "", "  ", "1031", "Value-Add"]},
    ).json()
    # First spelling wins; case-insensitive dedupe; empties dropped.
    assert out["tags"] == ["Core", "1031", "Value-Add"]
    assert out["inputs"] == {"x": 1}  # tags-only PUT touches nothing else

    # A PUT without `tags` leaves them alone; an explicit [] clears them.
    assert client.put(f"/api/deals/{deal['id']}", json={"name": "Still"}).json()["tags"] == [
        "Core", "1031", "Value-Add",
    ]
    assert client.put(f"/api/deals/{deal['id']}", json={"tags": []}).json()["tags"] == []


def test_tag_caps_are_422(client):
    deal = _deal(client, "Capped")
    too_long = client.put(f"/api/deals/{deal['id']}", json={"tags": ["x" * 41]})
    assert too_long.status_code == 422
    too_many = client.put(
        f"/api/deals/{deal['id']}", json={"tags": [f"t{i}" for i in range(21)]}
    )
    assert too_many.status_code == 422
    not_strings = client.put(f"/api/deals/{deal['id']}", json={"tags": [1, 2]})
    assert not_strings.status_code == 422
    # Exactly at the caps is fine; dupes don't count toward the 20.
    ok = client.put(
        f"/api/deals/{deal['id']}",
        json={"tags": [f"t{i}" for i in range(20)] + ["T1", "x" * 40]},
    )
    assert ok.status_code == 422  # 21 distinct after adding the 40-char one
    ok = client.put(f"/api/deals/{deal['id']}", json={"tags": [f"t{i}" for i in range(20)] + ["T1"]})
    assert ok.status_code == 200 and len(ok.json()["tags"]) == 20


# --- list filter ----------------------------------------------------------------

def test_list_filters_by_tag_case_insensitively(client):
    core = _deal(client, "Core One", tags=["Core"])
    other = _deal(client, "Opportunistic", tags=["opp"])
    archived = _deal(client, "Archived Core", tags=["core"])
    client.post(f"/api/deals/{archived['id']}/archive")

    assert {d["id"] for d in client.get("/api/deals?tag=CORE").json()} == {core["id"]}
    assert {d["id"] for d in client.get("/api/deals?tag=core&includeArchived=true").json()} == {
        core["id"], archived["id"],
    }
    assert {d["id"] for d in client.get("/api/deals?tag=nope").json()} == set()
    # No filter -> both live deals, tags present on every row.
    rows = client.get("/api/deals").json()
    assert {d["id"] for d in rows} == {core["id"], other["id"]}
    assert all(isinstance(d["tags"], list) for d in rows)


# --- bulk-tags ------------------------------------------------------------------

def test_bulk_tags_adds_removes_and_reports_missing(client):
    a = _deal(client, "A", tags=["Core", "stale"])
    b = _deal(client, "B", tags=["STALE"])
    result = client.post(
        "/api/deals/bulk-tags",
        json={"dealIds": [a["id"], b["id"], "ghost"], "add": [" 1031 ", "core"], "remove": ["Stale"]},
    ).json()
    assert result["missing"] == ["ghost"]
    by_id = {d["id"]: d["tags"] for d in result["updated"]}
    assert by_id[a["id"]] == ["Core", "1031"]  # existing spelling kept, no dupe
    assert by_id[b["id"]] == ["1031", "core"]
    assert client.get(f"/api/deals/{a['id']}").json()["tags"] == ["Core", "1031"]

    assert client.post("/api/deals/bulk-tags", json={"dealIds": [], "add": ["x"]}).status_code == 400
    assert client.post("/api/deals/bulk-tags", json={"dealIds": [a["id"]]}).status_code == 400
    # A cap violation on any deal is a 422 and nothing is written.
    client.put(f"/api/deals/{b['id']}", json={"tags": [f"t{i}" for i in range(20)]})
    over = client.post(
        "/api/deals/bulk-tags", json={"dealIds": [a["id"], b["id"]], "add": ["one-more"]}
    )
    assert over.status_code == 422
    assert client.get(f"/api/deals/{a['id']}").json()["tags"] == ["Core", "1031"]


# --- search facet -----------------------------------------------------------

def test_search_tag_facet_and_items_carry_tags(client):
    core_acq = _deal(client, "Riverside Core", tags=["Core"], inputs={
        "dealType": "acquisition",
        "commercialLeases": [{"tenant": "Riverside Books", "sf": 900}],
    })
    _deal(client, "Riverside Plain", inputs={"dealType": "acquisition"})
    core_dev = _deal(client, "Riverside Tower", tags=["core", "ground-up"], inputs={
        "dealType": "development",
    })
    client.post(f"/api/deals/{core_dev['id']}/notes", json={"body": "Riverside permits filed"})
    db = client._session()  # type: ignore[attr-defined]
    db.add(SaleComp(name="Riverside Comp", market="Austin"))
    db.commit()
    db.close()

    plain = client.get("/api/search?q=riverside").json()
    assert plain["tagFilter"] is None
    deals = {d["title"]: d["tags"] for g in plain["groups"] if g["kind"] == "deals" for d in g["items"]}
    assert deals == {
        "Riverside Core": ["Core"], "Riverside Plain": [], "Riverside Tower": ["core", "ground-up"],
    }

    tagged = client.get("/api/search?q=tag:CORE riverside").json()
    assert tagged["tagFilter"] == "core"
    groups = {g["kind"]: g["items"] for g in tagged["groups"]}
    assert {d["dealId"] for d in groups["deals"]} == {core_acq["id"], core_dev["id"]}
    assert [t["title"] for t in groups["tenants"]] == ["Riverside Books"]
    assert groups["notes"][0]["dealId"] == core_dev["id"]
    assert "comps" not in groups  # global comps drop out of any faceted query

    # Both facets, either order.
    both = client.get("/api/search?q=acq:tag:core riverside").json()
    assert both["typeFilter"] == "acquisition" and both["tagFilter"] == "core"
    both_groups = {g["kind"]: g["items"] for g in both["groups"]}
    assert [d["title"] for d in both_groups["deals"]] == ["Riverside Core"]
    assert "notes" not in both_groups
    swapped = client.get("/api/search?q=tag:core dev:riverside").json()
    assert [d["title"] for g in swapped["groups"] if g["kind"] == "deals" for d in g["items"]] == [
        "Riverside Tower",
    ]
    # Facet with a too-short remainder returns nothing, not junk.
    assert client.get("/api/search?q=tag:core r").json()["groups"] == []


# --- export / import / clone --------------------------------------------------

def test_tags_round_trip_export_import_and_clone(client):
    deal = _deal(client, "Bundle Me", tags=["Core", "1031"])
    bundle = client.get(f"/api/deals/{deal['id']}/export").json()
    assert bundle["deal"]["tags"] == ["Core", "1031"]

    imported = client.post("/api/deals/import", json={"bundle": bundle}).json()
    assert imported["tags"] == ["Core", "1031"]

    legacy = {**bundle, "deal": {k: v for k, v in bundle["deal"].items() if k != "tags"}}
    old = client.post("/api/deals/import", json={"bundle": legacy}).json()
    assert old["tags"] == []
    assert not any("tags" in w for w in old["importWarnings"])

    junk = {**bundle, "deal": {**bundle["deal"], "tags": ["ok", 7, "x" * 41]}}
    bad = client.post("/api/deals/import", json={"bundle": junk}).json()
    assert bad["tags"] == []
    assert any("tags" in w for w in bad["importWarnings"])

    clone = client.post(f"/api/deals/{deal['id']}/clone").json()
    assert clone["tags"] == ["Core", "1031"]
    client.put(f"/api/deals/{clone['id']}", json={"tags": []})
    assert client.get(f"/api/deals/{deal['id']}").json()["tags"] == ["Core", "1031"]


# --- migration -------------------------------------------------------------------

def test_tags_migration_backfills_and_is_idempotent(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'pre_tags.sqlite3'}")
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE deals (id VARCHAR PRIMARY KEY, name VARCHAR, inputs JSON, "
            "status VARCHAR, active_template_id VARCHAR, active_mapping_profile_id VARCHAR, "
            "archived_at DATETIME, created_at DATETIME, updated_at DATETIME)"
        ))
        conn.execute(text(
            "INSERT INTO deals (id, name, inputs, status) VALUES ('d1', 'Old', '{}', 'screening')"
        ))
    run_migrations(eng)
    run_migrations(eng)
    assert "tags" in {c["name"] for c in inspect(eng).get_columns("deals")}
    with eng.connect() as conn:
        assert conn.execute(text("SELECT tags FROM deals WHERE id = 'd1'")).scalar() == "[]"
    eng.dispose()
