"""The sequence pass, on its own.

`test_similarity.py` asks what a single segment is most like. This asks the next
question: what the *sitting* is most likely to have been, given that a sitting is
usually one piece taken section by section. The interesting cases are the ones where
the sequence disagrees with the segment — and the ones where it must not, because the
player really did switch piece.

Arithmetic only: no database, no settings. The wiring is tested in `test_autotag.py`,
where the claim "the sitting's own order is evidence" has to survive being part of a
page load.
"""

from __future__ import annotations

import pytest

from app.practice.sequence import Fragment, Option, band, decode

#: Comfortably above any `min_notes` these tests use, so only the tests about notes
#: actually exercise it.
NOTES = 30


def fragment(key: int, **scores: float) -> Fragment:
    """One segment, keyed, with each keyword as a piece id: ``fragment(1, **{"2": 0.7})``."""
    return Fragment(
        key=key,
        options=tuple(Option(piece_id=int(piece), score=score) for piece, score in scores.items()),
        notes=NOTES,
    )


def decode_one(fragments, *, switch: float = 0.2, temperature: float = 0.1):
    return decode(list(fragments), switch=switch, temperature=temperature)


# --------------------------------------------------------------------------
# The model
# --------------------------------------------------------------------------


def test_a_single_segment_has_no_sequence_to_learn_from():
    beliefs = decode_one([fragment(1, **{"2": 0.9, "3": 0.5})])
    assert len(beliefs) == 1
    belief = beliefs[0]
    assert belief.chosen == 2
    # Softmax of the two scores at temperature 0.1: exp(4) / (exp(4) + 1).
    assert belief.confidence == pytest.approx(0.982_013_8, abs=1e-6)
    assert sum(belief.probabilities.values()) == pytest.approx(1.0)


def test_every_position_sums_to_one():
    beliefs = decode_one(
        [fragment(1, **{"2": 0.7, "3": 0.4}), fragment(2, **{"2": 0.3, "3": 0.8})]
    )
    for belief in beliefs:
        assert sum(belief.probabilities.values()) == pytest.approx(1.0, abs=1e-9)
        assert belief.key in (1, 2)


def test_the_sitting_overrules_one_weak_segment():
    # The middle segment on its own is a slightly better match for piece 3, but the two
    # around it are both piece 2 — and a sitting is usually one piece.
    beliefs = decode_one(
        [
            fragment(1, **{"2": 0.85, "3": 0.40}),
            fragment(2, **{"2": 0.72, "3": 0.76}),
            fragment(3, **{"2": 0.85, "3": 0.40}),
        ]
    )
    assert [belief.chosen for belief in beliefs] == [2, 2, 2]


def test_the_sequence_does_not_hide_a_real_switch():
    # Two segments on piece 2, then two on piece 3, each with a clear margin. A player
    # changes piece mid-sitting, and smoothing that away would be a lie about the log.
    beliefs = decode_one(
        [
            fragment(1, **{"2": 0.92, "3": 0.18}),
            fragment(2, **{"2": 0.90, "3": 0.20}),
            fragment(3, **{"2": 0.20, "3": 0.90}),
            fragment(4, **{"2": 0.18, "3": 0.92}),
        ]
    )
    assert [belief.chosen for belief in beliefs] == [2, 2, 3, 3]


def test_a_strong_switch_survives_a_stubborn_prior():
    # The switch price must be a price, not a veto: at the default prior, evidence this
    # lopsided still moves the answer.
    beliefs = decode_one(
        [
            fragment(1, **{"2": 0.95, "3": 0.05}),
            fragment(2, **{"2": 0.05, "3": 0.95}),
        ],
        switch=0.05,
    )
    assert [belief.chosen for belief in beliefs] == [2, 3]


def test_an_ambiguous_segment_between_two_pieces_says_so():
    # Nothing in the middle segment separates the two, and its neighbours cannot agree:
    # the belt must not turn a coin toss into a claim.
    beliefs = decode_one(
        [
            fragment(1, **{"2": 0.9, "3": 0.2}),
            fragment(2, **{"2": 0.55, "3": 0.55}),
            fragment(3, **{"2": 0.2, "3": 0.9}),
        ],
        switch=0.5,
    )
    middle = beliefs[1]
    assert middle.confidence < 0.9
    assert middle.gap < 0.8


def test_a_segment_the_matcher_could_not_score_follows_its_neighbours():
    # A piece with no labelled references scores nothing. The exposure that gives is a
    # possibility, not a certainty, so the position is decided by the sequence.
    beliefs = decode_one(
        [
            fragment(1, **{"2": 0.9, "3": 0.1}),
            Fragment(key=2, options=(), notes=NOTES),
            fragment(3, **{"2": 0.9, "3": 0.1}),
        ]
    )
    assert beliefs[1].chosen == 2
    assert beliefs[1].probabilities[2] > 0.5


def test_a_tie_between_two_pieces_goes_to_the_smaller_id():
    # Determinism matters more than which one wins: the same sitting must not flip its
    # answer between two page loads.
    beliefs = decode_one([fragment(1, **{"7": 0.6, "3": 0.6})])
    assert beliefs[0].chosen == 3


def test_one_possible_piece_is_certain_and_alone():
    beliefs = decode_one([fragment(1, **{"4": 0.3}), fragment(2, **{"4": 0.6})])
    assert [belief.chosen for belief in beliefs] == [4, 4]
    assert [belief.confidence for belief in beliefs] == [1.0, 1.0]
    assert beliefs[0].runner_up == 0.0


def test_no_fragments_is_no_answer():
    assert decode([], switch=0.2, temperature=0.1) == []


def test_a_fragment_with_no_options_is_still_a_position():
    beliefs = decode([Fragment(key=5, options=()), Fragment(key=6, options=())], switch=0.2, temperature=0.1)
    assert [belief.chosen for belief in beliefs] == [None, None]
    assert beliefs[0].confidence == 0.0


@pytest.mark.parametrize(
    "switch, temperature",
    [(0.0, 0.1), (1.5, 0.1), (0.2, 0.0), (0.2, -0.1)],
)
def test_impossible_parameters_are_refused(switch, temperature):
    with pytest.raises(ValueError):
        decode([fragment(1, **{"2": 0.5, "3": 0.5})], switch=switch, temperature=temperature)


def test_the_notes_floor_is_the_matcher_s_own():
    belief = decode_one([fragment(1, **{"2": 0.9, "3": 0.1})])[0]
    assert band(belief, auto_probability=0.9, prompt_probability=0.5, min_notes=31) == "none"
    assert band(belief, auto_probability=0.9, prompt_probability=0.5, min_notes=30) == "auto"


def test_one_possible_piece_is_offered_not_written():
    # The single-segment matcher's rule: a perfect match with nothing to compare it
    # against has not been checked, so it is a question.
    belief = decode_one([fragment(1, **{"4": 0.9})])[0]
    assert band(belief, auto_probability=0.9, prompt_probability=0.5, min_notes=NOTES) == "suggest"


def test_low_confidence_claims_nothing():
    belief = decode_one([fragment(1, **{"2": 0.5, "3": 0.5})])[0]
    assert belief.confidence == pytest.approx(0.5)
    assert band(belief, auto_probability=0.9, prompt_probability=0.6, min_notes=NOTES) == "none"


def test_thresholds_that_contradict_each_other_are_refused():
    belief = decode_one([fragment(1, **{"2": 0.9, "3": 0.1})])[0]
    with pytest.raises(ValueError):
        band(belief, auto_probability=0.4, prompt_probability=0.5, min_notes=NOTES)
