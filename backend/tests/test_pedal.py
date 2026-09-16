"""Pedal analysis and the touch numbers beside it.

Pure functions, so they are checked directly rather than through a sitting. The
integration — that a refresh writes them onto the segment — is in
``test_practice_store.py``.
"""

from __future__ import annotations

from app.practice.pedal import (
    BASIS_OBSERVED,
    PEDAL_DOWN,
    blur_attacks,
    blurs,
    changes,
    down_ratio,
    intervals,
    median_velocity,
    register_balance,
    segment_pedal,
    velocity_range,
)
from app.practice.sessionize import Note


def note(onset: int, pitch: int, duration: int, velocity: int = 70) -> Note:
    return Note(epoch_ms=onset, pitch=pitch, velocity=velocity, duration_ms=duration, channel=0)


# --------------------------------------------------------------------------
# Intervals and crossings
# --------------------------------------------------------------------------


def test_a_press_and_a_release_become_one_stretch() -> None:
    stretches = intervals([(0, 127), (2_000, 0)])
    assert len(stretches) == 1
    assert (stretches[0].start_ms, stretches[0].end_ms) == (0, 2_000)


def test_a_press_that_is_never_released_is_closed_at_the_end() -> None:
    """A device unplugged mid-press must not produce a stretch that never ends."""
    stretch = intervals([(500, 127)], end_ms=9_000)[0]
    assert (stretch.start_ms, stretch.end_ms) == (500, 9_000)


def test_repeated_down_values_do_not_restart_the_stretch() -> None:
    """A pedal sends a stream on the way down; only the first starts the stretch."""
    stretches = intervals([(0, 80), (10, 100), (20, 127), (30, 120), (900, 0)])
    assert len(stretches) == 1
    assert stretches[0].start_ms == 0


def test_crossings_are_counted_rather_than_messages() -> None:
    """A continuous pedal sends dozens of values per press, and it is still one press.

    Eight messages, two crossings: down through 70 and up through 60. Counting
    messages would report this as six changes and make the figure useless.
    """
    stream = [(index * 10, value) for index, value in enumerate([10, 40, 70, 100, 127, 90, 60, 20])]
    assert changes(stream) == 2, "one press, one release, whatever the traffic between"


def test_the_down_ratio_is_the_share_of_the_span_under_the_pedal() -> None:
    assert down_ratio([(0, 127), (1_000, 0)], 4_000) == 0.25
    assert down_ratio([(0, 127), (9_000, 0)], 4_000) == 1.0, "clamped, not over 1"
    assert down_ratio([], 4_000) == 0.0
    assert down_ratio([(0, 127)], 0) == 0.0, "a zero span has no ratio"


def test_the_threshold_is_the_specifications() -> None:
    assert PEDAL_DOWN == 64
    assert intervals([(0, 63), (100, 0)]) == [], "below the threshold is not a press"
    assert len(intervals([(0, 64), (100, 0)])) == 1, "at it, it is"


# --------------------------------------------------------------------------
# Blur: new harmony over notes the pedal is already holding
# --------------------------------------------------------------------------


def test_a_new_triad_over_a_pedal_held_note_is_a_blur() -> None:
    """The fault this exists to report: the old note is ringing on the pedal alone,
    and a chord that does not contain it arrives on top."""
    notes = [
        note(0, 60, 200),  # released at 200, so the pedal is holding it
        note(500, 65, 200),
        note(500, 67, 200),
        note(500, 69, 200),
    ]
    stretches = intervals([(0, 127), (2_000, 0)])
    assert blurs(notes, stretches) == 1


def test_a_chord_counts_once_however_many_notes_it_holds() -> None:
    notes = [
        note(0, 60, 200),
        note(500, 65, 200),
        note(500, 67, 200),
        note(500, 69, 200),
        note(500, 71, 200),
    ]
    assert blurs(notes, intervals([(0, 127), (2_000, 0)])) == 1


def test_restriking_what_is_already_sounding_is_not_a_blur() -> None:
    notes = [note(0, 60, 200), note(500, 60, 200)]
    assert blurs(notes, intervals([(0, 127), (2_000, 0)])) == 0


def test_a_key_that_is_still_held_is_playing_not_pedalling() -> None:
    """The distinction the whole measure rests on.

    A key held through the attack is holding its own damper; there is nothing muddy
    about playing a new chord with the old one still under the fingers.
    """
    notes = [
        note(0, 60, 5_000),  # still held when the chord arrives
        note(500, 65, 200),
        note(500, 67, 200),
        note(500, 69, 200),
    ]
    assert blurs(notes, intervals([(0, 127), (2_000, 0)])) == 0


