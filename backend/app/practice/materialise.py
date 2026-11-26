"""Sitting materialisation: segmentation, metrics, passages, and detail assembly."""

from __future__ import annotations

import sqlite3

from . import store as _store
import time
from bisect import bisect_left, bisect_right
from pathlib import Path

from .. import db
from . import calibration
from . import capture_status
from . import kinds
from . import passages
from . import pedal_stream
from . import segment
from . import shingles
from .metrics import SegmentMetrics, segment_metrics
from .models import (
    PracticeKind,
    PracticePassageOut,
    SegmentMetricsOut,
    SegmentSummary,
    SittingDetail,
)
from .pedal import (
    BASIS_OBSERVED,
    median_velocity,
    register_balance,
    segment_pedal,
    velocity_range,
)
from .sessionize import Note
from .store_core import _SEGMENT_COLUMNS, NotFound, _find_sitting, _sitting_notes, utc_text

def _segment_rows(conn: sqlite3.Connection, sitting_id: int) -> list[SegmentSummary]:
    """Segments of a sitting, with piece, composer, note count and metrics.

    Note counts use ``onset_ms <= end_ms``. That cannot double-count: ``segment.cut``
    only ever puts a boundary on a strictly positive gap, so no note of the next segment
    can sit at or before this segment's end. Using ``<`` would drop a zero-duration note
    from its own segment.
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
               p.opus AS piece_opus,
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
               m.pedal_changes, m.pedal_down_ratio, m.pedal_partial_ratio,
               m.pedal_blur, m.pedal_blur_ms,
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
                pedal_partial_ratio=data["pedal_partial_ratio"],
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
                piece_opus=data["piece_opus"],
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
    # The pedal is read once for the whole sitting and each segment takes the prefix that
    # had happened by its end: a stretch that began before the boundary is still holding
    # notes inside it. Re-reading that prefix per segment read the same rows once for every
    # segment of the sitting — on a long pedalled sitting, one pass over the stream against
    # one per boundary.
    pedal_moves_all = pedal_stream.moves(conn, sitting_id)
    pedal_onsets = [onset for onset, _value, _channel in pedal_moves_all]
    # Any move at all is the same question as "has this sitting any pedal history" — and that
    # is not the same as whether the pedal was pressed: imported history has none, and
    # reporting a zero there would be reporting a fault that was never observed.
    pedals_recorded = bool(pedal_moves_all)
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
            attack_window_ms=_store.settings.attack_window_ms,
            restart_gap_ms=_store.settings.restart_gap_ms,
        )
        # Clipped to the segment, out of the stream read above: a stretch that began before
        # the boundary is still holding notes inside it.
        pedal_moves = [
            (onset, value)
            for onset, value, _channel in pedal_moves_all[
                : bisect_right(pedal_onsets, int(segment["end_ms"]))
            ]
        ]
        pedalling = segment_pedal(notes, pedal_moves, recorded=pedals_recorded)
        median = median_velocity(notes)
        spread = velocity_range(notes)
        low, high = register_balance(notes)
        conn.execute(
            "INSERT INTO segment_metrics"
            " (segment_id, duration_s, note_count, median_tempo, mean_velocity,"
            "  velocity_stddev, restarts, pedal_changes, pedal_down_ratio,"
            "  pedal_partial_ratio, pedal_blur, pedal_blur_ms, pedal_basis,"
            "  median_velocity, velocity_range, mean_velocity_low, mean_velocity_high)"
            " VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17)"
            " ON CONFLICT (segment_id) DO UPDATE SET"
            "  duration_s = excluded.duration_s,"
            "  note_count = excluded.note_count,"
            "  median_tempo = excluded.median_tempo,"
            "  mean_velocity = excluded.mean_velocity,"
            "  velocity_stddev = excluded.velocity_stddev,"
            "  restarts = excluded.restarts,"
            "  pedal_changes = excluded.pedal_changes,"
            "  pedal_down_ratio = excluded.pedal_down_ratio,"
            "  pedal_partial_ratio = excluded.pedal_partial_ratio,"
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
                pedalling.partial_ratio,
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


def _backfill_blur_positions(conn: sqlite3.Connection, sitting_id: int) -> bool:
    """Give a sitting segmented before Phase 21 its blur positions, once.

    A stored metric is a cache of a pure function, and this column arrived *after* these rows
    were written: a sitting has the blur count and no places, which is precisely the state the
    feature exists to fix. Recomputing every sitting at startup would cost minutes on a real
    library and would run on machines that never open the Log, so the first read of a sitting
    fills in its own — one pass over the notes, the same work `ensure_segments` already does when
    it segments. Returns whether anything was recomputed.
    """
    stale = conn.execute(
        "SELECT 1 FROM segment_metrics m JOIN segments g ON g.id = m.segment_id"
        " WHERE g.sitting_id = ? AND m.pedal_blur > 0 AND m.pedal_blur_ms IS NULL LIMIT 1",
        (sitting_id,),
    ).fetchone()
    if stale is None:
        return False
    _refresh_metrics(conn, sitting_id)
    return True


def _segment_config() -> segment.Config:
    """The tunables, from settings, so the measurement tool and the app share one shape."""
    return segment.Config(
        floor_ms=_store.settings.segment_floor_ms,
        multiplier=_store.settings.segment_pulse_multiplier,
        ceiling_ms=_store.settings.segment_ceiling_ms,
        min_notes=_store.settings.segment_min_notes,
        max_ms=_store.settings.segment_max_ms,
    )


def awaiting_segments(
    *,
    now_ms: int | None = None,
    limit: int = 4,
    db_path: Path | None = None,
) -> list[int]:
    """Finished sittings that have never been segmented, newest first.

    The selection a background preparation pass runs on: a sitting is finished when it was
    explicitly closed (the piano went away) or when the silence gap has run out, and it needs
    nothing done to it once it has any segments at all — stored boundaries are never
    recomputed implicitly.

    `EXISTS (note_events)` is not decoration: a sitting with no notes can never produce a
    segment, so without it such a row would be selected on every tick for ever, and the only
    work each selection could do is nothing.

    Its cost is O(sittings), which is one row per practice session, and it is deliberately
    the one query allowed to be: it runs on a *tick*, not on a click, and both `EXISTS`
    clauses are index probes — `segments(sitting_id, start_ms)` and
    `note_events(sitting_id, onset_ms)`. `limit` keeps one sweep to a batch, so the caller
    re-reads its selection between batches rather than acting on a stale list.
    """
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    conn = db.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT s.id FROM sittings s"
            " WHERE (s.closed_ms IS NOT NULL OR s.ended_ms + ? < ?)"
            "   AND NOT EXISTS (SELECT 1 FROM segments g WHERE g.sitting_id = s.id)"
            "   AND EXISTS (SELECT 1 FROM note_events n WHERE n.sitting_id = s.id)"
            " ORDER BY s.started_ms DESC LIMIT ?",
            (_store.settings.sitting_gap_s * 1000, now, int(limit)),
        ).fetchall()
        return [int(row["id"]) for row in rows]
    finally:
        conn.close()


def ensure_segments(
    sitting_id: int, now_ms: int | None = None, db_path: Path | None = None
) -> list[SegmentSummary]:
    """Materialise segments for a closed sitting, once.

    A sitting that already has segments is returned untouched: recomputing on read
    would silently discard hand-edited boundaries and tags.
    """
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    # `immediate`: this reads the sitting and its notes and then writes segments from them, so a
    # deferred transaction would have its first INSERT refused as "database is locked" if another
    # connection committed in between. It is reached from read routes (`sitting_detail`, and the
    # repertoire's take catch-up), which is exactly where that must not become a 500.
    with db.transaction(db_path, immediate=True) as conn:
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
            # A sitting segmented before Phase 21 carries the blur count and no places; this is
            # the one place that already knows "the segments exist", so it is where the cache is
            # brought up to date rather than in every reader.
            _backfill_blur_positions(conn, sitting_id)
            return _segment_rows(conn, sitting_id)

        # An open sitting's boundaries would be provisional, and because stored
        # segments are never recomputed implicitly, a provisional view would be
        # permanent. A sitting closed because the piano went away is closed *now*,
        # not five minutes from now — that is the whole point of closing it.
        closed = sitting["closed_ms"] is not None
        if not closed and int(sitting["ended_ms"]) + _store.settings.sitting_gap_s * 1000 >= now:
            return []

        started_ms = int(sitting["started_ms"])
        notes = _sitting_notes(conn, sitting_id, started_ms)
        for window in segment.cut(notes, config=_segment_config()):
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

        _store.autotag_sitting(conn, sitting_id)
        # Offered, never applied: the proposal is stored with basis 'offered', so it is
        # drawn as a question and counts in nothing until someone answers it. After the
        # matcher, because "slower than usual for this piece" needs the piece.
        offer_practice_kinds(conn, sitting_id)
        return _segment_rows(conn, sitting_id)


def _passage_rows(
    conn: sqlite3.Connection, sitting_id: int, *, note_count: int | None = None
) -> list[PracticePassageOut]:
    """The sitting's passages and the piece-session each belongs to.

    Derived on read from the attempts and their labels, so nothing is stored and nothing has to
    be migrated (22-D1): a re-segment or a re-label changes the input, and the same labels always
    produce the same groups.

    The weights come from the sitting's own attempts rather than from the library, so the question
    asked is "is this the same material as the one before it, out of what this sitting contains"
    — and so that a library with no labels yet, which is where grouping is worth the most, can
    still group anything at all.

    The *derivation* is cached — see `_passages_derived` — because it is a pass over the
    sitting's notes and nothing else in this read is: 130 ms of a 165 ms open on the owner's
    largest sitting, paid again on every open, every edit's re-read and every dashboard poll.
    What is cached is `passages.derive`'s own output. The rows below are deliberately not,
    because they carry each piece's *title*, and a renamed piece must not serve a stale name.
    """
    rows = conn.execute(
        f"SELECT {_SEGMENT_COLUMNS} FROM segments g"
        " WHERE g.sitting_id = ? ORDER BY g.start_ms",
        (sitting_id,),
    ).fetchall()
    if not rows:
        return []
    derived, session_of = _passages_derived(conn, sitting_id, rows, note_count=note_count)

    labels = _store._piece_labels(conn, [row.piece_id for row in derived if row.piece_id is not None])
    out: list[PracticePassageOut] = []
    for index, found in enumerate(derived):
        label = labels.get(found.piece_id) or {}
        out.append(
            PracticePassageOut(
                start_ms=found.start_ms,
                end_ms=found.end_ms,
                piece_id=found.piece_id,
                piece_title=label.get("title"),
                composer_name=label.get("composer_name"),
                piece_opus=label.get("opus"),
                attempt_ids=list(found.attempt_ids),
                attempts=found.attempts,
                session=session_of.get(index, 0),
            )
        )
    return out


#: Passages derived for one sitting, per database file: ``{database: {sitting_id: entry}}``.
#:
#: Keyed on the *inputs* rather than on ``reference_state.version``, and that difference is the
#: whole point. The version counts changes to the *reference set*, so a re-segment that deletes
#: segments nobody had labelled leaves it still — while changing exactly the rows this is a
#: function of (PERFORMANCE.md §1.5). A rule stated as "the inputs have not moved" cannot be
#: forgotten by a write path that does not exist yet, which is the property that made the
#: reference cache correct in the first place.
_PASSAGES: dict[str, dict[int, tuple[tuple, list[passages.Passage], dict[int, int]]]] = {}


#: How many sittings' derivations to keep per database. A miss costs the derivation, never an
#: answer, so this is a memory bound rather than a cap on what the app can see: nothing here is
#: data, it is a copy of something recomputed on demand, so nothing can be lost by evicting it.
_PASSAGES_KEEP = 64


def _passages_derived(
    conn: sqlite3.Connection,
    sitting_id: int,
    rows: list[sqlite3.Row],
    *,
    note_count: int | None = None,
) -> tuple[list[passages.Passage], dict[int, int]]:
    """`passages.derive` for one sitting, recomputed only when its inputs have moved.

    The key is the two things the answer is a function of: the sitting's segment rows (their
    ids, boundaries and pieces) and how many notes the sitting holds. Notes are only ever
    appended — nothing deletes or edits a note event — so the count is exact rather than a
    proxy for the notes. A piece's *name* is in neither the key nor the cached value, and is
    read fresh by the caller, so renaming a piece is answered immediately.

    ``note_count`` is passed in by `sitting_detail`, which has already counted the notes for its
    own response; callers that have not counted them get the indexed count here.
    """
    if note_count is None:
        note_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM note_events WHERE sitting_id = ?", (sitting_id,)
            ).fetchone()[0]
        )
    key = (
        int(note_count),
        tuple(
            (int(row["id"]), int(row["start_ms"]), int(row["end_ms"]), row["piece_id"])
            for row in rows
        ),
    )

    database = _store._database_name(conn)
    cached = _PASSAGES.get(database, {}).get(sitting_id)
    if cached is not None and cached[0] == key:
        return cached[1], cached[2]

    features = _store._segment_features(conn, rows)
    weights = shingles.idf(features)
    derived = passages.derive(
        [
            passages.Attempt(
                id=int(row["id"]),
                start_ms=int(row["start_ms"]),
                end_ms=int(row["end_ms"]),
                piece_id=row["piece_id"],
            )
            for row in rows
        ],
        features,
        weights,
    )
    session_of = {
        index: position
        for position, (_piece_id, members) in enumerate(passages.piece_sessions(derived))
        for index in members
    }
    per_database = _PASSAGES.setdefault(database, {})
    per_database[sitting_id] = (key, derived, session_of)
    while len(per_database) > _PASSAGES_KEEP:
        per_database.pop(next(iter(per_database)))
    return derived, session_of


def sitting_detail(
    sitting_id: int,
    now_ms: int | None = None,
    db_path: Path | None = None,
    *,
    materialise: bool = True,
) -> SittingDetail:
    """One sitting, with its segments.

    ``materialise`` is the whole of Phase 24's read-side change, and its default is the old
    behaviour: do the work here if it has not been done. The one caller that passes
    ``materialise=False`` is the detail route, and only when it already knows a background
    job is preparing this sitting — the answer is then what is stored plus ``preparing``, in
    about a millisecond, instead of a wait.

    ``preparing`` is only ever true on that path. A read that *did* the work and found no
    segments is looking at a sitting that genuinely holds none — pedals and marks with no
    notes, say — which is not a wait and must not be reported as one.
    """

    segments = (
        _store.ensure_segments(sitting_id, now_ms=now_ms, db_path=db_path) if materialise else None
    )
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
        if segments is None:
            segments = _segment_rows(conn, sitting_id)
        note_count = conn.execute(
            "SELECT COUNT(*) FROM note_events WHERE sitting_id = ?", (sitting_id,)
        ).fetchone()[0]
        review_marks_ms = [
            int(mark["onset_ms"])
            for mark in conn.execute(
                "SELECT onset_ms FROM sitting_marks WHERE sitting_id = ? ORDER BY onset_ms",
                (sitting_id,),
            )
        ]
        # What the undecided segments might be. Computed here rather than inside
        # `_segment_rows`, which every edit path calls: a suggestion is a read-time
        # question, and re-running the matcher after every split would put it in the
        # way of the editing it exists to help with.
        candidates = _store.candidates_for_sitting(conn, sitting_id)
        for segment in segments:
            segment.candidates = candidates.get(segment.id, [])
        # The same question `ensure_segments` asks, answered the same way: a
        # sitting is finished when it was explicitly closed (the piano went
        # away) *or* when the silence gap has run out. Deriving it from the
        # clock alone reported "not closed" for a sitting the piano had already
        # ended, so the interface disagreed with the segmentation underneath it.
        closed = row["closed_ms"] is not None or int(
            row["ended_ms"]
        ) + _store.settings.sitting_gap_s * 1000 < now
        return SittingDetail(
            id=int(row["id"]),
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            local_date=row["local_date"],
            source=row["source"],
            note_count=int(note_count),
            duration_s=(int(row["ended_ms"]) - int(row["started_ms"])) / 1000.0,
            closed=closed,
            segments=segments,
            preparing=not materialise and not segments and closed and int(note_count) > 0,
            passages=_passage_rows(conn, sitting_id, note_count=note_count),
            review_marks_ms=review_marks_ms,
        )
    finally:
        conn.close()

