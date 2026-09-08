"""J16: SQLite backup + rotation.

Each backup is a timestamped directory under BACKUPS_DIR/{daily|weekly}/
containing a consistent snapshot of the DB (via sqlite3's ONLINE BACKUP API,
never a file copy — a copy taken mid-write can be torn) plus a manifest.json
listing the uploads by name/hash/size. Upload BYTES are not copied — they
already live on the same data volume and would multiply its size on every
snapshot; the manifest is enough to detect a missing file after a restore
(documented in the README restore procedure).

Rotation keeps the last 7 daily and 4 weekly snapshots. The pure name-pruning
logic is unit-tested; the scheduler is a thin daemon wrapper.
"""

import json
import logging
import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import BACKUPS_DIR, DB_PATH, DOCUMENTS_DIR, TEMPLATES_DIR

DAILY_KEEP = 7
WEEKLY_KEEP = 4
_SNAPSHOT_NAME = "app.sqlite3"
_MANIFEST_NAME = "manifest.json"
_KINDS = ("daily", "weekly")
# Snapshot dirs are named by _timestamp() plus an optional same-second suffix.
# Restore only ever addresses one of these — anything else (absolute paths,
# `..`, drive letters) is rejected before it touches the filesystem.
_SNAPSHOT_NAME_RE = re.compile(r"\d{8}T\d{6}Z(_\d+)?")
# A process restart must not take a fresh daily snapshot if one was taken
# recently: rotation keeps the newest 7 by name, so a crash loop (or seven
# manual restarts in a day) would otherwise push every older daily out.
MIN_DAILY_INTERVAL_SECONDS = 20 * 3600


def _timestamp() -> str:
    # UTC, lexically sortable, filesystem-safe.
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_snapshot_time(name: str) -> datetime | None:
    if not _SNAPSHOT_NAME_RE.fullmatch(name):
        return None
    return datetime.strptime(name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def newest_snapshot_age_seconds(kind: str, *, backups_root: Path | None = None,
                                now: datetime | None = None) -> float | None:
    """Age of the newest `kind` snapshot (by its name timestamp), or None when
    there is none. Pure over the directory listing — unit-tested."""
    kind_dir = (backups_root or BACKUPS_DIR) / kind
    if not kind_dir.exists():
        return None
    times = [t for p in kind_dir.iterdir() if p.is_dir() and (t := _parse_snapshot_time(p.name))]
    if not times:
        return None
    return ((now or datetime.now(timezone.utc)) - max(times)).total_seconds()


def prune_names(names: list[str], keep: int) -> list[str]:
    """Pure: given snapshot directory names (lexically sortable timestamps),
    return the names to DELETE so that only the newest `keep` remain."""
    if keep <= 0:
        return list(names)
    ordered = sorted(names)
    return ordered[:-keep] if len(ordered) > keep else []


def _uploads_manifest() -> list[dict]:
    manifest = []
    for base in (DOCUMENTS_DIR, TEMPLATES_DIR):
        for path in sorted(base.glob("*")):
            if path.is_file():
                manifest.append({
                    "dir": base.name,
                    "name": path.name,
                    "sizeBytes": path.stat().st_size,
                })
    return manifest


def _online_backup(src: Path, dest: Path) -> None:
    """sqlite3 online backup — consistent even while the app is writing."""
    source = sqlite3.connect(str(src))
    try:
        target = sqlite3.connect(str(dest))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def perform_backup(kind: str = "daily", *, db_path: Path | None = None,
                   backups_root: Path | None = None) -> Path:
    """Snapshot the DB + write the uploads manifest into a fresh timestamped
    directory, then rotate `kind` to its cap. Returns the snapshot dir."""
    if kind not in _KINDS:
        raise ValueError(f"Unknown backup kind '{kind}'")
    db = db_path or DB_PATH
    root = (backups_root or BACKUPS_DIR) / kind
    root.mkdir(parents=True, exist_ok=True)

    snapshot_dir = root / _timestamp()
    # Guard the (unlikely) same-second collision so a backup never clobbers
    # another taken in the same second.
    suffix = 0
    while snapshot_dir.exists():
        suffix += 1
        snapshot_dir = root / f"{_timestamp()}_{suffix}"
    snapshot_dir.mkdir(parents=True)

    if db.exists():
        _online_backup(db, snapshot_dir / _SNAPSHOT_NAME)
    (snapshot_dir / _MANIFEST_NAME).write_text(
        json.dumps({
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "uploads": _uploads_manifest(),
        }, indent=2)
    )

    keep = DAILY_KEEP if kind == "daily" else WEEKLY_KEEP
    for name in prune_names([p.name for p in root.iterdir() if p.is_dir()], keep):
        shutil.rmtree(root / name, ignore_errors=True)
    return snapshot_dir


def list_backups(backups_root: Path | None = None) -> dict:
    root = backups_root or BACKUPS_DIR
    out: dict[str, list] = {"daily": [], "weekly": []}
    for kind in ("daily", "weekly"):
        kind_dir = root / kind
        if not kind_dir.exists():
            continue
        for snapshot in sorted((p for p in kind_dir.iterdir() if p.is_dir()), reverse=True):
            manifest_path = snapshot / _MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
            out[kind].append({
                "name": snapshot.name,
                "createdAt": manifest.get("createdAt"),
                "uploadCount": len(manifest.get("uploads", [])),
                "hasDb": (snapshot / _SNAPSHOT_NAME).exists(),
            })
    return out


def snapshot_path(kind: str, name: str, *, backups_root: Path | None = None) -> Path:
    """Resolve a (kind, name) pair to its snapshot directory, refusing anything
    that is not a well-formed snapshot name inside the backups root. Both
    checks matter: the regex rejects traversal by construction, and the
    containment check is belt-and-braces against symlinked roots."""
    if kind not in _KINDS:
        raise ValueError(f"Unknown backup kind '{kind}'")
    if not _SNAPSHOT_NAME_RE.fullmatch(name):
        raise ValueError(f"Invalid snapshot name '{name}'")
    root = (backups_root or BACKUPS_DIR).resolve()
    candidate = (root / kind / name).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"Snapshot '{kind}/{name}' escapes the backups root")
    return candidate


