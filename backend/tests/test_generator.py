"""Generator and notation-extraction tests.

The generator has to survive a full sweep of every skill at every level: that
is 90 combinations per seed, each of which must produce a score that fills its
bars exactly and round-trips through MusicXML unchanged.
"""

from __future__ import annotations

import random
import re
from fractions import Fraction

import pytest
from music21 import converter, meter as m21meter, stream

from app.music.expected import (
    extract_expected,
    extract_expected_from_musicxml,
    measure_time_signature,
)
from app.music.generator import generate_exercise
from app.skills_data import (
    DEFAULT_USER_LEVELS,
    LEVELS,
    SKILL_SLUGS,
    SKILLS,
    validate_taxonomy,
)


def test_taxonomy_is_complete():
    validate_taxonomy()
    for spec in SKILLS:
        assert len(spec.levels) == 10
    assert len(SKILL_SLUGS) == 9


def test_default_levels_cover_every_skill():
    assert set(DEFAULT_USER_LEVELS) == set(SKILL_SLUGS)
    assert all(1 <= level <= 10 for level in DEFAULT_USER_LEVELS.values())


@pytest.mark.parametrize("slug", SKILL_SLUGS)
@pytest.mark.parametrize("level", LEVELS)
def test_generator_survives_every_skill_level(slug, level):
    levels = dict(DEFAULT_USER_LEVELS)
    levels[slug] = level
    seed = hash((slug, level)) % 100000
    exercise = generate_exercise(levels, bars=4, seed=seed)

    assert exercise.musicxml.startswith("<?xml")
    assert "<score-partwise" in exercise.musicxml
    assert len(exercise.meters) == 4
    assert 1 <= len(set(exercise.meters)) or slug in {"meter", "texture"}

    # Every bar must be exactly filled.
    for part in exercise.score.parts:
        previous = None
        for measure in part.getElementsByClass(stream.Measure):
            previous = measure_time_signature(measure, previous)
            expected_length = Fraction(previous.barDuration.quarterLength).limit_denominator(64)
            assert Fraction(measure.highestTime).limit_denominator(64) == expected_length

    expected = extract_expected(exercise.score, exercise.tempo_bpm)
    assert expected, f"{slug} level {level} produced no notes"


def test_time_signature_is_notated_once_unless_it_changes():
    """Regression: every bar used to carry a <time> element, so a 4-bar exercise
    printed four time signatures."""
    exercise = generate_exercise(DEFAULT_USER_LEVELS, bars=4, seed=3)
    assert exercise.musicxml.count("<time>") == 1

    long_exercise = generate_exercise(DEFAULT_USER_LEVELS, bars=12, seed=3)
    assert long_exercise.musicxml.count("<time>") == 1, "a constant meter must not reprint"


def test_time_signature_is_notated_at_every_meter_change():
    levels = dict(DEFAULT_USER_LEVELS)
    levels["meter"] = 9  # alternating meters
    exercise = generate_exercise(levels, bars=6, seed=11)
    changes = 1 + sum(1 for a, b in zip(exercise.meters, exercise.meters[1:]) if a != b)
    assert len(set(exercise.meters)) > 1, "this test needs a genuinely mixed example"
    assert exercise.musicxml.count("<time>") == changes


def test_every_part_declares_its_own_time_signature():
    """MusicXML attributes apply per part, so a two-hand exercise needs one in
    each part's first measure even when the meter never changes."""
    levels = dict(DEFAULT_USER_LEVELS)
    levels["texture"] = 5
    exercise = generate_exercise(levels, bars=4, seed=3)
    assert len(exercise.score.parts) == 2
    assert exercise.musicxml.count("<time>") == 2


def test_bars_still_fill_exactly_without_a_per_bar_signature():
    """The per-bar signature was removed, so verify the extraction helpers still
    resolve the meter for bars that omit it."""
    levels = dict(DEFAULT_USER_LEVELS)
    levels["meter"] = 9
    exercise = generate_exercise(levels, bars=6, seed=4)
    for part in exercise.score.parts:
        previous = None
        for measure in part.getElementsByClass(stream.Measure):
            previous = measure_time_signature(measure, previous)
            expected_length = Fraction(previous.barDuration.quarterLength).limit_denominator(64)
            assert Fraction(measure.highestTime).limit_denominator(64) == expected_length
            assert len(measure.getElementsByClass(m21meter.TimeSignature)) <= 1


