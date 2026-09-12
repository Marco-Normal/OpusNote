"""Left-hand pattern library tests.

The roadmap's acceptance for this slice is explicit: every pattern must be
unit-tested for exact bar fill and for staying in the left hand's register. Both
are asserted for every pattern in every meter it claims to support, rather than
spot-checked, because a pattern that under-fills a bar produces a score that
silently disagrees with the expected-note timeline.
"""

from __future__ import annotations

import random
from fractions import Fraction

import pytest

from app.music.bass_patterns import (
    PATTERNS,
    PATTERNS_BY_ID,
    BassContext,
    pattern_catalogue,
    select_pattern,
)
from app.music.events import Event
from app.music.tonality import Tonality

#: One bar length and beat unit per meter the library claims to support, taken
#: from music21 rather than hand-computed so the tests cannot drift from it.
from music21 import meter as m21meter

SUPPORTED_METERS = ("4/4", "3/4", "2/4", "2/2", "6/8", "9/8", "12/8", "3/8", "7/8", "5/4")

#: The register a left hand can comfortably cover, in MIDI numbers.
LH_LOW = 28  # E1
LH_HIGH = 72  # C5 — generous, but a pattern that needs more is a bug

ALL_CHORDS = tuple(range(7))


def bar_shape(meter: str) -> tuple[Fraction, Fraction]:
    ts = m21meter.TimeSignature(meter)
    return (
        Fraction(ts.barDuration.quarterLength).limit_denominator(64),
        Fraction(ts.beatDuration.quarterLength).limit_denominator(64),
    )


def make_context(
    meter: str,
    *,
    chord: int = 0,
    next_chord: int = 4,
    span: int = 8,
    seed: int = 1,
    melody: bool = True,
) -> BassContext:
    bar_length, beat_unit = bar_shape(meter)
    tonality = Tonality("C")
    melody_events = (
        [Event(duration=Fraction(1), pitches=(72,)), Event(duration=Fraction(1), pitches=(74,))]
        if melody
        else []
    )
    return BassContext(
        bar_length=bar_length,
        beat_unit=beat_unit,
        meter=meter,
        tonality=tonality,
        base_midi=tonality.base_midi("LH"),
        chord_degree=chord,
        next_chord_degree=next_chord,
        span=span,
        rng=random.Random(seed),
        melody_events=melody_events,
        previous_melody_events=melody_events,
        melody_pitches=(72, 74),
    )


def applicable_cases(pattern) -> list[tuple[str, int]]:
    """Every (meter, chord) pairing this pattern claims to handle."""
    meters = pattern.meters or SUPPORTED_METERS
    return [(meter, chord) for meter in meters for chord in ALL_CHORDS]


def test_catalogue_is_not_trivially_small():
    """The point of the slice was breadth, not three figures."""
    assert len(PATTERNS) >= 15
    ids = [pattern.id for pattern in PATTERNS]
    assert len(ids) == len(set(ids)), "pattern ids must be unique"
    for pattern in PATTERNS:
        assert pattern.description.strip()
        assert 1 <= pattern.min_texture <= 10


