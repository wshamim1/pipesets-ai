"""
Shared pytest setup for the backend.

Run from the backend directory:   pytest          (or: pytest tests/security/test_secrets.py -k rotation)

Before anything imports the app, the environment points every piece of state at a throwaway
folder: the data dir (uploads, price overrides), the SQLite DB and a fixed master key — so a
test run never touches backend/pipesets.db or backend/.secrets_master_key. Model calls use
the built-in ``mock`` provider, so tests cost nothing and need no network.

Every test module gets its own fresh, migrated, seeded database (``_fresh_database``, autouse)
and clean in-process caches. Tests inside a module run in file order and may build on each
other's data, like the steps of a scenario; modules never share state.

``TEST_DATABASE_URL`` (e.g. a Postgres service in CI) runs every module against that server
instead of SQLite; the schema is dropped and re-created per module.
"""

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="pipesets-tests-")
os.environ["PIPESETS_DATA_DIR"] = _TMP
os.environ["SQLITE_DB_PATH"] = os.path.join(_TMP, "import.db")
os.environ.setdefault("PIPESETS_MASTER_KEY", "iDJ0D5c6p9V0Yy8a6xW9bqI5Y3m6m1Gx4Jg3cFh2kZ0=")
os.environ["AUTH_MODE"] = "headers"
os.environ["SCHEDULER_ENABLED"] = "false"
for _var in ("DATABASE_URL", "LLM_BACKEND", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "PIPESETS_MASTER_KEY_KMS",
             "PIPESETS_MASTER_KEY_VAULT_PATH", "PIPESETS_MASTER_KEY_PROVIDER"):
    os.environ.pop(_var, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import db  # noqa: E402
import main  # noqa: E402
from services import llm_settings, secret_store, shared_state  # noqa: E402
from services import llm_runner  # noqa: E402

# The mock model "types" its answer for the UI (18 ms per 4 characters); tests don't need to wait
llm_runner._mock_stream.__defaults__ = (4, 0.0)


def _reset_caches() -> None:
    secret_store._fernet = None
    llm_settings._cache.clear()
    shared_state.use(None)          # back to the configured backend (memory unless the env says otherwise)


def _drop_all(url: str) -> None:
    from sqlalchemy import MetaData, create_engine
    engine = create_engine(url)
    meta = MetaData()
    meta.reflect(bind=engine)
    meta.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    engine.dispose()


@pytest.fixture(scope="module", autouse=True)
def _fresh_database(request, tmp_path_factory):
    """A new migrated + seeded database for each test module, and an environment that is
    restored afterwards (use the ``env`` fixture to change variables)."""
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        _drop_all(url)
    else:
        url = f"sqlite:///{tmp_path_factory.mktemp(request.module.__name__.rsplit('.', 1)[-1])}/test.db"
    saved_env = dict(os.environ)
    db.use_database(url)
    _reset_caches()
    db.init_db()
    shared_state.store().clear()    # rate-limit windows, login lockouts, cancel flags (after migrating: may be tables)
    yield url
    os.environ.clear()
    os.environ.update(saved_env)
    _reset_caches()


@pytest.fixture(scope="module")
def env():
    """Module-scoped monkeypatch: setenv / setattr changes last for the module, then revert."""
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def client():
    # Not a context manager, so the app's lifespan (scheduler loop) never starts.
    return TestClient(main.app)