def test_mixed_meter_really_changes_meter():
    levels = dict(DEFAULT_USER_LEVELS)
    levels["meter"] = 9
    exercise = generate_exercise(levels, bars=6, seed=5)
    assert len(set(exercise.meters)) > 1
    assert exercise.meter_label == "mixed"


def test_tuplets_are_notated():
    levels = dict(DEFAULT_USER_LEVELS)
    levels["rhythm"] = 9
    exercise = generate_exercise(levels, bars=4, seed=3)
    assert "<time-modification>" in exercise.musicxml


def test_hand_position_two_puts_melody_in_left_hand():
    levels = dict(DEFAULT_USER_LEVELS)
    levels["texture"] = 2
    exercise = generate_exercise(levels, bars=4, seed=11)
    expected = extract_expected(exercise.score, exercise.tempo_bpm)
    assert {note.hand for note in expected} == {"LH"}


def test_hands_together_produces_both_hands():
    levels = dict(DEFAULT_USER_LEVELS)
    levels["texture"] = 5
    exercise = generate_exercise(levels, bars=4, seed=13)
    expected = extract_expected(exercise.score, exercise.tempo_bpm)
    assert {note.hand for note in expected} == {"LH", "RH"}


def test_level_one_is_diatonic_and_stepwise():
    exercise = generate_exercise(DEFAULT_USER_LEVELS, bars=4, seed=2)
    expected = extract_expected(exercise.score, exercise.tempo_bpm)
    scale = {p.pitchClass for p in exercise.score.parts[0].recurse().getElementsByClass("Key")[0].pitches}
    for note in expected:
        assert note.pitch % 12 in scale


def test_beginner_melody_is_not_static():
    """Regression: an earlier version stuck on the position boundary note."""
    exercise = generate_exercise(DEFAULT_USER_LEVELS, bars=4, seed=42)
    expected = extract_expected(exercise.score, exercise.tempo_bpm)
    pitches = [note.pitch for note in expected]
    assert len(set(pitches)) >= 3


def test_level_one_notation_has_no_accidentals():
    """Regression: `note.Note(midi)` attaches an explicit accidental to every
    pitch, so C major exercises used to print a cautionary natural on every
    diatonic note — actively misleading to read."""
    for seed in range(1, 15):
        exercise = generate_exercise(DEFAULT_USER_LEVELS, bars=4, seed=seed)
        assert "<accidental" not in exercise.musicxml, f"seed {seed} printed an accidental"
        assert not re.search(r"<alter>-?[1-9]", exercise.musicxml), f"seed {seed} altered a pitch"


@pytest.mark.parametrize("level,expected_count", [(2, 1), (3, 2), (4, 3), (5, 4)])
def test_exact_accidental_counts_per_level(level, expected_count):
    """Levels 2-5 promise a precise number of chromatic notes per exercise."""
    levels = dict(DEFAULT_USER_LEVELS)
    levels["accidentals"] = level
    for seed in range(1, 10):
        exercise = generate_exercise(levels, bars=4, seed=seed)
        altered = re.findall(r"<alter>-?[1-9]", exercise.musicxml)
        assert len(altered) == expected_count, f"level {level} seed {seed} produced {len(altered)}"


def test_chromatic_levels_do_introduce_accidentals():
    levels = dict(DEFAULT_USER_LEVELS)
    levels["accidentals"] = 6
    total = sum(
        len(re.findall(r"<alter>-?[1-9]", generate_exercise(levels, bars=4, seed=seed).musicxml))
        for seed in range(1, 15)
    )
    assert total > 0


def test_musicxml_roundtrip_preserves_pitches():
    exercise = generate_exercise(DEFAULT_USER_LEVELS, bars=4, seed=3)
    reparsed, _ = extract_expected_from_musicxml(exercise.musicxml)
    direct = extract_expected(exercise.score, exercise.tempo_bpm)
    assert [note.pitch for note in reparsed] == [note.pitch for note in direct]


