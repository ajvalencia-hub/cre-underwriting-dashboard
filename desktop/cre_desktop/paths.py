"""Filesystem locations for the desktop build.

App data follows each OS's conventions so nothing is written beside the
executable or into the repo:
- macOS: ~/Library/Application Support|Logs|Caches/CRE Underwriting
- Windows: %LOCALAPPDATA%\\CRE Underwriting\\{data,logs,cache,webview}
CRE_DESKTOP_DATA_DIR (testing) puts all four under one scratch folder.
The backend reads its storage root from CRE_STORAGE_ROOT, which the launcher
sets from here BEFORE importing the backend (app.config creates its folders
at import time).
"""

import glob
import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "CRE Underwriting"
KEYCHAIN_SERVICE = "com.cre-underwriting.desktop"
DATA_DIR_OVERRIDE_ENV = "CRE_DESKTOP_DATA_DIR"

# A Finder-launched app gets PATH=/usr/bin:/bin:/usr/sbin:/sbin, which hides
# LibreOffice (recalc, memo PDF) and Tesseract/Poppler (OCR) even when they're
# installed. The backend discovers them via shutil.which, so extending PATH
# here is enough — no change to the discovery or recalc code.
MAC_TOOL_DIRS = [
    "/Applications/LibreOffice.app/Contents/MacOS",
    str(Path.home() / "Applications/LibreOffice.app/Contents/MacOS"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
]

# Windows installers rarely add these to PATH (and a running app never sees a
# PATH change). soffice.py / ocr.py also probe the standard locations; adding
# them to PATH here covers per-user installs and keeps one discovery path.
# Entries with * are glob patterns (versioned Poppler folders).
WINDOWS_TOOL_DIRS = [
    r"C:\Program Files\LibreOffice\program",
    r"C:\Program Files (x86)\LibreOffice\program",
    r"C:\Program Files\Tesseract-OCR",
    r"%LOCALAPPDATA%\Programs\Tesseract-OCR",
    r"C:\Program Files\poppler*\Library\bin",
    r"C:\Program Files\poppler*\bin",
    r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\oschwartz10612.Poppler_*\poppler-*\Library\bin",
]


def external_tool_dirs(platform: str | None = None) -> list[str]:
    platform = platform or sys.platform
    if platform != "win32":
        return list(MAC_TOOL_DIRS)
    dirs: list[str] = []
    for entry in WINDOWS_TOOL_DIRS:
        expanded = os.path.expandvars(entry)
        if "*" in expanded:
            dirs += sorted(glob.glob(expanded), reverse=True)  # newest version first
        else:
            dirs.append(expanded)
    return dirs


EXTERNAL_TOOL_DIRS = external_tool_dirs()


@dataclass(frozen=True)
class AppPaths:
    support: Path  # database, templates, documents, backups
    logs: Path
    cache: Path
    webview_storage: Path  # web view localStorage (active deal, theme, views)
    settings_file: Path  # non-secret desktop preferences (e.g. extra tool dir)

    @property
    def log_file(self) -> Path:
        return self.logs / "app.log"


def _windows_local_appdata() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) if local else Path.home() / "AppData" / "Local"


def app_paths(platform: str | None = None) -> AppPaths:
    platform = platform or sys.platform
    override = os.environ.get(DATA_DIR_OVERRIDE_ENV)
    if override or platform == "win32":
        root = Path(override) if override else _windows_local_appdata() / APP_NAME
        support = root / "data"
        paths = AppPaths(
            support=support,
            logs=root / "logs",
            cache=root / "cache",
            webview_storage=root / "webview",
            settings_file=support / "desktop-settings.json",
        )
    else:
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