def restore_backup(kind: str, name: str, *, db_path: Path | None = None,
                   backups_root: Path | None = None) -> dict:
    """Restore a snapshot's DB over the live DB (online backup in reverse).
    The app should be restarted afterward so SQLAlchemy reopens the file.
    Returns the manifest so the caller can flag uploads that need re-transfer."""
    root = backups_root or BACKUPS_DIR
    snapshot_dir = snapshot_path(kind, name, backups_root=root)
    snapshot_db = snapshot_dir / _SNAPSHOT_NAME
    if not snapshot_db.exists():
        raise FileNotFoundError(f"No DB snapshot at {kind}/{name}")
    db = db_path or DB_PATH
    db.parent.mkdir(parents=True, exist_ok=True)
    _online_backup(snapshot_db, db)
    manifest_path = snapshot_dir / _MANIFEST_NAME
    return json.loads(manifest_path.read_text()) if manifest_path.exists() else {}


# --- Scheduler (in-process daemon) -----------------------------------------

_scheduler_started = False


def run_scheduled_backup(*, backups_root: Path | None = None,
                         db_path: Path | None = None) -> list[str]:
    """A daily snapshot (unless one younger than MIN_DAILY_INTERVAL_SECONDS
    already exists — see the constant's note on restart loops); the first
    backup of a new ISO week is also promoted to a weekly snapshot. Returns
    the kinds actually taken so the loop/tests can observe skips."""
    taken: list[str] = []
    age = newest_snapshot_age_seconds("daily", backups_root=backups_root)
    if age is None or age >= MIN_DAILY_INTERVAL_SECONDS:
        perform_backup("daily", backups_root=backups_root, db_path=db_path)
        taken.append("daily")
    week_tag = datetime.now(timezone.utc).strftime("%G-W%V")
    if not _weekly_exists_this_week(week_tag, backups_root=backups_root):
        perform_backup("weekly", backups_root=backups_root, db_path=db_path)
        taken.append("weekly")
    return taken


def _weekly_exists_this_week(week_tag: str, *, backups_root: Path | None = None) -> bool:
    weekly_dir = (backups_root or BACKUPS_DIR) / "weekly"
    if not weekly_dir.exists():
        return False
    for snapshot in weekly_dir.glob("*"):
        manifest = snapshot / _MANIFEST_NAME
        if not manifest.exists():
            continue
        created = json.loads(manifest.read_text()).get("createdAt", "")
        try:
            dt = datetime.fromisoformat(created)
        except ValueError:
            continue
        if dt.strftime("%G-W%V") == week_tag:
            return True
    return False


def start_scheduler(interval_seconds: int = 24 * 3600) -> None:
    """Best-effort daily backup loop on a daemon thread. Idempotent."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    def _loop():
        while True:
            try:
                run_scheduled_backup()
            except Exception:  # noqa: BLE001 - a backup failure must not crash the app
                logging.getLogger("app.backup").exception("Scheduled backup failed")
            time.sleep(interval_seconds)

    threading.Thread(target=_loop, daemon=True).start()
