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


def _timestamp() -> str:
    # UTC, lexically sortable, filesystem-safe.
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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
    if kind not in ("daily", "weekly"):
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


def restore_backup(kind: str, name: str, *, db_path: Path | None = None,
                   backups_root: Path | None = None) -> dict:
    """Restore a snapshot's DB over the live DB (online backup in reverse).
    The app should be restarted afterward so SQLAlchemy reopens the file.
    Returns the manifest so the caller can flag uploads that need re-transfer."""
    root = backups_root or BACKUPS_DIR
    snapshot_dir = root / kind / name
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


def run_scheduled_backup() -> None:
    """A daily snapshot; the first backup of a new ISO week is also promoted
    to a weekly snapshot."""
    perform_backup("daily")
    week_tag = datetime.now(timezone.utc).strftime("%G-W%V")
    if not _weekly_exists_this_week(week_tag):
        perform_backup("weekly")


def _weekly_exists_this_week(week_tag: str) -> bool:
    weekly_dir = BACKUPS_DIR / "weekly"
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
                pass
            time.sleep(interval_seconds)

    threading.Thread(target=_loop, daemon=True).start()
