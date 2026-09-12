"""The left-hand pattern library.

A named, individually testable catalogue of the accompaniment figures that
actually appear in piano music, replacing the five hard-coded styles that used to
live inside the generator.

Each pattern is a pure function from a :class:`BassContext` to a list of
:class:`~app.music.events.Event`, and every one of them must fill the bar exactly
and stay inside the left hand's register — both asserted in the tests rather than
assumed.

Patterns are selected by meter and by the ``texture`` skill level, so a beginner
meets sustained roots and a learner at level 7 meets stride bass and walking
lines. Several patterns are meter-specific because the figure *is* the meter:
a waltz bass is meaningless outside triple time.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable, Iterable, Sequence

from .events import Event, events_from_cells, fill_bar, fit_to_length, pulse_durations
from .harmony import FIFTH, ROOT, THIRD, nearest_chord_tone
from .melody import generate_degrees
from .tonality import Tonality

#: Eighth note, the subdivision most broken-chord figures are built from.
EIGHTH = Fraction(1, 2)
#: One octave in scale degrees.
OCTAVE = 7
#: A tenth above the root, the wide romantic voicing.
TENTH = 9
#: The top of the left hand's comfortable register. A figure that would exceed
#: this is moved down an octave as a whole, so its intervals stay intact.
LH_CEILING = 72

SIMPLE_METERS = ("4/4", "3/4", "2/4", "2/2")
COMPOUND_METERS = ("6/8", "9/8", "12/8")
TRIPLE_METERS = ("3/4", "3/8", "9/8", "3/2")
DUPLE_METERS = ("2/4", "4/4", "2/2", "12/8")


@dataclass
class BassContext:
    """Everything a pattern may need to build one bar of accompaniment."""

    bar_length: Fraction
    beat_unit: Fraction
    meter: str
    tonality: Tonality
    base_midi: int
    chord_degree: int
    next_chord_degree: int
    span: int
    rng: random.Random
    bar_index: int = 0
    #: The melody's current bar — ``mirror`` shadows its rhythm directly.
    melody_events: Sequence[Event] = field(default_factory=tuple)
    #: The melody's previous bar — ``canon`` answers it a bar later.
    previous_melody_events: Sequence[Event] = field(default_factory=tuple)
    #: The previous bar's pitches, for the contour ``countermelody`` moves against.
    melody_pitches: Sequence[int] = field(default_factory=tuple)

    # --- pitch helpers -------------------------------------------------
    def degree(self, offset: int, *, octave_shift: int = 0) -> int:
        return self.tonality.midi_for_degree(
            self.base_midi + 12 * octave_shift, self.chord_degree + offset
        )

    def triad(self, *, octave_shift: int = 0, size: int = 3) -> tuple[int, ...]:
        return self.tonality.chord_midis(
            self.base_midi + 12 * octave_shift, self.chord_degree, size
        )

    # --- rhythm helpers ------------------------------------------------
    def beat_pulses(self) -> list[Fraction]:
        return pulse_durations(self.bar_length, self.beat_unit)

    def half_pulses(self) -> list[Fraction]:
        unit = self.beat_unit * 2
        return pulse_durations(self.bar_length, unit if unit <= self.bar_length else self.bar_length)

    def subdivision(self, unit: Fraction = EIGHTH) -> list[Fraction]:
        return pulse_durations(self.bar_length, unit)


def _single(ctx: BassContext, duration: Fraction, pitch: int) -> Event:
    return Event(duration=duration, pitches=(pitch,))


# --------------------------------------------------------------------------
# Sustained accompaniments
# --------------------------------------------------------------------------


def sustained_root(ctx: BassContext) -> list[Event]:
    """A held root per pulse — the pedal-point bass of early method books."""
    return [_single(ctx, duration, ctx.degree(ROOT)) for duration in ctx.half_pulses()]


def sustained_fifth(ctx: BassContext) -> list[Event]:
    """Root and fifth held in alternation."""
    return [
        _single(ctx, duration, ctx.degree(ROOT if index % 2 == 0 else FIFTH))
        for index, duration in enumerate(ctx.half_pulses())
    ]


def block_chords(ctx: BassContext) -> list[Event]:
    """Root-position triads on every beat — hymnal style."""
    chord = ctx.triad()
    return [Event(duration=duration, pitches=chord) for duration in ctx.beat_pulses()]


# --------------------------------------------------------------------------
# Pulse basses
# --------------------------------------------------------------------------


def root_fifth_pulse(ctx: BassContext) -> list[Event]:
    """Alternating root and fifth on the beat — the ``boom-chick`` bass."""
    return [
        _single(ctx, duration, ctx.degree(ROOT if index % 2 == 0 else FIFTH))
        for index, duration in enumerate(ctx.beat_pulses())
    ]


def march_bass(ctx: BassContext) -> list[Event]:
    """Root on the strong beat, triad on the weak one — an oom-pah march."""
    chord = ctx.triad()
    events: list[Event] = []
    for index, duration in enumerate(ctx.beat_pulses()):
        if index % 2 == 0:
            events.append(_single(ctx, duration, ctx.degree(ROOT)))
        else:
            events.append(Event(duration=duration, pitches=chord))
    return events


def waltz_bass(ctx: BassContext) -> list[Event]:
    """Root on beat one, chord on the remaining beats: the waltz figure."""
    beats = ctx.beat_pulses()
    if not beats:
        return []
    chord = ctx.triad()
    events = [_single(ctx, beats[0], ctx.degree(ROOT))]
    events.extend(Event(duration=duration, pitches=chord) for duration in beats[1:])
    return events


def stride_bass(ctx: BassContext) -> list[Event]:
    """A low root alternating with a mid-register chord — stride piano.

    The wide leap is the point of the figure, so the root is dropped an octave.
    """
    events: list[Event] = []
    chord = ctx.triad()
    for index, duration in enumerate(ctx.beat_pulses()):
        if index % 2 == 0:
            events.append(_single(ctx, duration, ctx.degree(ROOT, octave_shift=-1)))
        else:
            events.append(Event(duration=duration, pitches=chord))
    return events


def tenths(ctx: BassContext) -> list[Event]:
    """Root plus a tenth, held — a wide, Romantic accompaniment."""
    events: list[Event] = []
    for duration in ctx.half_pulses():
        # Both voices sound an octave lower than the chord default so the tenth
        # does not stray into the melody's register.
        events.append(
            Event(
                duration=duration,
                pitches=(ctx.degree(ROOT, octave_shift=-1), ctx.degree(TENTH, octave_shift=-1)),
            )
        )
    return events


# --------------------------------------------------------------------------
# Broken chords and arpeggios
# --------------------------------------------------------------------------


def _figure(ctx: BassContext, steps: Sequence[int]) -> list[Event]:
    pitches = [ctx.degree(step) for step in steps]
    # Shift the whole figure by octaves rather than clamping individual notes:
    # clamping would flatten the intervals the figure is defined by (a broken
    # octave would stop being an octave).
    while max(pitches) > LH_CEILING:
        pitches = [pitch - 12 for pitch in pitches]
    return [
        _single(ctx, duration, pitches[index % len(pitches)])
        for index, duration in enumerate(ctx.subdivision())
    ]


def alberti_bass(ctx: BassContext) -> list[Event]:
    """Root-fifth-third-fifth in eighths — the classical Alberti figure."""
    return _figure(ctx, (ROOT, FIFTH, THIRD, FIFTH))


def murky_bass(ctx: BassContext) -> list[Event]:
    """Compound-meter broken chords: the 6/8 form of the Alberti figure."""
    return _figure(ctx, (ROOT, FIFTH, THIRD, FIFTH))


def broken_chord(ctx: BassContext) -> list[Event]:
    """An ascending root-third-fifth-octave arpeggio, repeating."""
    return _figure(ctx, (ROOT, THIRD, FIFTH, OCTAVE))


def arpeggio_wide(ctx: BassContext) -> list[Event]:
    """A broken chord spanning more than an octave."""
    return _figure(ctx, (ROOT, FIFTH, OCTAVE, TENTH))


def broken_octaves(ctx: BassContext) -> list[Event]:
    """Alternating low root and its octave."""
    return _figure(ctx, (ROOT, OCTAVE))


# --------------------------------------------------------------------------
# Independent lines
# --------------------------------------------------------------------------


def walking_bass(ctx: BassContext) -> list[Event]:
    """Quarter notes: chord tones, then a stepwise approach to the next root.

    The step into the following chord is what makes a walking line sound like it
    is going somewhere rather than merely marking time.
    """
    durations = ctx.beat_pulses()
    if not durations:
        return []

    approach = ctx.next_chord_degree + (1 if ctx.next_chord_degree >= ctx.chord_degree else -1)
    events: list[Event] = []
    for index, duration in enumerate(durations):
        if index == len(durations) - 1 and len(durations) > 1:
            events.append(_single(ctx, duration, ctx.degree(approach - ctx.chord_degree)))
        else:
            step = (ROOT, THIRD, FIFTH)[index % 3]
            events.append(_single(ctx, duration, ctx.degree(step)))
    return events


def canon(ctx: BassContext) -> list[Event]:
    """The left hand echoes the melody's previous bar, an octave or two down.

    Imitation at the bar is a real texture, and it is also the cheapest way to
    make the left hand genuinely *read* rather than predicted.
    """
    source = ctx.previous_melody_events
    if not source:
        return sustained_root(ctx)

    sounding = [event.pitches[0] for event in source if event.pitches]
    if not sounding:
        return sustained_root(ctx)

    # Transpose the phrase by a single octave interval, chosen so it lands in
    # the left hand's register. Lowering each note independently to fit would
    # flatten the melody's contour, which is the one thing an imitation has to
    # preserve to still read as an imitation.
    ceiling = min(ctx.base_midi + 16, LH_CEILING)
    floor = ctx.base_midi - 12
    shift = 0
    for _ in range(6):
        if max(sounding) + shift > ceiling:
            shift -= 12
        elif min(sounding) + shift < floor:
            shift += 12
        else:
            break

    events: list[Event] = []
    for event in source:
        if event.is_rest or not event.pitches:
            events.append(Event(duration=event.duration, rest=True))
            continue
        events.append(
            Event(duration=event.duration, pitches=tuple(sorted({p + shift for p in event.pitches})))
        )
    return fit_to_length(events, ctx.bar_length)


def free_line(ctx: BassContext) -> list[Event]:
    """An independent left-hand line, read rather than predicted.

    Its own register, its own rhythm, and its own stepwise contour: the point is
    that the player cannot guess it from the right hand.
    """
    cells = (
        ((Fraction(1), "n"), (Fraction(1), "n")),
        ((Fraction(2), "n"),),
        ((Fraction(1, 2), "n"), (Fraction(1, 2), "n"), (Fraction(1), "n")),
        ((Fraction(1), "n"), (Fraction(1, 2), "n"), (Fraction(1, 2), "n")),
    )
    cells_for_bar = fill_bar(ctx.bar_length, cells, ctx.rng)
    line_events = events_from_cells(cells_for_bar, ctx.beat_unit)
    degrees = generate_degrees(
        line_events,
        span=max(4, min(8, ctx.span)),
        window_offsets=(0, 3),
        interval_choices=(1, 2, 3),
        arpeggio=False,
        scale_runs=False,
        broken_octaves=False,
        rng=ctx.rng,
        bar_of_event=[0] * len(line_events),
        chord_degrees=[ctx.chord_degree] * len(line_events),
    )
    return [
        Event(
            duration=event.duration,
            pitches=() if event.is_rest else (ctx.tonality.midi_for_degree(ctx.base_midi, degree),),
            rest=event.is_rest,
        )
        for event, degree in zip(line_events, degrees)
    ]


def countermelody(ctx: BassContext) -> list[Event]:
    """A slower line moving against the melody's contour."""
    durations = ctx.half_pulses()
    if not durations:
        return []

    melody_direction = 0
    if len(ctx.melody_pitches) >= 2:
        melody_direction = 1 if ctx.melody_pitches[-1] >= ctx.melody_pitches[0] else -1

    events: list[Event] = []
    degree = ctx.chord_degree
    for index, duration in enumerate(durations):
        if index == 0:
            degree = ctx.chord_degree
        else:
            step = -melody_direction if melody_direction else ctx.rng.choice((-1, 1))
            degree += step * ctx.rng.choice((1, 2))
            degree = nearest_chord_tone(degree, ctx.chord_degree, window=5)
        events.append(_single(ctx, duration, ctx.tonality.midi_for_degree(ctx.base_midi, degree)))
    return events


