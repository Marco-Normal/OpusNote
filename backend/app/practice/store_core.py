"""Core practice persistence: sitting ingestion, closing, notes, and listing."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from .. import db
from . import store as _store
from . import kinds
from . import pedal_stream
from .models import (
    EventBatch,
    IngestResult,
    LoggedNote,
    LoggedPedal,
    SittingNotes,
    SittingSummary,
)
from .sessionize import Note

#: How long the piano must have been silent before a disconnect closes the sitting.
#:
#: Two failures to avoid, and the window is between them. Too short and a USB blip
#: during playing fragments a session; too long and switching the piano off
#: immediately after the last chord is refused, which is exactly how a session ends —
#: play the final chord, reach for the power switch. A second and a half is typically
#: less than the gap to the next note when someone is playing, and more than the gap
#: between a final chord and the hand reaching the switch.
CLOSE_QUIET_MS = 1_500


#: How far back to look for an open sitting to close. Without it, a device event
#: days after the last note would "close" a sitting that the silence already closed.
CLOSE_LOOKBACK_MS = 60 * 60 * 1000


#: The columns every identification query needs.
_SEGMENT_COLUMNS = "g.id, g.sitting_id, g.start_ms, g.end_ms, g.piece_id, g.identified_by"


#: Identification states that need no further question: a person has decided.
_SETTLED = ("manual", "workout")


@dataclass(frozen=True)
class CloseOutcome:
    """What closing found, including *why* it found nothing.

    The two ways to close nothing are different facts and the client has to be able
    to tell them apart. *nothing open* means the piano had already gone quiet and
    there is nothing to do; *still playing* means notes arrived moments ago and the
    sitting is deliberately being left alone, because splitting a session mid-phrase
    over a USB blip is worse than being slow. Both used to arrive as a bare `None`,
    so the interface had to guess which one it was looking at.
    """

    sitting_id: int | None
    reason: Literal["closed", "still playing", "nothing open"]


class NotFound(Exception):
    """The requested row does not exist."""


class InvalidRequest(Exception):
    """Well-formed, but not applicable to the current state."""


class ConfirmationRequired(Exception):
    """A destructive change needs explicit confirmation."""


def utc_text(epoch_ms: int) -> str:
    moment = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def local_date(epoch_ms: int, tz_offset_minutes: int) -> str:
    """The player's calendar day for an instant, computed when it happens.

    Deriving this later would be wrong across a DST change or travel: the
    historic offset is not recoverable from the stored UTC alone.
    """
    moment = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    return (moment + timedelta(minutes=tz_offset_minutes)).strftime("%Y-%m-%d")


def _find_sitting(
    conn: sqlite3.Connection, epoch_ms: int, gap_ms: int
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, started_ms
        FROM sittings
        WHERE ?1 >= started_ms AND ?1 <= ended_ms + ?2
          -- A sitting closed by hand or by the piano going away takes no more
          -- notes: the player said they were done, and playing again is a new
          -- sitting even if it is a minute later.
          AND closed_ms IS NULL
        ORDER BY started_ms DESC
        LIMIT 1
        """,
        (epoch_ms, gap_ms),
    ).fetchone()


