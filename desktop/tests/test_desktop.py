"""Desktop shell: the access gate, dialog filters, PATH handling and quit
cleanup, and the macOS/Windows differences. Run with:
    macOS:   desktop/.venv/bin/python -m pytest desktop/tests -q
    Windows: desktop/.venv/Scripts/python -m pytest desktop/tests -q
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

from cre_desktop import osutil, paths  # noqa: E402
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
    sep = os.pathsep
    monkeypatch.setenv("PATH", sep.join(["/usr/bin", "/bin"]))
    paths.extend_path(["/opt/homebrew/bin", "", "/usr/bin"])
    assert os.environ["PATH"] == sep.join(["/opt/homebrew/bin", "/usr/bin", "/bin"])


def test_app_data_lives_in_library_not_the_bundle(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.DATA_DIR_OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    p = paths.app_paths(platform="darwin")
    assert p.support == tmp_path / "Library" / "Application Support" / "CRE Underwriting"
    assert p.logs == tmp_path / "Library" / "Logs" / "CRE Underwriting"
    assert p.cache == tmp_path / "Library" / "Caches" / "CRE Underwriting"
    assert p.webview_storage == p.support / "webview"
    assert p.support.is_dir() and p.logs.is_dir() and p.webview_storage.is_dir()


def test_windows_app_data_lives_in_local_appdata(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.DATA_DIR_OVERRIDE_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    p = paths.app_paths(platform="win32")
    root = tmp_path / "Local" / "CRE Underwriting"
    assert (p.support, p.logs, p.cache, p.webview_storage) == (
        root / "data",
        root / "logs",
        root / "cache",
        root / "webview",
    )
    assert p.settings_file == root / "data" / "desktop-settings.json"
    assert p.log_file == root / "logs" / "app.log"
    assert all(d.is_dir() for d in (p.support, p.logs, p.cache, p.webview_storage))


def test_windows_app_data_without_localappdata_falls_back_to_home(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.DATA_DIR_OVERRIDE_ENV, raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    p = paths.app_paths(platform="win32")
    assert p.support == tmp_path / "AppData" / "Local" / "CRE Underwriting" / "data"


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_data_dir_override_keeps_tests_out_of_the_real_profile(monkeypatch, tmp_path, platform):
    monkeypatch.setenv(paths.DATA_DIR_OVERRIDE_ENV, str(tmp_path / "scratch"))
    p = paths.app_paths(platform=platform)
    assert p.support == tmp_path / "scratch" / "data"
    assert p.logs == tmp_path / "scratch" / "logs"
    assert p.webview_storage == tmp_path / "scratch" / "webview"


def test_windows_tool_dirs_cover_libreoffice_tesseract_and_poppler(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    poppler = tmp_path / "Microsoft" / "WinGet" / "Packages" / "oschwartz10612.Poppler_x" / "poppler-24.08.0" / "Library" / "bin"
    poppler.mkdir(parents=True)
    dirs = paths.external_tool_dirs("win32")
    assert r"C:\Program Files\LibreOffice\program" in dirs
    assert r"C:\Program Files (x86)\LibreOffice\program" in dirs
    assert r"C:\Program Files\Tesseract-OCR" in dirs
    assert str(tmp_path / "Programs" / "Tesseract-OCR") in dirs
    assert str(poppler) in dirs  # glob expanded
    assert not any("*" in d or "%" in d for d in dirs)
    assert paths.external_tool_dirs("darwin") == paths.MAC_TOOL_DIRS


def test_single_instance_lock_refuses_a_second_holder(tmp_path):
    lock_file = tmp_path / "app.lock"
    first = osutil.acquire_single_instance_lock(lock_file)
    assert first is not None
    assert osutil.acquire_single_instance_lock(lock_file) is None
    first.close()
    again = osutil.acquire_single_instance_lock(lock_file)
    assert again is not None
    again.close()


def test_single_instance_lock_is_seen_by_another_process(tmp_path):
    lock_file = tmp_path / "app.lock"
    held = osutil.acquire_single_instance_lock(lock_file)
    assert held is not None
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path; "
        "from cre_desktop import osutil; "
        "print('free' if osutil.acquire_single_instance_lock(Path(sys.argv[2])) else 'held')"
    )
    desktop = str(Path(__file__).resolve().parents[1])
    out = subprocess.run([sys.executable, "-c", probe, desktop, str(lock_file)], capture_output=True, text=True, check=False)
    assert out.stdout.strip() == "held", out.stderr
    held.close()
    out = subprocess.run([sys.executable, "-c", probe, desktop, str(lock_file)], capture_output=True, text=True, check=False)
    assert out.stdout.strip() == "free", out.stderr


def test_quit_stops_child_processes():
    import launcher

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert child.pid in osutil.child_pids()
        launcher.terminate_child_processes(timeout=2)
        deadline = time.monotonic() + 5
        while child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process tree")
def test_quit_stops_grandchildren_on_windows():
    """soffice.exe runs soffice.bin as its own child: the whole tree goes."""
    code = (
        "import subprocess, sys, time; "
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "print(g.pid, flush=True); time.sleep(60)"
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    grandchild = int(child.stdout.readline())
    try:
        osutil.terminate_child_processes(timeout=5)
        child.wait(5)
        deadline = time.monotonic() + 5
        while grandchild in {pid for pid, _, _ in osutil._windows_process_table()} and time.monotonic() < deadline:
            time.sleep(0.1)
        assert grandchild not in {pid for pid, _, _ in osutil._windows_process_table()}
    finally:
        if child.poll() is None:
            child.kill()


def test_relaunch_command(monkeypatch, tmp_path):
    script = tmp_path / "launcher.py"
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert osutil.relaunch_command(script) == [sys.executable, str(script)]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    if osutil.IS_WINDOWS:
        assert osutil.relaunch_command(script) == [sys.executable]
    else:
        assert osutil.relaunch_command(script)[:2] == ["/usr/bin/open", "-n"]


def test_webview2_detection_reads_machine_and_user_keys():
    def registry(values):
        return lambda hive, key, name: values.get((hive, "WOW6432Node" in key))

    assert osutil.webview2_version(registry({("HKLM", True): "130.0.2849.80"})) == "130.0.2849.80"
    assert osutil.webview2_version(registry({("HKCU", False): "131.0.1"})) == "131.0.1"
    assert osutil.webview2_version(registry({("HKLM", True): "0.0.0.0"})) is None
    assert osutil.webview2_version(registry({})) is None


def test_missing_webview2_offers_the_download_page_instead_of_crashing():
    asked, opened = [], []

    def ask(text, title, flags):
        asked.append((text, title))
        return osutil.IDYES

    ok = osutil.ensure_webview2("CRE Underwriting", read_value=lambda *a: None, ask=ask, open_url=opened.append)
    assert ok is False
    assert "WebView2" in asked[0][0] and "WebView2" in asked[0][1]
    assert opened == [osutil.WEBVIEW2_DOWNLOAD_PAGE]

    opened.clear()
    osutil.ensure_webview2("CRE Underwriting", read_value=lambda *a: None, ask=lambda *a: 7, open_url=opened.append)
    assert opened == []  # "No"
    assert osutil.ensure_webview2("x", read_value=lambda *a: "120.0", ask=ask, open_url=opened.append) is True


@pytest.mark.skipif(sys.platform != "win32", reason="real registry")
def test_webview2_registry_probe_runs_on_windows():
    # Present or not (CI images vary), reading the real registry never raises.
    version = osutil.webview2_version()
    assert version is None or version[0].isdigit()


class _FakeWindow:
    def __init__(self, url):
        self.url = url
        self.confirm_close = False

    def get_current_url(self):
        return self.url


def _bridge(url, tmp_path):
    from types import SimpleNamespace

    from cre_desktop.bridge import DesktopBridge

    paths = SimpleNamespace(support=tmp_path, settings_file=tmp_path / "settings.json", log_file=tmp_path / "x.log")
    bridge = DesktopBridge(paths, app_origin=f"http://127.0.0.1:{PORT}")
    bridge._attach(_FakeWindow(url))
    return bridge


def test_bridge_answers_only_the_app_page(tmp_path, monkeypatch):
    from cre_desktop import bridge as bridge_module

    opened = []
    monkeypatch.setattr(osutil.subprocess, "run", lambda args, **kw: opened.append(args))
    monkeypatch.setattr(osutil, "open_with_default_app", opened.append)
    monkeypatch.setattr(osutil, "reveal_in_file_browser", opened.append)
    monkeypatch.setattr(bridge_module.keys, "stored_names", lambda: [])

    app = _bridge(f"http://127.0.0.1:{PORT}/", tmp_path)
    settings = app.get_settings()
    assert settings["dataFolder"] == str(tmp_path)
    assert settings["secretStore"] == ("Credential Manager" if sys.platform == "win32" else "Keychain")
    app.set_unsaved(True)
    assert app._window.confirm_close is True

    for foreign in ("https://evil.example/", f"http://127.0.0.1:{PORT + 1}/", f"http://127.0.0.1:{PORT}evil.example/", None):
        other = _bridge(foreign, tmp_path)
        assert other.get_settings() == {"error": "Not available on this page."}
        assert other.set_api_key("FRED_API_KEY", "x") == {"error": "Not available on this page."}
        other.open_external("https://example.com")
        other.set_unsaved(True)
        assert other._window.confirm_close is False
    assert opened == []
    app.open_external("https://example.com")
    app.open_external("file:///etc/passwd")
    assert opened == ["https://example.com"]


def test_bridge_does_not_expose_attach():
    from cre_desktop.bridge import DesktopBridge

    public = [n for n in dir(DesktopBridge) if not n.startswith("_") and callable(getattr(DesktopBridge, n))]
    assert "attach" not in public
