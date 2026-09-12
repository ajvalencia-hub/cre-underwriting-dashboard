"""Input change history (H9).

Recording rules (see DECISIONS.md):
- A snapshot is the deal's inputs AFTER a save (a restorable checkpoint).
- The first save for a deal writes a BASELINE snapshot of the pre-edit
  state first, so "before I touched anything" is always restorable.
- Saves coalesce into the newest snapshot while it is younger than
  COALESCE_WINDOW_MINUTES (anchored on created_at, so continuous editing
  still checkpoints every window); changed_paths accumulate as the union
  of the per-save diffs.
- Retention: the oldest snapshots beyond RETENTION_PER_DEAL are deleted.

Restore sets the deal's inputs to the snapshot's and records that as its
own "restore" snapshot, so a restore is itself undoable.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Deal, DealSnapshot

COALESCE_WINDOW_MINUTES = 10
RETENTION_PER_DEAL = 200


def changed_paths(old: dict, new: dict) -> list[str]:
    """Top-level keys that differ, dotted one level into dict values (so the
    quickScreen blob reports quickScreen.rent, not one opaque key)."""
    paths: list[str] = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a == b:
            continue
        if isinstance(a, dict) and isinstance(b, dict):
            for sub in sorted(set(a) | set(b)):
                if a.get(sub) != b.get(sub):
                    paths.append(f"{key}.{sub}")
        else:
            paths.append(key)
    return paths


# created_at can tie within a request; SQLite's rowid is the insertion-order
# tiebreaker that keeps "latest" deterministic.
_NEWEST_FIRST = (DealSnapshot.created_at.desc(), text("rowid DESC"))


def _latest_snapshot(db: Session, deal_id: str) -> DealSnapshot | None:
    return db.execute(
        select(DealSnapshot)
        .where(DealSnapshot.deal_id == deal_id)
        .order_by(*_NEWEST_FIRST)
        .limit(1)
    ).scalar_one_or_none()


def _enforce_retention(db: Session, deal_id: str) -> None:
    ids = db.execute(
        select(DealSnapshot.id)
        .where(DealSnapshot.deal_id == deal_id)
        .order_by(*_NEWEST_FIRST)
    ).scalars().all()
    for snapshot_id in ids[RETENTION_PER_DEAL:]:
        snapshot = db.get(DealSnapshot, snapshot_id)
        if snapshot is not None:
            db.delete(snapshot)


def record_snapshot(db: Session, deal: Deal, new_inputs: dict, kind: str = "autosave") -> None:
    """Call BEFORE deal.inputs is overwritten; does not commit (rides the
    caller's transaction)."""
    old_inputs = deal.inputs or {}
    paths = changed_paths(old_inputs, new_inputs)
    if not paths:
        return  # no-op save; don't spam history

    latest = _latest_snapshot(db, deal.id)
    if latest is None and old_inputs:
        # First edit ever: checkpoint the pre-edit state so it stays restorable.
        db.add(
            DealSnapshot(deal_id=deal.id, inputs=old_inputs, changed_paths=[], kind="baseline")
        )
        db.flush()
        latest = None  # the new save below still gets its own snapshot

    window_start = datetime.now(UTC) - timedelta(minutes=COALESCE_WINDOW_MINUTES)
    created = latest.created_at if latest is not None else None
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if (
        latest is not None
        and kind == "autosave"
        and latest.kind == "autosave"
        and created is not None
        and created > window_start
    ):
        latest.inputs = new_inputs
        latest.changed_paths = sorted(set(latest.changed_paths or []) | set(paths))
        latest.updated_at = datetime.now(UTC)
    else:
        db.add(
            DealSnapshot(deal_id=deal.id, inputs=new_inputs, changed_paths=paths, kind=kind)
        )
    db.flush()
    _enforce_retention(db, deal.id)


def list_snapshots(db: Session, deal_id: str) -> list[DealSnapshot]:
    return list(db.execute(
        select(DealSnapshot)
        .where(DealSnapshot.deal_id == deal_id)
        .order_by(*_NEWEST_FIRST)
    ).scalars().all())
