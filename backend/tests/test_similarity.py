"""The matcher's arithmetic, on its own.

Pure functions over note lists, so everything here is a statement about the
algorithm rather than about the database. The behavioural questions — does a
right-hand drill match a right-hand example, does a near-tie lose to the piece the
sitting is already about — are here too, because those are the decisions that
matter and they are cheap to check at this level.
"""

from __future__ import annotations

import pytest

from app.practice.sessionize import Note
from app.practice.similarity import (
    DEFAULT_WEIGHTS,
    NEUTRAL_TEMPO,
    Example,
    Fingerprint,
    Weights,
    cosine,
    fingerprint,
    identify,
    rank,
    register_overlap,
    tempo_proximity,
)

WINDOW = 50


def notes(pitches: list[int], *, spacing_ms: int = 250, start_ms: int = 1_000) -> list[Note]:
    return [
        Note(
            epoch_ms=start_ms + index * spacing_ms,
            pitch=pitch,
            velocity=70,
            duration_ms=200,
            channel=0,
        )
        for index, pitch in enumerate(pitches)
    ]


def profile(*pitches: int) -> Fingerprint:
    return fingerprint(notes(list(pitches)), attack_window_ms=WINDOW)


def example(segment_id: int, piece_id: int, *pitches: int, spacing_ms: int = 250) -> Example:
    return Example(
        segment_id=segment_id,
        piece_id=piece_id,
        fingerprint=fingerprint(notes(list(pitches), spacing_ms=spacing_ms), attack_window_ms=WINDOW),
    )


# --------------------------------------------------------------------------
# Fingerprints
# --------------------------------------------------------------------------


def test_a_profile_is_the_share_of_each_pitch_class():
    # Two Cs and one G: 2/3 and 1/3, and nothing else.
    result = profile(60, 72, 67)
    assert result.note_count == 3
    assert result.pc_profile[0] == pytest.approx(2 / 3)
    assert result.pc_profile[7] == pytest.approx(1 / 3)
    assert sum(result.pc_profile) == pytest.approx(1.0)


def test_octaves_are_the_same_pitch_class():
    # A piece played an octave up is the same piece, and the profile must say so.
    assert profile(60, 62, 64).pc_profile == profile(72, 74, 76).pc_profile


def test_an_empty_stretch_has_no_opinion():
    result = fingerprint([], attack_window_ms=WINDOW)
    assert result.note_count == 0
    assert not result.has_notes
    assert sum(result.pc_profile) == 0.0
    assert result.note_rate is None


def test_the_register_is_the_range_actually_played():
    result = profile(55, 60, 79)
    assert (result.pitch_min, result.pitch_max) == (55, 79)


def test_tempo_is_measured_over_attacks_not_notes():
    # A chord is one attack: three notes at the same instant must not read as an
    # infinitely fast tempo, which is the same rule the metrics module uses.
    chord = [
        Note(epoch_ms=1_000, pitch=60, velocity=70, duration_ms=200, channel=0),
        Note(epoch_ms=1_000, pitch=64, velocity=70, duration_ms=200, channel=0),
        Note(epoch_ms=1_000, pitch=67, velocity=70, duration_ms=200, channel=0),
        Note(epoch_ms=1_500, pitch=60, velocity=70, duration_ms=200, channel=0),
    ]
    result = fingerprint(chord, attack_window_ms=WINDOW)
    assert result.note_rate == pytest.approx(120.0)


# --------------------------------------------------------------------------
# The three terms
# --------------------------------------------------------------------------


def test_cosine_is_one_for_the_same_profile_and_zero_for_no_overlap():
    assert cosine((0.5, 0.5), (0.5, 0.5)) == pytest.approx(1.0)
    assert cosine((1.0, 0.0), (0.0, 1.0)) == 0.0
    assert cosine((0.0, 0.0), (1.0, 0.0)) == 0.0, "nothing to compare is not a match"


