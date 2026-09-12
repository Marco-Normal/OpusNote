"""Practice-domain queries and mutations.

Ported from ``practice-logger/app/services.py`` with three changes:

* the tables are ``sittings``/``note_events``/``segments``/``segment_metrics``;
* ``piece_id`` points at our own ``pieces`` table, so titles and composers come
  from a join rather than a second query;
* segment metrics are materialised here (the original's Phase 4 never landed), and
  segments are tagged from overlapping workouts, which is the cross-domain payoff
  of one app owning both.

Sessionization is *absolute-time* based, not "the newest sitting": a note joins
the stored sitting whose window contains it — at or after that sitting's start,
and no more than one gap after its end — and otherwise opens a new one. Bounding
only the upper side looks equivalent and is not: a retried or out-of-order batch
would be appended to the newest sitting with a negative ``onset_ms``, silently
inventing events that never happened.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import db
from ..config import settings
from . import schema as practice_schema
from .metrics import SegmentMetrics, segment_metrics
from .models import (
    AnalyticsSummary,
    CalendarDay,
    EventBatch,
    IngestResult,
    NeglectedPiece,
    PiecePractice,
    PiecePracticeDetail,
    SegmentMetricsOut,
    SegmentSummary,
    SittingDetail,
    SittingSummary,
    SourceSplit,
    TempoPoint,
    TempoSeries,
)
from .sessionize import Note, sessionize


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
        ORDER BY started_ms DESC
        LIMIT 1
        """,
        (epoch_ms, gap_ms),
    ).fetchone()


