"""Shared fixtures.

The database path is redirected *before* any ``app`` module is imported so the
whole suite runs against a throwaway file inside the repo (not ``/tmp``, which
is not reliably writable in this environment).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_TMP_ROOT = Path(__file__).resolve().parent.parent / ".pytest-tmp"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)
_TEST_DB = _TMP_ROOT / "test.sqlite3"
os.environ["SRT_DB_PATH"] = str(_TEST_DB)

import pytest  # noqa: E402

from app import db as db_module  # noqa: E402
from app import main as main_module  # noqa: E402
from app import services  # noqa: E402
from app.config import settings  # noqa: E402


def _wipe() -> None:
    for path in (_TEST_DB, Path(str(_TEST_DB) + "-wal"), Path(str(_TEST_DB) + "-shm")):
        if path.exists():
            path.unlink()


@pytest.fixture
def fresh_db():
    _wipe()
    db_module.init_db(settings.db_path)
    user_id = services.init_workspace()
    main_module.USER_ID = user_id
    yield user_id
    _wipe()


@pytest.fixture
def conn(fresh_db):
    connection = db_module.connect(settings.db_path)
    yield connection
    connection.close()


@pytest.fixture
def client(fresh_db):
    from fastapi.testclient import TestClient

    with TestClient(main_module.app) as test_client:
        yield test_client


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)
