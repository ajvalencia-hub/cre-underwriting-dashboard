"""Python functions exposed to the web UI as window.pywebview.api.*

Every public method here is callable from JavaScript, so keep the surface
small and validate inputs. Each one (except reveal_logs, which the built-in
error page offers) first checks the window is showing the app itself —
http://127.0.0.1:<port>/ — so no other page that ends up in the window can
reach the file system, the Keychain or the shell. File contents cross the bridge as base64; the
backend's upload limit is 50 MB per file, so that's the ceiling here too.
"""

import base64
import json
import logging
import re
import subprocess
from pathlib import Path

import webview

from . import keys, updates

log = logging.getLogger(__name__)

MAX_FILE_BYTES = 50 * 1024 * 1024  # mirrors backend/app/routers/upload_limit.py


def _file_types(accept: list[str], description: str) -> tuple[str, ...]:
    """['.xlsx', '.xlsm'] -> ('Excel workbooks (*.xlsx;*.xlsm)',). MIME types
    in an HTML accept list are dropped; no extensions means no filter."""
    exts = [a.lstrip(".").lower() for a in accept if re.fullmatch(r"\.[A-Za-z0-9]+", a)]
    if not exts:
        return ()
    return (f"{description} ({';'.join('*.' + e for e in exts)})",)


