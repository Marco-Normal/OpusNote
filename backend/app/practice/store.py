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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Literal, Sequence

from .. import db
from ..config import settings
from . import capture_status
from . import kinds
from . import schema as practice_schema
from .metrics import SegmentMetrics, segment_metrics
from .pedal import (
    BASIS_OBSERVED,
    median_velocity,
    register_balance,
    segment_pedal,
    velocity_range,
)
from .similarity import (
    DEFAULT_WEIGHTS,
    Candidate,
    Example,
    Fingerprint,
    Identification,
    Weights,
    fingerprint,
    identify,
)
from .models import (
    AnalyticsSummary,
    AutotagReport,
    CalendarDay,
    EventBatch,
    IdentificationQuality,
    IngestResult,
    LoggedNote,
    LoggedPedal,
    NeglectedPiece,
    PiecePractice,
    PiecePracticeDetail,
    PracticeKind,
    PracticeKindSplit,
    SegmentCandidate,
    SegmentMetricsOut,
    SegmentSummary,
    SittingDetail,
    SittingNotes,
    SittingSummary,
    SourceSplit,
    TempoPoint,
    TempoSeries,
)
from .sessionize import Note, sessionize


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
    pedals = sorted(batch.pedals, key=lambda pedal: pedal.epoch_ms)
    if not notes and not pedals:
        raise InvalidRequest("cannot ingest an empty batch")

    accepted = 0
    duplicates = 0
    pedals_accepted = 0
    pedals_ignored = 0
    sitting_id: int | None = None
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

        # Pedals after the notes, on purpose: a batch that opens a sitting must
        # attach its pedal to that sitting, and one that presses the pedal after
        # the last note must find the window the notes just extended.
        #
        # Nothing here extends a sitting. A pedal is not practice — a foot resting
        # on it for an hour would otherwise hold a sitting open — so a move with
        # no sitting around it is dropped and counted, not invented into one.
        for pedal in pedals:
            row = _find_sitting(conn, pedal.epoch_ms, gap_ms)
            if row is None:
                pedals_ignored += 1
                continue
            pedal_sitting = int(row["id"])
            cursor = conn.execute(
                "INSERT OR IGNORE INTO pedal_events"
                " (sitting_id, onset_ms, value, channel) VALUES (?1, ?2, ?3, ?4)",
                (
                    pedal_sitting,
                    pedal.epoch_ms - int(row["started_ms"]),
                    pedal.value,
                    pedal.channel,
                ),
            )
            if cursor.rowcount:
                pedals_accepted += 1
                sitting_id = pedal_sitting

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
    with db.transaction(db_path) as conn:
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
               g.practice_kind,
               g.practice_kind_basis,
               (SELECT COUNT(*) FROM note_events e
                 WHERE e.sitting_id = g.sitting_id
                   AND e.onset_ms >= g.start_ms
                   AND e.onset_ms <= g.end_ms) AS note_count,
               m.duration_s, m.note_count AS metric_note_count, m.median_tempo,
               m.mean_velocity, m.velocity_stddev, m.restarts,
               m.median_velocity, m.velocity_range,
               m.mean_velocity_low, m.mean_velocity_high,
               m.pedal_changes, m.pedal_down_ratio, m.pedal_blur, m.pedal_blur_ms,
               m.pedal_basis
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
                median_velocity=data["median_velocity"],
                velocity_range=data["velocity_range"],
                mean_velocity_low=data["mean_velocity_low"],
                mean_velocity_high=data["mean_velocity_high"],
                pedal_changes=data["pedal_changes"],
                pedal_down_ratio=data["pedal_down_ratio"],
                pedal_blur=data["pedal_blur"],
                pedal_blur_ms=db.json_load(data["pedal_blur_ms"], []),
                pedal_basis=data["pedal_basis"],
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
                practice_kind=data["practice_kind"],
                practice_kind_basis=data["practice_kind_basis"],
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
    # Whether this sitting has any pedal rows at all, which is not the same question
    # as whether the pedal was pressed: imported history has none, and reporting a
    # zero there would be reporting a fault that was never observed.
    pedals_recorded = (
        conn.execute(
            "SELECT 1 FROM pedal_events WHERE sitting_id = ? LIMIT 1", (sitting_id,)
        ).fetchone()
        is not None
    )
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
        # The pedal is read for the whole sitting and then clipped to the segment: a
        # stretch that began before the boundary is still holding notes inside it.
        pedal_rows = conn.execute(
            "SELECT onset_ms, value FROM pedal_events"
            " WHERE sitting_id = ? AND onset_ms <= ? ORDER BY onset_ms",
            (sitting_id, segment["end_ms"]),
        ).fetchall()
        pedal_moves = [(int(row["onset_ms"]), int(row["value"])) for row in pedal_rows]
        pedalling = segment_pedal(notes, pedal_moves, recorded=pedals_recorded)
        median = median_velocity(notes)
        spread = velocity_range(notes)
        low, high = register_balance(notes)
        conn.execute(
            "INSERT INTO segment_metrics"
            " (segment_id, duration_s, note_count, median_tempo, mean_velocity,"
            "  velocity_stddev, restarts, pedal_changes, pedal_down_ratio, pedal_blur,"
            "  pedal_blur_ms, pedal_basis, median_velocity, velocity_range,"
            "  mean_velocity_low, mean_velocity_high)"
            " VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16)"
            " ON CONFLICT (segment_id) DO UPDATE SET"
            "  duration_s = excluded.duration_s,"
            "  note_count = excluded.note_count,"
            "  median_tempo = excluded.median_tempo,"
            "  mean_velocity = excluded.mean_velocity,"
            "  velocity_stddev = excluded.velocity_stddev,"
            "  restarts = excluded.restarts,"
            "  pedal_changes = excluded.pedal_changes,"
            "  pedal_down_ratio = excluded.pedal_down_ratio,"
            "  pedal_blur = excluded.pedal_blur,"
            "  pedal_blur_ms = excluded.pedal_blur_ms,"
            "  pedal_basis = excluded.pedal_basis,"
            "  median_velocity = excluded.median_velocity,"
            "  velocity_range = excluded.velocity_range,"
            "  mean_velocity_low = excluded.mean_velocity_low,"
            "  mean_velocity_high = excluded.mean_velocity_high",
            (
                segment["id"],
                stats.duration_s,
                stats.note_count,
                stats.median_tempo,
                stats.mean_velocity,
                stats.velocity_stddev,
                stats.restarts,
                pedalling.changes,
                pedalling.down_ratio,
                pedalling.blur,
                db.json_dump(list(pedalling.blur_at_ms)),
                BASIS_OBSERVED if pedalling.recorded else None,
                median,
                spread,
                low,
                high,
            ),
        )
    # Drop metrics whose segment no longer exists (a merge removes one).
    #
    # This used to read `NOT IN (SELECT id FROM segments WHERE sitting_id = ?)`, which is
    # not "the stale rows of this sitting" but "every segment of every other sitting" —
    # so segmenting one sitting silently emptied every earlier sitting's metrics, taking
    # the piece tempo trend and the per-segment pedal and touch figures with it. A metric
    # row is stale exactly when its segment is gone from the table, so that is the test.
    conn.execute(
        "DELETE FROM segment_metrics WHERE segment_id NOT IN (SELECT id FROM segments)"
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


def _piece_tempo_baseline(
    conn: sqlite3.Connection, piece_id: int | None, exclude_segment_id: int
) -> tuple[float | None, int]:
    """The piece's own typical note rate, and how many segments it is drawn from.

    Relative to the piece, never to a metronome mark: the log has no score, so there is
    no target tempo to be slower *than*. The segment being judged is excluded so it can
    never provide its own baseline, and the mean is named a mean rather than a median —
    SQLite has no median and inventing one here would be a bigger claim than the data.

    `piece_id` is None for a segment nobody has labelled; there is then no piece to be
    slower than, which is a legitimate "no baseline" rather than an error.
    """
    if piece_id is None:
        return None, 0
    row = conn.execute(
        """
        SELECT AVG(m.median_tempo) AS typical, COUNT(*) AS n
        FROM segments g
        JOIN segment_metrics m ON m.segment_id = g.id
        WHERE g.piece_id = ?1 AND g.id != ?2 AND m.median_tempo IS NOT NULL
        """,
        (piece_id, exclude_segment_id),
    ).fetchone()
    return (row["typical"], int(row["n"] or 0))


def offer_practice_kinds(conn: sqlite3.Connection, sitting_id: int) -> int:
    """Write an unconfirmed kind proposal on the segments that have none.

    Never touches a row that already carries a kind *or* a basis, whatever they are: a
    proposal may not overwrite a person, and that one guard is what makes re-running the
    pass safe rather than destructive. Returns how many offers were written, which is
    what the tests assert against.
    """
    rows = conn.execute(
        """
        SELECT g.id, g.piece_id, g.source, g.practice_kind, g.practice_kind_basis,
               m.note_count, m.median_tempo, m.restarts
        FROM segments g
        LEFT JOIN segment_metrics m ON m.segment_id = g.id
        WHERE g.sitting_id = ?
        """,
        (sitting_id,),
    ).fetchall()
    written = 0
    for row in rows:
        if row["practice_kind"] is not None or row["practice_kind_basis"] is not None:
            continue
        typical, baseline = _piece_tempo_baseline(conn, row["piece_id"], int(row["id"]))
        offered = kinds.offer_for(
            note_count=int(row["note_count"] or 0),
            is_sight_reading=row["source"] == "sight_reading",
            median_tempo=row["median_tempo"],
            piece_typical_tempo=typical,
            piece_baseline_segments=baseline,
            restarts=row["restarts"],
        )
        if offered is None:
            continue
        conn.execute(
            "UPDATE segments SET practice_kind = ?1, practice_kind_basis = 'offered'"
            " WHERE id = ?2",
            (offered, int(row["id"])),
        )
        written += 1
    return written


def set_practice_kind(
    segment_id: int,
    action: str,
    kind: PracticeKind | None,
    db_path: Path | None = None,
) -> list[SegmentSummary]:
    """Record how a segment was practised, or answer the offer about it.

    The single owner of "someone has decided about the kind", the same way
    ``_settle_label`` is the one owner of a piece decision:

    * ``set`` is the player's own choice. It writes ``basis = 'manual'`` and may replace a
      previous choice, because changing your mind is not a mistake.
    * ``accept`` promotes a pending offer. It is refused when there is no offer, so a
      stale button cannot manufacture one.
    * ``decline`` clears an offer. Declining nothing is a deliberate no-op rather than a
      409: a double-click is not an error.
    """
    with db.transaction(db_path) as conn:
        row = conn.execute(
            "SELECT id, sitting_id, practice_kind, practice_kind_basis FROM segments WHERE id = ?",
            (segment_id,),
        ).fetchone()
        if row is None:
            raise NotFound(f"no segment {segment_id}")

        if action == "accept":
            if row["practice_kind_basis"] != "offered" or row["practice_kind"] is None:
                raise InvalidRequest("this segment has no offer to accept")
            conn.execute(
                "UPDATE segments SET practice_kind_basis = 'accepted' WHERE id = ?",
                (segment_id,),
            )
        elif action == "decline":
            conn.execute(
                "UPDATE segments SET practice_kind = NULL, practice_kind_basis = NULL"
                " WHERE id = ?",
                (segment_id,),
            )
        else:
            conn.execute(
                "UPDATE segments SET practice_kind = ?1, practice_kind_basis = ?2"
                " WHERE id = ?3",
                (kind, None if kind is None else "manual", segment_id),
            )
        return _segment_rows(conn, int(row["sitting_id"]))


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
            "SELECT id, started_ms, ended_ms, source, closed_ms FROM sittings WHERE id = ?",
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
        # permanent. A sitting closed because the piano went away is closed *now*,
        # not five minutes from now — that is the whole point of closing it.
        closed = sitting["closed_ms"] is not None
        if not closed and int(sitting["ended_ms"]) + settings.sitting_gap_s * 1000 >= now:
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
        # Identify before returning, so a sitting arrives already tagged rather than
        # waiting for someone to press a button. Only the unambiguous band is
        # written; the rest comes back as candidates on the detail read. This is a
        # read path that writes labels, which is deliberate — and is exactly why the
        # label is marked as inferred and is one click from being rejected.
        autotag_sitting(conn, sitting_id)
        # Offered, never applied: the proposal is stored with basis 'offered', so it is
        # drawn as a question and counts in nothing until someone answers it. After the
        # matcher, because "slower than usual for this piece" needs the piece.
        offer_practice_kinds(conn, sitting_id)
        return _segment_rows(conn, sitting_id)


def sitting_detail(
    sitting_id: int, now_ms: int | None = None, db_path: Path | None = None
) -> SittingDetail:
    segments = ensure_segments(sitting_id, now_ms=now_ms, db_path=db_path)
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    conn = db.connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, started_ms, ended_ms, started_at, ended_at, local_date, source,"
            " closed_ms FROM sittings WHERE id = ?",
            (sitting_id,),
        ).fetchone()
        if row is None:
            raise NotFound(f"no sitting {sitting_id}")
        note_count = conn.execute(
            "SELECT COUNT(*) FROM note_events WHERE sitting_id = ?", (sitting_id,)
        ).fetchone()[0]
        # What the undecided segments might be. Computed here rather than inside
        # `_segment_rows`, which every edit path calls: a suggestion is a read-time
        # question, and re-running the matcher after every split would put it in the
        # way of the editing it exists to help with.
        candidates = candidates_for_sitting(conn, sitting_id)
        for segment in segments:
            segment.candidates = candidates.get(segment.id, [])
        return SittingDetail(
            id=int(row["id"]),
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            local_date=row["local_date"],
            source=row["source"],
            note_count=int(note_count),
            duration_s=(int(row["ended_ms"]) - int(row["started_ms"])) / 1000.0,
            # The same question `ensure_segments` asks, answered the same way: a
            # sitting is finished when it was explicitly closed (the piano went
            # away) *or* when the silence gap has run out. Deriving it from the
            # clock alone reported "not closed" for a sitting the piano had already
            # ended, so the interface disagreed with the segmentation underneath it.
            closed=row["closed_ms"] is not None
            or int(row["ended_ms"]) + settings.sitting_gap_s * 1000 < now,
            segments=segments,
        )
    finally:
        conn.close()


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
        pedals = conn.execute(
            "SELECT onset_ms, value, channel FROM pedal_events"
            " WHERE sitting_id = ? ORDER BY onset_ms",
            (sitting_id,),
        ).fetchall()
        return SittingNotes(
            sitting_id=int(sitting["id"]),
            started_ms=int(sitting["started_ms"]),
            notes=[LoggedNote(**dict(row)) for row in rows],
            pedals=[LoggedPedal(**dict(row)) for row in pedals],
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
        " confidence, identified_by, practice_kind, practice_kind_basis"
        " FROM segments WHERE id = ?",
        (segment_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"no segment {segment_id}")
    return row


def _counted_kind(row: sqlite3.Row) -> tuple[str | None, str | None]:
    """A row's practice kind, but only when a person actually settled it.

    An ``offered`` kind is the app's question about the *whole* stretch, so it is not
    something a boundary edit may carry to either half — the halves are exactly what makes
    the question doubtful, and the offer pass will ask again on its own terms. A kind a
    person chose is theirs, and cutting a segment administratively must not silently drop
    half their answer.
    """
    if row["practice_kind_basis"] in ("manual", "accepted"):
        return row["practice_kind"], row["practice_kind_basis"]
    return None, None


def _settle_label(
    conn: sqlite3.Connection, row: sqlite3.Row, piece_id: int | None
) -> None:
    """Write a person's decision about a segment, and record what became of the guess.

    The single owner of "someone has decided": whether the decision arrives from the
    piece dropdown, from accepting a match or from refusing one, the label is written
    here and the outcome is recorded here. Two call sites writing labels is how one
    of them ends up forgetting to record a rejection, and a live accuracy figure
    that only counts some of the mistakes is worse than none.
    """
    previous = row["piece_id"]
    inferred = row["identified_by"] == "similarity"

    conn.execute(
        "UPDATE segments SET piece_id = ?1, confidence = ?2, identified_by = ?3,"
        " source = ?4 WHERE id = ?5",
        (
            piece_id,
            None if piece_id is None else 1.0,
            None if piece_id is None else "manual",
            None if piece_id is None else "repertoire",
            int(row["id"]),
        ),
    )

    if not inferred:
        return  # there was no guess, so there is nothing to be right or wrong about
    same = piece_id is not None and previous is not None and int(previous) == int(piece_id)
    if piece_id is None:
        action, accepted = "rejected", False
    elif same:
        action, accepted = "confirmed", True
    else:
        action, accepted = "changed", False
    _record_outcome(
        conn,
        segment_id=int(row["id"]),
        guessed_piece_id=int(previous) if previous is not None else None,
        resolved_piece_id=piece_id,
        action=action,
        accepted=accepted,
        score=row["confidence"],
    )


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
        _settle_label(conn, row, piece_id)
        # A label can make a kind offer possible that was not before: "slower than usual"
        # needs a piece. Safe to call every time — it writes only where nothing is set.
        offer_practice_kinds(conn, int(row["sitting_id"]))
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

        inherit_kind, inherit_basis = _counted_kind(row)
        conn.execute(
            "UPDATE segments SET start_ms = ?1, end_ms = ?2,"
            " practice_kind = ?3, practice_kind_basis = ?4 WHERE id = ?5",
            (int(left[0]["onset_ms"]), left_end, inherit_kind, inherit_basis, segment_id),
        )
        # The new half inherits *what the activity was* — source and workout —
        # because splitting a boundary says nothing about which piece it is, and
        # a piece label would have to arbitrarily belong to one side.
        conn.execute(
            "INSERT INTO segments (sitting_id, start_ms, end_ms, source, workout_id,"
            " practice_kind, practice_kind_basis)"
            " VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            (
                sitting_id,
                int(right[0]["onset_ms"]),
                right_end,
                row["source"],
                row["workout_id"],
                inherit_kind,
                inherit_basis,
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
        # The kind follows the same rule as the piece label: whichever half carries one
        # wins, and the earlier half is preferred when both do. An offer is not carried,
        # for the reason `_counted_kind` gives.
        low_kind, low_basis = _counted_kind(low)
        high_kind, high_basis = _counted_kind(high)
        merged_kind = low_kind if low_kind is not None else high_kind
        merged_basis = low_basis if low_kind is not None else high_basis
        conn.execute(
            "UPDATE segments SET start_ms = ?1, end_ms = ?2, piece_id = ?3,"
            " confidence = ?4, identified_by = ?5, practice_kind = ?6,"
            " practice_kind_basis = ?7 WHERE id = ?8",
            (
                int(low["start_ms"]),
                int(high["end_ms"]),
                low["piece_id"] if from_low else high["piece_id"],
                low["confidence"] if from_low else high["confidence"],
                low["identified_by"] if from_low else high["identified_by"],
                merged_kind,
                merged_basis,
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
    # What was written down, kept as its own series. The practice domain reads the
    # journal here for the same reason `by_piece` already does: "how long did I
    # practise" is a question about the whole log, and the journal is part of it.
    written_rows = conn.execute(
        """
        SELECT entry_date AS date,
               COALESCE(SUM(practice_minutes), 0) AS minutes,
               COUNT(*) AS entries
        FROM piece_journal
        WHERE practice_minutes IS NOT NULL
        GROUP BY entry_date
        """
    ).fetchall()
    written_by_date = {
        row["date"]: (round(float(row["minutes"] or 0.0), 1), int(row["entries"]))
        for row in written_rows
    }
    by_date = {}
    for row in days_rows:
        date = row["date"]
        written, entries = written_by_date.get(date, (0.0, 0))
        by_date[date] = CalendarDay(
            date=date,
            minutes=round(float(row["minutes"] or 0.0), 1),
            notes=notes_by_date.get(date, 0),
            sittings=int(row["sittings"]),
            written_minutes=written,
            written_entries=entries,
        )
    # A day with prose but no notes still has to appear, or the entries vanish from
    # the calendar entirely.
    for date, (written, entries) in written_by_date.items():
        if date not in by_date:
            by_date[date] = CalendarDay(
                date=date, minutes=0.0, notes=0, sittings=0,
                written_minutes=written, written_entries=entries,
            )
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


def kinds_breakdown(conn: sqlite3.Connection, days: int) -> list[PracticeKindSplit]:
    """Logged minutes per practice kind, untagged included.

    Two rules live in this query and both are asserted:

    * the kind is taken through a CASE, so a row whose basis is ``offered`` resolves to
      NULL and lands in the untagged bucket rather than its own. An unanswered question
      must not be counted as a label, and it must not vanish either — a split that
      dropped it could not be reconciled against the segments it summarises;
    * minutes are segment minutes, not sitting minutes, because the axis is per segment.
      The Log dashboard's ``total_minutes`` stays sitting-based and is a different number.
    """
    since = (_today() - timedelta(days=days - 1)).isoformat()
    rows = conn.execute(
        """
        WITH per_segment AS (
            SELECT CASE
                       WHEN g.practice_kind_basis IN ('manual', 'accepted')
                       THEN g.practice_kind
                       ELSE NULL
                   END AS kind,
                   (g.end_ms - g.start_ms) / 60000.0 AS minutes,
                   (SELECT COUNT(*) FROM note_events e
                     WHERE e.sitting_id = g.sitting_id
                       AND e.onset_ms >= g.start_ms
                       AND e.onset_ms <= g.end_ms) AS notes
            FROM segments g
            JOIN sittings s ON s.id = g.sitting_id
            WHERE s.local_date >= ?1
        )
        SELECT kind, SUM(minutes) AS minutes, SUM(notes) AS notes, COUNT(*) AS segments
        FROM per_segment
        GROUP BY kind
        ORDER BY minutes DESC
        """,
        (since,),
    ).fetchall()
    return [
        PracticeKindSplit(
            kind=row["kind"],
            minutes=round(float(row["minutes"] or 0.0), 1),
            notes=int(row["notes"] or 0),
            segments=int(row["segments"] or 0),
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
        " MAX(ended_ms) AS last_ms,"
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
        kinds=kinds_breakdown(conn, days),
        recent=list_sittings_conn(conn, recent),
        last_note_ms=(
            int(totals["last_ms"]) if totals["last_ms"] is not None else None
        ),
        capture=capture_status.snapshot(),
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


# --------------------------------------------------------------------------
# Identifying a segment from your own labelled practice
#
# The matcher itself lives in `similarity.py` and knows nothing about the
# database. This section is the part that does: which labelled segments are the
# training set, how a segment's notes are fetched, and what happens to a match
# once it has been made.
# --------------------------------------------------------------------------


def _notes_for_segments(
    conn: sqlite3.Connection, rows: list[sqlite3.Row]
) -> dict[int, list[Note]]:
    """Notes per segment, fetched sitting by sitting.

    One query per sitting rather than per segment: a sitting holds a few hundred
    notes, and asking for them once is the difference between a handful of queries
    and one per segment on every page load.
    """
    by_sitting: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        by_sitting.setdefault(int(row["sitting_id"]), []).append(row)

    out: dict[int, list[Note]] = {int(row["id"]): [] for row in rows}
    for sitting_id, group in by_sitting.items():
        notes = conn.execute(
            "SELECT onset_ms, duration_ms, pitch, velocity, channel FROM note_events"
            " WHERE sitting_id = ? ORDER BY onset_ms, pitch",
            (sitting_id,),
        ).fetchall()
        for row in group:
            start = int(row["start_ms"])
            end = int(row["end_ms"])
            out[int(row["id"])] = [
                Note(
                    epoch_ms=int(note["onset_ms"]),
                    pitch=int(note["pitch"]),
                    velocity=int(note["velocity"]),
                    duration_ms=int(note["duration_ms"]),
                    channel=note["channel"],
                )
                for note in notes
                if start <= int(note["onset_ms"]) <= end
            ]
    return out


#: The columns every identification query needs.
_SEGMENT_COLUMNS = "g.id, g.sitting_id, g.start_ms, g.end_ms, g.piece_id, g.identified_by"


def _labelled_rows(
    conn: sqlite3.Connection,
    *,
    exclude_segment_id: int | None = None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """The training set: segments a *person* put a piece on, oldest first.

    Machine guesses are excluded, deliberately. Training on your own guesses
    compounds whatever the matcher got wrong the first time — a mislabelled
    segment would become evidence for the same mistake — and the design's promise
    is that every segment *you* tag becomes the reference.

    ``limit`` keeps the newest that many, which is what every live path uses: a
    fingerprint is derived per reference on every read, so an uncapped set would
    make the log slower every month. Oldest-first is preserved after the cut, so
    callers that walk the rows (the sitting context) still see them in order.
    """
    sql = (
        f"SELECT {_SEGMENT_COLUMNS} FROM segments g"
        " WHERE g.piece_id IS NOT NULL"
        "   AND (g.identified_by IS NULL OR g.identified_by <> 'similarity')"
    )
    params: list = []
    if exclude_segment_id is not None:
        sql += " AND g.id <> ?"
        params.append(exclude_segment_id)
    if limit is None:
        sql += " ORDER BY g.sitting_id, g.start_ms"
        return conn.execute(sql, params).fetchall()

    sql += " ORDER BY g.sitting_id DESC, g.start_ms DESC LIMIT ?"
    params.append(limit)
    return list(reversed(conn.execute(sql, params).fetchall()))


def labelled_count(conn: sqlite3.Connection) -> int:
    """How many segments a person has labelled, ignoring the matcher's cap."""
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM segments"
            " WHERE piece_id IS NOT NULL"
            "   AND (identified_by IS NULL OR identified_by <> 'similarity')"
        ).fetchone()[0]
    )


def _fingerprints(
    conn: sqlite3.Connection, rows: list[sqlite3.Row]
) -> dict[int, Fingerprint]:
    notes = _notes_for_segments(conn, rows)
    return {
        int(row["id"]): fingerprint(
            notes.get(int(row["id"]), []), attack_window_ms=settings.attack_window_ms
        )
        for row in rows
    }


def examples_from(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[Example]:
    """Turn labelled segment rows into training examples."""
    prints = _fingerprints(conn, rows)
    return [
        Example(
            segment_id=int(row["id"]),
            piece_id=int(row["piece_id"]),
            fingerprint=prints[int(row["id"])],
        )
        for row in rows
    ]


def segment_identification(
    conn: sqlite3.Connection,
    segment_id: int,
    *,
    examples: list[Example] | None = None,
    context_piece_id: int | None = None,
    weights: Weights = DEFAULT_WEIGHTS,
) -> Identification:
    """Match one segment against your labelled practice.

    ``examples`` is passed in by callers that identify several segments at once —
    the training set is the same for all of them, and rebuilding it per segment
    would re-derive every fingerprint for every row.
    """
    row = conn.execute(
        f"SELECT {_SEGMENT_COLUMNS} FROM segments g WHERE g.id = ?", (segment_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f"no segment {segment_id}")
    if examples is None:
        examples = examples_from(conn, _labelled_rows(conn, exclude_segment_id=segment_id))

    segment_print = _fingerprints(conn, [row])[segment_id]
    return identify(
        segment_print,
        examples,
        neighbours=settings.autotag_neighbours,
        score_auto=settings.autotag_score_auto,
        score_prompt=settings.autotag_score_prompt,
        min_margin=settings.autotag_min_margin,
        min_notes=settings.autotag_min_notes,
        weights=weights,
        context_piece_id=context_piece_id,
    )


def _piece_labels(conn: sqlite3.Connection, piece_ids: Iterable[int]) -> dict[int, dict]:
    ids = sorted({int(piece) for piece in piece_ids})
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT p.id, p.title, c.name AS composer_name
        FROM pieces p LEFT JOIN composers c ON c.id = p.composer_id
        WHERE p.id IN ({placeholders})
        """,
        ids,
    ).fetchall()
    return {int(row["id"]): dict(row) for row in rows}


def _candidate_out(
    conn: sqlite3.Connection,
    candidates: Sequence[Candidate],
    *,
    reason: str,
    band: str,
    context_piece_id: int | None,
    limit: int = 3,
) -> list[SegmentCandidate]:
    labels = _piece_labels(conn, [candidate.piece_id for candidate in candidates[:limit]])
    out: list[SegmentCandidate] = []
    for position, candidate in enumerate(candidates[:limit]):
        label = labels.get(candidate.piece_id, {})
        out.append(
            SegmentCandidate(
                piece_id=candidate.piece_id,
                title=label.get("title") or f"piece {candidate.piece_id}",
                composer_name=label.get("composer_name"),
                score=round(candidate.score, 4),
                pitch_class=round(candidate.pitch_class, 4),
                tempo=round(candidate.tempo, 4),
                register_overlap=round(candidate.register, 4),
                support=candidate.support,
                margin=round(candidate.margin, 4),
                band=band if position == 0 else "listed",
                reason=reason if position == 0 else None,
                from_context=context_piece_id is not None
                and candidate.piece_id == context_piece_id,
            )
        )
    return out


def candidates_for_sitting(conn: sqlite3.Connection, sitting_id: int) -> dict[int, list[SegmentCandidate]]:
    """What each unlabelled segment of a sitting might be.

    Computed on read rather than stored, because a suggestion is a statement about
    the labels you have *now*: tagging today's segment can change what yesterday's
    unlabelled one should be, and a stored suggestion would not know that.

    Segments that have already been resolved — accepted, rejected or dismissed —
    are skipped, so a declined suggestion does not come back on every reload.
    """
    rows = conn.execute(
        f"SELECT {_SEGMENT_COLUMNS}, g.workout_id FROM segments g"
        " WHERE g.sitting_id = ? ORDER BY g.start_ms",
        (sitting_id,),
    ).fetchall()

    undecided = [
        int(row["id"])
        for row in rows
        if row["piece_id"] is None
        # A workout segment is sight-reading by declaration, and an inferred label
        # is a question already answered; only a blank, unquestioned segment is
        # worth offering a piece for.
        and row["identified_by"] not in _SETTLED
        and row["identified_by"] != "similarity"
        and int(row["workout_id"] or 0) == 0
        and not _has_outcome(conn, int(row["id"]))
    ]
    if not undecided:
        return {}
    labelled = _labelled_rows(conn, limit=settings.autotag_training_limit)
    if not labelled:
        return {}
    examples = examples_from(conn, labelled)

    out: dict[int, list[SegmentCandidate]] = {}
    context: int | None = None
    # In order, carrying the last resolved piece forward: a sitting is normally one
    # piece at a time, and the segment being identified may itself be the evidence
    # for the next one.
    for row in rows:
        segment_id = int(row["id"])
        if row["piece_id"] is not None:
            context = int(row["piece_id"])
        if segment_id not in undecided:
            continue
        identification = segment_identification(
            conn, segment_id, examples=examples, context_piece_id=context
        )
        if identification.candidates:
            out[segment_id] = _candidate_out(
                conn,
                list(identification.candidates),
                reason=identification.reason,
                band=identification.band,
                context_piece_id=context,
            )
    return out


#: Identification states that need no further question: a person has decided.
_SETTLED = ("manual", "workout")


def _has_outcome(conn: sqlite3.Connection, segment_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM identification_outcomes WHERE segment_id = ? LIMIT 1", (segment_id,)
    ).fetchone()
    return row is not None


def _record_outcome(
    conn: sqlite3.Connection,
    *,
    segment_id: int,
    guessed_piece_id: int | None,
    resolved_piece_id: int | None,
    action: str,
    accepted: bool,
    score: float | None,
) -> None:
    conn.execute(
        "INSERT INTO identification_outcomes"
        " (segment_id, guessed_piece_id, resolved_piece_id, action, accepted, score)"
        " VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        (segment_id, guessed_piece_id, resolved_piece_id, action, 1 if accepted else 0, score),
    )


def _autotag_rows(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> AutotagReport:
    """Identify a run of segments, carrying each segment's context forward.

    The context is the piece of the last segment already decided *in this same
    pass*, which is what makes a sitting behave like one piece: the first segment
    may need a real match or your help, and the rest of the sitting then leans the
    way the sitting is already going.
    """
    report = AutotagReport(considered=len(rows))
    references = _labelled_rows(conn, limit=settings.autotag_training_limit)
    examples = examples_from(conn, references)
    if not examples:
        report.notes.append(
            "No labelled segments yet, so there is nothing to compare with. Tag a few "
            "segments by hand and the matcher has a reference."
        )
        report.unresolved = len(rows)
        return report

    # Context starts from whatever this sitting already has, so re-running over an
    # old sitting does not lose what the earlier segments say.
    context: int | None = None
    for row in rows:
        if row["piece_id"] is not None:
            context = int(row["piece_id"])
            continue
        identification = segment_identification(
            conn, int(row["id"]), examples=examples, context_piece_id=context
        )
        if identification.band == "auto" and identification.best is not None:
            best = identification.best
            conn.execute(
                "UPDATE segments SET piece_id = ?1, confidence = ?2, identified_by = 'similarity'"
                " WHERE id = ?3",
                (best.piece_id, round(best.score, 4), int(row["id"])),
            )
            context = best.piece_id
            report.assigned += 1
        elif identification.band == "suggest":
            report.offered += 1
        else:
            report.unresolved += 1
    return report


def autotag_sitting(conn: sqlite3.Connection, sitting_id: int) -> AutotagReport:
    """Write the matches that are unambiguous for one sitting's unlabelled segments.

    Called where segments are materialised, so a sitting arrives already
    identified rather than waiting for someone to press a button. It writes only
    the confident band and leaves everything else for the timeline to offer.
    """
    rows = conn.execute(
        f"SELECT {_SEGMENT_COLUMNS} FROM segments g"
        " WHERE g.sitting_id = ? AND g.piece_id IS NULL"
        "   AND (g.identified_by IS NULL OR g.identified_by <> 'similarity')"
        " ORDER BY g.start_ms",
        (sitting_id,),
    ).fetchall()
    if not rows:
        return AutotagReport(considered=0)
    return _autotag_rows(conn, rows)


def autotag_unlabelled(db_path: Path | None = None) -> AutotagReport:
    """Look at every unlabelled segment in the library, newest sittings last.

    The backfill path, for a library that was already full of segments before the
    matcher existed. It writes the confident band only, exactly like the automatic
    pass, so re-running it can never invent a label it would not have written.
    """
    with db.transaction(db_path) as conn:
        rows = conn.execute(
            f"SELECT {_SEGMENT_COLUMNS} FROM segments g"
            " WHERE g.piece_id IS NULL"
            "   AND (g.identified_by IS NULL OR g.identified_by <> 'similarity')"
            " ORDER BY g.sitting_id, g.start_ms"
        ).fetchall()
        if not rows:
            return AutotagReport(considered=0)
        return _autotag_rows(conn, rows)


def identification_quality(db_path: Path | None = None) -> IdentificationQuality:
    """How good the matcher is on *your* library, measured by hiding each label.

    Leave-one-out: every labelled segment is matched against all the others, and
    scored on whether the piece you actually tagged it with came back. It is the
    only accuracy claim worth making, because it is computed from the material the
    matcher will really be asked about — including the pieces that sound like each
    other.

    The work is quadratic in the number of labels, so the newest
    ``autotag_quality_limit`` are evaluated and the report says how many were left
    out rather than quietly sampling.
    """
    conn = db.connect(db_path)
    try:
        # The *count* is of everything you have tagged; the *work* is bounded by the
        # cap, and the report says so rather than presenting a sample as the whole.
        total_labelled = labelled_count(conn)
        labelled = _labelled_rows(conn, limit=settings.autotag_training_limit)
        inferred = int(
            conn.execute(
                "SELECT COUNT(*) FROM segments WHERE identified_by = 'similarity'"
            ).fetchone()[0]
        )
        quality = IdentificationQuality(
            labelled=total_labelled,
            inferred=inferred,
            **_outcome_counts(conn),
        )
        if len(labelled) < total_labelled:
            quality.notes.append(
                f"compared against your newest {len(labelled)} labelled segments; "
                f"the older {total_labelled - len(labelled)} are beyond the matcher's "
                "reference window (SRT_AUTOTAG_TRAINING_LIMIT)"
            )
        if len(labelled) < 2:
            quality.notes.append(
                "Two labelled segments are the minimum: with one there is nothing to "
                "compare it against."
            )
            return quality

        considered = labelled[-settings.autotag_quality_limit :]
        quality.evaluated = len(considered)
        quality.skipped = len(labelled) - len(considered)
        examples = examples_from(conn, labelled)
        by_id = {example.segment_id: example for example in examples}
        prints = {example.segment_id: example.fingerprint for example in examples}

        if quality.skipped:
            quality.notes.append(
                f"evaluated the newest {quality.evaluated} labelled segments; "
                f"{quality.skipped} older ones were left out to keep the report quick"
            )

        context: int | None = None
        previous_sitting: int | None = None
        for row in considered:
            segment_id = int(row["id"])
            sitting_id = int(row["sitting_id"])
            if sitting_id != previous_sitting:
                context = None
                previous_sitting = sitting_id
            identification = identify(
                prints[segment_id],
                [example for example in examples if example.segment_id != segment_id],
                neighbours=settings.autotag_neighbours,
                score_auto=settings.autotag_score_auto,
                score_prompt=settings.autotag_score_prompt,
                min_margin=settings.autotag_min_margin,
                min_notes=settings.autotag_min_notes,
                context_piece_id=context,
            )
            truth = int(row["piece_id"])
            top = identification.best.piece_id if identification.best else None
            quality.correct_top += int(top == truth)
            quality.correct_top3 += int(
                truth in [candidate.piece_id for candidate in identification.candidates[:3]]
            )
            if identification.band == "auto":
                quality.auto_attempted += 1
                quality.auto_correct += int(top == truth)
            elif identification.band == "suggest":
                quality.offered_attempted += 1
                quality.offered_correct += int(top == truth)
            else:
                quality.unresolved += 1
            # The next segment in this sitting gets to know what this one is, exactly
            # as the live pass does.
            context = truth
        return quality
    finally:
        conn.close()


def _outcome_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT action, COUNT(*) AS total FROM identification_outcomes GROUP BY action"
    ).fetchall()
    counts = {row["action"]: int(row["total"]) for row in rows}
    return {
        "confirmed": counts.get("confirmed", 0),
        "changed": counts.get("changed", 0),
        "rejected": counts.get("rejected", 0),
        "dismissed": counts.get("dismissed", 0),
    }


def resolve_identification(
    segment_id: int, action: str, db_path: Path | None = None
) -> list[SegmentSummary]:
    """Answer the question a match asks: it is right, it is wrong, or not now.

    Only the decisions that are *about a guess* live here. Replacing a label with a
    different piece is an ordinary assignment and goes through ``assign_piece`` —
    which also records what became of the guess, so there is exactly one way to
    change a label and exactly one place that notices a guess was overruled.
    ``dismiss`` writes no label at all, because the match was never written either.
    """
    if action not in {"accept", "reject", "dismiss"}:
        raise InvalidRequest(f"{action!r} is not an identification outcome")

    with db.transaction(db_path) as conn:
        row = _segment_or_raise(conn, segment_id)
        inferred = row["identified_by"] == "similarity"

        if action == "dismiss":
            if inferred:
                raise InvalidRequest("that label was written by the matcher; reject it instead")
            # Recorded so the app stops asking. A declined suggestion is not an error
            # by the matcher, so it is deliberately not part of the accuracy figure.
            _record_outcome(
                conn,
                segment_id=segment_id,
                guessed_piece_id=None,
                resolved_piece_id=None,
                # The stored vocabulary is the past participle throughout, matching
                # the four counters the quality report reads: a request says
                # "dismiss", the row records that it *was* dismissed.
                action="dismissed",
                accepted=False,
                score=None,
            )
            return _segment_rows(conn, int(row["sitting_id"]))

        if not inferred:
            raise InvalidRequest(f"there is no inferred label to {action}")

        _settle_label(conn, row, row["piece_id"] if action == "accept" else None)
        return _segment_rows(conn, int(row["sitting_id"]))
