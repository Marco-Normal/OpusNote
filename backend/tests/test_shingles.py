"""Tempo-invariant local content features, and containment over them."""

from __future__ import annotations

from app.practice.shingles import containment, features, idf, pooled
from app.practice.sessionize import Note


def line(onsets_ms, pitches, *, duration_ms: int = 100) -> list[Note]:
    return [Note(onset, pitch, 70, duration_ms, 0) for onset, pitch in zip(onsets_ms, pitches)]


PHRASE = [0, 200, 400, 600, 800, 1000, 1200, 1400]
PITCHES = [60, 62, 64, 65, 67, 69, 71, 72]


def test_a_fragment_is_a_subset_of_the_whole() -> None:
    """This is the property that makes the score survive re-cutting."""
    whole = features(line(PHRASE, PITCHES))
    fragment = features(line(PHRASE[:5], PITCHES[:5]))
    assert set(fragment) <= set(whole)


def test_the_same_passage_at_half_speed_is_the_same_features() -> None:
    """Tempo must not be in the key. Putting the inter-onset bin back in cost 7-15 points."""
    fast = features(line(PHRASE, PITCHES))
    slow = features(line([onset * 2 for onset in PHRASE], PITCHES))
    assert fast == slow


def test_a_transposed_passage_is_a_different_piece() -> None:
    """Register and pitch class both carry information; only rhythm is normalised away."""
    assert features(line(PHRASE, PITCHES)) != features(line(PHRASE, [p + 1 for p in PITCHES]))


def test_pooling_adds_the_segments_of_one_piece() -> None:
    one = features(line(PHRASE, PITCHES))
    two = features(line(PHRASE, PITCHES))
    assert pooled([one, two])["n", "R", 0] == one["n", "R", 0] * 2


def test_containment_of_a_subset_is_one() -> None:
    whole = features(line(PHRASE, PITCHES))
    fragment = features(line(PHRASE[:5], PITCHES[:5]))
    weights = idf({1: whole, 2: features(line(PHRASE, [p + 7 for p in PITCHES]))})
    assert containment(fragment, whole, weights) == 1.0


def test_containment_of_unrelated_material_is_low() -> None:
    """Weights come from a library, not from one piece.

    With a single signature every feature weighs the same, a query's unmatched features fall
    out of the denominator entirely, and two phrases sharing only a couple of pitch classes
    score as if one contained the other. That is a property of IDF rather than of the
    material, and the app always computes it over the pieces that exist — so this measures
    the metric the matcher uses.
    """
    home = features(line(PHRASE, PITCHES))
    weights = idf(
        {
            1: home,
            2: features(line(PHRASE, [p + 6 for p in PITCHES])),
            3: features(line(PHRASE, [p - 5 for p in PITCHES])),
        }
    )
    unrelated = features(line(PHRASE, [p + 6 for p in PITCHES]))
    assert containment(unrelated, home, weights) < 0.5


def test_an_empty_query_contains_nothing() -> None:
    weights = idf({1: features(line(PHRASE, PITCHES))})
    assert containment({}, features(line(PHRASE, PITCHES)), weights) == 0.0