class DesktopBridge:
    def __init__(self, paths, app_origin: str):
        # Leading underscore: pywebview doesn't expose private attributes.
        self._paths = paths
        self._app_origin = app_origin.rstrip("/")
        self._window = None
        self._last_dir = str(Path.home() / "Downloads")
        self._saved_paths: set[str] = set()  # only these may be revealed/opened
        self._restart_needed = False  # a setting changed that applies on next launch
        self.restart_requested = False

    def _attach(self, window) -> None:
        # Private: a public method would be callable from the page.
        self._window = window

    def _from_app(self) -> bool:
        """True when the window is on the app's own origin."""
        try:
            url = self._window.get_current_url() if self._window is not None else None
        except Exception:  # noqa: BLE001 — treat an unreadable URL as foreign
            url = None
        ok = bool(url) and (url == self._app_origin or url.startswith(self._app_origin + "/"))
        if not ok:
            log.warning("Blocked a bridge call from %r", url)
        return ok

    # --- files -------------------------------------------------------------

    def pick_files(self, options: dict) -> dict:
        """Native Open dialog. Returns {"files": [{name, base64}]} (empty list
        if cancelled) or {"error": message}."""
        if not self._from_app():
            return {"error": "Not available on this page."}
        accept = [str(a) for a in options.get("accept") or []]
        multiple = bool(options.get("multiple"))
        description = str(options.get("description") or "Supported files")
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=self._last_dir,
            allow_multiple=multiple,
            file_types=_file_types(accept, description),
        )
        if not result:
            return {"files": []}
        files = []
        for raw in result:
            path = Path(raw)
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                return {
                    "error": f"{path.name} is {size / 1_048_576:.0f} MB — the limit is "
                    f"{MAX_FILE_BYTES // 1_048_576} MB per file."
                }
            files.append({"name": path.name, "base64": base64.b64encode(path.read_bytes()).decode()})
            self._last_dir = str(path.parent)
        return {"files": files}

    def save_file(self, options: dict) -> dict:
        """Native Save dialog, then write the bytes. Returns {"path"} on
        success, {"cancelled": true}, or {"error": message}."""
        if not self._from_app():
            return {"error": "Not available on this page."}
        suggested = Path(str(options.get("suggestedName") or "download")).name
        data = base64.b64decode(str(options.get("base64") or ""))
        result = self._window.create_file_dialog(
            webview.FileDialog.SAVE, directory=self._last_dir, save_filename=suggested
        )
        if not result:
            return {"cancelled": True}
        target = Path(result if isinstance(result, str) else result[0])
        try:
            target.write_bytes(data)
        except OSError as exc:
            log.exception("Save failed: %s", target)
            return {"error": f"Couldn't save to {target}: {exc.strerror or exc}"}
        self._last_dir = str(target.parent)
        self._saved_paths.add(str(target))
        return {"path": str(target)}

    def reveal_path(self, path: str) -> None:
        if not self._from_app():
            return
        if path in self._saved_paths:
            subprocess.run(["/usr/bin/open", "-R", path], check=False)

    def open_path(self, path: str) -> None:
        """Open a file this session saved in its default app (e.g. Excel)."""
        if not self._from_app():
            return
        if path in self._saved_paths:
            subprocess.run(["/usr/bin/open", path], check=False)

    def set_unsaved(self, unsaved: bool) -> None:
        """The page reports whether it holds edits the backend hasn't saved;
        while it does, closing the window or Cmd+Q asks first (the prompt
        text is set in launcher.py)."""
        if not self._from_app():
            return
        if self._window is not None:
            self._window.confirm_close = bool(unsaved)

    # --- settings ----------------------------------------------------------

    def get_settings(self) -> dict:
        if not self._from_app():
            return {"error": "Not available on this page."}
        settings = self._read_settings()
        return {
            "storedKeys": keys.stored_names(),
            "extraToolDir": settings.get("extraToolDir") or None,
            "restartNeeded": self._restart_needed,
            "dataFolder": str(self._paths.support),
        }

    def set_api_key(self, name: str, value: str) -> dict:
        """Store (or, with an empty value, remove) a key in the Keychain."""
        if not self._from_app():
            return {"error": "Not available on this page."}
        try:
            keys.set_key(str(name), str(value or ""))
        except ValueError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — Keychain denied/locked
            log.exception("Keychain write failed for %s", name)
            return {"error": f"The Keychain refused the change: {exc}"}
        self._restart_needed = True
        return self.get_settings()

    def choose_tool_folder(self) -> dict:
        """Folder with LibreOffice's `soffice` (or tesseract) when it's
        installed somewhere non-standard. Applied on next launch (PATH)."""
        if not self._from_app():
            return {"error": "Not available on this page."}
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not result:
            return self.get_settings()
        folder = Path(result if isinstance(result, str) else result[0])
        # Accept the .app bundle itself and dig to the binary folder.
        if folder.suffix == ".app" and (folder / "Contents" / "MacOS").is_dir():
            folder = folder / "Contents" / "MacOS"
        self._write_settings({**self._read_settings(), "extraToolDir": str(folder)})
        self._restart_needed = True
        return self.get_settings()

    def clear_tool_folder(self) -> dict:
        if not self._from_app():
            return {"error": "Not available on this page."}
        settings = self._read_settings()
        settings.pop("extraToolDir", None)
        self._write_settings(settings)
        self._restart_needed = True
        return self.get_settings()

    # --- updates (roadmap #31) ---------------------------------------------

    def check_for_updates(self, force: bool = False) -> dict:
        """Is a newer release on GitHub? At launch at most once a day and
        only when enabled; `force` is Settings' "Check now"."""
        if not self._from_app():
            return {"error": "Not available on this page."}
        result, settings = updates.check(self._read_settings(), force=bool(force))
        self._write_settings(settings)
        return result

    def set_update_checks(self, enabled: bool) -> dict:
        if not self._from_app():
            return {"error": "Not available on this page."}
        self._write_settings({**self._read_settings(), "checkForUpdates": bool(enabled)})
        return {"enabled": bool(enabled), "currentVersion": updates.VERSION}

    def restart(self) -> None:
        """Quit and relaunch so Keychain keys / tool folder take effect."""
        if not self._from_app():
            return
        self.restart_requested = True
        self._window.destroy()

    def open_external(self, url: str) -> None:
        """Open an https link (e.g. the LibreOffice download page) in the
        user's default browser rather than inside the app window."""
        if not self._from_app():
            return
        if isinstance(url, str) and url.startswith("https://"):
            subprocess.run(["/usr/bin/open", url], check=False)

    def _read_settings(self) -> dict:
        try:
            return json.loads(self._paths.settings_file.read_text())
        except (OSError, ValueError):
            return {}

    def _write_settings(self, settings: dict) -> None:
        self._paths.settings_file.write_text(json.dumps(settings, indent=2))

    def reveal_logs(self) -> None:
        subprocess.run(["/usr/bin/open", "-R", str(self._paths.log_file)], check=False)