def mirror_melody(ctx: BassContext) -> list[Event]:
    """Both hands in the same rhythm, the left on chord tones.

    This is the ``hands together in similar rhythm`` texture, where the two hands
    move as one unit rather than the left accompanying.
    """
    if not ctx.melody_events:
        return sustained_root(ctx)

    chord = ctx.degree(ROOT)
    events: list[Event] = []
    for index, event in enumerate(ctx.melody_events):
        if event.is_rest:
            events.append(Event(duration=event.duration, rest=True))
            continue
        pitch = chord if index % 2 == 0 else ctx.degree(FIFTH)
        events.append(_single(ctx, event.duration, pitch))
    return fit_to_length(events, ctx.bar_length)


# --------------------------------------------------------------------------
# Registry and selection
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BassPattern:
    id: str
    name: str
    description: str
    min_texture: int
    build: Callable[[BassContext], list[Event]]
    #: None means the figure works in any meter.
    meters: tuple[str, ...] | None = None

    def supports(self, meter: str) -> bool:
        return self.meters is None or meter in self.meters


PATTERNS: tuple[BassPattern, ...] = (
    BassPattern(
        "sustained_root",
        "Sustained root",
        "A held root note per pulse — the pedal-point bass of early method books.",
        3,
        sustained_root,
    ),
    BassPattern(
        "sustained_fifth",
        "Sustained root and fifth",
        "Root and fifth held in alternation.",
        3,
        sustained_fifth,
    ),
    BassPattern(
        "block_chords",
        "Block chords",
        "Root-position triads on every beat, hymnal style.",
        3,
        block_chords,
    ),
    BassPattern(
        "root_fifth_pulse",
        "Root-fifth pulse",
        "Alternating root and fifth on the beat: the boom-chick bass.",
        4,
        root_fifth_pulse,
    ),
    BassPattern(
        "march_bass",
        "March bass",
        "Root on the strong beat, triad on the weak one — an oom-pah march.",
        4,
        march_bass,
        DUPLE_METERS,
    ),
    BassPattern(
        "waltz_bass",
        "Waltz bass",
        "Root on beat one, chord on the remaining beats.",
        4,
        waltz_bass,
        TRIPLE_METERS,
    ),
    BassPattern(
        "mirror",
        "Hands in similar rhythm",
        "Both hands share a rhythm, the left on chord tones.",
        4,
        mirror_melody,
    ),
    BassPattern(
        "alberti",
        "Alberti bass",
        "Root-fifth-third-fifth in eighths — the classical Alberti figure.",
        5,
        alberti_bass,
        SIMPLE_METERS,
    ),
    BassPattern(
        "murky_bass",
        "Compound broken chords",
        "The 6/8 form of the Alberti figure, grouped in threes.",
        5,
        murky_bass,
        COMPOUND_METERS,
    ),
    BassPattern(
        "broken_chord",
        "Broken chord",
        "An ascending root-third-fifth-octave arpeggio, repeating.",
        5,
        broken_chord,
    ),
    BassPattern(
        "broken_octaves",
        "Broken octaves",
        "Alternating low root and its octave.",
        6,
        broken_octaves,
    ),
    BassPattern(
        "walking_bass",
        "Walking bass",
        "Chord tones on the beat, stepping into the next chord.",
        6,
        walking_bass,
    ),
    BassPattern(
        "arpeggio_wide",
        "Wide arpeggio",
        "A broken chord spanning more than an octave.",
        7,
        arpeggio_wide,
    ),
    BassPattern(
        "tenths",
        "Tenths",
        "Root plus a tenth, held — a wide, Romantic accompaniment.",
        7,
        tenths,
    ),
    BassPattern(
        "stride_bass",
        "Stride bass",
        "A low root alternating with a mid-register chord.",
        7,
        stride_bass,
        ("4/4", "2/2", "4/2"),
    ),
    BassPattern(
        "free_line",
        "Free left-hand line",
        "An independent line with its own register and contour.",
        7,
        free_line,
    ),
    BassPattern(
        "countermelody",
        "Countermelody",
        "A slower line moving against the melody's contour.",
        8,
        countermelody,
    ),
    BassPattern(
        "canon",
        "Canon",
        "The left hand echoes the melody's previous bar in a low register.",
        8,
        canon,
    ),
)

