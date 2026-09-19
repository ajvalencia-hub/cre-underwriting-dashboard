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


# --- Schema version 2 (Run 6 port: Deal.archived_at, Deal.tags, agent_*) ---

_AGENT_TABLES = {"agent_threads", "agent_messages", "agent_tool_calls", "agent_proposals"}

# The deals table as schema version 1 built it (no archived_at / tags).
_V1_DEALS_DDL = """
CREATE TABLE deals (
    id VARCHAR NOT NULL PRIMARY KEY,
    name VARCHAR NOT NULL,
    inputs JSON NOT NULL,
    status VARCHAR NOT NULL,
    active_template_id VARCHAR,
    active_mapping_profile_id VARCHAR,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""

# The deals table as Run 6's create_all built it: tags NOT NULL with NO
# database default (the hazard the server_default / backfill probe cover).
_RUN6_DEALS_DDL = """
CREATE TABLE deals (
    id VARCHAR NOT NULL PRIMARY KEY,
    name VARCHAR NOT NULL,
    inputs JSON NOT NULL,
    status VARCHAR NOT NULL,
    active_template_id VARCHAR,
    active_mapping_profile_id VARCHAR,
    archived_at DATETIME,
    tags JSON NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""


def _create_tables_except(eng, skip: set[str]) -> None:
    tables = [t for name, t in Base.metadata.tables.items() if name not in skip]
    Base.metadata.create_all(eng, tables=tables)


def _deal_columns(eng) -> set[str]:
    from sqlalchemy import inspect

    return {c["name"] for c in inspect(eng).get_columns("deals")}


def _table_names(eng) -> set[str]:
    from sqlalchemy import inspect

    return set(inspect(eng).get_table_names())


def _startup(eng, backups: list) -> None:
    """The main.py sequence: prepare -> create_all -> run_migrations."""
    prepare_migrations(eng, backup=backups.append)
    Base.metadata.create_all(eng)
    run_migrations(eng)


def _insert_deal(eng) -> str:
    from sqlalchemy.orm import sessionmaker

    from app.models import Deal

    session = sessionmaker(bind=eng)()
    try:
        deal = Deal(name="Inserted after migration", inputs={})
        session.add(deal)
        session.commit()
        session.refresh(deal)
        assert deal.tags == []
        assert deal.archived_at is None
        return deal.id
    finally:
        session.close()


def test_schema_version_is_2():
    assert SCHEMA_VERSION == 2


def test_laptop_v1_database_migrates_to_v2(tmp_path):
    eng = _engine(tmp_path)
    with eng.begin() as conn:
        conn.execute(text(_V1_DEALS_DDL))
        conn.execute(
            text(
                "INSERT INTO deals (id, name, inputs, status, created_at, updated_at) "
                "VALUES ('d1', 'Legacy', '{}', 'screening', '2026-01-01', '2026-01-01')"
            )
        )
    _create_tables_except(eng, {"deals"} | _AGENT_TABLES)
    with eng.begin() as conn:
        conn.exec_driver_sql("PRAGMA user_version = 1")
    assert "tags" not in _deal_columns(eng)

    backups: list = []
    _startup(eng, backups)

    assert backups == [1]
    assert _version(eng) == 2
    assert {"archived_at", "tags"} <= _deal_columns(eng)
    assert _AGENT_TABLES <= _table_names(eng)
    with eng.connect() as conn:
        row = conn.execute(text("SELECT tags, archived_at FROM deals WHERE id = 'd1'")).one()
    assert row[0] == "[]" and row[1] is None
    _insert_deal(eng)
    # Idempotent: a second startup neither backs up nor changes anything.
    _startup(eng, backups)
    assert backups == [1] and _version(eng) == 2


def test_run6_shaped_v0_database_migrates_to_v2(tmp_path):
    """Run 6 never stamped user_version, already has archived_at/tags (tags
    NOT NULL, no default) and the agent tables, but lacks ic_events."""
    eng = _engine(tmp_path)
    with eng.begin() as conn:
        conn.execute(text(_RUN6_DEALS_DDL))
    _create_tables_except(eng, {"deals", "ic_events"})
    with eng.begin() as conn:
        # A legacy orphan scenario forces the Default Deal backfill's raw
        # INSERT, which must supply tags on this table shape.
        conn.execute(
            text(
                "INSERT INTO scenarios (id, scenario_name, kind, inputs, outputs, created_at, updated_at) "
                "VALUES ('s1', 'Orphan', 'full', '{}', '{}', '2026-01-01', '2026-01-01')"
            )
        )
    assert _version(eng) == 0 and "ic_events" not in _table_names(eng)

    backups: list = []
    _startup(eng, backups)

    assert backups == [0]
    assert _version(eng) == 2
    assert "ic_events" in _table_names(eng)
    with eng.connect() as conn:
        deal_id, tags = conn.execute(
            text("SELECT id, tags FROM deals WHERE name = 'Default Deal'")
        ).one()
        scenario_deal = conn.execute(text("SELECT deal_id FROM scenarios WHERE id = 's1'")).scalar()
    assert tags == "[]" and scenario_deal == deal_id
    _insert_deal(eng)


def test_fresh_database_gets_v2_schema_and_accepts_deals(tmp_path):
    eng = _engine(tmp_path)
    backups: list = []
    _startup(eng, backups)
    assert backups == [] and _version(eng) == 2
    assert {"archived_at", "tags"} <= _deal_columns(eng)
    assert _AGENT_TABLES <= _table_names(eng)
    _insert_deal(eng)
    # The server_default lets a raw INSERT that omits tags succeed too.
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO deals (id, name, inputs, status, created_at, updated_at) "
                "VALUES ('raw', 'Raw', '{}', 'screening', '2026-01-01', '2026-01-01')"
            )
        )
        assert conn.execute(text("SELECT tags FROM deals WHERE id = 'raw'")).scalar() == "[]"
