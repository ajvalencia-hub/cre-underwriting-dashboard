"""Roadmap #32: SQLite runs in WAL mode with a busy timeout, and backups
stay single-file snapshots."""

import sqlite3

from sqlalchemy import create_engine, event

from app.database import BUSY_TIMEOUT_MS, configure_sqlite_connection
from app.services import backup_service


def _engine(path):
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", configure_sqlite_connection)
    return eng


def test_connections_use_wal_and_busy_timeout(tmp_path):
    eng = _engine(tmp_path / "app.sqlite3")
    with eng.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == BUSY_TIMEOUT_MS
    eng.dispose()


def test_reader_is_not_blocked_by_an_open_write(tmp_path):
    db = tmp_path / "app.sqlite3"
    eng = _engine(db)
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE t (x INTEGER)")
        conn.exec_driver_sql("INSERT INTO t VALUES (1)")
    writer = eng.connect()
    writer.exec_driver_sql("BEGIN IMMEDIATE")
    writer.exec_driver_sql("INSERT INTO t VALUES (2)")
    # Under the old rollback journal this read would wait for the writer.
    reader = sqlite3.connect(str(db), timeout=0)
    try:
        assert reader.execute("SELECT count(*) FROM t").fetchone()[0] == 1
    finally:
        reader.close()
        writer.rollback()
        writer.close()
        eng.dispose()


def test_backup_snapshot_is_a_single_file(tmp_path):
    db = tmp_path / "live.sqlite3"
    eng = _engine(db)
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE t (x INTEGER)")
        conn.exec_driver_sql("INSERT INTO t VALUES (42)")
    dest = tmp_path / "snap.sqlite3"
    backup_service._online_backup(db, dest)
    eng.dispose()
    assert not (tmp_path / "snap.sqlite3-wal").exists()
    snap = sqlite3.connect(str(dest))
    try:
        assert snap.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert snap.execute("SELECT x FROM t").fetchone()[0] == 42
    finally:
        snap.close()
