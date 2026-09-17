"""SQLite persistence layer.

Schema follows the MVP blueprint: users, skills, user_skills, exercises,
exercise_skills, performances. Three *additive* columns/columns-sets exist
beyond the blueprint so the API can be stateless about exercise content:

* ``exercises.params_json``   - generator parameters (for reproducibility)
* ``exercises.expected_json`` - the expected-note timeline used by scoring
* ``performances.analysis_json`` - per-note feedback for the stats screen

No ORM: plain sqlite3 with short-lived connections keeps the layer swappable for
PostgreSQL later (the SQL is ANSI apart from the AUTOINCREMENT spelling).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import settings
from .practice.schema import PRACTICE_SCHEMA, migrate as migrate_practice
from .repertoire.schema import REPERTOIRE_SCHEMA, migrate as migrate_repertoire
from .workout.schema import WORKOUT_SCHEMA, migrate as migrate_workouts

#: The schema generation this code builds. Written to ``PRAGMA user_version`` at the
#: *end* of :func:`init_db`, so a database can say which version of the app made it and
#: an older build can refuse it instead of reading columns it does not understand. Bump
#: this whenever a migration changes the shape an older reader could not honour.
SCHEMA_VERSION = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS skills (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slug          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL UNIQUE,
    description   TEXT,
    sort_order    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_skills (
    user_id           INTEGER NOT NULL,
    skill_id          INTEGER NOT NULL,
    elo_rating        REAL NOT NULL DEFAULT 700.0,
    attempts          INTEGER NOT NULL DEFAULT 0,
    last_practiced_at TIMESTAMP,
    PRIMARY KEY (user_id, skill_id),
    FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE CASCADE,
    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exercises (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    musicxml_blob   TEXT NOT NULL,
    difficulty_elo  REAL NOT NULL,
    key_name        TEXT,
    meter           TEXT,
    bars            INTEGER,
    tempo_bpm       REAL,
    generator_seed  INTEGER,
    source          TEXT NOT NULL DEFAULT 'generated',
    params_json     TEXT,
    expected_json   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exercise_skills (
    exercise_id INTEGER NOT NULL,
    skill_id    INTEGER NOT NULL,
    level       INTEGER NOT NULL,
    PRIMARY KEY (exercise_id, skill_id),
    FOREIGN KEY (exercise_id) REFERENCES exercises(id) ON DELETE CASCADE,
    FOREIGN KEY (skill_id)    REFERENCES skills(id)    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS performances (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL,
    exercise_id         INTEGER NOT NULL,
    score               REAL,
    pitch_accuracy      REAL,
    rhythm_accuracy     REAL,
    continuity_accuracy REAL,
    mode                TEXT NOT NULL DEFAULT 'practice',
    tempo_bpm           REAL,
    latency_ms          REAL DEFAULT 0,
    played_notes_json   TEXT,
    analysis_json       TEXT,
    performed_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id)     REFERENCES users(id)     ON DELETE CASCADE,
    FOREIGN KEY (exercise_id) REFERENCES exercises(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_performances_user_time
    ON performances (user_id, performed_at DESC);

-- Every Elo change, one row per skill per performance.
--
-- `user_skills` holds only the current rating, so without this there is no curve to
-- draw: "your rhythm is up 40 points this month" is the reason a rating is worth
-- keeping, and a number that only ever shows today's value cannot say it.
CREATE TABLE IF NOT EXISTS rating_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    skill_id       INTEGER NOT NULL,
    before         REAL NOT NULL,
    after          REAL NOT NULL,
    score          REAL,
    performance_id INTEGER REFERENCES performances(id) ON DELETE SET NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE CASCADE,
    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rating_events_skill
    ON rating_events (user_id, skill_id, id);
CREATE INDEX IF NOT EXISTS idx_exercise_skills_skill
    ON exercise_skills (skill_id);
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat(sep=" ")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False is required, not a shortcut. FastAPI resolves a
    # sync dependency and runs a sync endpoint in *different* threadpool threads,
    # so a connection created in the dependency would be used from another
    # thread and SQLite refuses it. Safe here because a connection is opened per
    # request, handed to exactly one request, and used sequentially — never
    # shared concurrently, which is the hazard the flag actually guards.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    # Two machines write to this file over the LAN (capture on the notebook, an
    # upload from the main computer), so "database is locked" must be waited out
    # rather than raised. Five seconds is far longer than any write here takes.
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(
    db_path: Path | None = None, *, immediate: bool = False
) -> Iterator[sqlite3.Connection]:
    """One write transaction. `immediate` takes the write lock before the first read.

    A plain `BEGIN` is deferred: the read snapshot is fixed by the first SELECT, and if another
    connection commits before this one writes, SQLite cannot upgrade the read transaction and
    raises `SQLITE_BUSY_SNAPSHOT` — reported as "database is locked", and *not* retried by
    `busy_timeout`. A transaction that reads a row and then decides to write it must therefore
    say so up front, or a second reader can turn its UPDATE into an error.
    """
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


class SchemaTooNew(RuntimeError):
    """The database was written by a newer version of the app than this code knows.

    There is no downgrade path and there cannot be an honest one: a newer schema may have
    reshaped a column this build would read as something else. Refusing is the only
    failure that does not risk the player's practice log.
    """


def init_db(db_path: Path | None = None) -> None:
    """Create or upgrade the database. The single creation path.

    Each domain owns its own DDL; this function owns the order. The order is not
    arbitrary — ``segments`` references ``pieces`` and ``workouts``, so the
    practice schema runs between them, and a migration must run before the script
    that indexes the column it adds. Columns are added first on an existing
    database (a no-op on a fresh one, where the CREATE handles everything).
    """
    conn = connect(db_path)
    try:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise SchemaTooNew(
                f"the database reports schema version {version} but this build only "
                f"knows {SCHEMA_VERSION}; upgrade the app before opening it"
            )
        conn.executescript(SCHEMA)
        migrate_repertoire(conn)
        conn.executescript(REPERTOIRE_SCHEMA)
        migrate_practice(conn)
        conn.executescript(PRACTICE_SCHEMA)
        migrate_workouts(conn)
        conn.executescript(WORKOUT_SCHEMA)
        # Last, and as text: SQLite rejects a bound parameter in a PRAGMA, and the version
        # must describe a schema that finished building rather than one about to.
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class CorruptJSON(ValueError):
    """Stored JSON text is damaged, so the row cannot be read as the shape it claims.

    Distinct from an empty value: ``NULL`` or the empty string means "nothing stored",
    which is a legitimate default. Text that does not parse is a fault, and T9 in
    ``docs/TEST-STRATEGY.md`` decides it must be visible rather than degrade into an
    empty list that looks like "this exercise has no expected notes".
    """


def _truncate(value: Any, limit: int = 120) -> str:
    """The raw value, short enough to put in an error message."""
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def json_load(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise CorruptJSON(
            f"stored JSON is corrupt ({type(exc).__name__}: {exc}): {_truncate(raw)}"
        ) from exc


def json_dump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=False)


def get_or_create_user(conn: sqlite3.Connection, username: str | None = None) -> int:
    username = username or settings.default_username
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute("INSERT INTO users (username) VALUES (?)", (username,))
    return int(cur.lastrowid)


def ensure_user_skill_rows(conn: sqlite3.Connection, user_id: int, skills: Iterable[dict[str, Any]]) -> None:
    for skill in skills:
        conn.execute(
            """
            INSERT INTO user_skills (user_id, skill_id, elo_rating)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id, skill_id) DO NOTHING
            """,
            (user_id, skill["id"], settings.default_rating),
        )