def test_cosine_refuses_profiles_of_different_lengths():
    """A silent bug otherwise: zip() would quietly compare the first twelve of a
    longer vector against a shorter one and return a plausible number."""
    with pytest.raises(ValueError):
        cosine((0.5, 0.5), (0.3, 0.3, 0.4))


def test_tempo_proximity_is_a_ratio():
    assert tempo_proximity(120, 120) == pytest.approx(1.0)
    assert tempo_proximity(60, 120) == pytest.approx(0.5)
    # Ten BPM apart means something quite different at these two speeds.
    assert tempo_proximity(100, 120) > tempo_proximity(40, 60)


def test_an_unknown_tempo_neither_helps_nor_hurts():
    assert tempo_proximity(None, 120) == NEUTRAL_TEMPO
    assert tempo_proximity(120, None) == NEUTRAL_TEMPO
    assert tempo_proximity(0, 120) == NEUTRAL_TEMPO


def test_register_overlap_is_intersection_over_union():
    assert register_overlap((60, 72), (60, 72)) == pytest.approx(1.0)
    assert register_overlap((60, 72), (73, 80)) == 0.0
    # 61..72 shared out of 60..80.
    assert register_overlap((60, 80), (61, 72)) == pytest.approx(12 / 21)


def test_an_empty_register_overlaps_nothing():
    assert register_overlap((0, -1), (60, 72)) == 0.0


def test_weights_are_normalised_so_only_their_ratio_matters():
    segment = profile(60, 62, 64, 65)
    candidate = profile(60, 62, 64, 65)
    from app.practice.similarity import compare

    doubled = compare(segment, candidate, weights=Weights(1.5, 0.2, 0.3))
    single = compare(segment, candidate, weights=Weights(0.75, 0.1, 0.15))
    assert doubled[0] == pytest.approx(single[0])


def test_an_identical_stretch_scores_one():
    segment = profile(60, 64, 67, 72)
    from app.practice.similarity import compare

    total, pitch, tempo, register = compare(segment, segment)
    assert (pitch, tempo, register) == (1.0, 1.0, 1.0)
    assert total == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------


def test_the_best_neighbour_of_each_piece_wins_and_agreement_is_reported():
    segment = profile(*PRIMARY)
    examples = [
        example(1, 10, *PRIMARY),
        example(2, 10, *PRIMARY),
        example(3, 20, 57, 60, 64, 69, 56, 59, 63, 68),
    ]
    ranked = rank(segment, examples)
    assert ranked[0].piece_id == 10
    assert ranked[0].support == 2, "two labelled segments agree"
    assert ranked[1].piece_id == 20
    assert ranked[0].runner_up == pytest.approx(ranked[1].score)
    assert ranked[0].margin > 0


def test_a_heavily_drilled_piece_cannot_crowd_out_another():
    """The defect 22-D4 retires.

    With a window over *segments*, four labels of one piece filled it and the second piece
    was not a candidate at all — which is why `runner_up` was None for 46 of the owner's 54
    labelled segments and the auto band had never once fired. Evidence is pooled per piece
    now, so a second piece is a candidate however many labels the first one has.
    """
    segment = profile(*PRIMARY)
    examples = [example(index, 10, *PRIMARY) for index in range(1, 5)]
    examples.append(example(99, 20, 57, 60, 64, 69, 56, 59, 63, 68))
    assert {candidate.piece_id for candidate in rank(segment, examples)} == {10, 20}
    assert rank(segment, examples)[0].runner_up is not None


def test_a_single_piece_has_no_runner_up_to_beat():
    segment = profile(*PRIMARY)
    ranked = rank(segment, [example(1, 10, *PRIMARY)])
    assert ranked[0].runner_up is None
    assert ranked[0].margin == 0.0


def test_nothing_labelled_means_no_candidates():
    assert rank(profile(60), []) == []


# --------------------------------------------------------------------------
# The mix: the local content share folded into the global score
# --------------------------------------------------------------------------