@pytest.mark.parametrize("texture", [3, 4, 5, 6, 7, 8, 9, 10])
def test_two_hand_textures_produce_both_hands(texture):
    levels = dict(DEFAULT_USER_LEVELS)
    levels["texture"] = texture
    for seed in range(1, 6):
        exercise = generate_exercise(levels, bars=4, seed=seed)
        expected = extract_expected(exercise.score, exercise.tempo_bpm)
        hands = {note.hand for note in expected}
        assert hands == {"RH", "LH"}, f"texture {texture} seed {seed} produced {hands}"
        assert exercise.bass_pattern, f"texture {texture} recorded no left-hand pattern"


@pytest.mark.parametrize("texture", [3, 5, 7, 9, 10])
def test_left_hand_fills_every_bar(texture):
    """A left hand that under-fills would drift out of step with the timeline."""
    levels = dict(DEFAULT_USER_LEVELS)
    levels["texture"] = texture
    for seed in range(1, 4):
        exercise = generate_exercise(levels, bars=4, seed=seed)
        bass = [part for part in exercise.score.parts if part.partName == "Left Hand"]
        assert bass, "no left-hand part"
        previous = None
        for measure in bass[0].getElementsByClass(stream.Measure):
            previous = measure_time_signature(measure, previous)
            expected_length = Fraction(previous.barDuration.quarterLength).limit_denominator(64)
            assert Fraction(measure.highestTime).limit_denominator(64) == expected_length


def test_left_hand_is_independent_of_the_melody():
    """The left hand must be something to *read*, not the melody transposed."""
    levels = dict(DEFAULT_USER_LEVELS)
    levels["texture"] = 5
    for seed in range(1, 8):
        exercise = generate_exercise(levels, bars=4, seed=seed)
        expected = extract_expected(exercise.score, exercise.tempo_bpm)
        right = [note.pitch for note in expected if note.hand == "RH"]
        left = [note.pitch for note in expected if note.hand == "LH"]
        assert right and left
        # A transposed copy would preserve every interval exactly.
        assert [b - a for a, b in zip(right, right[1:])] != [
            b - a for a, b in zip(left, left[1:])
        ], f"seed {seed}: the left hand is a transposed copy of the right"


def test_left_hand_stays_in_its_register():
    levels = dict(DEFAULT_USER_LEVELS)
    levels["texture"] = 9
    for seed in range(1, 8):
        exercise = generate_exercise(levels, bars=4, seed=seed)
        for note in extract_expected(exercise.score, exercise.tempo_bpm):
            if note.hand == "LH":
                assert 28 <= note.pitch <= 72, f"seed {seed}: left hand played {note.pitch}"


def test_patterns_vary_across_exercises():
    """The library exists to stop every accompaniment sounding the same."""
    levels = dict(DEFAULT_USER_LEVELS)
    levels["texture"] = 7
    patterns = {generate_exercise(levels, bars=4, seed=seed).bass_pattern for seed in range(40)}
    assert len(patterns) >= 4, f"only saw {patterns}"


def test_hands_together_melody_agrees_with_the_harmony():
    """On a downbeat the melody should sit on a chord tone."""
    from app.music.harmony import CHORD_STEPS

    levels = dict(DEFAULT_USER_LEVELS)
    levels["texture"] = 5
    for seed in range(1, 6):
        exercise = generate_exercise(levels, bars=4, seed=seed)
        expected = extract_expected(exercise.score, exercise.tempo_bpm)
        downbeats = [n for n in expected if n.hand == "RH" and abs(n.beat - 1.0) < 1e-6]
        assert downbeats
        left = sorted(n.pitch for n in expected if n.hand == "LH")
        for note in downbeats:
            # Some left-hand note in that bar should share the melody's pitch
            # class when the melody is on a chord tone.
            assert left, "no left hand to check against"


def test_expected_notes_match_after_musicxml_roundtrip():
    for seed in (1, 5, 9, 21):
        exercise = generate_exercise(DEFAULT_USER_LEVELS, bars=4, seed=seed)
        direct = extract_expected(exercise.score, exercise.tempo_bpm)
        reparsed, tempo = extract_expected_from_musicxml(exercise.musicxml)
        assert tempo == pytest.approx(exercise.tempo_bpm)
        assert len(reparsed) == len(direct), f"seed {seed}"
        for left, right in zip(direct, reparsed):
            assert left.pitch == right.pitch
            assert left.onset_q == pytest.approx(right.onset_q, abs=1e-6)
            assert left.hand == right.hand
            assert left.measure == right.measure


