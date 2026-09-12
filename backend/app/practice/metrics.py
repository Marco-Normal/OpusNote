"""Per-segment metrics, derived from raw note events.

Five metrics, the practice-logger's MVP set: ``duration_s``, ``note_count``,
``median_tempo``, ``mean_velocity`` with ``velocity_stddev``, and ``restarts``.

**Tempo is measured over attacks, not consecutive notes.** Taking the interval
between adjacent notes makes a chord read as ~0 ms and the BPM estimate explode
to infinity, which is wrong for anything with two hands. Notes within
``attack_window_ms`` of the attack's first note are one attack, and the interval
is measured between attack onsets.

Everything here is a pure function of a note list, so metrics are always
recomputable from ``note_events`` and there is nothing to keep in sync.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .sessionize import Note


@dataclass(frozen=True)
class SegmentMetrics:
    duration_s: float
    note_count: int
    median_tempo: float | None
    mean_velocity: float | None
    velocity_stddev: float | None
    restarts: int


def attacks(notes: list[Note], window_ms: int) -> list[list[Note]]:
    """Cluster notes into attacks.

    Measured from the *first* note of the attack rather than the previous one, so
    a fast run of notes cannot chain into a single unbounded "attack" that would
    report a tempo far slower than what was played.
    """
    ordered = sorted(notes, key=lambda note: (note.epoch_ms, note.pitch))
    clusters: list[list[Note]] = []
    for note in ordered:
        if clusters and note.epoch_ms - clusters[-1][0].epoch_ms <= window_ms:
            clusters[-1].append(note)
        else:
            clusters.append([note])
    return clusters


def median_tempo(notes: list[Note], window_ms: int) -> float | None:
    """BPM from the median interval between attacks, or None below two attacks.

    This is a note-rate proxy, not a metronome reading: with no score there is no
    way to know where the beat falls, so a passage of sixteenths reports four
    times its nominal tempo. That is fine for the question it answers — *is this
    piece faster than it was last week* — because the same passage measured the
    same way is comparable with itself. It is not fine as an absolute claim, so
    nothing should present it as one.
    """
    onsets = [cluster[0].epoch_ms for cluster in attacks(notes, window_ms)]
    if len(onsets) < 2:
        return None
    intervals = [b - a for a, b in zip(onsets, onsets[1:]) if b > a]
    if not intervals:
        return None
    median_ms = statistics.median(intervals)
    if median_ms <= 0:
        return None
    return round(60_000.0 / median_ms, 2)


def restarts(notes: list[Note], restart_gap_ms: int) -> int:
    """Mid-segment silences long enough to read as "started again".

    Counted from one note's release to the next note's onset, so a held note is
    not itself counted as a pause.
    """
    ordered = sorted(notes, key=lambda note: (note.epoch_ms, note.pitch))
    count = 0
    for previous, following in zip(ordered, ordered[1:]):
        if following.epoch_ms - previous.end_ms >= restart_gap_ms:
            count += 1
    return count


def segment_metrics(
    notes: list[Note], *, attack_window_ms: int, restart_gap_ms: int
) -> SegmentMetrics:
    if not notes:
        return SegmentMetrics(0.0, 0, None, None, None, 0)
    start = min(note.epoch_ms for note in notes)
    end = max(note.end_ms for note in notes)
    velocities = [float(note.velocity) for note in notes]
    return SegmentMetrics(
        duration_s=round((end - start) / 1000.0, 3),
        note_count=len(notes),
        median_tempo=median_tempo(notes, attack_window_ms),
        mean_velocity=round(statistics.fmean(velocities), 2),
        velocity_stddev=(
            round(statistics.pstdev(velocities), 2) if len(velocities) > 1 else 0.0
        ),
        restarts=restarts(notes, restart_gap_ms),
    )
