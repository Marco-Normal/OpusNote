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
# Point the legacy-import settings at the scratch directory too. Without this the
# repertoire tests would read the real piano-progress library on this machine.
os.environ["SRT_LEGACY_DB"] = str(_TMP_ROOT / "legacy-piano.db")
# Deliberately NOT the legacy media directory: "copied into our library" and
# "still only in the old app's directory" must be distinguishable in tests.
os.environ["SRT_MEDIA_DIR"] = str(_TMP_ROOT / "ecosystem-media")

import pytest  # noqa: E402

from app import db as db_module  # noqa: E402
from app import main as main_module  # noqa: E402
from app import services  # noqa: E402
from app.config import settings  # noqa: E402


def _wipe() -> None:
    # The capture heartbeat is process-local, so it outlives a database wipe.
    from app.practice import capture_status

    capture_status.reset()

    for path in (_TEST_DB, Path(str(_TEST_DB) + "-wal"), Path(str(_TEST_DB) + "-shm")):
        if path.exists():
            path.unlink()
    # Wipe the media directories too. A "fresh" database whose media directory
    # still holds files from the previous test is not fresh, and it silently
    # turns "not copied yet" into "already copied".
    for name in ("ecosystem-media", "media"):
        shutil.rmtree(_TMP_ROOT / name, ignore_errors=True)


@pytest.fixture
def legacy_db():
    """A piano-progress-shaped database, rebuilt for each test that needs one."""
    path = Path(os.environ["SRT_LEGACY_DB"])
    build_legacy_db(path)
    yield path
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
    """A client that is treated as the piano machine.

    `TestClient` is not a socket, so its client address is the literal "testclient"
    and `hostinfo.is_loopback` answers False. That is correct behaviour and useless
    for a suite in which almost every write is a delete: rather than weaken the
    check, the suite declares itself local for the duration and the two directions
    are tested explicitly in `test_server_hardening.py` (the real implementation
    directly, and a 403 by patching `is_loopback` back to False).
    """
    from fastapi.testclient import TestClient

    from app import hostinfo

    original = hostinfo.is_loopback
    hostinfo.is_loopback = lambda request: True
    try:
        with TestClient(main_module.app) as test_client:
            yield test_client
    finally:
        hostinfo.is_loopback = original


LEGACY_SCHEMA = """
CREATE TABLE composers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    notes TEXT
);
CREATE TABLE pieces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    composer_id INTEGER,
    title TEXT NOT NULL,
    difficulty TEXT,
    key TEXT,
    started_on TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    description TEXT,
    created_at TEXT,
    opus TEXT
);
CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    piece_id INTEGER,
    entry_date TEXT,
    content TEXT,
    practice_minutes INTEGER,
    created_at TEXT
);
CREATE TABLE media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    piece_id INTEGER,
    kind TEXT,
    file_name TEXT,
    original_name TEXT,
    title TEXT,
    duration_secs REAL,
    size_bytes INTEGER,
    codec TEXT,
    taken_on TEXT,
    created_at TEXT
);
"""


