"""Workout schema.

Executed last by :mod:`app.db`: ``workouts`` references ``sittings`` and
``performances.workout_id`` references ``workouts``, so both parents must exist
before SQLite will accept an insert into either.
"""

from __future__ import annotations

WORKOUT_SCHEMA = """
CREATE TABLE IF NOT EXISTS workouts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_ms    INTEGER NOT NULL,
    ended_ms      INTEGER,               -- NULL while the workout is running
    local_date    TEXT NOT NULL,
    target_skill  TEXT,                  -- NULL means "whatever the engine picks"
    bars          INTEGER,
    planned       INTEGER,               -- exercises intended, for the progress bar
    completed     INTEGER NOT NULL DEFAULT 0,
    -- The sitting this workout happened inside, resolved when it finishes. A
    -- workout with no notes played links to nothing, which is the honest answer.
    sitting_id    INTEGER REFERENCES sittings(id) ON DELETE SET NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_workouts_date ON workouts(local_date DESC);
CREATE INDEX IF NOT EXISTS idx_workouts_open ON workouts(ended_ms);
"""


#: Additive columns, applied before ``WORKOUT_SCHEMA`` for the same reason the
#: other domains do it: an existing ``performances`` table needs the column added
#: before anything can reference it.
ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    (
        "performances",
        "workout_id",
        "INTEGER REFERENCES workouts(id) ON DELETE SET NULL",
    ),
)


def migrate(conn) -> list[str]:
    applied: list[str] = []
    for table, column, kind in ADDED_COLUMNS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            applied.append(f"{table}.{column}")
    return applied
