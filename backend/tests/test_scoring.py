"""Scoring engine tests.

These use hand-built note lists rather than generated music so each expected
score can be derived on paper.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.music.expected import ExpectedNote
from app.scoring.engine import PlayedNote, accuracy_by_hand, score_performance

TEMPO = 60.0  # one quarter note == one second, so beats map 1:1 to seconds


def expected_note(index: int, pitch: int, onset_s: float, *, hand: str = "RH", event_id: int | None = None) -> ExpectedNote:
    return ExpectedNote(
        index=index,
        event_id=index if event_id is None else event_id,
        pitch=pitch,
        onset_q=onset_s,
        duration_q=1.0,
        onset_s=onset_s,
        hand=hand,
        measure=1,
        beat=onset_s + 1.0,
    )


def played_note(pitch: int, onset: float) -> PlayedNote:
    return PlayedNote(pitch=pitch, onset=onset, duration=0.5, velocity=80)


MELODY = [60, 62, 64, 65]
EXPECTED = [expected_note(i, pitch, float(i)) for i, pitch in enumerate(MELODY)]


def test_perfect_performance_scores_full_marks():
    played = [played_note(pitch, float(i)) for i, pitch in enumerate(MELODY)]
    result = score_performance(EXPECTED, played, tempo_bpm=TEMPO)
    assert result.score == pytest.approx(100.0)
    assert result.pitch_accuracy == pytest.approx(100.0)
    assert result.rhythm_accuracy == pytest.approx(100.0)
    assert result.continuity_accuracy == pytest.approx(100.0)
    assert result.missed_count == 0
    assert result.wrong_pitch_count == 0
    assert all(item.status == "correct" for item in result.feedback)


def test_all_wrong_pitches_scores_zero_for_pitch():
    played = [played_note(pitch + 1, float(i)) for i, pitch in enumerate(MELODY)]
    result = score_performance(EXPECTED, played, tempo_bpm=TEMPO)
    assert result.pitch_accuracy == 0.0
    assert result.wrong_pitch_count == 4
    assert result.missed_count == 0
    assert all(item.status == "wrong_pitch" for item in result.feedback)


def test_silence_is_missed_not_wrong():
    result = score_performance(EXPECTED, [], tempo_bpm=TEMPO)
    assert result.pitch_accuracy == 0.0
    assert result.missed_count == 4
    assert result.played_count == 0
    assert result.continuity_accuracy == 0.0


def test_partial_performance_uses_f1():
    played = [played_note(60, 0.0), played_note(62, 1.0)]
    result = score_performance(EXPECTED, played, tempo_bpm=TEMPO)
    # precision 1.0, recall 0.5 -> F1 = 2/3
    assert result.pitch_accuracy == pytest.approx(66.67, abs=0.01)
    assert result.missed_count == 2


def test_extra_notes_lower_precision():
    played = [played_note(pitch, float(i)) for i, pitch in enumerate(MELODY)]
    played.append(played_note(72, 0.5))  # not in the notation
    result = score_performance(EXPECTED, played, tempo_bpm=TEMPO)
    # precision 4/5, recall 1.0 -> F1 = 8/9
    assert result.pitch_accuracy == pytest.approx(88.89, abs=0.01)
    assert result.extra_count == 1


def test_notes_outside_the_match_window_are_not_matched():
    played = [played_note(pitch, float(i) + 0.5) for i, pitch in enumerate(MELODY)]
    result = score_performance(EXPECTED, played, tempo_bpm=TEMPO, )
    assert result.pitch_accuracy == 0.0
    assert result.missed_count == 4
    assert result.extra_count == 4


def test_consistent_lateness_only_costs_rhythm():
    played = [played_note(pitch, float(i) + 0.1) for i, pitch in enumerate(MELODY)]
    result = score_performance(EXPECTED, played, tempo_bpm=TEMPO)
    assert result.pitch_accuracy == pytest.approx(100.0)
    # 0.1 beat mean error against a 0.5 beat tolerance -> 0.7*0.8 + 0.3*1.0
    assert result.rhythm_accuracy == pytest.approx(86.0, abs=0.1)
    assert result.continuity_accuracy == pytest.approx(100.0)
    assert result.mean_onset_error_beats == pytest.approx(0.1, abs=1e-6)


def test_rhythm_penalises_inconsistency_as_well_as_bias():
    steady = [played_note(pitch, float(i) + 0.1) for i, pitch in enumerate(MELODY)]
    jittery = [
        played_note(60, 0.0),
        played_note(62, 1.15),
        played_note(64, 2.0),
        played_note(65, 3.15),
    ]
    steady_result = score_performance(EXPECTED, steady, tempo_bpm=TEMPO)
    jittery_result = score_performance(EXPECTED, jittery, tempo_bpm=TEMPO)
    assert jittery_result.rhythm_accuracy < steady_result.rhythm_accuracy
    assert jittery_result.onset_error_std_beats > 0


def test_hesitation_is_detected_even_though_the_note_is_late():
    """A one-second stall must show up as a continuity problem.

    Regression: hesitation detection originally reused the tight 200 ms pitch
    window, so a genuinely late note was classed as missing and the stall was
    invisible.
    """
    played = [
        played_note(60, 0.0),
        played_note(62, 1.0),
        played_note(64, 3.0),  # one second late
        played_note(65, 4.0),
    ]
    result = score_performance(EXPECTED, played, tempo_bpm=TEMPO)
    assert result.hesitation_count == 1
    assert result.continuity_accuracy < 60.0


def test_steady_performance_has_no_hesitations():
    played = [played_note(pitch, float(i)) for i, pitch in enumerate(MELODY)]
    result = score_performance(EXPECTED, played, tempo_bpm=TEMPO)
    assert result.hesitation_count == 0


def test_latency_compensation_removes_a_systematic_delay():
    played = [played_note(pitch, float(i) + 0.15) for i, pitch in enumerate(MELODY)]
    uncompensated = score_performance(EXPECTED, played, tempo_bpm=TEMPO)
    compensated = score_performance(EXPECTED, played, tempo_bpm=TEMPO, latency_ms=150.0)
    assert compensated.rhythm_accuracy > uncompensated.rhythm_accuracy
    assert compensated.mean_onset_error_beats == pytest.approx(0.0, abs=1e-6)


def test_chords_share_an_event_and_do_not_create_false_gaps():
    chord_expected = [
        expected_note(0, 60, 0.0, event_id=0),
        expected_note(1, 64, 0.0, event_id=0),
        expected_note(2, 67, 0.0, event_id=0),
        expected_note(3, 62, 1.0, event_id=1),
        expected_note(4, 65, 1.0, event_id=1),
    ]
    played = [
        played_note(60, 0.0),
        played_note(64, 0.01),
        played_note(67, 0.02),
        played_note(62, 1.0),
        played_note(65, 1.01),
    ]
    result = score_performance(chord_expected, played, tempo_bpm=TEMPO)
    assert result.pitch_accuracy == pytest.approx(100.0)
    assert result.hesitation_count == 0
    assert result.continuity_accuracy > 90.0


def test_hand_breakdown_is_reported():
    mixed = [
        expected_note(0, 60, 0.0, hand="RH"),
        expected_note(1, 48, 1.0, hand="LH"),
    ]
    played = [played_note(60, 0.0), played_note(50, 1.0)]
    result = score_performance(mixed, played, tempo_bpm=TEMPO)
    by_hand = accuracy_by_hand(result.feedback)
    assert by_hand["RH"]["accuracy"] == pytest.approx(100.0)
    assert by_hand["LH"]["accuracy"] == pytest.approx(0.0)
    assert by_hand["LH"]["wrong_pitch"] == 1


def test_weights_sum_to_one_and_drive_the_total():
    weights = settings.weights
    assert sum(weights.values()) == pytest.approx(1.0)
    played = [played_note(pitch, float(i)) for i, pitch in enumerate(MELODY)]
    result = score_performance(EXPECTED, played, tempo_bpm=TEMPO)
    expected_total = (
        weights["pitch"] * result.pitch_accuracy
        + weights["rhythm"] * result.rhythm_accuracy
        + weights["continuity"] * result.continuity_accuracy
    )
    assert result.score == pytest.approx(expected_total, abs=0.01)


def test_tempo_scales_onset_error_into_beats():
    """At 120 BPM a quarter is 0.5 s, so a 0.1 s error is 0.2 beats."""
    fast_expected = [expected_note(i, pitch, float(i) * 0.5) for i, pitch in enumerate(MELODY)]
    played = [played_note(pitch, float(i) * 0.5 + 0.1) for i, pitch in enumerate(MELODY)]
    result = score_performance(fast_expected, played, tempo_bpm=120.0)
    assert result.pitch_accuracy == pytest.approx(100.0)
    assert result.mean_onset_error_beats == pytest.approx(0.2, abs=1e-6)


def test_result_is_json_serialisable():
    played = [played_note(pitch, float(i)) for i, pitch in enumerate(MELODY)]
    payload = score_performance(EXPECTED, played, tempo_bpm=TEMPO).to_dict()
    assert payload["score"] == pytest.approx(100.0)
    assert len(payload["feedback"]) == 4
    assert payload["feedback"][0]["status"] == "correct"
