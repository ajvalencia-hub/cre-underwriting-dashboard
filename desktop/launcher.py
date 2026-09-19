"""CRE Underwriting desktop entry point.

One process: sets up app-data locations, starts the FastAPI backend on a
free local port (in-process thread), and opens a native window on it.
Closing the window stops the backend and any LibreOffice child it spawned.

Run from source (after `npm run build` in frontend/):
    macOS:   desktop/.venv/bin/python desktop/launcher.py
    Windows: desktop/.venv/Scripts/python desktop/launcher.py
"""

import json
import logging
import logging.handlers
import os
import sys
import traceback
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cre_desktop import keys, osutil, pages  # noqa: E402
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
    return osutil.acquire_single_instance_lock(lock_path)


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
    log.info("Loaded %d API key(s) from the %s", len(loaded), osutil.SECRET_STORE_LABEL)


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
    stopped = osutil.terminate_child_processes(timeout)
    if stopped:
        log.info("Stopped %d child process(es) on quit", stopped)


def main() -> int:
    paths = app_paths()
    configure_logging(paths.log_file)
    log.info("Launching %s (pid %s)", APP_NAME, os.getpid())

    # Windows: the window needs Microsoft's WebView2 runtime. Without it,
    # explain and offer the download instead of failing with a traceback.
    if not osutil.ensure_webview2(APP_NAME):
        return 1

    lock = acquire_single_instance_lock(paths.support / "app.lock")
    if lock is None:
        log.info("Another copy is already running; showing the notice")
        webview.create_window(APP_NAME, html=pages.ALREADY_RUNNING_HTML, width=520, height=260)
        webview.start()
        return 0

    prepare_environment(paths)
    server = BackendServer()
    bridge = DesktopBridge(paths, app_origin=server.base_url)
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
    bridge._attach(window)

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

    if sys.platform == "darwin":
        from cre_desktop import macos

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
    osutil.relaunch(Path(__file__).resolve())


def report_fatal_error() -> None:
    """Windows: an unexpected crash before/around the window gets a plain
    message box pointing at the log, not PyInstaller's traceback dialog."""
    log.exception("Fatal error")
    try:
        log_file = str(app_paths().log_file)
    except Exception:  # noqa: BLE001
        log_file = "(unavailable)"
    osutil.message_box(
        f"{APP_NAME} couldn't start because of an unexpected error.\n\n"
        "Your saved deals are not affected. Try opening it again; if it keeps "
        f"happening, send the log file to whoever supports this app:\n\n{log_file}",
        APP_NAME,
        osutil.MB_OK | osutil.MB_ICONERROR,
    )


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        from cre_desktop import selftest

        sys.exit(selftest.run())
    if osutil.IS_WINDOWS:
        try:
            sys.exit(main())
        except SystemExit:
            raise
        except Exception:  # noqa: BLE001
            report_fatal_error()
            sys.exit(1)
    sys.exit(main())