def test_the_mix_reorders_on_the_containment_share():
    """The local term is what names a fragment the whole-segment average cannot."""
    segment = profile(*PRIMARY)
    examples = [example(1, 10, *PRIMARY), example(2, 20, 57, 60, 64, 69, 56, 59, 63, 68)]
    assert rank(segment, examples)[0].piece_id == 10, "the global term prefers 10"
    mixed = rank(segment, examples, shares={10: 0.1, 20: 1.0}, containment_weight=0.9)
    assert mixed[0].piece_id == 20, "the local term prefers 20, and outweighs it"


def test_the_runner_up_is_recomputed_after_the_mix():
    """A stale runner-up would make the margin — and so the band — a claim about the old
    scores rather than about the ones the matcher returns."""
    segment = profile(*PRIMARY)
    examples = [example(1, 10, *PRIMARY), example(2, 20, 57, 60, 64, 69, 56, 59, 63, 68)]
    mixed = rank(segment, examples, shares={10: 0.0, 20: 1.0}, containment_weight=1.0)
    assert mixed[0].piece_id == 20
    assert mixed[0].runner_up == pytest.approx(0.0)
    assert mixed[0].margin == pytest.approx(1.0)


def test_the_band_follows_the_mixed_score_not_the_global_one():
    """Acceptance 4's precision claim is about the numbers the matcher actually uses."""
    segment = profile(*PRIMARY)
    examples = [example(1, 10, *PRIMARY), example(2, 20, 57, 60, 64, 69, 56, 59, 63, 68)]
    result = bands(
        segment, examples, shares={10: 0.0, 20: 1.0}, containment_weight=1.0
    )
    assert result.best is not None and result.best.piece_id == 20
    assert result.band == "auto"


# --------------------------------------------------------------------------
# Bands
# --------------------------------------------------------------------------


def bands(segment, examples, **overrides):
    settings = dict(
        score_auto=0.85,
        score_prompt=0.55,
        min_margin=0.10,
        min_notes=4,
        context_piece_id=None,
    )
    settings.update(overrides)
    return identify(segment, examples, **settings)


#: Eight notes that are a piece, and the same eight with one moved: the closest
#: two pieces can be without being the same multiset, which the pitch-class profile
#: cannot separate at all.
PRIMARY = [60, 62, 64, 65, 67, 69, 71, 72]
ONE_NOTE_OFF = [60, 62, 64, 65, 67, 69, 71, 73]


def two_distinct_pieces():
    return [
        example(1, 10, *PRIMARY),
        example(2, 20, 57, 60, 63, 68, 55, 58, 61, 63),
    ]


def test_an_unambiguous_match_is_written_automatically():
    result = bands(profile(*PRIMARY), two_distinct_pieces())
    assert result.band == "auto"
    assert result.best is not None and result.best.piece_id == 10


def test_a_weak_match_is_offered_rather_than_written():
    # A different key: recognisable as *not* the second piece, not clearly the first.
    result = bands(profile(61, 63, 66, 68, 70, 73), two_distinct_pieces())
    assert result.band in {"suggest", "none"}
    if result.band == "none":
        assert result.reason == "no close match"


def test_a_high_score_with_a_close_runner_up_is_offered_not_written():
    """The documented failure mode: two pieces that sound alike. The matcher must
    not confuse "best of several similar answers" with confidence, however high the
    winning score is."""
    segment = profile(*PRIMARY)
    examples = [example(1, 10, *PRIMARY), example(2, 20, *ONE_NOTE_OFF)]
    result = bands(segment, examples)
    assert result.best is not None and result.best.score > 0.9, "a high score"
    assert result.best.margin < 0.10, "with nothing to choose between them"
    assert result.band == "suggest"
    assert result.reason is not None and "close" in result.reason


def test_a_perfect_match_with_nothing_to_compare_against_is_only_offered():
    """One piece in the library means every segment "matches" it. That is not
    evidence, and the band must not pretend otherwise."""
    result = bands(profile(*PRIMARY), [example(1, 10, *PRIMARY)])
    assert result.band == "suggest"
    assert result.reason == "nothing else to compare it with"


