"""Workout lifecycle: start, current, finish, and the statistics built on them."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from .. import db
from ..config import settings
from ..practice.store import local_date, utc_text
from .models import WorkoutOut


class NotFound(Exception):
    """The requested workout does not exist."""


class InvalidRequest(Exception):
    """Well-formed, but not applicable to the current state."""


def _row_out(conn: sqlite3.Connection, row: sqlite3.Row, now_ms: int) -> WorkoutOut:
    start = int(row["started_ms"])
    end = int(row["ended_ms"]) if row["ended_ms"] is not None else now_ms
    done = conn.execute(
        "SELECT COUNT(*) FROM performances WHERE workout_id = ?", (row["id"],)
    ).fetchone()[0]
    return WorkoutOut(
        id=int(row["id"]),
        started_ms=start,
        started_at=utc_text(start),
        ended_ms=int(row["ended_ms"]) if row["ended_ms"] is not None else None,
        ended_at=utc_text(int(row["ended_ms"])) if row["ended_ms"] is not None else None,
        local_date=row["local_date"],
        target_skill=row["target_skill"],
        bars=row["bars"],
        planned=row["planned"],
        completed=bool(row["completed"]),
        running=row["ended_ms"] is None,
        sitting_id=row["sitting_id"],
        exercises_done=int(done),
        minutes=round((end - start) / 60000.0, 1),
    )


def _fetch(conn: sqlite3.Connection, workout_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM workouts WHERE id = ?", (workout_id,)).fetchone()
    if row is None:
        raise NotFound(f"no workout {workout_id}")
    return row


def current(now_ms: int | None = None, db_path: Path | None = None) -> WorkoutOut | None:
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    conn = db.connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM workouts WHERE ended_ms IS NULL ORDER BY started_ms DESC LIMIT 1"
        ).fetchone()
        return _row_out(conn, row, now) if row else None
    finally:
        conn.close()


def start(
    *,
    tz_offset_minutes: int,
    target_skill: str | None = None,
    bars: int | None = None,
    now_ms: int | None = None,
    db_path: Path | None = None,
) -> WorkoutOut:
    """Begin a workout, or hand back the one already running.

    Idempotent on purpose: two open workouts would make "which workout is this
    attempt part of" ambiguous, and a second Start click is far more likely than
    an intent to abandon the first.
    """
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    with db.transaction(db_path) as conn:
        existing = conn.execute(
            "SELECT * FROM workouts WHERE ended_ms IS NULL ORDER BY started_ms DESC LIMIT 1"
        ).fetchone()
        if existing is not None:
            return _row_out(conn, existing, now)

        created = conn.execute(
            "INSERT INTO workouts (started_ms, local_date, target_skill, bars, planned)"
            " VALUES (?1, ?2, ?3, ?4, ?5)",
            (
                now,
                local_date(now, tz_offset_minutes),
                target_skill,
                bars or settings.exercise_bars,
                settings.workout_length,
            ),
        )
        return _row_out(conn, _fetch(conn, int(created.lastrowid)), now)


def finish(
    workout_id: int, now_ms: int | None = None, db_path: Path | None = None
) -> WorkoutOut:
    """Close a workout and resolve which sitting it happened inside."""
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    with db.transaction(db_path) as conn:
        row = _fetch(conn, workout_id)
        if row["ended_ms"] is None:
            ended = max(now, int(row["started_ms"]))
            conn.execute(
                "UPDATE workouts SET ended_ms = ?1, completed = 1 WHERE id = ?2",
                (ended, workout_id),
            )
            conn.execute(
                "UPDATE workouts SET sitting_id = ?1 WHERE id = ?2",
                (_sitting_for(conn, int(row["started_ms"]), ended), workout_id),
            )
        return _row_out(conn, _fetch(conn, workout_id), now)


def _sitting_for(conn: sqlite3.Connection, start_ms: int, end_ms: int) -> int | None:
    """The sitting a workout happened inside, if there is one.

    Matched on *overlap*, not on where the workout ended: a workout is largely
    spent reading and thinking, so its last note can fall more than one gap before
    the player stops the clock. Requiring containment would lose exactly the
    workouts that ended in reflection.

    A workout with no note received at all (MIDI unplugged, tab asleep) links to
    nothing rather than to whatever sitting happened to be nearest.
    """
    row = conn.execute(
        """
        SELECT id FROM sittings
        WHERE started_ms <= ?1 AND ended_ms + ?2 >= ?3
        ORDER BY started_ms DESC
        LIMIT 1
        """,
        (end_ms, settings.sitting_gap_s * 1000, start_ms),
    ).fetchone()
    return int(row["id"]) if row else None


def recent(limit: int = 10, db_path: Path | None = None) -> list[WorkoutOut]:
    now = int(time.time() * 1000)
    conn = db.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM workouts WHERE ended_ms IS NOT NULL"
            " ORDER BY started_ms DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_out(conn, row, now) for row in rows]
    finally:
        conn.close()


def open_workout(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """The running workout, for a caller that already holds a connection."""
    return conn.execute(
        "SELECT * FROM workouts WHERE ended_ms IS NULL ORDER BY started_ms DESC LIMIT 1"
    ).fetchone()


def attach_performance(conn: sqlite3.Connection, performance_id: int) -> int | None:
    """Attribute an attempt to the running workout, if there is one.

    Called after scoring, so a performance is never lost to a workout lookup
    failing; the worst case is an attempt that counts as ordinary sight-reading.
    """
    row = open_workout(conn)
    if row is None:
        return None
    conn.execute(
        "UPDATE performances SET workout_id = ?1 WHERE id = ?2",
        (int(row["id"]), performance_id),
    )
    return int(row["id"])


def stats(conn: sqlite3.Connection, days: int = 7) -> dict[str, object]:
    today = datetime.now().date()
    since = (today - timedelta(days=days - 1)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS completed, MAX(local_date) AS last_date"
        " FROM workouts WHERE completed = 1"
    ).fetchone()
    week = conn.execute(
        "SELECT COUNT(*) FROM workouts WHERE completed = 1 AND local_date >= ?", (since,)
    ).fetchone()[0]
    return {
        "workouts_completed": int(row["completed"] or 0),
        "workouts_this_week": int(week or 0),
        "last_workout_date": row["last_date"],
        "window_days": days,
    }