def ingest(batch: EventBatch, db_path: Path | None = None) -> IngestResult:
    gap_ms = settings.sitting_gap_s * 1000
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
    if not notes:
        raise InvalidRequest("cannot ingest an empty batch")

    accepted = 0
    duplicates = 0
    sitting_id = 0
    with db.transaction(db_path) as conn:
        for note in notes:
            row = _find_sitting(conn, note.epoch_ms, gap_ms)
            if row is None:
                created = conn.execute(
                    "INSERT INTO sittings"
                    " (started_ms, ended_ms, started_at, ended_at, local_date, source)"
                    " VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                    (
                        note.epoch_ms,
                        note.end_ms,
                        utc_text(note.epoch_ms),
                        utc_text(note.end_ms),
                        local_date(note.epoch_ms, batch.tz_offset_minutes),
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

        final = conn.execute(
            "SELECT started_at, ended_at FROM sittings WHERE id = ?", (sitting_id,)
        ).fetchone()

    return IngestResult(
        sitting_id=sitting_id,
        accepted=accepted,
        duplicates=duplicates,
        started_at=final["started_at"],
        ended_at=final["ended_at"],
    )


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


def _segment_rows(conn: sqlite3.Connection, sitting_id: int) -> list[SegmentSummary]:
    """Segments of a sitting, with piece, composer, note count and metrics.

    Note counts use ``onset_ms <= end_ms``. That cannot double-count: two segments
    of one sitting are separated by at least ``segment_gap_s`` of silence, so no
    note of the next segment can sit at or before this segment's end. Using ``<``
    would drop a zero-duration note from its own segment.
    """
    rows = conn.execute(
        """
        SELECT g.id,
               g.sitting_id,
               g.start_ms,
               g.end_ms,
               g.piece_id,
               p.title AS piece_title,
               c.name AS composer_name,
               g.source,
               g.workout_id,
               g.confidence,
               g.identified_by,
               (SELECT COUNT(*) FROM note_events e
                 WHERE e.sitting_id = g.sitting_id
                   AND e.onset_ms >= g.start_ms
                   AND e.onset_ms <= g.end_ms) AS note_count,
               m.duration_s, m.note_count AS metric_note_count, m.median_tempo,
               m.mean_velocity, m.velocity_stddev, m.restarts
        FROM segments g
        LEFT JOIN pieces p ON p.id = g.piece_id
        LEFT JOIN composers c ON c.id = p.composer_id
        LEFT JOIN segment_metrics m ON m.segment_id = g.id
        WHERE g.sitting_id = ?
        ORDER BY g.start_ms
        """,
        (sitting_id,),
    ).fetchall()
    out: list[SegmentSummary] = []
    for row in rows:
        data = dict(row)
        metrics = None
        if data["duration_s"] is not None:
            metrics = SegmentMetricsOut(
                duration_s=data["duration_s"],
                note_count=data["metric_note_count"],
                median_tempo=data["median_tempo"],
                mean_velocity=data["mean_velocity"],
                velocity_stddev=data["velocity_stddev"],
                restarts=data["restarts"],
            )
        out.append(
            SegmentSummary(
                id=data["id"],
                sitting_id=data["sitting_id"],
                start_ms=data["start_ms"],
                end_ms=data["end_ms"],
                piece_id=data["piece_id"],
                piece_title=data["piece_title"],
                composer_name=data["composer_name"],
                source=data["source"],
                workout_id=data["workout_id"],
                confidence=data["confidence"],
                identified_by=data["identified_by"],
                note_count=data["note_count"],
                metrics=metrics,
            )
        )
    return out


def _refresh_metrics(conn: sqlite3.Connection, sitting_id: int) -> None:
    """Recompute stored metrics for every segment of a sitting.

    Derived, so rather than tracking which mutation invalidated which row, the
    whole sitting is recomputed whenever its boundaries change. Notes are already
    in the database; the work is arithmetic over a few hundred rows.
    """
    segments = conn.execute(
        "SELECT id, start_ms, end_ms FROM segments WHERE sitting_id = ?",
        (sitting_id,),
    ).fetchall()
    for segment in segments:
        rows = conn.execute(
            "SELECT onset_ms, duration_ms, pitch, velocity, channel FROM note_events"
            " WHERE sitting_id = ? AND onset_ms >= ? AND onset_ms <= ?"
            " ORDER BY onset_ms, pitch",
            (sitting_id, segment["start_ms"], segment["end_ms"]),
        ).fetchall()
        notes = [
            Note(
                epoch_ms=int(row["onset_ms"]),
                pitch=int(row["pitch"]),
                velocity=int(row["velocity"]),
                duration_ms=int(row["duration_ms"]),
                channel=row["channel"],
            )
            for row in rows
        ]
        stats: SegmentMetrics = segment_metrics(
            notes,
            attack_window_ms=settings.attack_window_ms,
            restart_gap_ms=settings.restart_gap_ms,
        )
        conn.execute(
            "INSERT INTO segment_metrics"
            " (segment_id, duration_s, note_count, median_tempo, mean_velocity,"
            "  velocity_stddev, restarts)"
            " VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)"
            " ON CONFLICT (segment_id) DO UPDATE SET"
            "  duration_s = excluded.duration_s,"
            "  note_count = excluded.note_count,"
            "  median_tempo = excluded.median_tempo,"
            "  mean_velocity = excluded.mean_velocity,"
            "  velocity_stddev = excluded.velocity_stddev,"
            "  restarts = excluded.restarts",
            (
                segment["id"],
                stats.duration_s,
                stats.note_count,
                stats.median_tempo,
                stats.mean_velocity,
                stats.velocity_stddev,
                stats.restarts,
            ),
        )
    # Drop metrics for segments that no longer exist (a merge removes one).
    conn.execute(
        "DELETE FROM segment_metrics WHERE segment_id NOT IN"
        " (SELECT id FROM segments WHERE sitting_id = ?)",
        (sitting_id,),
    )


def _tag_from_workouts(conn: sqlite3.Connection, sitting_id: int, started_ms: int) -> None:
    """Label segments that overlap a finished workout.

    A workout is a deliberate, bounded set of exercises; a segment is a chunk of
    a sitting. A whole workout normally lands as one segment, and where it does
    not, every segment it overlaps is still sight-reading rather than a mystery
    blob on the timeline.
    """
    workouts = conn.execute(
        "SELECT id, started_ms, ended_ms FROM workouts WHERE ended_ms IS NOT NULL"
    ).fetchall()
    if not workouts:
        return
    segments = conn.execute(
        "SELECT id, start_ms, end_ms FROM segments WHERE sitting_id = ?", (sitting_id,)
    ).fetchall()
    for segment in segments:
        start_abs = started_ms + int(segment["start_ms"])
        end_abs = started_ms + int(segment["end_ms"])
        best: tuple[int, int] | None = None
        for workout in workouts:
            overlap = min(end_abs, int(workout["ended_ms"])) - max(
                start_abs, int(workout["started_ms"])
            )
            if overlap >= 0 and (best is None or overlap > best[1]):
                best = (int(workout["id"]), overlap)
        if best is not None:
            conn.execute(
                "UPDATE segments SET source = 'sight_reading', workout_id = ?1,"
                " identified_by = COALESCE(identified_by, 'workout') WHERE id = ?2",
                (best[0], segment["id"]),
            )


def ensure_segments(
    sitting_id: int, now_ms: int | None = None, db_path: Path | None = None
) -> list[SegmentSummary]:
    """Materialise segments for a closed sitting, once.

    A sitting that already has segments is returned untouched: recomputing on read
    would silently discard hand-edited boundaries and tags.
    """
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    with db.transaction(db_path) as conn:
        sitting = conn.execute(
            "SELECT id, started_ms, ended_ms, source FROM sittings WHERE id = ?",
            (sitting_id,),
        ).fetchone()
        if sitting is None:
            raise NotFound(f"no sitting {sitting_id}")

        existing = conn.execute(
            "SELECT COUNT(*) FROM segments WHERE sitting_id = ?", (sitting_id,)
        ).fetchone()[0]
        if existing:
            return _segment_rows(conn, sitting_id)

        # An open sitting's boundaries would be provisional, and because stored
        # segments are never recomputed implicitly, a provisional view would be
        # permanent.
        if int(sitting["ended_ms"]) + settings.sitting_gap_s * 1000 >= now:
            return []

        started_ms = int(sitting["started_ms"])
        notes = _sitting_notes(conn, sitting_id, started_ms)
        for window in sessionize(notes, settings.segment_gap_s * 1000):
            conn.execute(
                "INSERT INTO segments (sitting_id, start_ms, end_ms, source)"
                " VALUES (?1, ?2, ?3, ?4)",
                (
                    sitting_id,
                    window.start_ms - started_ms,
                    window.end_ms - started_ms,
                    "sight_reading" if sitting["source"] == "sight_reading" else None,
                ),
            )
        _tag_from_workouts(conn, sitting_id, started_ms)
        _refresh_metrics(conn, sitting_id)
        return _segment_rows(conn, sitting_id)


def sitting_detail(
    sitting_id: int, now_ms: int | None = None, db_path: Path | None = None
) -> SittingDetail:
    segments = ensure_segments(sitting_id, now_ms=now_ms, db_path=db_path)
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    conn = db.connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, started_ms, ended_ms, started_at, ended_at, local_date, source"
            " FROM sittings WHERE id = ?",
            (sitting_id,),
        ).fetchone()
        if row is None:
            raise NotFound(f"no sitting {sitting_id}")
        note_count = conn.execute(
            "SELECT COUNT(*) FROM note_events WHERE sitting_id = ?", (sitting_id,)
        ).fetchone()[0]
        return SittingDetail(
            id=int(row["id"]),
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            local_date=row["local_date"],
            source=row["source"],
            note_count=int(note_count),
            duration_s=(int(row["ended_ms"]) - int(row["started_ms"])) / 1000.0,
            closed=int(row["ended_ms"]) + settings.sitting_gap_s * 1000 < now,
            segments=segments,
        )
    finally:
        conn.close()