def ingest(batch: EventBatch, db_path: Path | None = None) -> IngestResult:
    gap_ms = _store.settings.sitting_gap_s * 1000
    notes = sorted(
        (
            Note(
                epoch_ms=item.epoch_ms,
                pitch=item.pitch,
                velocity=item.velocity,
                duration_ms=item.duration_ms,
                channel=item.channel,
            )
            for item in batch.events
        ),
        key=lambda note: (note.epoch_ms, note.pitch),
    )
    pedals = sorted(batch.pedals, key=lambda pedal: pedal.epoch_ms)
    marks = sorted(batch.marks, key=lambda mark: mark.epoch_ms)
    if not notes and not pedals and not marks:
        raise InvalidRequest("cannot ingest an empty batch")

    accepted = 0
    duplicates = 0
    pedals_accepted = 0
    pedals_ignored = 0
    marks_accepted = 0
    marks_ignored = 0
    sitting_id: int | None = None
    # `immediate`: every one of these reads a row and then writes what it read, and the app's
    # own design has two machines writing this file. A deferred transaction would fix its snapshot
    # at the first SELECT and then fail the write as "database is locked" if anything committed in
    # between — SQLITE_BUSY_SNAPSHOT, which `busy_timeout` does not retry.
    with db.transaction(db_path, immediate=True) as conn:
        for note in notes:
            row = _find_sitting(conn, note.epoch_ms, gap_ms)
            if row is None:
                created = conn.execute(
                    "INSERT INTO sittings"
                    " (started_ms, ended_ms, started_at, ended_at, local_date,"
                    "  tz_offset_minutes, source)"
                    " VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                    (
                        note.epoch_ms,
                        note.end_ms,
                        utc_text(note.epoch_ms),
                        utc_text(note.end_ms),
                        local_date(note.epoch_ms, batch.tz_offset_minutes),
                        # Stored with the day it produced: the two are one decision, and
                        # `local_date` is not reversible without it.
                        batch.tz_offset_minutes,
                        batch.source,
                    ),
                )
                sitting_id = int(created.lastrowid)
                start_ms = note.epoch_ms
            else:
                sitting_id = int(row["id"])
                start_ms = int(row["started_ms"])

            cursor = conn.execute(
                "INSERT OR IGNORE INTO note_events"
                " (sitting_id, onset_ms, duration_ms, pitch, velocity, channel)"
                " VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                (
                    sitting_id,
                    note.epoch_ms - start_ms,
                    note.duration_ms,
                    note.pitch,
                    note.velocity,
                    note.channel,
                ),
            )
            if cursor.rowcount:
                accepted += 1
            else:
                duplicates += 1

            # Keep the window fresh so later notes in this same batch see the
            # extended end rather than the stale one from the previous batch.
            conn.execute(
                "UPDATE sittings SET ended_ms = ?1, ended_at = ?2"
                " WHERE id = ?3 AND ended_ms < ?1",
                (note.end_ms, utc_text(note.end_ms), sitting_id),
            )

        # Pedals after the notes, on purpose: a batch that opens a sitting must
        # attach its pedal to that sitting, and one that presses the pedal after
        # the last note must find the window the notes just extended.
        #
        # Nothing here extends a sitting. A pedal is not practice — a foot resting
        # on it for an hour would otherwise hold a sitting open — so a move with
        # no sitting around it is dropped and counted, not invented into one.
        #
        # Collected per sitting and written once: the stream's unit is a chunk, so
        # `insert_moves` merges the batch into one chunk rather than one row at a time.
        pending: dict[int, list[pedal_stream.Move]] = {}
        for pedal in pedals:
            row = _find_sitting(conn, pedal.epoch_ms, gap_ms)
            if row is None:
                pedals_ignored += 1
                continue
            pedal_sitting = int(row["id"])
            pending.setdefault(pedal_sitting, []).append(
                (pedal.epoch_ms - int(row["started_ms"]), pedal.value, pedal.channel)
            )
        for pedal_sitting, moves in pending.items():
            added = pedal_stream.insert_moves(conn, pedal_sitting, moves)
            pedals_accepted += added
            if added:
                sitting_id = pedal_sitting

        # Marks last, for the same reason the pedals are second: a batch that opens a sitting must
        # attach its mark to that sitting. Nothing here opens or extends one either — a flag with
        # no music around it is not practice, so it is counted and dropped.
        for mark in marks:
            row = _find_sitting(conn, mark.epoch_ms, gap_ms)
            if row is None:
                marks_ignored += 1
                continue
            mark_sitting = int(row["id"])
            cursor = conn.execute(
                "INSERT OR IGNORE INTO sitting_marks"
                " (sitting_id, onset_ms, epoch_ms) VALUES (?1, ?2, ?3)",
                (
                    mark_sitting,
                    mark.epoch_ms - int(row["started_ms"]),
                    mark.epoch_ms,
                ),
            )
            if cursor.rowcount:
                marks_accepted += 1
                sitting_id = mark_sitting

        final = (
            conn.execute(
                "SELECT started_at, ended_at FROM sittings WHERE id = ?", (sitting_id,)
            ).fetchone()
            if sitting_id is not None
            else None
        )

    return IngestResult(
        sitting_id=sitting_id,
        accepted=accepted,
        duplicates=duplicates,
        started_at=final["started_at"] if final is not None else None,
        ended_at=final["ended_at"] if final is not None else None,
        pedals_accepted=pedals_accepted,
        pedals_ignored=pedals_ignored,
        marks_accepted=marks_accepted,
        marks_ignored=marks_ignored,
    )


def close_open_sitting(
    *,
    db_path: Path | None = None,
    now_ms: int | None = None,
    quiet_ms: int = CLOSE_QUIET_MS,
) -> CloseOutcome:
    """Close the newest open sitting, if the player has stopped.

    Called when the piano goes away — switched off, unplugged — because that answers
    "are they finished?" far sooner than waiting out the five-minute silence, and the
    sitting appears on the dashboard immediately instead of five minutes later.

    ``quiet_ms`` guards the other direction: a device event while notes are still
    arriving is a blip (a USB hiccup, a statechange race), not the end of a session,
    and splitting a sitting in the middle of playing would be worse than being slow.

    Returns the sitting that was closed and the reason, so a caller can tell "nothing
    was open" from "you are still playing" without asking a second question.
    """
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    # `immediate`: every one of these reads a row and then writes what it read, and the app's
    # own design has two machines writing this file. A deferred transaction would fix its snapshot
    # at the first SELECT and then fail the write as "database is locked" if anything committed in
    # between — SQLITE_BUSY_SNAPSHOT, which `busy_timeout` does not retry.
    with db.transaction(db_path, immediate=True) as conn:
        sitting = conn.execute(
            "SELECT id, ended_ms FROM sittings"
            " WHERE closed_ms IS NULL AND ended_ms >= ?"
            " ORDER BY started_ms DESC LIMIT 1",
            (now - CLOSE_LOOKBACK_MS,),
        ).fetchone()
        if sitting is None:
            return CloseOutcome(sitting_id=None, reason="nothing open")
        if now - int(sitting["ended_ms"]) < quiet_ms:
            return CloseOutcome(sitting_id=None, reason="still playing")
        conn.execute(
            "UPDATE sittings SET closed_ms = ?1 WHERE id = ?2",
            (int(sitting["ended_ms"]), int(sitting["id"])),
        )
        return CloseOutcome(sitting_id=int(sitting["id"]), reason="closed")


