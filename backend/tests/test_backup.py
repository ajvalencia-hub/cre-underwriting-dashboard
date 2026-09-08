"""J16: backup rotation logic + restore round-trip on a scratch DB."""

import sqlite3

import pytest

from app.services import backup_service


def test_prune_names_keeps_newest():
    names = ["20260101T000000Z", "20260102T000000Z", "20260103T000000Z",
             "20260104T000000Z"]
    # Keep 2 -> delete the two oldest.
    assert backup_service.prune_names(names, 2) == [
        "20260101T000000Z", "20260102T000000Z"
    ]
    # Keep >= count -> delete nothing.
    assert backup_service.prune_names(names, 4) == []
    assert backup_service.prune_names(names, 10) == []
    # Unsorted input is sorted first.
    assert backup_service.prune_names(["c", "a", "b"], 1) == ["a", "b"]
    # keep 0 -> delete all.
    assert backup_service.prune_names(names, 0) == names


def _make_db(path, deal_name: str) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE deals (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO deals (name) VALUES (?)", (deal_name,))
    conn.commit()
    conn.close()


def test_backup_and_rotation(tmp_path):
    db = tmp_path / "app.sqlite3"
    _make_db(db, "Maple")
    backups = tmp_path / "backups"

    # Nine daily backups -> rotation keeps the newest 7. (Same-second calls
    # get a lexically-ordered collision suffix, so name order == creation
    # order regardless of how fast the loop runs.)
    created = [
        backup_service.perform_backup("daily", db_path=db, backups_root=backups).name
        for _ in range(9)
    ]
    remaining = sorted(p.name for p in (backups / "daily").iterdir())
    assert len(remaining) == backup_service.DAILY_KEEP
    # The retained set is exactly the newest 7 of everything created.
    assert remaining == sorted(created)[-backup_service.DAILY_KEEP:]


def test_backup_uses_online_api_and_is_readable(tmp_path):
    db = tmp_path / "app.sqlite3"
    _make_db(db, "Birchwood")
    backups = tmp_path / "backups"
    snapshot = backup_service.perform_backup("weekly", db_path=db, backups_root=backups)

    snap_db = snapshot / "app.sqlite3"
    assert snap_db.exists()
    conn = sqlite3.connect(str(snap_db))
    rows = conn.execute("SELECT name FROM deals").fetchall()
    conn.close()
    assert rows == [("Birchwood",)]
    # Manifest is present and records the (empty here) uploads set.
    assert (snapshot / "manifest.json").exists()


def test_restore_round_trip(tmp_path):
    db = tmp_path / "app.sqlite3"
    _make_db(db, "Original")
    backups = tmp_path / "backups"
    snapshot = backup_service.perform_backup("daily", db_path=db, backups_root=backups)

    # Mutate the live DB after the snapshot.
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE deals SET name = 'Changed'")
    conn.commit()
    conn.close()

    backup_service.restore_backup("daily", snapshot.name, db_path=db, backups_root=backups)
    conn = sqlite3.connect(str(db))
    name = conn.execute("SELECT name FROM deals").fetchone()[0]
    conn.close()
    assert name == "Original"  # restored to the snapshot state


def test_restore_missing_snapshot_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_service.restore_backup(
            "daily", "20260101T000000Z", db_path=tmp_path / "db.sqlite3",
            backups_root=tmp_path / "backups",
        )


@pytest.mark.parametrize("kind,name", [
    ("../db", "."),                       # climb out of the backups root
    ("daily", ".."),
    ("daily", "../../db"),
    ("daily", "nope"),                    # not a snapshot name at all
    ("daily", "20260101T000000Z/../x"),
    ("weekly", "C:\\Windows\\app"),
    ("daily", "/etc"),
    ("monthly", "20260101T000000Z"),      # unknown kind
])
def test_restore_rejects_malformed_kind_or_name(tmp_path, kind, name):
    """Restore overwrites the LIVE database, so the (kind, name) pair must be
    validated by construction — never joined onto the filesystem raw."""
    live = tmp_path / "live.sqlite3"
    _make_db(live, "Untouched")
    # Plant a decoy DB outside the backups root that a traversal would reach.
    _make_db(tmp_path / "app.sqlite3", "Decoy")
    with pytest.raises(ValueError):
        backup_service.restore_backup(
            kind, name, db_path=live, backups_root=tmp_path / "backups",
        )
    conn = sqlite3.connect(str(live))
    assert conn.execute("SELECT name FROM deals").fetchone()[0] == "Untouched"
    conn.close()


def test_snapshot_path_accepts_well_formed_names(tmp_path):
    root = tmp_path / "backups"
    (root / "daily" / "20260101T000000Z_1").mkdir(parents=True)
    resolved = backup_service.snapshot_path("daily", "20260101T000000Z_1", backups_root=root)
    assert resolved == (root / "daily" / "20260101T000000Z_1").resolve()


def test_scheduled_backup_skips_daily_when_a_recent_one_exists(tmp_path):
    """A process restart runs the scheduler loop immediately; without this
    guard, seven restarts in a day would rotate every older daily away."""
    db = tmp_path / "app.sqlite3"
    _make_db(db, "Sched")
    backups = tmp_path / "backups"

    first = backup_service.run_scheduled_backup(backups_root=backups, db_path=db)
    assert first == ["daily", "weekly"]
    # Immediately again (a restart): the daily is fresh, the weekly exists.
    second = backup_service.run_scheduled_backup(backups_root=backups, db_path=db)
    assert second == []
    assert len(list((backups / "daily").iterdir())) == 1

    # Age the only daily past the interval by renaming it -> a new one is taken.
    old = next((backups / "daily").iterdir())
    old.rename(backups / "daily" / "20200101T000000Z")
    third = backup_service.run_scheduled_backup(backups_root=backups, db_path=db)
    assert third == ["daily"]
    assert len(list((backups / "daily").iterdir())) == 2


def test_newest_snapshot_age_ignores_foreign_dirs(tmp_path):
    root = tmp_path / "backups"
    (root / "daily" / "notes").mkdir(parents=True)  # not a snapshot
    assert backup_service.newest_snapshot_age_seconds("daily", backups_root=root) is None
    (root / "daily" / "20260101T000000Z").mkdir()
    from datetime import datetime, timezone
    now = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    age = backup_service.newest_snapshot_age_seconds("daily", backups_root=root, now=now)
    assert age == 6 * 3600


def test_list_backups(tmp_path):
    db = tmp_path / "app.sqlite3"
    _make_db(db, "Listed")
    backups = tmp_path / "backups"
    backup_service.perform_backup("daily", db_path=db, backups_root=backups)
    backup_service.perform_backup("weekly", db_path=db, backups_root=backups)
    listing = backup_service.list_backups(backups_root=backups)
    assert len(listing["daily"]) == 1
    assert len(listing["weekly"]) == 1
    assert listing["daily"][0]["hasDb"] is True
