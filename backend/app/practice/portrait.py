"""The note-level portrait: what a window of practice sounded like, key by key.

Separate from ``store.rhythm`` because the two have opposite costs. The rhythm read is a
handful of sitting rows and a join to the segment metrics; this one is a pass over every
note in the window, five passes in all, and on the owner's million-note library that is a
couple of seconds. It is therefore its own request, fetched when the portrait is opened,
and it never appears on anything that is polled.

The numbers are descriptive, not judgements: a wide dynamic range and a narrow one are both
correct playing, and the portrait says which the window held rather than which it should
have held.
"""

from __future__ import annotations

import collections
import math
import sqlite3
from datetime import date, timedelta

from .models import (
    HourTouch,
    OctaveNotes,
    PitchClassNotes,
    PracticePortrait,
    RegisterProfile,
    TextureProfile,
    TimingProfile,
    TouchProfile,
    TravelProfile,
    VelocitySpan,
)
from .store import _database_name, _round, _today, _utc_offset_minutes_now

#: Notes this close together are one attack — a chord, or a chord rolled by less than a
#: fortieth of a second. Wide enough for a roll, far narrower than a deliberate run.
ATTACK_WINDOW_MS = 40

#: Intervals longer than this are phrase boundaries, not rhythm. Two seconds is slower than
#: any deliberate pulse and faster than the gaps between thoughts.
PHRASE_GAP_MS = 2_000

#: A key span is about 17 cm per octave; used only to turn semitones into an intuition.
METRES_PER_SEMITONE = 0.17 / 12

#: The last portrait built per database file, with the inputs it was built from.
#:
#: Keyed on the inputs rather than on a version counter, the same way the passages cache is:
#: the facts this is a function of are the notes (append-only, so their count and highest id
#: name the set), the sittings (their count and highest id) and the window. A cache keyed on
#: "the database has not changed" would be wrong the moment a note arrived, and this is the
#: one read in the app whose cost is the whole library.
_PORTRAITS: dict[str, tuple[tuple, PracticePortrait]] = {}


def forget() -> None:
    """Drop every cached portrait — a rebuilt file must not answer for the old one."""
    _PORTRAITS.clear()


def _signature(conn: sqlite3.Connection, since: str, offset: int, days: int) -> tuple:
    notes = conn.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM note_events").fetchone()
    sittings = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM sittings WHERE local_date >= ?", (since,)
    ).fetchone()
    return (since, offset, days, int(notes[0]), int(notes[1]), int(sittings[0]), int(sittings[1]))


def portrait(
    conn: sqlite3.Connection,
    days: int = 90,
    tz_offset_minutes: int | None = None,
) -> PracticePortrait:
    """Measure the notes of the window: register, touch, texture, travel, regularity.

    Every query is bounded by the same sitting subquery, so ``days`` costs what the window
    holds rather than what the file holds, and the window's own minutes come from the
    sittings rather than from the notes (a long silence between pieces is still practice
    time, and a sitting's length is a fact the log already stores).
    """
    assumed_offset = (
        tz_offset_minutes if tz_offset_minutes is not None else _utc_offset_minutes_now()
    )
    today = _today()
    since = (today - timedelta(days=days - 1)).isoformat()
    window = "SELECT id FROM sittings WHERE local_date >= ?"
    database = _database_name(conn)
    signature = _signature(conn, since, assumed_offset, days)
    cached = _PORTRAITS.get(database)
    if cached is not None and cached[0] == signature:
        return cached[1]

    sitting_rows = conn.execute(
        "SELECT id, started_ms, ended_ms, local_date, tz_offset_minutes"
        " FROM sittings WHERE local_date >= ? ORDER BY started_ms, id",
        (since,),
    ).fetchall()
    offsets = {
        int(row["id"]): (
            int(row["tz_offset_minutes"])
            if row["tz_offset_minutes"] is not None
            else assumed_offset
        )
        for row in sitting_rows
    }
    minutes = sum((int(row["ended_ms"]) - int(row["started_ms"])) for row in sitting_rows)
    minutes = max(minutes, 0) / 60_000.0

    # One scan for both histograms: the pair (pitch, velocity) is at most a few thousand
    # rows, and folding it here is cheaper than asking the note table the same question twice.
    histogram = conn.execute(
        f"SELECT pitch, velocity, COUNT(*) AS notes FROM note_events"
        f" WHERE sitting_id IN ({window}) GROUP BY pitch, velocity",
        (since,),
    ).fetchall()
    pitches: dict[int, int] = collections.Counter()
    velocities: dict[int, int] = collections.Counter()
    for row in histogram:
        count = int(row["notes"])
        pitches[int(row["pitch"])] += count
        velocities[int(row["velocity"])] += count

    note_total = sum(pitches.values())
    keyboard = _register(pitches)
    origin = (
        date.fromisoformat(str(sitting_rows[0]["local_date"]))
        if sitting_rows
        else today
    )
    touch, velocity_spans = _touch(
        velocities, sitting_rows, offsets, since, conn, origin
    )
    texture, travel, timing = _attacks(conn, since, window, minutes)

    result = PracticePortrait(
        days=days,
        window_start=sitting_rows[0]["local_date"] if sitting_rows else None,
        window_end=today.isoformat(),
        minutes=_round(minutes),
        notes=note_total,
        tz_offset_minutes=assumed_offset,
        keyboard=keyboard,
        touch=touch,
        texture=texture,
        travel=travel,
        timing=timing,
        velocity_spans=velocity_spans,
    )
    _PORTRAITS[database] = (signature, result)
    return result


