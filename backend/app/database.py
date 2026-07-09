from datetime import UTC

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
    _migrate_extraction_unit_mix_proposal(eng)
    _migrate_deals_status(eng)
    _migrate_documents_deal_id(eng)


def _migrate_documents_deal_id(eng) -> None:
    """Documents gained a deal_id column — pre-existing rows are left NULL
    (unassigned) rather than guessed at; the list endpoint only returns a
    NULL row when no dealId filter is given, so nothing already uploaded
    disappears, but it also won't show up mixed into any specific deal."""
    inspector = inspect(eng)
    if "documents" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("documents")}
    if "deal_id" in columns:
        return
    with eng.begin() as conn:
        conn.execute(text("ALTER TABLE documents ADD COLUMN deal_id VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_deal_id ON documents (deal_id)"))


def _migrate_deals_status(eng) -> None:
    """Deals gained a pipeline status column (H7); existing rows default to
    'screening'."""
    inspector = inspect(eng)
    if "deals" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("deals")}
    if "status" in columns:
        return
    with eng.begin() as conn:
        conn.execute(text("ALTER TABLE deals ADD COLUMN status VARCHAR DEFAULT 'screening'"))
        conn.execute(text("UPDATE deals SET status = 'screening' WHERE status IS NULL"))


def _migrate_extraction_unit_mix_proposal(eng) -> None:
    """extraction_results gained a unit_mix_proposal JSON column (G5) and a
    commercial_lease_proposal column (H1)."""
    inspector = inspect(eng)
    if "extraction_results" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("extraction_results")}
    with eng.begin() as conn:
        if "unit_mix_proposal" not in columns:
            conn.execute(text("ALTER TABLE extraction_results ADD COLUMN unit_mix_proposal JSON"))
        if "commercial_lease_proposal" not in columns:
            conn.execute(
                text("ALTER TABLE extraction_results ADD COLUMN commercial_lease_proposal JSON")
            )


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
                        (id, scenario_name, kind, template_id, mapping_profile_id,
                         inputs, outputs, created_at, updated_at)
                    SELECT id, scenario_name, {kind_select}, template_id, mapping_profile_id,
                        inputs, outputs, created_at, updated_at
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
    from datetime import datetime

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
            now = datetime.now(UTC).isoformat(sep=" ")
            # status only exists once create_all/_migrate_deals_status has run;
            # both happen before this backfill, but a hand-built legacy table
            # may still lack it — probe instead of assuming.
            deal_columns = {c["name"] for c in inspector.get_columns("deals")}
            status_col = ", status" if "status" in deal_columns else ""
            status_val = ", 'screening'" if "status" in deal_columns else ""
            conn.execute(
                text(
                    "INSERT INTO deals (id, name, inputs, active_template_id, active_mapping_profile_id, created_at, updated_at"  # noqa: E501
                    f"{status_col}) "
                    f"VALUES (:id, 'Default Deal', '{{}}', NULL, NULL, :now, :now{status_val})"
                ),
                {"id": default_deal_id, "now": now},
            )
        conn.execute(
            text("UPDATE scenarios SET deal_id = :deal_id WHERE deal_id IS NULL"),
            {"deal_id": default_deal_id},
        )
