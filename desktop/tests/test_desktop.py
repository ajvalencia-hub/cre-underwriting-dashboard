"""Desktop shell: the access gate, dialog filters, PATH handling and quit
cleanup. Run with:  desktop/.venv/bin/python -m pytest desktop/tests -q
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cre_desktop import paths  # noqa: E402
from cre_desktop.bridge import _file_types  # noqa: E402
from cre_desktop.server import AUTH_PATH, COOKIE_NAME, AccessGate  # noqa: E402

PORT = 51234
TOKEN = "t0ken-for-tests"


@pytest.fixture
def client():
    inner = FastAPI()

    @inner.get("/api/ping")
    def ping():
        return {"ok": True}

    gate = AccessGate(inner, TOKEN, PORT)
    return TestClient(gate, base_url=f"http://127.0.0.1:{PORT}")


def test_gate_refuses_requests_without_the_window_cookie(client):
    r = client.get("/api/ping")
    assert r.status_code == 403
    assert "only answers the CRE Underwriting window" in r.text


def test_gate_auth_sets_a_strict_httponly_cookie_then_admits(client):
    r = client.get(f"{AUTH_PATH}?t={TOKEN}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert f"{COOKIE_NAME}={TOKEN}" in cookie
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert any(v.startswith("cre_desktop=1;") for v in r.headers.get_list("set-cookie"))
    assert client.get("/api/ping").json() == {"ok": True}


def test_gate_rejects_wrong_token_and_foreign_host(client):
    assert client.get(f"{AUTH_PATH}?t=nope", follow_redirects=False).status_code == 403
    client.cookies.set(COOKIE_NAME, TOKEN)
    # DNS-rebinding style request: right cookie, wrong Host header.
    assert client.get("/api/ping", headers={"host": f"evil.example:{PORT}"}).status_code == 403
    assert client.get("/api/ping").status_code == 200


def test_native_dialog_file_filters():
    assert _file_types([".xlsx", ".xlsm"], "Excel workbooks") == ("Excel workbooks (*.xlsx;*.xlsm)",)
    assert _file_types([".csv", "text/csv"], "CSV files") == ("CSV files (*.csv)",)
    assert _file_types(["application/json"], "x") == ()
    assert _file_types([], "x") == ()


def test_extend_path_prepends_without_duplicates(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    paths.extend_path(["/opt/homebrew/bin", "", "/usr/bin"])
    assert os.environ["PATH"] == "/opt/homebrew/bin:/usr/bin:/bin"


def test_app_data_lives_in_library_not_the_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    p = paths.app_paths()
    assert p.support == tmp_path / "Library" / "Application Support" / "CRE Underwriting"
    assert p.logs == tmp_path / "Library" / "Logs" / "CRE Underwriting"
    assert p.support.is_dir() and p.logs.is_dir() and p.webview_storage.is_dir()


def test_quit_stops_child_processes():
    import launcher

    child = subprocess.Popen(["sleep", "60"])
    launcher.terminate_child_processes(timeout=2)
    time.sleep(0.2)
    assert child.poll() is not None
