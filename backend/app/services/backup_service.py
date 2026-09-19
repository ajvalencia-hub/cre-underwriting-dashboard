"""J16: SQLite backup + rotation.

Each backup is a timestamped directory under BACKUPS_DIR/{daily|weekly}/
containing a consistent snapshot of the DB (via sqlite3's ONLINE BACKUP API,
never a file copy — a copy taken mid-write can be torn) plus a manifest.json
listing the uploads by name/hash/size. Upload BYTES are not copied — they
already live on the same data volume and would multiply its size on every
snapshot; the manifest is enough to detect a missing file after a restore
(documented in the README restore procedure).

Rotation keeps one daily snapshot per day for the last 7 days that have
one (the last 7 SNAPSHOTS used to be kept, so 7 relaunches in a day — the
desktop app backs up at launch — wiped every older day), 4 weekly, and the
5 most recent "pre_restore" snapshots: a restore first snapshots the live
database, so a wrong restore can be undone. The automatic backup skips a
launch when the newest daily is under 20 hours old, logs failures and
reports its last outcome (it used to swallow them). kind/name are
validated so a request can't reach outside the backups folder. The pure
name-pruning logic is unit-tested; the scheduler is a thin daemon wrapper.
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

log = logging.getLogger(__name__)

DAILY_KEEP = 7  # days
WEEKLY_KEEP = 4
PRE_RESTORE_KEEP = 5
KINDS = ("daily", "weekly", "pre_restore")
AUTO_BACKUP_MIN_AGE_HOURS = 20
_SNAPSHOT_NAME = "app.sqlite3"
_MANIFEST_NAME = "manifest.json"
_NAME_RE = re.compile(r"^\d{8}T\d{6}Z(_\d+)?$")

# Outcome of the last automatic backup attempt, for Settings.
_last_automatic: dict | None = None


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


def prune_daily_names(names: list[str], keep_days: int) -> list[str]:
    """Pure: keep the newest snapshot of each of the newest `keep_days` days
    (names start with YYYYMMDD); return every other name, to DELETE."""
    newest_per_day: dict[str, str] = {}
    for name in sorted(names):
        newest_per_day[name[:8]] = name
    kept_days = sorted(newest_per_day)[-keep_days:] if keep_days > 0 else []
    keep = {newest_per_day[day] for day in kept_days}
    return [name for name in sorted(names) if name not in keep]


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"Unknown backup kind '{kind}'")


def _snapshot_time(name: str) -> datetime | None:
    try:
        return datetime.strptime(name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


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
    _check_kind(kind)
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

    _rotate(root, kind)
    return snapshot_dir


def _rotate(kind_dir: Path, kind: str) -> None:
    if not kind_dir.exists():
        return
    names = [p.name for p in kind_dir.iterdir() if p.is_dir()]
    if kind == "daily":
        doomed = prune_daily_names(names, DAILY_KEEP)
    else:
        doomed = prune_names(names, WEEKLY_KEEP if kind == "weekly" else PRE_RESTORE_KEEP)
    for name in doomed:
        shutil.rmtree(kind_dir / name, ignore_errors=True)


def list_backups(backups_root: Path | None = None) -> dict:
    root = backups_root or BACKUPS_DIR
    out: dict = {kind: [] for kind in KINDS}
    out["lastAutomatic"] = _last_automatic
    for kind in KINDS:
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
    _check_kind(kind)
    if not _NAME_RE.match(name):
        raise ValueError(f"'{name}' isn't a snapshot name")
    root = backups_root or BACKUPS_DIR
    snapshot_dir = root / kind / name
    snapshot_db = snapshot_dir / _SNAPSHOT_NAME
    if not snapshot_db.exists():
        raise FileNotFoundError(f"No DB snapshot at {kind}/{name}")
    db = db_path or DB_PATH
    db.parent.mkdir(parents=True, exist_ok=True)
    # Snapshot the live database first so a wrong restore can be undone.
    safety = None
    if db.exists():
        safety = perform_backup("pre_restore", db_path=db, backups_root=root).name
    _online_backup(snapshot_db, db)
    manifest_path = snapshot_dir / _MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    return {**manifest, "preRestoreSnapshot": safety}


# --- Scheduler (in-process daemon) -----------------------------------------

_scheduler_started = False


def _latest_daily_age_hours(backups_root: Path) -> float | None:
    daily_dir = backups_root / "daily"
    times = [
        t for t in (_snapshot_time(p.name) for p in daily_dir.glob("*") if p.is_dir()) if t
    ] if daily_dir.exists() else []
    if not times:
        return None
    return (datetime.now(timezone.utc) - max(times)).total_seconds() / 3600


def run_scheduled_backup(*, db_path: Path | None = None, backups_root: Path | None = None) -> str:
    """A daily snapshot unless one is under AUTO_BACKUP_MIN_AGE_HOURS old
    (the desktop app runs this at every launch); the first backup of a new
    ISO week is also promoted to a weekly snapshot. Returns what it did."""
    root = backups_root or BACKUPS_DIR
    age = _latest_daily_age_hours(root)
    did = "skipped (recent daily exists)"
    if age is None or age >= AUTO_BACKUP_MIN_AGE_HOURS:
        did = perform_backup("daily", db_path=db_path, backups_root=root).name
    else:
        _rotate(root / "daily", "daily")  # tidy snapshots left by older builds
    week_tag = datetime.now(timezone.utc).strftime("%G-W%V")
    if not _weekly_exists_this_week(week_tag, root):
        perform_backup("weekly", db_path=db_path, backups_root=root)
    return did


def run_automatic_backup(**kwargs) -> None:
    """run_scheduled_backup that never raises: logs and records the outcome
    for Settings instead (a backup failure must not crash the app, but it
    must not be silent either)."""
    global _last_automatic
    at = datetime.now(timezone.utc).isoformat()
    try:
        did = run_scheduled_backup(**kwargs)
        _last_automatic = {"at": at, "ok": True, "result": did, "error": None}
    except Exception as exc:  # noqa: BLE001
        log.exception("Automatic backup failed")
        _last_automatic = {"at": at, "ok": False, "result": None, "error": f"{type(exc).__name__}: {exc}"}


def _weekly_exists_this_week(week_tag: str, backups_root: Path | None = None) -> bool:
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
            run_automatic_backup()
            time.sleep(interval_seconds)

    threading.Thread(target=_loop, daemon=True).start()