def _sitting_notes(conn: sqlite3.Connection, sitting_id: int, started_ms: int) -> list[Note]:
    rows = conn.execute(
        "SELECT onset_ms, duration_ms, pitch, velocity, channel"
        " FROM note_events WHERE sitting_id = ? ORDER BY onset_ms, pitch",
        (sitting_id,),
    ).fetchall()
    return [
        Note(
            epoch_ms=started_ms + int(row["onset_ms"]),
            pitch=int(row["pitch"]),
            velocity=int(row["velocity"]),
            duration_ms=int(row["duration_ms"]),
            channel=row["channel"],
        )
        for row in rows
    ]


def sitting_notes(sitting_id: int, db_path: Path | None = None) -> SittingNotes:
    """Every note of a sitting, in the order it was played, with its pedalling.

    The stored form is exactly what a synthesiser needs — onset, release-derived
    duration, pitch, velocity, and the pedal moves that held notes past their
    release. That is why playback is faithful to timing, touch and pedalling
    without any reconstruction.
    """
    conn = db.connect(db_path)
    try:
        sitting = conn.execute(
            "SELECT id, started_ms FROM sittings WHERE id = ?", (sitting_id,)
        ).fetchone()
        if sitting is None:
            raise NotFound(f"no sitting {sitting_id}")
        rows = conn.execute(
            "SELECT onset_ms, duration_ms, pitch, velocity, channel FROM note_events"
            " WHERE sitting_id = ? ORDER BY onset_ms, pitch",
            (sitting_id,),
        ).fetchall()
        pedals = [
            LoggedPedal(onset_ms=onset, value=value, channel=channel)
            for onset, value, channel in pedal_stream.moves(conn, sitting_id)
        ]
        return SittingNotes(
            sitting_id=int(sitting["id"]),
            started_ms=int(sitting["started_ms"]),
            notes=[LoggedNote(**dict(row)) for row in rows],
            pedals=pedals,
        )
    finally:
        conn.close()


def list_sittings(limit: int = 20, db_path: Path | None = None) -> list[SittingSummary]:
    conn = db.connect(db_path)
    try:
        return list_sittings_conn(conn, limit)
    finally:
        conn.close()


def list_sittings_conn(conn: sqlite3.Connection, limit: int) -> list[SittingSummary]:
    """``list_sittings`` for a caller that already holds a connection.

    The rows are chosen *first*, then counted, and both halves of that matter.

    ``LIMIT`` does not bound an aggregate: the join form grouped every note event in the
    database and sorted the result with a temp B-tree before the limit applied, so the
    dashboard's ten-row list cost the same as its thousand-row list — a flat 65 ms on the
    owner's 512k-note library, a cost that grows with the log while the request does not (R1).

    Correlated subqueries alone do not fix that, which is worth knowing before rewriting them
    back. They are part of the *result list*, so a plain ``ORDER BY ... LIMIT`` still evaluates
    one per sitting scanned and then throws most away: with 400 notes added to a sitting this
    list does not return, the work went 660 → 1,857 VM steps. Materialising the limited set into
    a CTE first is what makes the limit load-bearing — 686 → 686 on the same fixture.
    """
    rows = conn.execute(
        """
        WITH recent AS MATERIALIZED (
            SELECT id, started_at, ended_at, local_date, source, started_ms, ended_ms
            FROM sittings
            ORDER BY started_ms DESC
            LIMIT ?
        )
        SELECT r.id,
               r.started_at,
               r.ended_at,
               r.local_date,
               r.source,
               (SELECT COUNT(*) FROM note_events e WHERE e.sitting_id = r.id) AS note_count,
               (SELECT COUNT(*) FROM segments g WHERE g.sitting_id = r.id) AS segment_count,
               (r.ended_ms - r.started_ms) / 1000.0 AS duration_s
        FROM recent r
        ORDER BY r.started_ms DESC
        """,
        (limit,),
    ).fetchall()
    return [SittingSummary(**dict(row)) for row in rows]

