"""CRE Underwriting desktop entry point.

One process: sets up app-data locations, starts the FastAPI backend on a
free local port (in-process thread), and opens a native window on it.
Closing the window stops the backend and any LibreOffice child it spawned.

Run from source (after `npm run build` in frontend/):
    desktop/.venv/bin/python desktop/launcher.py
"""

import fcntl
import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cre_desktop import keys, macos, pages  # noqa: E402
from cre_desktop.bridge import DesktopBridge  # noqa: E402
from cre_desktop.paths import (  # noqa: E402
    APP_NAME,
    EXTERNAL_TOOL_DIRS,
    app_paths,
    backend_dir,
    extend_path,
    frontend_dist,
)
from cre_desktop.server import BackendServer  # noqa: E402

log = logging.getLogger("desktop")

STARTUP_TIMEOUT_SECONDS = 90


def configure_logging(log_file: Path) -> None:
    handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr is not None:
        root.addHandler(logging.StreamHandler())


def acquire_single_instance_lock(lock_path: Path):
    """Two copies would share one SQLite file and both run backup schedulers."""
    handle = open(lock_path, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def read_desktop_settings(settings_file: Path) -> dict:
    try:
        return json.loads(settings_file.read_text())
    except (OSError, ValueError):
        return {}


def prepare_environment(paths) -> None:
    # Must all happen BEFORE the backend is imported: app.config reads these
    # at import time and creates its storage folders.
    os.environ["CRE_STORAGE_ROOT"] = str(paths.support)
    os.environ["CRE_FRONTEND_DIST"] = str(frontend_dist())
    os.environ["CRE_ENABLE_BACKUP_SCHEDULER"] = "1"
    os.environ["CRE_DESKTOP"] = "1"
    os.environ["MPLCONFIGDIR"] = str(paths.cache / "matplotlib")
    settings = read_desktop_settings(paths.settings_file)
    extend_path([settings.get("extraToolDir", "")] + EXTERNAL_TOOL_DIRS)
    loaded = keys.load_into_environ()
    log.info("Loaded %d API key(s) from the Keychain", len(loaded))


def boot(window, server: BackendServer, paths) -> None:
    """Runs on pywebview's worker thread once the window exists."""

    def status(text: str) -> None:
        try:
            window.evaluate_js(f"window.setStatus && window.setStatus({json.dumps(text)})")
        except Exception:  # noqa: BLE001 — cosmetic only
            pass

    def fail(summary: str, detail: str) -> None:
        log.error("Startup failed: %s\n%s", summary, detail)
        window.load_html(pages.error_html(summary, detail, str(paths.log_file)))

    if not frontend_dist().joinpath("index.html").exists():
        fail(
            "The app's interface files are missing.",
            f"Expected {frontend_dist() / 'index.html'}. From source, run `npm run build` in frontend/.",
        )
        return

    status("Preparing your deal database.")
    try:
        sys.path.insert(0, str(backend_dir()))
        from app.main import app as asgi_app  # runs migrations, seeds presets
    except Exception:  # noqa: BLE001
        fail("The backend failed to initialise.", traceback.format_exc())
        return

    status("Starting the calculation engine.")
    server.start(asgi_app)
    if not server.wait_until_started(STARTUP_TIMEOUT_SECONDS):
        detail = (
            "".join(traceback.format_exception(server.error))
            if server.error
            else f"The backend did not respond within {STARTUP_TIMEOUT_SECONDS} seconds."
        )
        fail("The backend didn't start.", detail)
        return

    log.info("Backend ready on %s", server.base_url)
    window.load_url(server.entry_url)


def terminate_child_processes(timeout: float = 5.0) -> None:
    """LibreOffice (recalc / memo PDF) runs as a child via subprocess.run; a
    conversion still in flight at quit would otherwise outlive the app."""
    try:
        out = subprocess.run(
            ["pgrep", "-P", str(os.getpid())], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return
    pids = [int(p) for p in out.split() if p.strip().isdigit()]
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    for pid in pids:
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    if pids:
        log.info("Stopped %d child process(es) on quit", len(pids))


def main() -> int:
    paths = app_paths()
    configure_logging(paths.log_file)
    log.info("Launching %s (pid %s)", APP_NAME, os.getpid())

    lock = acquire_single_instance_lock(paths.support / "app.lock")
    if lock is None:
        webview.create_window(APP_NAME, html=pages.ALREADY_RUNNING_HTML, width=520, height=260)
        webview.start()
        return 0

    prepare_environment(paths)
    server = BackendServer()
    bridge = DesktopBridge(paths)
    window = webview.create_window(
        APP_NAME,
        html=pages.STARTUP_HTML,
        js_api=bridge,
        width=1440,
        height=900,
        min_size=(1100, 700),
        text_select=True,
        localization={
            "global.quitConfirmation": (
                "Some changes haven't been saved yet. Quit anyway and lose them?"
            ),
        },
    )
    bridge.attach(window)

    shut_down = False

    def shutdown() -> None:
        # Reached either after the window loop returns (last window closed)
        # or from the will-terminate hook (Cmd+Q exits without returning).
        nonlocal shut_down
        if shut_down:
            return
        shut_down = True
        log.info("Shutting down")
        server.stop()
        terminate_child_processes()
        lock.close()
        if bridge.restart_requested:
            relaunch()

    macos.on_app_will_terminate(shutdown)

    exit_code = 0
    try:
        webview.start(
            boot,
            args=(window, server, paths),
            private_mode=False,  # keep localStorage (active deal, theme, views)
            storage_path=str(paths.webview_storage),
        )
    except Exception:  # noqa: BLE001
        log.exception("Window loop crashed")
        exit_code = 1
    finally:
        shutdown()
    return exit_code


def relaunch() -> None:
    """Settings > "Restart to apply": start a fresh copy after this one exits."""
    if getattr(sys, "frozen", False):
        # Contents/MacOS/<exe> -> the .app bundle; `open -n` starts a new instance.
        app_bundle = Path(sys.executable).resolve().parents[2]
        cmd = ["/usr/bin/open", "-n", str(app_bundle)]
    else:
        cmd = [sys.executable, str(Path(__file__).resolve())]
    # Detached so it survives this process exiting; the single-instance lock
    # is already released by the time the new copy tries to take it.
    subprocess.Popen(cmd, start_new_session=True)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        from cre_desktop import selftest

        sys.exit(selftest.run())
    sys.exit(main())
