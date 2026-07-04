from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DB_PATH

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations(target_engine=None) -> None:
    """Minimal, idempotent schema patches for an existing SQLite file — this
    app has no Alembic, so hand-roll each migration as an independent
    check-and-patch step. Safe to call on every startup. `target_engine` is
    injectable so migration tests can run against a scratch database."""
    eng = target_engine if target_engine is not None else engine
    _migrate_scenarios_kind_and_nullable(eng)
    _migrate_scenarios_deal_id(eng)
    _backfill_orphan_scenarios_onto_default_deal(eng)
    _migrate_scenarios_sensitivity(eng)


def _migrate_scenarios_sensitivity(eng) -> None:
    """Scenarios gained a sensitivity JSON column (saved sensitivity runs)."""
    inspector = inspect(eng)
    if "scenarios" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("scenarios")}
    if "sensitivity" in columns:
        return
    with eng.begin() as conn:
        conn.execute(text("ALTER TABLE scenarios ADD COLUMN sensitivity JSON"))


def _migrate_scenarios_kind_and_nullable(eng) -> None:
    """Scenarios gained a `kind` column and template_id/mapping_profile_id
    became nullable (quickscreen-kind scenarios have neither)."""
    inspector = inspect(eng)
    if "scenarios" not in inspector.get_table_names():
        return

    columns = {c["name"]: c for c in inspector.get_columns("scenarios")}
    needs_kind = "kind" not in columns
    needs_nullable = columns.get("template_id", {}).get("nullable") is False

    if not needs_kind and not needs_nullable:
        return

    with eng.begin() as conn:
        if needs_kind and not needs_nullable:
            conn.execute(text("ALTER TABLE scenarios ADD COLUMN kind VARCHAR DEFAULT 'full'"))
            return

        if needs_nullable:
            # SQLite can't drop a NOT NULL constraint in place — rebuild the table,
            # preserving existing rows.
            conn.execute(text("ALTER TABLE scenarios RENAME TO scenarios_old"))
            conn.execute(
                text(
                    """
                    CREATE TABLE scenarios (
                        id VARCHAR PRIMARY KEY,
                        scenario_name VARCHAR,
                        kind VARCHAR DEFAULT 'full',
                        template_id VARCHAR,
                        mapping_profile_id VARCHAR,
                        inputs JSON,
                        outputs JSON,
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                    """
                )
            )
            kind_select = "kind" if needs_kind is False else "'full'"
            conn.execute(
                text(
                    f"""
                    INSERT INTO scenarios
                        (id, scenario_name, kind, template_id, mapping_profile_id, inputs, outputs, created_at, updated_at)
                    SELECT id, scenario_name, {kind_select}, template_id, mapping_profile_id, inputs, outputs, created_at, updated_at
                    FROM scenarios_old
                    """
                )
            )
            conn.execute(text("DROP TABLE scenarios_old"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_scenarios_template_id ON scenarios (template_id)"))
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_scenarios_mapping_profile_id ON scenarios (mapping_profile_id)")
            )


def _migrate_scenarios_deal_id(eng) -> None:
    """Scenarios gained a deal_id column when multi-deal support landed."""
    inspector = inspect(eng)
    if "scenarios" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("scenarios")}
    if "deal_id" in columns:
        return
    with eng.begin() as conn:
        conn.execute(text("ALTER TABLE scenarios ADD COLUMN deal_id VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_scenarios_deal_id ON scenarios (deal_id)"))


def _backfill_orphan_scenarios_onto_default_deal(eng) -> None:
    """Legacy scenarios predate deals entirely — give them a home so the
    deal-scoped scenario list still shows them. Only creates the Default Deal
    when orphans actually exist."""
    import uuid
    from datetime import datetime, timezone

    inspector = inspect(eng)
    tables = inspector.get_table_names()
    if "scenarios" not in tables or "deals" not in tables:
        return

    with eng.begin() as conn:
        orphans = conn.execute(
            text("SELECT COUNT(*) FROM scenarios WHERE deal_id IS NULL")
        ).scalar()
        if not orphans:
            return
        default_deal_id = conn.execute(
            text("SELECT id FROM deals WHERE name = 'Default Deal' LIMIT 1")
        ).scalar()
        if default_deal_id is None:
            default_deal_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat(sep=" ")
            conn.execute(
                text(
                    "INSERT INTO deals (id, name, inputs, active_template_id, active_mapping_profile_id, created_at, updated_at) "
                    "VALUES (:id, 'Default Deal', '{}', NULL, NULL, :now, :now)"
                ),
                {"id": default_deal_id, "now": now},
            )
        conn.execute(
            text("UPDATE scenarios SET deal_id = :deal_id WHERE deal_id IS NULL"),
            {"deal_id": default_deal_id},
        )