def _register(counts: dict[int, int]) -> RegisterProfile:
    if not counts:
        return RegisterProfile()
    total = sum(counts.values())
    octave_counts = collections.Counter()
    class_counts = [0] * 12
    for pitch, notes in counts.items():
        octave_counts[pitch // 12 - 1] += notes
        class_counts[pitch % 12] += notes
    lowest, highest = min(counts), max(counts)
    return RegisterProfile(
        distinct_keys=len(counts),
        lowest=lowest,
        highest=highest,
        span_semitones=highest - lowest,
        mean_pitch=round(sum(p * n for p, n in counts.items()) / total, 2),
        octaves=[
            OctaveNotes(octave=octave, notes=octave_counts[octave])
            for octave in range(min(octave_counts), max(octave_counts) + 1)
        ],
        pitch_classes=[
            PitchClassNotes(pitch_class=index, notes=class_counts[index])
            for index in range(12)
        ],
    )


def _touch(velocities, sitting_rows, offsets, since, conn, origin):
    if not velocities:
        return TouchProfile(), []
    total = sum(velocities.values())
    weighted = sum(velocity * notes for velocity, notes in velocities.items())
    values = sorted(velocities)
    entropy = 0.0
    for notes in velocities.values():
        p = notes / total
        entropy -= p * math.log2(p)
    lowest, highest = min(values), max(values)
    touch = TouchProfile(
        notes=total,
        mean_velocity=round(weighted / total, 2),
        min_velocity=lowest,
        max_velocity=highest,
        distinct_velocities=len(values),
        entropy_bits=round(entropy, 3),
        dynamic_range_db=(
            round(20 * math.log10(highest / lowest), 2) if lowest > 0 else None
        ),
    )

    # Per sitting rather than per note: the mean, weighted by that sitting's note count, is
    # the same number, and 72 rows is a cheaper way to get it than 1 000 000.
    per_sitting = conn.execute(
        f"SELECT sitting_id, AVG(velocity) AS mean, COUNT(*) AS notes FROM note_events"
        f" WHERE sitting_id IN (SELECT id FROM sittings WHERE local_date >= ?)"
        f" GROUP BY sitting_id",
        (since,),
    ).fetchall()
    mean_by_sitting = {int(row["sitting_id"]): (float(row["mean"]), int(row["notes"])) for row in per_sitting}

    hour_totals = [[0, 0.0] for _ in range(24)]  # notes, velocity*notes
    for row in sitting_rows:
        sitting_id = int(row["id"])
        if sitting_id not in mean_by_sitting:
            continue
        mean, notes = mean_by_sitting[sitting_id]
        offset = offsets[sitting_id]
        hour = (int(row["started_ms"]) + offset * 60_000) // 3_600_000 % 24
        hour_totals[hour][0] += notes
        hour_totals[hour][1] += mean * notes
    touch.by_hour = [
        HourTouch(
            hour=hour,
            notes=notes,
            mean_velocity=round(velocity / notes, 2) if notes else None,
        )
        for hour, (notes, velocity) in enumerate(hour_totals)
    ]

    # Equal time slices of the *practised* span, not equal sitting counts and not the
    # calendar window: a library six weeks old must not put all of its playing in the last
    # two quarters because the other two are before the log began.
    span_days = max((date.today() - origin).days / 4.0, 1.0)
    spans = [[0, 0.0] for _ in range(4)]
    for row in sitting_rows:
        sitting_id = int(row["id"])
        if sitting_id not in mean_by_sitting:
            continue
        mean, notes = mean_by_sitting[sitting_id]
        age = (date.fromisoformat(str(row["local_date"])) - origin).days
        index = min(3, max(0, int(age / span_days)))
        spans[index][0] += notes
        spans[index][1] += mean * notes
    return touch, [
        VelocitySpan(
            span=index,
            notes=notes,
            mean_velocity=round(velocity / notes, 2) if notes else None,
        )
        for index, (notes, velocity) in enumerate(spans)
    ]


def _attacks(conn: sqlite3.Connection, since: str, window: str, minutes: float):
    """Attacks, travel and interval regularity from one scan of the window's notes.

    The cluster id needs two window passes: `LAG` may not be nested inside the `SUM` that
    numbers the clusters, so the gap is computed first and flagged second. That is why this
    is one query rather than three — the note scan itself is the expensive part.
    """
    row = conn.execute(
        f"""
        WITH lagged AS (
            SELECT sitting_id, onset_ms, pitch,
                   onset_ms - LAG(onset_ms) OVER (
                       PARTITION BY sitting_id ORDER BY onset_ms, pitch
                   ) AS gap
            FROM note_events
            WHERE sitting_id IN ({window})
        ), flagged AS (
            SELECT sitting_id, onset_ms, pitch,
                   CASE WHEN gap IS NULL OR gap > {ATTACK_WINDOW_MS} THEN 1 ELSE 0 END AS starts
            FROM lagged
        ), ordered AS (
            SELECT sitting_id, onset_ms, pitch,
                   SUM(starts) OVER (
                       PARTITION BY sitting_id ORDER BY onset_ms, pitch
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   ) AS cluster
            FROM flagged
        ), attacks AS (
            SELECT sitting_id, cluster, MIN(onset_ms) AS at_ms,
                   AVG(pitch) AS pitch, COUNT(*) AS notes
            FROM ordered
            GROUP BY sitting_id, cluster
        ), sequence AS (
            SELECT sitting_id, at_ms, pitch, notes,
                   LAG(pitch) OVER (PARTITION BY sitting_id ORDER BY at_ms) AS previous_pitch,
                   at_ms - LAG(at_ms) OVER (PARTITION BY sitting_id ORDER BY at_ms) AS gap
            FROM attacks
        )
        SELECT COUNT(*) AS attacks,
               AVG(notes) AS notes_per_attack,
               COALESCE(SUM(CASE WHEN notes >= 3 THEN 1 ELSE 0 END), 0) AS chord_attacks,
               COALESCE(SUM(ABS(pitch - previous_pitch)), 0) AS semitones,
               AVG(ABS(pitch - previous_pitch)) AS mean_leap,
               MAX(ABS(pitch - previous_pitch)) AS max_leap,
               SUM(CASE WHEN gap IS NOT NULL AND gap <= {PHRASE_GAP_MS} THEN 1 ELSE 0 END)
                   AS intervals,
               AVG(CASE WHEN gap IS NOT NULL AND gap <= {PHRASE_GAP_MS} THEN gap END)
                   AS mean_interval,
               AVG(CASE WHEN gap IS NOT NULL AND gap <= {PHRASE_GAP_MS} THEN gap * gap END)
                   AS mean_square
        FROM sequence
        """,
        (since,),
    ).fetchone()

    attacks = int(row["attacks"] or 0)
    if attacks == 0:
        return TextureProfile(), TravelProfile(), TimingProfile()
    intervals = int(row["intervals"] or 0)
    mean_interval = row["mean_interval"]
    cv = None
    if intervals and mean_interval and row["mean_square"] is not None:
        variance = max(0.0, float(row["mean_square"]) - float(mean_interval) ** 2)
        cv = _round(math.sqrt(variance) / float(mean_interval), 3)
    semitones = float(row["semitones"] or 0.0)
    return (
        TextureProfile(
            attacks=attacks,
            notes_per_attack=_round(row["notes_per_attack"], 3),
            chord_attacks=int(row["chord_attacks"] or 0),
            chord_share=_round(float(row["chord_attacks"] or 0) / attacks, 3),
            attacks_per_minute=_round(attacks / minutes, 1) if minutes > 0 else None,
        ),
        TravelProfile(
            semitones=_round(semitones, 1),
            metres=_round(semitones * METRES_PER_SEMITONE, 1),
            mean_leap=_round(row["mean_leap"], 2),
            max_leap=_round(row["max_leap"], 2),
        ),
        TimingProfile(
            intervals=intervals,
            mean_interval_ms=_round(mean_interval, 1),
            cv=cv,
        ),
    )
