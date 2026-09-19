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


def test_daily_rotation_keeps_one_snapshot_per_day_for_seven_days():
    # 9 days, several snapshots on some days (the desktop app backs up at
    # every launch). Keeping the last 7 SNAPSHOTS used to let one busy day
    # wipe every older day.
    names = [
        "20260901T090000Z", "20260902T090000Z", "20260903T090000Z",
        "20260904T090000Z", "20260905T090000Z", "20260906T090000Z",
        "20260907T090000Z", "20260908T080000Z", "20260908T090000Z",
        "20260909T080000Z", "20260909T090000Z", "20260909T090000Z_1",
    ]
    doomed = backup_service.prune_daily_names(names, 7)
    kept = sorted(set(names) - set(doomed))
    assert kept == [
        "20260903T090000Z", "20260904T090000Z", "20260905T090000Z",
        "20260906T090000Z", "20260907T090000Z", "20260908T090000Z",
        "20260909T090000Z_1",
    ]


def test_many_backups_in_one_day_keep_the_newest_of_that_day(tmp_path):
    db = tmp_path / "app.sqlite3"
    _make_db(db, "Maple")
    backups = tmp_path / "backups"
    created = [
        backup_service.perform_backup("daily", db_path=db, backups_root=backups).name
        for _ in range(9)
    ]
    remaining = sorted(p.name for p in (backups / "daily").iterdir())
    assert remaining == [sorted(created)[-1]]


def test_automatic_backup_skips_when_a_recent_daily_exists(tmp_path):
    db = tmp_path / "app.sqlite3"
    _make_db(db, "Maple")
    backups = tmp_path / "backups"
    first = backup_service.run_scheduled_backup(db_path=db, backups_root=backups)
    second = backup_service.run_scheduled_backup(db_path=db, backups_root=backups)
    assert first != second and second.startswith("skipped")
    assert len(list((backups / "daily").iterdir())) == 1


def test_automatic_backup_failure_is_recorded_not_swallowed(tmp_path, monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(backup_service, "perform_backup", broken)
    backup_service.run_automatic_backup(db_path=tmp_path / "db", backups_root=tmp_path / "b")
    status = backup_service.list_backups(backups_root=tmp_path / "b")["lastAutomatic"]
    assert status["ok"] is False and status["error"] == "OSError: disk full"
    assert "Automatic backup failed" in caplog.text


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
    ("../..", "20260101T000000Z"),
    ("daily", "../../etc"),
    ("daily", "nope"),
    ("monthly", "20260101T000000Z"),
])
def test_restore_rejects_names_outside_the_backups_folder(tmp_path, kind, name):
    with pytest.raises(ValueError):
        backup_service.restore_backup(kind, name, db_path=tmp_path / "db", backups_root=tmp_path / "b")


def test_restore_snapshots_the_live_database_first_so_it_can_be_undone(tmp_path):
    db = tmp_path / "app.sqlite3"
    _make_db(db, "Original")
    backups = tmp_path / "backups"
    snapshot = backup_service.perform_backup("daily", db_path=db, backups_root=backups)
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE deals SET name = 'Latest work'")
    conn.commit()
    conn.close()

    result = backup_service.restore_backup("daily", snapshot.name, db_path=db, backups_root=backups)
    safety = result["preRestoreSnapshot"]
    assert safety is not None

    # Undo: restoring the safety snapshot brings the latest work back.
    backup_service.restore_backup("pre_restore", safety, db_path=db, backups_root=backups)
    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT name FROM deals").fetchone()[0] == "Latest work"
    conn.close()
    assert len(backup_service.list_backups(backups_root=backups)["pre_restore"]) == 2


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
