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


def run_migrations() -> None:
    """Minimal, idempotent schema patches for an existing SQLite file — this app
    has no Alembic, so hand-roll the one migration it currently needs: scenarios
    gained a `kind` column and template_id/mapping_profile_id became nullable
    (quickscreen-kind scenarios have neither). Safe to call on every startup."""
    inspector = inspect(engine)
    if "scenarios" not in inspector.get_table_names():
        return

    columns = {c["name"]: c for c in inspector.get_columns("scenarios")}
    needs_kind = "kind" not in columns
    needs_nullable = columns.get("template_id", {}).get("nullable") is False

    if not needs_kind and not needs_nullable:
        return

    with engine.begin() as conn:
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