PATTERNS_BY_ID: dict[str, BassPattern] = {pattern.id: pattern for pattern in PATTERNS}


def select_pattern(
    meters: Sequence[str],
    texture_level: int,
    rng: random.Random,
    *,
    prefer: Iterable[str] = (),
) -> BassPattern:
    """Choose a pattern the meter and the texture level allow.

    ``prefer`` names patterns implied by the texture description itself — the
    imitation texture should actually produce imitation — and is treated as a
    strong hint rather than a guarantee, so the same exercise type does not
    always sound identical.
    """
    wanted = tuple(meters) or ("4/4",)
    candidates = [
        pattern
        for pattern in PATTERNS
        if pattern.min_texture <= texture_level
        # One figure per exercise, so it has to suit every bar — otherwise a
        # waltz bass would be asked to play in 4/4 halfway through.
        and all(pattern.supports(meter) for meter in wanted)
    ]
    if not candidates:
        return PATTERNS_BY_ID["sustained_root"]

    preferred = [pattern for pattern in candidates if pattern.id in set(prefer)]
    if preferred and rng.random() < 0.75:
        return rng.choice(preferred)
    return rng.choice(candidates)


def pattern_catalogue() -> list[dict[str, object]]:
    """The library as plain data, for the API and for documentation."""
    return [
        {
            "id": pattern.id,
            "name": pattern.name,
            "description": pattern.description,
            "min_texture": pattern.min_texture,
            "meters": list(pattern.meters) if pattern.meters else None,
        }
        for pattern in PATTERNS
    ]
