"""Port of Run 6 archive (soft delete) and clone onto the target, plus the
target-specific rules: archived deals leave metrics and the IC state list,
archiving works while IC-locked, and a clone starts in the draft IC state.
(Run 6's token-gate and archived_at migration tests are covered by
test_port_w0_auth_gate.py / test_schema_version.py.)"""

import json
from pathlib import Path

import pytest

_DEAL = json.loads((Path(__file__).parent / "fixtures" / "analytic_acquisition.json").read_text())
_DEAL.pop("_comment", None)


def _deal(client, name, inputs=None):
    return client.post("/api/deals", json={"name": name, "inputs": inputs or {}}).json()["id"]


def _submit(client, deal_id):
    response = client.post(
        f"/api/deals/{deal_id}/ic/events", json={"kind": "submit", "actor": "Ana", "comment": "Base"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["locked"] is True


# --- archive -------------------------------------------------------------------

def test_archive_hides_deal_from_list_portfolio_and_search(client):
    keep = _deal(client, "Keeper Court")
    gone = _deal(client, "Goner Court")
    client.post(f"/api/deals/{gone}/notes", json={"body": "remember this court"})

    out = client.post(f"/api/deals/{gone}/archive").json()
    assert out["archivedAt"] is not None
    # Idempotent: archiving again keeps the original timestamp.
    assert client.post(f"/api/deals/{gone}/archive").json()["archivedAt"] == out["archivedAt"]

    ids = {d["id"] for d in client.get("/api/deals").json()}
    assert ids == {keep}
    all_ids = {d["id"] for d in client.get("/api/deals?includeArchived=true").json()}
    assert all_ids == {keep, gone}
    # Still fetchable directly (nothing was destroyed).
    assert client.get(f"/api/deals/{gone}").status_code == 200
    assert client.get(f"/api/deals/{gone}/notes").json()[0]["body"] == "remember this court"

    search = client.get("/api/search?q=court").json()["groups"]
    titles = [i["title"] for g in search if g["kind"] == "deals" for i in g["items"]]
    assert titles == ["Keeper Court"]
    notes = [i for g in search if g["kind"] == "notes" for i in g["items"]]
    assert notes == []
    portfolio = client.get("/api/portfolio").json()
    portfolio_ids = {d["id"] for d in portfolio["deals"]} | {d["id"] for d in portfolio["excluded"]}
    assert gone not in portfolio_ids
    assert gone not in client.get("/api/deals/metrics").json()
    assert keep in client.get("/api/deals/metrics").json()

    back = client.post(f"/api/deals/{gone}/unarchive").json()
    assert back["archivedAt"] is None
    assert {d["id"] for d in client.get("/api/deals").json()} == {keep, gone}
    assert client.post("/api/deals/nope/archive").status_code == 404
    assert client.post("/api/deals/nope/unarchive").status_code == 404


def test_archive_is_allowed_while_ic_locked_and_leaves_the_ic_state_list(client):
    deal_id = _deal(client, "Locked", dict(_DEAL))
    _submit(client, deal_id)
    assert client.get("/api/ic/states").json() == {deal_id: "submitted"}

    archived = client.post(f"/api/deals/{deal_id}/archive")
    assert archived.status_code == 200
    assert client.get("/api/ic/states").json() == {}
    # The sign-off record itself is untouched.
    assert client.get(f"/api/deals/{deal_id}/ic").json()["state"] == "submitted"

    client.post(f"/api/deals/{deal_id}/unarchive")
    assert client.get("/api/ic/states").json() == {deal_id: "submitted"}


# --- clone -------------------------------------------------------------------

def test_clone_copies_inputs_stage_tags_and_scenarios_but_not_notes(client):
    source = _deal(client, "Original")
    client.put(f"/api/deals/{source}", json={
        "inputs": {"dealType": "acquisition", "purchasePrice": 1000000, "_omWizard": {"step": 2}},
        "status": "underwriting",
        "tags": ["Core", "Sunbelt"],
    })
    client.post(f"/api/deals/{source}/notes", json={"body": "private"})
    client.post("/api/scenarios", json={
        "scenarioName": "Base", "kind": "quickscreen", "dealId": source,
        "inputs": {"a": 1}, "outputs": {"b": 2},
    })

    response = client.post(f"/api/deals/{source}/clone")
    assert response.status_code == 200
    assert response.headers.get("ETag")
    clone = response.json()
    assert clone["id"] != source
    assert clone["name"] == "Copy of Original"
    assert clone["status"] == "underwriting"
    assert clone["tags"] == ["Core", "Sunbelt"]
    assert clone["inputs"]["purchasePrice"] == 1000000
    assert clone["inputs"]["dealName"] == "Copy of Original"
    assert "_omWizard" not in clone["inputs"]
    assert clone["archivedAt"] is None

    cloned_scenarios = client.get(f"/api/scenarios?deal_id={clone['id']}").json()
    assert [s["scenarioName"] for s in cloned_scenarios] == ["Base"]
    assert cloned_scenarios[0]["id"] != client.get(f"/api/scenarios?deal_id={source}").json()[0]["id"]
    assert client.get(f"/api/deals/{clone['id']}/notes").json() == []
    assert client.get(f"/api/deals/{clone['id']}/history").json() == []

    # Editing the clone does not touch the source.
    client.put(f"/api/deals/{clone['id']}", json={"inputs": {"purchasePrice": 5}})
    assert client.get(f"/api/deals/{source}").json()["inputs"]["purchasePrice"] == 1000000

    named = client.post(f"/api/deals/{source}/clone", json={"name": "Downside case"}).json()
    assert named["name"] == "Downside case"
    assert client.post("/api/deals/nope/clone").status_code == 404


def test_clone_of_an_ic_locked_deal_starts_in_draft_and_is_editable(client):
    source = _deal(client, "Signed off", dict(_DEAL))
    _submit(client, source)

    clone = client.post(f"/api/deals/{source}/clone").json()
    ic = client.get(f"/api/deals/{clone['id']}/ic").json()
    assert ic["state"] == "draft" and ic["locked"] is False and ic["events"] == []
    changed = client.put(
        f"/api/deals/{clone['id']}",
        json={"inputs": {**clone["inputs"], "purchasePrice": 1}},
    )
    assert changed.status_code == 200
    # The source is still locked.
    blocked = client.put(f"/api/deals/{source}", json={"inputs": {**_DEAL, "purchasePrice": 1}})
    assert blocked.status_code == 409


@pytest.mark.parametrize("archived_first", [False, True])
def test_clone_of_an_archived_deal_is_active(client, archived_first):
    source = _deal(client, "Old")
    if archived_first:
        client.post(f"/api/deals/{source}/archive")
    clone = client.post(f"/api/deals/{source}/clone").json()
    assert clone["archivedAt"] is None
    assert clone["id"] in {d["id"] for d in client.get("/api/deals").json()}
