"""Harmony engine tests."""

from __future__ import annotations

import random

import pytest

from app.music.harmony import (
    CHORD_STEPS,
    PROGRESSIONS,
    bar_chords,
    chord_steps,
    nearest_chord_tone,
)
from app.skills_data import LEVELS


def test_every_level_has_a_progression():
    for level in LEVELS:
        assert level in PROGRESSIONS, f"no progression for level {level}"


@pytest.mark.parametrize("level", LEVELS)
def test_progressions_are_diatonic_degrees(level):
    for template in PROGRESSIONS[level]:
        assert template, "a template must not be empty"
        for degree in template:
            assert 0 <= degree <= 6, f"degree {degree} is not a diatonic root"


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("bars", [1, 2, 4, 8, 12, 16])
def test_one_chord_per_bar(level, bars):
    chords = bar_chords(bars, level, random.Random(0))
    assert len(chords) == bars
    assert all(0 <= degree <= 6 for degree in chords)


@pytest.mark.parametrize("bars", [1, 3, 5, 7, 12])
def test_progressions_end_on_the_tonic(bars):
    """An exercise that stops on the dominant sounds unfinished."""
    chords = bar_chords(bars, 6, random.Random(4))
    assert chords[-1] == 0


def test_longer_progressions_approach_through_the_dominant():
    chords = bar_chords(8, 6, random.Random(4))
    assert chords[-2] == 4, "the penultimate bar should set up the final tonic"


def test_short_exercises_are_not_forced_into_a_cadence():
    chords = bar_chords(2, 6, random.Random(4))
    assert len(chords) == 2
    assert chords[-1] == 0


def test_chords_are_deterministic_for_a_seed():
    assert bar_chords(8, 5, random.Random(11)) == bar_chords(8, 5, random.Random(11))


def test_progressions_vary_across_seeds():
    seen = {tuple(bar_chords(8, 8, random.Random(seed))) for seed in range(25)}
    assert len(seen) > 3, f"expected variety, got {seen}"


def test_beginner_progressions_use_only_tonic_and_dominant():
    """Level 1 should stay on I and V, not tour the scale.

    V appears because the cadence is forced onto the penultimate bar of any
    exercise long enough to have one.
    """
    for seed in range(20):
        chords = bar_chords(8, 1, random.Random(seed))
        assert set(chords) <= {0, 4}, chords


def test_higher_levels_use_more_of_the_scale():
    simple = {degree for template in PROGRESSIONS[2] for degree in template}
    rich = {degree for template in PROGRESSIONS[9] for degree in template}
    assert len(rich) > len(simple)


def test_bar_chords_handles_zero_bars():
    assert bar_chords(0, 5, random.Random(1)) == []


def test_chord_steps_are_bounded():
    assert chord_steps(3) == (0, 2, 4)
    assert chord_steps(4) == (0, 2, 4, 6)
    assert chord_steps(99) == CHORD_STEPS
    assert chord_steps(0) == (0,), "a chord always has at least its root"


def test_nearest_chord_tone_keeps_the_register():
    """Snapping must move a note as little as possible, in either direction."""
    # C major: the tonic triad is degrees 0, 2, 4 (mod 7).
    assert nearest_chord_tone(1, 0) == 0, "the second should fall back to the root"
    assert nearest_chord_tone(3, 0) == 2, "the fourth should fall to the third"
    assert nearest_chord_tone(5, 0) == 4
    assert nearest_chord_tone(6, 0) == 7, "the leading tone rises to the octave"


def test_nearest_chord_tone_is_idempotent_on_chord_tones():
    for degree in range(-3, 12):
        snapped = nearest_chord_tone(degree, 0)
        assert nearest_chord_tone(snapped, 0) == snapped


def test_nearest_chord_tone_respects_the_chord_root():
    # With V as the chord, the tonic degree is not a chord tone.
    snapped = nearest_chord_tone(0, 4)
    assert snapped % 7 in {(4 + step) % 7 for step in CHORD_STEPS[:3]}
