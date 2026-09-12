"""Metric extraction: the arithmetic that turns raw notes into a practice record."""

from __future__ import annotations

from app.practice.metrics import attacks, median_tempo, restarts, segment_metrics
from app.practice.sessionize import Note

WINDOW_MS = 50
RESTART_MS = 3_000


def note(onset_ms: int, pitch: int = 60, velocity: int = 70, duration_ms: int = 300) -> Note:
    return Note(epoch_ms=onset_ms, pitch=pitch, velocity=velocity, duration_ms=duration_ms)


def test_a_chord_is_one_attack() -> None:
    cluster = attacks([note(0, 60), note(3, 64), note(6, 67)], WINDOW_MS)
    assert len(cluster) == 1
    assert len(cluster[0]) == 3


def test_a_chord_does_not_make_the_tempo_infinite() -> None:
    """The bug the attack rule exists for: adjacent-note intervals on a chord.

    Two chords, a second apart. Measuring onset-to-onset between *adjacent* notes
    would see 3 ms and report 20,000 BPM.
    """
    notes = [note(0, 60), note(3, 64), note(1_000, 60), note(1_003, 64)]
    assert median_tempo(notes, WINDOW_MS) == 60.0


def test_a_fast_run_does_not_chain_into_one_attack() -> None:
    # Eight notes 30 ms apart. Measured from the *previous* note they would all
    # merge into one attack and report no tempo at all; measured from the attack's
    # first note they form four pairs, which is what a chord-like hand position
    # 30 ms apart actually is.
    notes = [note(index * 30) for index in range(8)]
    assert len(attacks(notes, WINDOW_MS)) == 4


def test_tempo_needs_two_attacks() -> None:
    assert median_tempo([note(0)], WINDOW_MS) is None
    assert median_tempo([], WINDOW_MS) is None


def test_restarts_count_silences_but_not_held_notes() -> None:
    # A pause of one second is phrasing; three seconds is a restart.
    assert restarts([note(0, duration_ms=100), note(1_100)], RESTART_MS) == 0
    assert restarts([note(0, duration_ms=100), note(3_200)], RESTART_MS) == 1
    # A note held through the gap is not a restart: the silence is measured from
    # its release.
    assert restarts([note(0, duration_ms=9_000), note(9_100)], RESTART_MS) == 0


def test_metrics_are_measured_from_first_onset_to_last_release() -> None:
    stats = segment_metrics(
        [note(0, duration_ms=500), note(1_000, duration_ms=500)],
        attack_window_ms=WINDOW_MS,
        restart_gap_ms=RESTART_MS,
    )
    assert stats.duration_s == 1.5
    assert stats.note_count == 2
    assert stats.median_tempo == 60.0
    assert stats.mean_velocity == 70.0
    assert stats.velocity_stddev == 0.0
    assert stats.restarts == 0


def test_velocity_spread_is_reported() -> None:
    stats = segment_metrics(
        [note(0, velocity=40), note(500, velocity=80)],
        attack_window_ms=WINDOW_MS,
        restart_gap_ms=RESTART_MS,
    )
    assert stats.mean_velocity == 60.0
    assert stats.velocity_stddev == 20.0


def test_a_single_velocity_has_no_spread() -> None:
    stats = segment_metrics(
        [note(0)], attack_window_ms=WINDOW_MS, restart_gap_ms=RESTART_MS
    )
    assert stats.velocity_stddev == 0.0
    assert stats.median_tempo is None


def test_no_notes_is_an_empty_metric_not_an_error() -> None:
    stats = segment_metrics([], attack_window_ms=WINDOW_MS, restart_gap_ms=RESTART_MS)
    assert (stats.note_count, stats.duration_s, stats.restarts) == (0, 0.0, 0)