def list_sittings(limit: int = 20, db_path: Path | None = None) -> list[SittingSummary]:
    conn = db.connect(db_path)
    try:
        return list_sittings_conn(conn, limit)
    finally:
        conn.close()


def _segment_or_raise(conn: sqlite3.Connection, segment_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, sitting_id, start_ms, end_ms, piece_id, source, workout_id,"
        " confidence, identified_by FROM segments WHERE id = ?",
        (segment_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"no segment {segment_id}")
    return row


def assign_piece(
    segment_id: int, piece_id: int | None, db_path: Path | None = None
) -> list[SegmentSummary]:
    """Tag a segment with a piece, or clear it with ``piece_id = None``."""
    with db.transaction(db_path) as conn:
        row = _segment_or_raise(conn, segment_id)
        if piece_id is not None:
            known = conn.execute("SELECT 1 FROM pieces WHERE id = ?", (piece_id,)).fetchone()
            if known is None:
                raise InvalidRequest(f"no piece {piece_id} in the library")

        conn.execute(
            "UPDATE segments SET piece_id = ?1, confidence = ?2, identified_by = ?3,"
            " source = ?4 WHERE id = ?5",
            (
                piece_id,
                None if piece_id is None else 1.0,
                None if piece_id is None else "manual",
                None if piece_id is None else "repertoire",
                segment_id,
            ),
        )
        return _segment_rows(conn, int(row["sitting_id"]))


def split_segment(
    segment_id: int, at_ms: int, db_path: Path | None = None
) -> list[SegmentSummary]:
    """Split at a sitting-relative instant; boundaries stay tight to notes."""
    with db.transaction(db_path) as conn:
        row = _segment_or_raise(conn, segment_id)
        start_ms = int(row["start_ms"])
        end_ms = int(row["end_ms"])
        if not start_ms < at_ms < end_ms:
            raise InvalidRequest(
                f"at_ms must fall strictly inside the segment ({start_ms}..{end_ms})"
            )

        sitting_id = int(row["sitting_id"])
        notes = conn.execute(
            "SELECT onset_ms, duration_ms FROM note_events"
            " WHERE sitting_id = ? AND onset_ms >= ? AND onset_ms <= ?"
            " ORDER BY onset_ms, pitch",
            (sitting_id, start_ms, end_ms),
        ).fetchall()
        left = [item for item in notes if int(item["onset_ms"]) < at_ms]
        right = [item for item in notes if int(item["onset_ms"]) >= at_ms]
        if not left or not right:
            raise InvalidRequest("the split point leaves one side with no notes")

        left_end = max(int(item["onset_ms"]) + int(item["duration_ms"]) for item in left)
        right_end = max(int(item["onset_ms"]) + int(item["duration_ms"]) for item in right)

        conn.execute(
            "UPDATE segments SET start_ms = ?1, end_ms = ?2 WHERE id = ?3",
            (int(left[0]["onset_ms"]), left_end, segment_id),
        )
        # The new half inherits *what the activity was* — source and workout —
        # because splitting a boundary says nothing about which piece it is, and
        # a piece label would have to arbitrarily belong to one side.
        conn.execute(
            "INSERT INTO segments (sitting_id, start_ms, end_ms, source, workout_id)"
            " VALUES (?1, ?2, ?3, ?4, ?5)",
            (
                sitting_id,
                int(right[0]["onset_ms"]),
                right_end,
                row["source"],
                row["workout_id"],
            ),
        )
        _refresh_metrics(conn, sitting_id)
        return _segment_rows(conn, sitting_id)


def merge_segments(
    segment_id: int, other_id: int, db_path: Path | None = None
) -> list[SegmentSummary]:
    """Merge two adjacent segments of one sitting."""
    if segment_id == other_id:
        raise InvalidRequest("cannot merge a segment with itself")
    with db.transaction(db_path) as conn:
        first = _segment_or_raise(conn, segment_id)
        second = _segment_or_raise(conn, other_id)
        if int(first["sitting_id"]) != int(second["sitting_id"]):
            raise InvalidRequest("segments belong to different sittings")

        sitting_id = int(first["sitting_id"])
        low, high = sorted((first, second), key=lambda row: int(row["start_ms"]))
        between = conn.execute(
            "SELECT COUNT(*) FROM segments WHERE sitting_id = ?1"
            " AND id NOT IN (?2, ?3) AND start_ms > ?4 AND start_ms < ?5",
            (
                sitting_id,
                segment_id,
                other_id,
                int(low["start_ms"]),
                int(high["start_ms"]),
            ),
        ).fetchone()[0]
        if between:
            raise InvalidRequest("segments are not adjacent")

        from_low = low["piece_id"] is not None
        conn.execute(
            "UPDATE segments SET start_ms = ?1, end_ms = ?2, piece_id = ?3,"
            " confidence = ?4, identified_by = ?5 WHERE id = ?6",
            (
                int(low["start_ms"]),
                int(high["end_ms"]),
                low["piece_id"] if from_low else high["piece_id"],
                low["confidence"] if from_low else high["confidence"],
                low["identified_by"] if from_low else high["identified_by"],
                int(low["id"]),
            ),
        )
        conn.execute("DELETE FROM segments WHERE id = ?", (int(high["id"]),))
        _refresh_metrics(conn, sitting_id)
        return _segment_rows(conn, sitting_id)


def resegment_sitting(
    sitting_id: int,
    confirm: bool = False,
    now_ms: int | None = None,
    db_path: Path | None = None,
) -> list[SegmentSummary]:
    """Recompute boundaries, discarding them. The only destructive path."""
    with db.transaction(db_path) as conn:
        sitting = conn.execute(
            "SELECT id FROM sittings WHERE id = ?", (sitting_id,)
        ).fetchone()
        if sitting is None:
            raise NotFound(f"no sitting {sitting_id}")
        labelled = conn.execute(
            "SELECT COUNT(*) FROM segments WHERE sitting_id = ? AND piece_id IS NOT NULL",
            (sitting_id,),
        ).fetchone()[0]
        if labelled and not confirm:
            raise ConfirmationRequired(
                f"{labelled} segment(s) carry a piece; confirm=true discards that"
            )
        conn.execute("DELETE FROM segments WHERE sitting_id = ?", (sitting_id,))
    return ensure_segments(sitting_id, now_ms=now_ms, db_path=db_path)


# --------------------------------------------------------------------------
# Analytics. Read-only, so they take an open connection rather than a path.
# --------------------------------------------------------------------------


def _minutes(seconds: float | None) -> float:
    return round((seconds or 0.0) / 60.0, 1)


def _today():
    """The player's calendar day.

    Server-local, not UTC. This app runs on the piano machine — one host, one
    timezone — and `local_date` was written in the player's timezone, so comparing
    it against a UTC date would call an evening's practice "yesterday" for anyone
    west of Greenwich.
    """
    return datetime.now().date()


def calendar(conn: sqlite3.Connection, days: int) -> list[CalendarDay]:
    days_rows = conn.execute(
        """
        SELECT local_date AS date,
               COUNT(*) AS sittings,
               SUM(ended_ms - started_ms) / 60000.0 AS minutes
        FROM sittings
        GROUP BY local_date
        ORDER BY local_date
        """
    ).fetchall()
    note_rows = conn.execute(
        "SELECT s.local_date AS date, COUNT(*) AS notes"
        " FROM note_events e JOIN sittings s ON s.id = e.sitting_id"
        " GROUP BY s.local_date"
    ).fetchall()
    notes_by_date = {row["date"]: int(row["notes"]) for row in note_rows}
    by_date = {
        row["date"]: CalendarDay(
            date=row["date"],
            minutes=round(float(row["minutes"] or 0.0), 1),
            notes=notes_by_date.get(row["date"], 0),
            sittings=int(row["sittings"]),
        )
        for row in days_rows
    }
    return _fill_days(by_date, days)


def _fill_days(by_date: dict[str, CalendarDay], days: int) -> list[CalendarDay]:
    """Every day in the window, including the empty ones.

    A heatmap drawn only from days that have rows renders a gap-free strip and
    silently loses the fact that nothing happened for a week.
    """
    today = _today()
    out: list[CalendarDay] = []
    for offset in range(days - 1, -1, -1):
        key = (today - timedelta(days=offset)).isoformat()
        out.append(by_date.get(key) or CalendarDay(date=key, minutes=0.0, notes=0, sittings=0))
    return out


def by_piece(conn: sqlite3.Connection, days: int) -> list[PiecePractice]:
    since = (_today() - timedelta(days=days - 1)).isoformat()
    rows = conn.execute(
        """
        SELECT p.id AS piece_id,
               p.title,
               c.name AS composer_name,
               COUNT(g.id) AS segments,
               SUM(m.duration_s) AS seconds,
               SUM(m.note_count) AS notes,
               MAX(s.local_date) AS last_played,
               (SELECT COALESCE(SUM(j.practice_minutes), 0) FROM piece_journal j
                 WHERE j.piece_id = p.id) AS journal_minutes
        FROM segments g
        JOIN sittings s ON s.id = g.sitting_id
        JOIN pieces p ON p.id = g.piece_id
        LEFT JOIN composers c ON c.id = p.composer_id
        LEFT JOIN segment_metrics m ON m.segment_id = g.id
        WHERE g.piece_id IS NOT NULL AND s.local_date >= ?
        GROUP BY p.id
        ORDER BY seconds DESC, p.title COLLATE NOCASE
        """,
        (since,),
    ).fetchall()
    return [
        PiecePractice(
            piece_id=int(row["piece_id"]),
            title=row["title"],
            composer_name=row["composer_name"],
            minutes=_minutes(row["seconds"]),
            notes=int(row["notes"] or 0),
            segments=int(row["segments"]),
            last_played=row["last_played"],
            journal_minutes=int(row["journal_minutes"] or 0),
        )
        for row in rows
    ]


def piece_practice(conn: sqlite3.Connection, piece_id: int, days: int = 3650) -> PiecePracticeDetail:
    """Logged practice for one piece, all time, plus its tempo trend."""
    rows = by_piece(conn, days)
    row = next((item for item in rows if item.piece_id == piece_id), None)
    if row is None:
        piece = conn.execute(
            "SELECT p.id, p.title, c.name AS composer_name,"
            " (SELECT COALESCE(SUM(j.practice_minutes), 0) FROM piece_journal j"
            "   WHERE j.piece_id = p.id) AS journal_minutes"
            " FROM pieces p LEFT JOIN composers c ON c.id = p.composer_id"
            " WHERE p.id = ?",
            (piece_id,),
        ).fetchone()
        if piece is None:
            raise NotFound(f"no piece {piece_id}")
        row = PiecePractice(
            piece_id=int(piece["id"]),
            title=piece["title"],
            composer_name=piece["composer_name"],
            minutes=0.0,
            notes=0,
            segments=0,
            last_played=None,
            journal_minutes=int(piece["journal_minutes"] or 0),
        )
    return PiecePracticeDetail(**row.model_dump(), tempo=tempo_series(conn, piece_id))


def neglected(conn: sqlite3.Connection, limit: int = 8) -> list[NeglectedPiece]:
    """Active pieces, least recently played first.

    A piece with no logged segment at all sorts first: "never logged" is the
    strongest form of neglected, and dropping it for having no date would hide
    exactly the pieces the list exists to surface.
    """
    rows = conn.execute(
        """
        SELECT p.id AS piece_id,
               p.title,
               c.name AS composer_name,
               MAX(s.local_date) AS last_played
        FROM pieces p
        LEFT JOIN composers c ON c.id = p.composer_id
        LEFT JOIN segments g ON g.piece_id = p.id
        LEFT JOIN sittings s ON s.id = g.sitting_id
        WHERE p.status != 'completed'
        GROUP BY p.id
        ORDER BY (last_played IS NOT NULL), last_played ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    today = _today()
    out: list[NeglectedPiece] = []
    for row in rows:
        last = row["last_played"]
        days_since = None
        if last:
            days_since = (today - datetime.fromisoformat(last).date()).days
        out.append(
            NeglectedPiece(
                piece_id=int(row["piece_id"]),
                title=row["title"],
                composer_name=row["composer_name"],
                days_since=days_since,
                last_played=last,
            )
        )
    return out


def tempo_series(conn: sqlite3.Connection, piece_id: int) -> TempoSeries:
    """Median tempo per segment over time — the "is it getting faster?" line."""
    piece = conn.execute(
        "SELECT id, title FROM pieces WHERE id = ?", (piece_id,)
    ).fetchone()
    if piece is None:
        raise NotFound(f"no piece {piece_id}")
    rows = conn.execute(
        """
        SELECT s.local_date AS date, m.median_tempo, g.id AS segment_id
        FROM segments g
        JOIN sittings s ON s.id = g.sitting_id
        JOIN segment_metrics m ON m.segment_id = g.id
        WHERE g.piece_id = ? AND m.median_tempo IS NOT NULL
        ORDER BY s.local_date, g.start_ms
        """,
        (piece_id,),
    ).fetchall()
    return TempoSeries(
        piece_id=int(piece["id"]),
        title=piece["title"],
        points=[
            TempoPoint(
                date=row["date"],
                median_tempo=float(row["median_tempo"]),
                segment_id=int(row["segment_id"]),
            )
            for row in rows
        ],
    )


def sources(conn: sqlite3.Connection, days: int) -> list[SourceSplit]:
    since = (_today() - timedelta(days=days - 1)).isoformat()
    rows = conn.execute(
        """
        SELECT s.source,
               SUM(s.ended_ms - s.started_ms) / 60000.0 AS minutes,
               (SELECT COUNT(*) FROM note_events e JOIN sittings s2 ON s2.id = e.sitting_id
                 WHERE s2.source = s.source AND s2.local_date >= ?) AS notes
        FROM sittings s
        WHERE s.local_date >= ?
        GROUP BY s.source
        ORDER BY minutes DESC
        """,
        (since, since),
    ).fetchall()
    return [
        SourceSplit(
            source=row["source"],
            minutes=round(float(row["minutes"] or 0.0), 1),
            notes=int(row["notes"] or 0),
        )
        for row in rows
    ]


def streak_days(conn: sqlite3.Connection) -> int:
    """Consecutive days ending today with at least one sitting.

    Today not yet having practice does not break the streak: the day is not over,
    and a streak that resets every midnight until you play is a nag, not a
    measurement.
    """
    rows = [
        row["local_date"]
        for row in conn.execute(
            "SELECT DISTINCT local_date FROM sittings ORDER BY local_date DESC"
        )
    ]
    if not rows:
        return 0
    dates = {datetime.fromisoformat(value).date() for value in rows}
    today = _today()
    start = today if today in dates else today - timedelta(days=1)
    if start not in dates:
        return 0
    streak = 0
    cursor = start
    while cursor in dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def summary(conn: sqlite3.Connection, days: int = 30, recent: int = 10) -> AnalyticsSummary:
    """Everything the Log dashboard draws, in one call.

    ``total_minutes`` and ``total_notes`` are all-time on purpose: the dashboard's
    headline numbers answer "how much have I practised", and a 30-day total would
    shrink on its own with no practice having been lost.
    """
    calendar_days = calendar(conn, days)
    today = _today().isoformat()
    totals = conn.execute(
        "SELECT COALESCE(SUM(ended_ms - started_ms), 0) / 60000.0 AS minutes,"
        " (SELECT COUNT(*) FROM note_events) AS notes FROM sittings"
    ).fetchone()
    return AnalyticsSummary(
        days=days,
        total_minutes=round(float(totals["minutes"] or 0.0), 1),
        total_notes=int(totals["notes"] or 0),
        today_minutes=next(
            (day.minutes for day in calendar_days if day.date == today), 0.0
        ),
        streak_days=streak_days(conn),
        calendar=calendar_days,
        by_piece=by_piece(conn, days),
        neglected=neglected(conn),
        sources=sources(conn, days),
        recent=list_sittings_conn(conn, recent),
    )


def list_sittings_conn(conn: sqlite3.Connection, limit: int) -> list[SittingSummary]:
    """``list_sittings`` for a caller that already holds a connection."""
    rows = conn.execute(
        """
        SELECT s.id,
               s.started_at,
               s.ended_at,
               s.local_date,
               s.source,
               COUNT(DISTINCT e.id) AS note_count,
               (SELECT COUNT(*) FROM segments g WHERE g.sitting_id = s.id) AS segment_count,
               (s.ended_ms - s.started_ms) / 1000.0 AS duration_s
        FROM sittings s
        LEFT JOIN note_events e ON e.sitting_id = s.id
        GROUP BY s.id
        ORDER BY s.started_ms DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [SittingSummary(**dict(row)) for row in rows]


#: Exposed so `app.db.init_db` owns exactly one creation path while this module
#: owns the DDL text.
SCHEMA = practice_schema.PRACTICE_SCHEMA
migrate = practice_schema.migrate
