"""Filesystem locations for the desktop build.

App data follows macOS conventions (Application Support / Logs / Caches) so
nothing is written beside the executable or into the repo. The backend reads
its storage root from CRE_STORAGE_ROOT, which the launcher sets from here
BEFORE importing the backend (app.config creates its folders at import time).
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "CRE Underwriting"
KEYCHAIN_SERVICE = "com.cre-underwriting.desktop"

# A Finder-launched app gets PATH=/usr/bin:/bin:/usr/sbin:/sbin, which hides
# LibreOffice (recalc, memo PDF) and Tesseract/Poppler (OCR) even when they're
# installed. The backend discovers them via shutil.which, so extending PATH
# here is enough — no change to the discovery or recalc code.
EXTERNAL_TOOL_DIRS = [
    "/Applications/LibreOffice.app/Contents/MacOS",
    str(Path.home() / "Applications/LibreOffice.app/Contents/MacOS"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
]


@dataclass(frozen=True)
class AppPaths:
    support: Path  # database, templates, documents, backups
    logs: Path
    cache: Path
    webview_storage: Path  # WKWebView localStorage (active deal, theme, views)
    settings_file: Path  # non-secret desktop preferences (e.g. extra tool dir)

    @property
    def log_file(self) -> Path:
        return self.logs / "app.log"


def app_paths() -> AppPaths:
    home = Path.home()
    support = home / "Library" / "Application Support" / APP_NAME
    paths = AppPaths(
        support=support,
        logs=home / "Library" / "Logs" / APP_NAME,
        cache=home / "Library" / "Caches" / APP_NAME,
        webview_storage=support / "webview",
        settings_file=support / "desktop-settings.json",
    )
    for d in (paths.support, paths.logs, paths.cache, paths.webview_storage):
        d.mkdir(parents=True, exist_ok=True)
    return paths


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Where bundled resources live: the PyInstaller bundle when frozen, the
    repo root when run from source."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[2]


def backend_dir() -> Path:
    return bundle_root() if is_frozen() else bundle_root() / "backend"


def frontend_dist() -> Path:
    if is_frozen():
        return bundle_root() / "frontend_dist"
    return bundle_root() / "frontend" / "dist"


def extend_path(extra_dirs: list[str]) -> None:
    current = os.environ.get("PATH", "").split(os.pathsep)
    additions = [d for d in extra_dirs if d and d not in current]
    os.environ["PATH"] = os.pathsep.join(additions + current)
