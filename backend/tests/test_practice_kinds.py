"""The deliberate-practice taxonomy: what may be offered, and what may not."""

from __future__ import annotations

import typing

import pytest

from app.practice import kinds
from app.practice.models import PracticeKind


def test_the_tuple_and_the_wire_literal_are_one_list() -> None:
    """Two spellings of one vocabulary; drift between them is a silent 422."""
    assert kinds.KINDS == typing.get_args(PracticeKind)


def test_sight_reading_is_not_a_kind() -> None:
    """It is already owned by `segments.source`/`workout_id`, so it is not offered here."""
    assert "sight_reading" not in kinds.KINDS


def test_only_slow_and_section_may_ever_be_inferred() -> None:
    """The offer path is a closed set, asserted over its whole input space.

    Hands-separate is the one that matters: `mean_velocity_low`/`high` is a register
    balance and not a measurement of the hands — the piano sends both on one channel — so
    Phase 18b refused that claim in the UI and inference must not make it here.
    """
    offered: set[str | None] = set()
    for note_count in (0, 3, 4, 40):
        for median_tempo in (None, 20.0, 60.0, 120.0, 240.0):
            for typical in (None, 40.0, 80.0, 160.0):
                for baseline in (0, 1, 3, 30):
                    for restarts in (None, 0, 2, 3, 12):
                        offered.add(
                            kinds.offer_for(
                                note_count=note_count,
                                is_sight_reading=False,
                                median_tempo=median_tempo,
                                piece_typical_tempo=typical,
                                piece_baseline_segments=baseline,
                                restarts=restarts,
                            )
                        )
    assert offered <= {"slow", "section", None}


def test_a_slow_pass_is_offered_slow() -> None:
    assert (
        kinds.offer_for(
            note_count=30,
            is_sight_reading=False,
            median_tempo=40.0,
            piece_typical_tempo=80.0,
            piece_baseline_segments=5,
            restarts=0,
        )
        == "slow"
    )


@pytest.mark.parametrize("baseline", [0, 1, 2])
def test_slow_needs_a_piece_to_be_slow_against(baseline: int) -> None:
    """Two segments are a difference; three are a habit."""
    assert (
        kinds.offer_for(
            note_count=30,
            is_sight_reading=False,
            median_tempo=40.0,
            piece_typical_tempo=80.0,
            piece_baseline_segments=baseline,
            restarts=0,
        )
        is None
    )


def test_slow_never_fires_without_a_tempo_on_both_sides() -> None:
    for median_tempo, typical in ((None, 80.0), (40.0, None)):
        assert (
            kinds.offer_for(
                note_count=30,
                is_sight_reading=False,
                median_tempo=median_tempo,
                piece_typical_tempo=typical,
                piece_baseline_segments=9,
                restarts=0,
            )
            is None
        )


def test_repeated_starts_are_offered_as_section_work() -> None:
    assert (
        kinds.offer_for(
            note_count=30,
            is_sight_reading=False,
            median_tempo=None,
            piece_typical_tempo=None,
            piece_baseline_segments=0,
            restarts=kinds.RESTARTS_FOR_SECTION,
        )
        == "section"
    )


def test_a_slow_pass_outranks_repeated_starts() -> None:
    """One offer, deterministically chosen, so the timeline never shows two questions."""
    assert (
        kinds.offer_for(
            note_count=30,
            is_sight_reading=False,
            median_tempo=30.0,
            piece_typical_tempo=80.0,
            piece_baseline_segments=6,
            restarts=9,
        )
        == "slow"
    )


def test_a_sight_reading_segment_and_a_scrap_are_never_offered() -> None:
    common = dict(
        median_tempo=30.0,
        piece_typical_tempo=80.0,
        piece_baseline_segments=6,
        restarts=9,
    )
    assert kinds.offer_for(note_count=30, is_sight_reading=True, **common) is None
    assert (
        kinds.offer_for(
            note_count=kinds.MIN_NOTES_FOR_OFFER - 1, is_sight_reading=False, **common
        )
        is None
    )


def test_an_offer_is_a_question_and_only_a_confirmed_basis_counts() -> None:
    assert kinds.counted("manual") is True
    assert kinds.counted("accepted") is True
    assert kinds.counted("offered") is False
    assert kinds.counted(None) is False