def test_catalogue_serialises_for_the_api():
    catalogue = pattern_catalogue()
    assert len(catalogue) == len(PATTERNS)
    assert all(isinstance(item["id"], str) for item in catalogue)


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.id)
def test_every_pattern_fills_its_bar_exactly(pattern):
    for meter, chord in applicable_cases(pattern):
        context = make_context(meter, chord=chord, next_chord=(chord + 4) % 7)
        events = pattern.build(context)
        total = sum((event.duration for event in events), Fraction(0))
        assert total == context.bar_length, (
            f"{pattern.id} in {meter} chord {chord} filled {total}, "
            f"expected {context.bar_length}"
        )


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.id)
def test_every_pattern_stays_in_the_left_hand_register(pattern):
    for meter, chord in applicable_cases(pattern):
        context = make_context(meter, chord=chord, next_chord=(chord + 4) % 7)
        for event in pattern.build(context):
            for pitch in event.pitches:
                assert LH_LOW <= pitch <= LH_HIGH, (
                    f"{pattern.id} in {meter} chord {chord} played {pitch}, "
                    f"outside the left hand's register"
                )


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.id)
def test_every_pattern_is_diatonic(pattern):
    tonality = Tonality("C")
    for meter, chord in applicable_cases(pattern):
        context = make_context(meter, chord=chord, next_chord=(chord + 4) % 7)
        for event in pattern.build(context):
            for pitch in event.pitches:
                assert tonality.is_diatonic_midi(pitch), (
                    f"{pattern.id} produced the non-diatonic pitch {pitch}"
                )


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.id)
def test_every_pattern_produces_something(pattern):
    for meter, chord in applicable_cases(pattern):
        context = make_context(meter, chord=chord, next_chord=(chord + 4) % 7)
        events = pattern.build(context)
        assert events, f"{pattern.id} produced no events in {meter}"


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.id)
def test_every_pattern_is_deterministic(pattern):
    meter = (pattern.meters or ("4/4",))[0]
    first = pattern.build(make_context(meter, seed=99))
    second = pattern.build(make_context(meter, seed=99))
    assert [(e.duration, e.pitches) for e in first] == [(e.duration, e.pitches) for e in second]


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.id)
def test_every_pattern_survives_every_tonality(pattern):
    """Keys with many accidentals must not push the left hand out of register."""
    for key_name in ("C", "F#", "Gb", "Cb", "bb", "f#"):
        bar_length, beat_unit = bar_shape("4/4")
        tonality = Tonality(key_name)
        context = BassContext(
            bar_length=bar_length,
            beat_unit=beat_unit,
            meter="4/4",
            tonality=tonality,
            base_midi=tonality.base_midi("LH"),
            chord_degree=0,
            next_chord_degree=4,
            span=8,
            rng=random.Random(3),
            melody_events=[Event(duration=Fraction(1), pitches=(60,))],
            previous_melody_events=[Event(duration=Fraction(1), pitches=(60,))],
            melody_pitches=(60,),
        )
        events = pattern.build(context)
        assert sum((e.duration for e in events), Fraction(0)) == bar_length
        for event in events:
            for pitch in event.pitches:
                assert LH_LOW <= pitch <= LH_HIGH, f"{pattern.id} in {key_name}: {pitch}"


# --------------------------------------------------------------------------
# Figure-specific checks: these are what make the names mean something
# --------------------------------------------------------------------------


def test_alberti_is_root_fifth_third_fifth():
    context = make_context("4/4", chord=0)
    pitches = [event.pitches[0] for event in PATTERNS_BY_ID["alberti"].build(context)]
    root, third, fifth = context.degree(0), context.degree(2), context.degree(4)
    assert pitches[:4] == [root, fifth, third, fifth]
    assert len(pitches) == 8, "a 4/4 bar of Alberti eighths has eight notes"


def test_murky_bass_is_the_compound_meter_form():
    context = make_context("6/8", chord=0)
    pitches = [event.pitches[0] for event in PATTERNS_BY_ID["murky_bass"].build(context)]
    assert len(pitches) == 6, "a 6/8 bar of broken-chord eighths has six notes"
    assert pitches[0] == context.degree(0)


def test_waltz_bass_has_root_then_two_chords():
    context = make_context("3/4", chord=0)
    events = PATTERNS_BY_ID["waltz_bass"].build(context)
    assert len(events) == 3
    assert len(events[0].pitches) == 1, "beat one is a single root"
    assert len(events[1].pitches) == 3 and len(events[2].pitches) == 3, "beats two and three are chords"


def test_march_bass_alternates_root_and_chord():
    context = make_context("4/4", chord=0)
    events = PATTERNS_BY_ID["march_bass"].build(context)
    assert [len(event.pitches) for event in events] == [1, 3, 1, 3]


def test_stride_bass_leaps_between_registers():
    context = make_context("4/4", chord=0)
    events = PATTERNS_BY_ID["stride_bass"].build(context)
    low = events[0].pitches[0]
    chord = events[1].pitches
    assert all(pitch > low for pitch in chord), "the chord must sit above the bass note"
    assert chord[0] - low >= 12, "stride is defined by its wide leap"


