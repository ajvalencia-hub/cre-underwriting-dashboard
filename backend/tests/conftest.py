"""Shared pytest configuration for the backend suite.

Two jobs:

1. **Isolate the on-disk storage.** ``app.config`` resolves ``CRE_STORAGE_ROOT``
   / ``CRE_DB_PATH`` from the environment *at import time* and creates the
   directories immediately, and most test modules ``import app.main`` at
   collection time. pytest imports this conftest before it imports any test
   module in ``tests/`` (and ``tests/__init__.py`` is empty), so setting the
   variables here — at module import, not inside a fixture — is early enough:
   every ``app.*`` import in the session sees a throwaway storage root instead
   of ``backend/storage``. ``load_dotenv`` in ``app.config`` never overrides
   variables that already exist, so a developer's ``backend/.env`` cannot
   redirect the suite back to the real directory either.

   Limitation: anything imported *before* pytest loads this conftest (a
   ``-p`` plugin, or running a test module as a script) bypasses the redirect.
   ``python -m tests.parity.run`` is a CLI, not a pytest run, and deliberately
   uses the real config with its own temp dirs.

2. **Shared DB fixtures.** ``session_factory`` (in-memory SQLite on a
   ``StaticPool`` so every connection shares one database, ``create_all`` +
   ``run_migrations``) and ``client`` (a ``TestClient`` with ``get_db``
   overridden onto that factory; ``client._session`` exposes the factory for
   tests that seed rows directly). A test module may still define its own
   ``client`` — pytest's nearest-definition rule makes the module-level one
   win, and a module fixture may *extend* this one by requesting it under the
   same name (see ``test_memo.py``).
"""

import os
import shutil
import tempfile

# ---- 1. storage isolation — MUST run before any `app.*` import ---------------
_SCRATCH_ROOT = tempfile.mkdtemp(prefix="cre-tests-")
os.environ["CRE_STORAGE_ROOT"] = _SCRATCH_ROOT
os.environ["CRE_DB_PATH"] = os.path.join(_SCRATCH_ROOT, "db", "test.sqlite3")
# The suite must never spawn the daily backup thread or hit a token gate a
# developer happens to have configured locally.
os.environ["CRE_ENABLE_BACKUP_SCHEDULER"] = "0"
os.environ["CRE_API_TOKEN"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db, run_migrations  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _scratch_storage_root():
    """Yields the throwaway storage root and removes it when the session ends.
    The real app engine is disposed first so Windows releases the SQLite
    file handle; removal is best-effort (a straggling soffice profile dir
    should never fail the run)."""
    yield _SCRATCH_ROOT
    from app.database import engine as app_engine

    app_engine.dispose()
    shutil.rmtree(_SCRATCH_ROOT, ignore_errors=True)


@pytest.fixture
def session_factory():
    """sessionmaker bound to a fresh in-memory SQLite database (StaticPool =
    one shared connection, so the schema created here is visible to every
    session the app opens). Migrations run so tests see the same indexes /
    columns a real startup produces."""
    db_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(db_engine)
    run_migrations(db_engine)
    yield sessionmaker(bind=db_engine)
    db_engine.dispose()


@pytest.fixture
def client(session_factory):
    """TestClient whose `get_db` dependency yields sessions from
    `session_factory`. `client._session` is the factory itself for tests
    that need to seed or inspect rows outside the API."""

    def _override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    test_client = TestClient(app)
    test_client._session = session_factory  # type: ignore[attr-defined]
    yield test_client
    app.dependency_overrides.pop(get_db, None)