def test_a_handful_of_notes_is_never_recognised():
    short = fingerprint(notes([60, 62, 64]), attack_window_ms=WINDOW)
    result = bands(short, two_distinct_pieces(), min_notes=8)
    assert result.band == "none"
    assert result.reason is not None and "notes" in result.reason


# --------------------------------------------------------------------------
# What the sitting is already about
# --------------------------------------------------------------------------


def test_a_near_tie_goes_to_the_piece_the_sitting_is_already_about():
    # The same eight notes under two piece names: nothing in the notes can separate
    # them, which is exactly when the sitting's own context is the only evidence
    # there is.
    segment = profile(*PRIMARY)
    examples = [example(1, 10, *PRIMARY), example(2, 20, *PRIMARY)]
    without = rank(segment, examples)
    with_context = rank(segment, examples, context_piece_id=20)
    assert without[0].piece_id == 10, "with no context, the first piece id wins the tie"
    assert with_context[0].piece_id == 20, "the sitting's piece takes the near-tie"
    # Moving a candidate is not the same as changing its score.
    assert with_context[0].score == pytest.approx(
        next(c.score for c in without if c.piece_id == 20)
    )
    # And it is still offered rather than written: the context decides *which*
    # piece to suggest, it does not manufacture the confidence to write it.
    assert bands(segment, examples, context_piece_id=20).band == "suggest"


def test_the_context_does_not_overrule_a_clear_winner():
    segment = profile(*PRIMARY)
    examples = [
        example(1, 10, *PRIMARY),
        example(2, 20, 55, 58, 61, 63, 56, 59, 62, 64),
    ]
    ranked = rank(segment, examples, context_piece_id=20)
    assert ranked[0].piece_id == 10, "a real difference in the notes still wins"


def test_the_context_can_reach_a_piece_that_is_not_second():
    segment = profile(*PRIMARY)
    examples = [
        example(1, 10, *PRIMARY),
        example(2, 20, *ONE_NOTE_OFF),
        example(3, 30, *PRIMARY),
    ]
    ranked = rank(segment, examples, context_piece_id=30)
    assert [c.piece_id for c in ranked] == [30, 10, 20], "promoted from third, not re-scored"


def test_no_context_leaves_the_ranking_alone():
    segment = profile(*PRIMARY)
    examples = two_distinct_pieces()
    assert rank(segment, examples) == rank(
        segment, examples, context_piece_id=None
    )


# --------------------------------------------------------------------------
# What one-hand practice looks like to the matcher
# --------------------------------------------------------------------------


def test_a_right_hand_drill_prefers_the_right_hand_example():
    """The player drills one hand at a time. The register term is what tells a
    right-hand drill of a passage from a left-hand one, and it has to earn its
    weight by getting this right."""
    right_hand = [72, 74, 76, 77, 79]
    left_hand = [45, 48, 52, 45, 48]
    examples = [
        Example(1, piece_id=10, fingerprint=fingerprint(notes(right_hand), attack_window_ms=WINDOW)),
        Example(2, piece_id=20, fingerprint=fingerprint(notes(left_hand), attack_window_ms=WINDOW)),
    ]
    # Drilled slowly, so the tempo term is actively unhelpful — which is the point.
    drilled = fingerprint(notes(right_hand, spacing_ms=600), attack_window_ms=WINDOW)
    ranked = rank(drilled, examples)
    assert ranked[0].piece_id == 10
    assert ranked[0].register > ranked[1].register


def test_the_shipped_weights_keep_the_tempo_term_small():
    """Measured, not preferred: on drilled sections a heavy tempo term cost more
    correct answers than it won. See tools/measure_autotag.py."""
    assert DEFAULT_WEIGHTS.pitch_class >= 0.70
    assert DEFAULT_WEIGHTS.tempo <= 0.15