def test_broken_octaves_really_are_octaves():
    context = make_context("4/4", chord=0)
    pitches = [event.pitches[0] for event in PATTERNS_BY_ID["broken_octaves"].build(context)]
    for low, high in zip(pitches[::2], pitches[1::2]):
        assert high - low == 12


def test_walking_bass_steps_into_the_next_chord():
    context = make_context("4/4", chord=0, next_chord=3)
    events = PATTERNS_BY_ID["walking_bass"].build(context)
    assert len(events) == 4, "one note per quarter"
    final = events[-1].pitches[0]
    target = context.degree(3)
    assert abs(final - target) <= 4, "the last note should approach the next chord"


def test_canon_answers_the_melody_an_octave_lower():
    context = make_context("4/4", chord=0)
    events = PATTERNS_BY_ID["canon"].build(context)
    sounding = [event for event in events if event.pitches]
    # The phrase is transposed as a unit, so the melodic shape survives.
    answered = [event.pitches[0] for event in sounding]
    assert answered[:2] == [60, 62], f"a twelfth below the melody, got {answered}"
    assert answered[1] - answered[0] == 2, "the interval from the melody is preserved"
    assert all(pitch < 72 for pitch in (event.pitches[0] for event in sounding))
    # The two-note melody occupies half the bar, so the rest is padded out.
    assert any(event.is_rest for event in events), "a short melody must be padded to the bar"
    assert sum((e.duration for e in events), Fraction(0)) == context.bar_length


def test_canon_falls_back_when_there_is_nothing_to_imitate():
    context = make_context("4/4", chord=0, melody=False)
    events = PATTERNS_BY_ID["canon"].build(context)
    assert sum((e.duration for e in events), Fraction(0)) == context.bar_length


def test_tenths_are_tenths():
    context = make_context("4/4", chord=0)
    for event in PATTERNS_BY_ID["tenths"].build(context):
        low, high = event.pitches
        assert high > low
        # A tenth is 16 semitones in a diatonic scale (up to 17 in minor).
        assert 15 <= high - low <= 17


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


def test_selection_respects_the_meter():
    for seed in range(40):
        pattern = select_pattern(["3/4"], 10, random.Random(seed))
        assert pattern.supports("3/4"), f"{pattern.id} does not support 3/4"


def test_selection_respects_the_texture_level():
    for seed in range(40):
        pattern = select_pattern(["4/4"], 3, random.Random(seed))
        assert pattern.min_texture <= 3, f"{pattern.id} needs texture {pattern.min_texture}"


def test_selection_only_picks_patterns_that_suit_every_bar():
    """A waltz bass must never be chosen for a piece that changes to 4/4."""
    mixed = ["3/4", "4/4"]
    for seed in range(60):
        pattern = select_pattern(mixed, 10, random.Random(seed))
        assert all(pattern.supports(meter) for meter in mixed), pattern.id


def test_selection_produces_variety_at_a_fixed_level():
    chosen = {select_pattern(["4/4"], 7, random.Random(seed)).id for seed in range(60)}
    assert len(chosen) >= 6, f"expected a varied library, got {sorted(chosen)}"


def test_low_textures_stay_simple():
    chosen = {select_pattern(["4/4"], 3, random.Random(seed)).id for seed in range(60)}
    assert chosen <= {"sustained_root", "sustained_fifth", "block_chords"}, chosen


def test_preference_is_honoured_most_of_the_time():
    """The imitation texture should usually actually produce imitation."""
    chosen = [
        select_pattern(["4/4"], 8, random.Random(seed), prefer=("canon",)).id for seed in range(40)
    ]
    assert chosen.count("canon") >= 25, f"canon chosen {chosen.count('canon')}/40"


def test_exotic_meters_only_get_meter_agnostic_patterns():
    """A meter nothing claims must still yield a usable figure — and only from
    the patterns that are not meter-specific."""
    for seed in range(30):
        pattern = select_pattern(["11/16"], 10, random.Random(seed))
        assert pattern.meters is None, f"{pattern.id} is meter-specific"
