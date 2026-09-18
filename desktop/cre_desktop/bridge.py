"""Python functions exposed to the web UI as window.pywebview.api.*

Every public method here is callable from JavaScript, so keep the surface
small and validate inputs. File contents cross the bridge as base64; the
backend's upload limit is 50 MB per file, so that's the ceiling here too.
"""

import base64
import logging
import re
import subprocess
from pathlib import Path

import webview

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
    def __init__(self, paths):
        # Leading underscore: pywebview doesn't expose private attributes.
        self._paths = paths
        self._window = None
        self._last_dir = str(Path.home() / "Downloads")
        self._saved_paths: set[str] = set()  # only these may be revealed/opened
        self.restart_requested = False

    def attach(self, window) -> None:
        self._window = window

    # --- files -------------------------------------------------------------

    def pick_files(self, options: dict) -> dict:
        """Native Open dialog. Returns {"files": [{name, base64}]} (empty list
        if cancelled) or {"error": message}."""
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
        if path in self._saved_paths:
            subprocess.run(["/usr/bin/open", "-R", path], check=False)

    def open_path(self, path: str) -> None:
        """Open a file this session saved in its default app (e.g. Excel)."""
        if path in self._saved_paths:
            subprocess.run(["/usr/bin/open", path], check=False)

    def reveal_logs(self) -> None:
        subprocess.run(["/usr/bin/open", "-R", str(self._paths.log_file)], check=False)