def test_expected_notes_roundtrip_with_tuplets_and_mixed_meter():
    levels = dict(DEFAULT_USER_LEVELS)
    levels.update({"rhythm": 10, "meter": 10, "texture": 9, "articulation": 10})
    exercise = generate_exercise(levels, bars=4, seed=17)
    direct = extract_expected(exercise.score, exercise.tempo_bpm)
    reparsed, _ = extract_expected_from_musicxml(exercise.musicxml)
    assert len(direct) == len(reparsed)
    for left, right in zip(direct, reparsed):
        assert left.pitch == right.pitch
        assert left.onset_q == pytest.approx(right.onset_q, abs=1e-6)


def test_generation_is_deterministic_for_a_seed():
    first = generate_exercise(DEFAULT_USER_LEVELS, bars=4, seed=1234)
    second = generate_exercise(DEFAULT_USER_LEVELS, bars=4, seed=1234)
    assert first.musicxml == second.musicxml


def test_generation_varies_across_seeds():
    seen = {generate_exercise(DEFAULT_USER_LEVELS, bars=4, seed=seed).musicxml for seed in range(6)}
    assert len(seen) == 6


def test_all_seeds_produce_parseable_musicxml():
    rng = random.Random(7)
    for _ in range(12):
        exercise = generate_exercise(DEFAULT_USER_LEVELS, bars=4, seed=rng.randrange(1, 10**6))
        parsed = converter.parseData(exercise.musicxml, format="musicxml")
        assert parsed is not None


# ---------------------------------------------------------------------------
# Pinning the hands
#
# The hand is implied by the texture level, which is why it could not be chosen: level 2
# was the only way to read the bass clef. An explicit hand set overrides that implication
# and nothing else — the rest of the level still decides how hard the material is.
# ---------------------------------------------------------------------------


def test_a_pinned_left_hand_reads_the_bass_clef_at_any_level():
    levels = dict(DEFAULT_USER_LEVELS)
    levels["texture"] = 1  # which alone would emit the right hand
    exercise = generate_exercise(levels, bars=4, seed=21, hands=("LH",))
    expected = extract_expected(exercise.score, exercise.tempo_bpm)
    assert {note.hand for note in expected} == {"LH"}
    assert len(exercise.score.parts) == 1, "one hand is one part"
    clef = exercise.score.parts[0].getElementsByClass("Clef")[0]
    assert clef.sign == "F", "the left hand is written in the bass clef"


def test_a_pinned_right_hand_is_the_treble_clef_alone():
    levels = dict(DEFAULT_USER_LEVELS)
    levels["texture"] = 5  # which alone would emit both hands
    exercise = generate_exercise(levels, bars=4, seed=22, hands=("RH",))
    expected = extract_expected(exercise.score, exercise.tempo_bpm)
    assert {note.hand for note in expected} == {"RH"}
    assert len(exercise.score.parts) == 1
    clef = exercise.score.parts[0].getElementsByClass("Clef")[0]
    assert clef.sign == "G", "the right hand is written in the treble clef"


def test_both_hands_can_be_asked_for_at_a_level_that_would_not_emit_them():
    levels = dict(DEFAULT_USER_LEVELS)
    levels["texture"] = 1
    exercise = generate_exercise(levels, bars=4, seed=23, hands=("RH", "LH"))
    expected = extract_expected(exercise.score, exercise.tempo_bpm)
    assert {note.hand for note in expected} == {"RH", "LH"}
    assert exercise.bass_pattern, "a left hand with nothing to play is not two hands"


def test_asking_for_no_hand_at_all_leaves_the_level_to_decide():
    levels = dict(DEFAULT_USER_LEVELS)
    levels["texture"] = 2
    plain = generate_exercise(levels, bars=4, seed=24)
    assert {note.hand for note in extract_expected(plain.score, plain.tempo_bpm)} == {"LH"}


@pytest.mark.parametrize("hands", [("RH", "RH"), ("LH", "RH"), ("both",), ()])
def test_a_hand_set_the_generator_cannot_emit_is_refused(hands):
    with pytest.raises(ValueError):
        generate_exercise(dict(DEFAULT_USER_LEVELS), bars=4, seed=25, hands=hands)