def test_an_attack_outside_the_pedal_stretch_is_ignored() -> None:
    notes = [
        note(0, 60, 200),
        note(3_000, 65, 200),  # the pedal was already up
        note(3_000, 67, 200),
        note(3_000, 69, 200),
    ]
    assert blurs(notes, intervals([(0, 127), (2_000, 0)])) == 0


def test_no_pedal_at_all_is_no_blur() -> None:
    assert blurs([note(0, 60, 200)], []) == 0
    assert blurs([], intervals([(0, 127), (1_000, 0)])) == 0


# --------------------------------------------------------------------------
# Not recorded is not zero
# --------------------------------------------------------------------------


def test_a_sitting_with_no_pedal_rows_reports_not_recorded() -> None:
    """Imported history has no pedal events at all.

    Reporting zero there would be reporting a fault that was never observed, which is
    why this is a third state and not a refinement of nought.
    """
    result = segment_pedal([note(0, 60, 200)], [], recorded=False)
    assert result.recorded is False
    assert result.changes == 0 and result.blur == 0 and result.down_ratio == 0.0


def test_a_sitting_where_the_pedal_was_recorded_but_never_pressed_is_recorded() -> None:
    result = segment_pedal([note(0, 60, 200)], [(0, 0)], recorded=True)
    assert result.recorded is True
    assert result.changes == 0, "observed, and nothing happened"


def test_the_basis_names_the_harmony_source() -> None:
    assert BASIS_OBSERVED == "observed", (
        "a score-derived basis can be added later without reinterpreting this one"
    )


# --------------------------------------------------------------------------
# Touch
# --------------------------------------------------------------------------


def test_the_median_ignores_one_stray_accent() -> None:
    notes = [note(0, 60, 100, 50), note(100, 62, 100, 52), note(200, 64, 100, 127)]
    assert median_velocity(notes) == 52.0, "the mean would be dragged to 76"


def test_the_range_is_the_distance_between_softest_and_loudest() -> None:
    notes = [note(0, 60, 100, 40), note(100, 62, 100, 100)]
    assert velocity_range(notes) == 60.0


def test_nothing_played_has_no_touch_to_report() -> None:
    assert median_velocity([]) is None
    assert velocity_range([]) is None
    assert register_balance([]) == (None, None)


def test_the_register_split_is_around_middle_c() -> None:
    notes = [note(0, 48, 100, 60), note(100, 55, 100, 80), note(200, 72, 100, 100)]
    low, high = register_balance(notes)
    assert low == 70.0, "48 and 55 are below middle C"
    assert high == 100.0, "72 is above it"


def test_the_blur_positions_are_where_the_blurs_are() -> None:
    """Two blurs, and the onsets they happened at — a count alone cannot be acted on.

    The second chord shares exactly one pitch class with what is ringing, so it still brings
    three new ones; a chord that shared two would be an ornament, not a blur, and this test
    would be asserting the wrong rule.
    """
    notes = [
        note(0, 60, 200),      # released at 200, so the pedal is holding it
        note(500, 65, 200),    # a triad that does not contain C: blur at 500
        note(500, 67, 200),
        note(500, 69, 200),
        note(1_500, 71, 200),  # and another over what is now ringing: blur at 1500
        note(1_500, 73, 200),
        note(1_500, 76, 200),
    ]
    stretches = intervals([(0, 127), (3_000, 0)])
    assert blur_attacks(notes, stretches) == [500, 1_500]
    assert blurs(notes, stretches) == 2, "and the count is their length"


def test_the_count_and_the_positions_can_never_disagree() -> None:
    """One owner: `blurs` is the length of `blur_attacks`, not a second loop over the same rule."""
    notes = [
        note(0, 60, 200),
        note(500, 65, 200),
        note(500, 67, 200),
        note(500, 69, 200),
    ]
    stretches = intervals([(0, 127), (2_000, 0)])
    assert blurs(notes, stretches) == len(blur_attacks(notes, stretches)) == 1


def test_no_pedal_means_no_positions_either() -> None:
    assert blur_attacks([note(0, 60, 200)], []) == []
    assert blur_attacks([], intervals([(0, 127), (1_000, 0)])) == []
