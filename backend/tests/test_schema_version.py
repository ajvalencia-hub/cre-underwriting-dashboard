"""Database schema versioning (roadmap #21)."""

import pytest
from sqlalchemy import create_engine, text

import app.models  # noqa: F401  (registers the tables on Base.metadata)
from app.database import (
    SCHEMA_VERSION,
    Base,
    DatabaseTooNewError,
    prepare_migrations,
    run_migrations,
)


def _engine(tmp_path, name="db.sqlite3"):
    return create_engine(f"sqlite:///{tmp_path / name}")


def _version(eng) -> int:
    with eng.connect() as conn:
        return conn.exec_driver_sql("PRAGMA user_version").scalar()


def test_a_new_database_is_stamped_without_a_backup(tmp_path):
    eng = _engine(tmp_path)
    backups = []
    prepare_migrations(eng, backup=backups.append)
    Base.metadata.create_all(eng)
    run_migrations(eng)
    assert _version(eng) == SCHEMA_VERSION and backups == []


def test_an_existing_older_database_is_backed_up_then_migrated(tmp_path):
    eng = _engine(tmp_path)
    Base.metadata.create_all(eng)  # tables exist, user_version still 0
    backups = []
    prepare_migrations(eng, backup=backups.append)
    run_migrations(eng)
    assert backups == [0] and _version(eng) == SCHEMA_VERSION
    # Up to date now: no second backup.
    prepare_migrations(eng, backup=backups.append)
    assert backups == [0]


def test_a_database_from_a_newer_build_is_refused(tmp_path):
    eng = _engine(tmp_path)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE t (x INTEGER)"))
        conn.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(DatabaseTooNewError, match="newer version of the app"):
        prepare_migrations(eng, backup=lambda v: None)
    with pytest.raises(DatabaseTooNewError):
        run_migrations(eng)
