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
            "daily", "nope", db_path=tmp_path / "db.sqlite3",
            backups_root=tmp_path / "backups",
        )


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