def build_legacy_db(path: Path, *, media_files: int = 2) -> Path:
    """A minimal database shaped like the Rust app's, for import tests."""
    import sqlite3

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.execute("INSERT INTO composers (id, name, notes) VALUES (1, 'Chopin', 'Romantic')")
    conn.execute("INSERT INTO composers (id, name, notes) VALUES (2, 'Bach', NULL)")
    conn.execute(
        "INSERT INTO pieces (id, composer_id, title, opus, difficulty, key, status, started_on)"
        " VALUES (1, 1, 'Ballade', 'Op. 23', 'Intermediate', 'B Major', 'active', '2026-01-05')"
    )
    conn.execute(
        "INSERT INTO pieces (id, composer_id, title, opus, difficulty, key, status)"
        " VALUES (2, 2, 'Prelude', 'BWV 846', 'Early Intermediate', 'C Major', 'completed')"
    )
    conn.execute(
        "INSERT INTO notes (id, piece_id, entry_date, content, practice_minutes)"
        " VALUES (1, 1, '2026-02-01', 'Hands separate, bars 1-16.', 30)"
    )
    conn.execute(
        "INSERT INTO notes (id, piece_id, entry_date, content)"
        " VALUES (2, 1, '2026-02-02', 'Coda still shaky.')"
    )
    # One journal row with no piece, to prove it is skipped rather than crashing.
    conn.execute("INSERT INTO notes (id, piece_id, entry_date, content) VALUES (3, NULL, '2026-02-03', 'orphan')")

    media_dir = path.parent / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    for index in range(media_files):
        name = f"{'ab' * 32}{index}.ogg" if False else f"hash{index:02d}.ogg"
        (media_dir / name).write_bytes(b"fake audio")
        conn.execute(
            "INSERT INTO media (id, piece_id, kind, file_name, original_name, duration_secs,"
            " size_bytes, codec) VALUES (?, 1, 'audio', ?, ?, 61.5, 10, 'opus')",
            (index + 1, name, f"recording{index}.ogg"),
        )
    # One row whose file is absent, to prove the report counts it.
    conn.execute(
        "INSERT INTO media (id, piece_id, kind, file_name, original_name)"
        " VALUES (99, 1, 'audio', 'missing.ogg', 'gone.ogg')"
    )
    conn.commit()
    conn.close()
    return path


#: The tables the standalone practice-logger added to the Rust app's database.
#: Column names are copied from its `app/db.py`, because the point of the
#: importer test is to read the real shape rather than one we invented.
LEGACY_PRACTICE_SCHEMA = """
CREATE TABLE practice_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_ms INTEGER NOT NULL,
    ended_ms INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    local_date TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'web_midi'
);
CREATE TABLE note_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    onset_ms INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    pitch INTEGER NOT NULL,
    velocity INTEGER NOT NULL,
    channel INTEGER
);
CREATE TABLE segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    piece_id INTEGER,
    confidence REAL,
    identified_by TEXT
);
"""


def add_legacy_practice(path: Path) -> Path:
    """Give a legacy database some practice history from the standalone logger.

    Two sittings a week apart, three notes in the first and two in the second, and
    a segment in the first labelled with legacy piece 1 — enough to prove the
    import remaps pieces, keeps times, and is idempotent.
    """
    import sqlite3

    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_PRACTICE_SCHEMA)
    base = 1_700_011_800_000
    conn.execute(
        "INSERT INTO practice_sessions (id, started_ms, ended_ms, started_at, ended_at,"
        " local_date, source) VALUES (1, ?, ?, '2023-11-15 01:30:00',"
        " '2023-11-15 01:30:01', '2023-11-15', 'web_midi')",
        (base, base + 1_300),
    )
    conn.execute(
        "INSERT INTO practice_sessions (id, started_ms, ended_ms, started_at, ended_at,"
        " local_date, source) VALUES (2, ?, ?, '2023-11-22 18:00:00',"
        " '2023-11-22 18:00:02', '2023-11-22', 'web_midi')",
        (base + 604_800_000, base + 604_802_000),
    )
    for index, onset in enumerate((0, 500, 1_000)):
        conn.execute(
            "INSERT INTO note_events (session_id, onset_ms, duration_ms, pitch, velocity,"
            " channel) VALUES (1, ?, 300, ?, 70, 0)",
            (onset, 60 + index),
        )
    for onset in (0, 500):
        conn.execute(
            "INSERT INTO note_events (session_id, onset_ms, duration_ms, pitch, velocity,"
            " channel) VALUES (2, ?, 300, ?, 70, 0)",
            (onset, 60),
        )
    conn.execute(
        "INSERT INTO segments (session_id, start_ms, end_ms, piece_id, confidence,"
        " identified_by) VALUES (1, 0, 1300, 1, 1.0, 'manual')"
    )
    conn.commit()
    conn.close()
    return path


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)
