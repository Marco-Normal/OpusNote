"""Exercise generation.

Turns a mapping of ``{skill_slug: level}`` into a notated exercise. The unit of
output is :class:`GeneratedExercise`, which carries both the music21 score and
its MusicXML serialisation.

This module is orchestration. The pieces it assembles live next door:

* :mod:`~app.music.events`        — rhythmic events and bar filling
* :mod:`~app.music.tonality`      — scale-degree arithmetic
* :mod:`~app.music.melody`        — the melodic degree walk
* :mod:`~app.music.harmony`       — a chord per bar
* :mod:`~app.music.bass_patterns` — the left-hand accompaniment catalogue

Nothing here knows about Elo or HTTP, so the generator can be replaced by a
curated library or a smarter composer without touching the API.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal, Sequence

from music21 import (
    articulations,
    chord as m21chord,
    clef,
    duration as m21duration,
    dynamics,
    instrument,
    metadata as m21metadata,
    meter as m21meter,
    musicxml,
    note as m21note,
    spanner,
    stream,
    tempo as m21tempo,
)
from music21.duration import Tuplet

from .bass_patterns import BassContext, select_pattern
from .events import Event, events_from_cells, fill_bar
from .harmony import bar_chords
from .melody import apply_accidentals, generate_degrees
from .tonality import Tonality
from ..skills_data import (
    ARTICULATION_LEVELS,
    KEY_LEVELS,
    DEFAULT_USER_LEVELS,
    HAND_POSITION_LEVELS,
    INTERVAL_LEVELS,
    KEY_SIGNATURE_LEVELS,
    METER_LEVELS,
    MIXED_METER_LEVELS,
    RHYTHM_CELLS,
    TEMPO_LEVELS,
    TEXTURE_LEVELS,
)

Hand = Literal["RH", "LH"]
Notated = m21note.Note | m21chord.Chord


@dataclass
class GeneratedExercise:
    score: stream.Score
    musicxml: str
    key_name: str
    meters: list[str]
    tempo_bpm: float
    bars: int
    seed: int
    levels: dict[str, int]
    #: The left-hand figure used, or None for single-hand exercises.
    bass_pattern: str | None = None

    @property
    def meter_label(self) -> str:
        unique = list(dict.fromkeys(self.meters))
        return unique[0] if len(unique) == 1 else "mixed"


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------


def _bar_plan(
    meter_level: int, bars: int, rng: random.Random
) -> tuple[list[str], list[Fraction], list[Fraction]]:
    options = METER_LEVELS[meter_level]
    if meter_level in MIXED_METER_LEVELS and len(options) > 1:
        meters: list[str] = []
        while len(meters) < bars:
            order = list(options)
            rng.shuffle(order)
            meters.extend(order)
        meters = meters[:bars]
        if len(set(meters)) == 1:  # guarantee the example really is mixed
            meters[-1] = options[1] if meters[0] == options[0] else options[0]
    else:
        meters = [rng.choice(options)] * bars

    lengths: list[Fraction] = []
    beat_units: list[Fraction] = []
    for label in meters:
        ts = m21meter.TimeSignature(label)
        lengths.append(Fraction(ts.barDuration.quarterLength).limit_denominator(64))
        beat = Fraction(ts.beatDuration.quarterLength).limit_denominator(64)
        beat_units.append(beat if beat > 0 else Fraction(1))
    return meters, lengths, beat_units


def _make_part(part_id: str, instrument_id: str, part_name: str, clef_obj, key_obj) -> stream.Part:
    """Build a piano part.

    The explicit :class:`~music21.instrument.Instrument` matters: without one,
    music21 invents random UUIDs for both the MusicXML ``part id`` and
    ``score-instrument id`` on every export, which would make otherwise
    identical exercises byte-different.
    """
    part = stream.Part(id=part_id)
    part.partName = part_name
    piano = instrument.Instrument()
    piano.instrumentId = instrument_id
    piano.partId = part_id
    piano.instrumentName = "Piano"
    piano.midiProgram = 0
    part.insert(0, piano)
    part.append(clef_obj)
    part.append(key_obj)
    return part


def _clear_implied_accidentals(element: Notated, tonality: Tonality | None) -> None:
    """Drop accidentals the key signature already supplies.

    ``note.Note(midi_number)`` always sets an explicit accidental (``natural``
    for a plain C, for example). Left alone, music21 prints a cautionary natural
    in front of diatonic notes, which is actively misleading to read.
    Chromatic notes keep their accidental.
    """
    if tonality is None:
        return
    for pitch in element.pitches:
        if tonality.is_diatonic_midi(int(pitch.midi)):
            pitch.accidental = None


def _add_events(
    container: stream.Stream,
    events: Sequence[Event],
    tonality: Tonality | None = None,
) -> list[tuple[Notated, Event]]:
    created: list[tuple[Notated, Event]] = []
    tuplets: dict[int, Tuplet] = {}
    for event in events:
        if not event.pitches:
            container.append(m21note.Rest(quarterLength=event.duration))
            continue
        if len(event.pitches) == 1:
            element: Notated = m21note.Note(event.pitches[0])
        else:
            element = m21chord.Chord(list(event.pitches))
        element.duration = m21duration.Duration(quarterLength=event.duration)
        _clear_implied_accidentals(element, tonality)
        if event.tuplet_group is not None:
            if event.tuplet_group not in tuplets:
                tuplet = Tuplet(number=3, type="eighth")
                tuplet.durationNormal = m21duration.Duration(Fraction(1, 2))
                tuplet.durationActual = m21duration.Duration(Fraction(1, 3))
                tuplets[event.tuplet_group] = tuplet
            element.duration.tuplets = (tuplets[event.tuplet_group],)
        container.append(element)
        created.append((element, event))
    return created


def _annotate_beats(events: Sequence[Event], beat_unit: Fraction) -> Sequence[Event]:
    """Give pattern-generated events their beat position, for accents."""
    position = Fraction(0)
    for event in events:
        event.beat = float(position / beat_unit) + 1.0
        position += event.duration
    return events


def _apply_articulation(
    created: Sequence[tuple[Notated, Event]],
    *,
    level: int,
    rng: random.Random,
    container: stream.Stream,
) -> None:
    params = ARTICULATION_LEVELS[level]
    if not params or not created:
        return

    elements = [element for element, _ in created]

    if params.get("staccato_prob"):
        for element in elements:
            if rng.random() < float(params["staccato_prob"]):
                element.articulations.append(articulations.Staccato())
    if params.get("tenuto_prob"):
        for element in elements:
            if rng.random() < float(params["tenuto_prob"]):
                element.articulations.append(articulations.Tenuto())
    if params.get("accent_strong_beats"):
        for element, event in created:
            if abs(event.beat - 1.0) < 1e-6:
                element.articulations.append(articulations.Accent())

    slur_length = params.get("slur_len")
    if slur_length:
        length = int(slur_length)
        index = 0
        while index + length - 1 < len(elements):
            group = elements[index : index + length]
            for left, right in zip(group, group[1:]):
                try:
                    container.insert(0, spanner.Slur(left, right))
                except Exception:  # pragma: no cover - spanner edge cases
                    pass
            index += length

    dynamic_names = params.get("dynamic")
    if dynamic_names:
        mark = dynamics.Dynamic(rng.choice(tuple(dynamic_names)))
        try:
            container.insert(created[0][0].offset, mark)
        except Exception:  # pragma: no cover
            pass

    if params.get("hairpins") and len(elements) >= 3:
        wedge_class = dynamics.Crescendo if rng.random() < 0.5 else dynamics.Diminuendo
        wedge = wedge_class()
        try:
            wedge.addSpannedElements(elements[0], elements[-1])
            container.insert(elements[0].offset, wedge)
        except Exception:  # pragma: no cover - best effort
            pass


def _inner_voice_events(
    bar_length: Fraction,
    beat_unit: Fraction,
    tonality: Tonality,
    base_midi: int,
    span: int,
    chord_degree: int,
    rng: random.Random,
) -> list[Event]:
    """A slow chord-tone line used as a second voice in the melody hand."""
    unit = beat_unit * 2 if beat_unit * 2 <= bar_length else bar_length
    events: list[Event] = []
    remaining = bar_length
    index = 0
    while remaining > 0:
        step = unit if remaining >= unit else remaining
        degree = chord_degree + (0, 2, 4, 2)[index % 4]
        events.append(
            Event(duration=step, pitches=(tonality.midi_for_degree(base_midi - 7, degree),))
        )
        remaining -= step
        index += 1
    return events


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def generate_exercise(
    levels: dict[str, int] | None = None,
    *,
    bars: int = 4,
    seed: int | None = None,
    key_name: str | None = None,
) -> GeneratedExercise:
    """Build one exercise.

    ``key_name`` pins the key. It is used by the repertoire bridge, so an
    exercise can be written in the key of the piece the player is working on
    rather than in whichever key the key-signature level happens to allow.
    """
    resolved = dict(DEFAULT_USER_LEVELS)
    if levels:
        for slug, level in levels.items():
            resolved[slug] = max(1, min(10, int(level)))

    seed = random.randrange(1, 2**31) if seed is None else int(seed)
    rng = random.Random(seed)

    texture_level = resolved["texture"]
    texture = TEXTURE_LEVELS[texture_level]
    hand_params = HAND_POSITION_LEVELS[resolved["hand_position"]]
    interval_choices = INTERVAL_LEVELS[resolved["intervals"]]
    rhythm_cells = RHYTHM_CELLS[resolved["rhythm"]]
    if key_name is None:
        chosen_key = rng.choice(KEY_SIGNATURE_LEVELS[resolved["key_signature"]])
    else:
        if key_name not in KEY_LEVELS:
            raise ValueError(f"{key_name!r} is not a key this taxonomy knows")
        chosen_key = key_name
    tonality = Tonality(chosen_key)

    tempo_low, tempo_high = TEMPO_LEVELS[resolved["tempo"]]
    tempo_bpm = float(rng.randint(tempo_low, tempo_high))

    meters, lengths, beat_units = _bar_plan(resolved["meter"], bars, rng)

    span = int(hand_params["span"])
    shifts = max(1, int(hand_params["shifts"]))
    shift_pool = [0, 3, -3, 5][:shifts]
    window_offsets: list[int] = []
    while len(window_offsets) < bars:
        window_offsets.extend(shift_pool)
    window_offsets = window_offsets[:bars]

    two_hands = texture["hands"] == ("RH", "LH")
    melody_hand: Hand = "LH" if texture["hands"] == ("LH",) else "RH"
    melody_base = tonality.base_midi(melody_hand)

    # ---- harmony ---------------------------------------------------------
    # Complexity follows `texture`: the progression is part of the
    # accompaniment's character, and richer textures unlock richer harmony.
    chords = bar_chords(bars, texture_level, rng)

    # ---- rhythm ----------------------------------------------------------
    bar_events: list[list[Event]] = [
        events_from_cells(fill_bar(lengths[index], rhythm_cells, rng), beat_units[index])
        for index in range(bars)
    ]
    flat_events: list[Event] = [event for bar in bar_events for event in bar]
    bar_of_event: list[int] = [index for index, bar in enumerate(bar_events) for _ in bar]

    # ---- melody ----------------------------------------------------------
    degrees = generate_degrees(
        flat_events,
        span=span,
        window_offsets=window_offsets,
        interval_choices=interval_choices,
        arpeggio=bool(hand_params.get("arpeggio")),
        scale_runs=bool(hand_params.get("scale_runs")),
        broken_octaves=bool(hand_params.get("broken_octaves")),
        rng=rng,
        bar_of_event=bar_of_event,
        # Anchor the melody to the harmony only when the harmony is actually
        # sounding. A solo line has nothing to clash with, and pinning every
        # downbeat to a chord tone would flatten the beginner material.
        chord_degrees=chords if two_hands else None,
    )
    raw_midis: list[int | None] = [
        None if event.is_rest else tonality.midi_for_degree(melody_base, degree)
        for event, degree in zip(flat_events, degrees)
    ]
    present = [midi for midi in raw_midis if midi is not None]
    altered = iter(
        apply_accidentals(present, tonality=tonality, level=resolved["accidentals"], rng=rng)
    )
    melody_midis: list[int | None] = [
        None if midi is None else next(altered) for midi in raw_midis
    ]

    chord_every = int(texture.get("rh_chord_every") or 0)
    note_index = 0
    for event, midi in zip(flat_events, melody_midis):
        if midi is None:
            continue
        note_index += 1
        if chord_every > 0 and note_index % chord_every == 0:
            third = midi + (3 if tonality.is_minor else 4)
            if third <= 96:
                event.pitches = tuple(sorted((midi, third)))
                continue
        event.pitches = (midi,)

    # ---- melody part -----------------------------------------------------
    melody_part = _make_part(
        "P1",
        "I1",
        "Right Hand" if melody_hand == "RH" else "Left Hand",
        clef.TrebleClef() if melody_hand == "RH" else clef.BassClef(),
        tonality.key,
    )

    use_inner_voice = bool(texture.get("inner_voice")) or bool(texture.get("three_voices"))
    # A time signature is only notated where it changes. MusicXML attributes stay
    # in force until replaced, and the extraction helpers already carry the
    # signature forward for bars that omit it — so printing one per bar only
    # produces engraving noise.
    previous_meter: str | None = None
    for index in range(bars):
        measure = stream.Measure(number=index + 1)
        if meters[index] != previous_meter:
            measure.append(m21meter.TimeSignature(meters[index]))
            previous_meter = meters[index]
        if index == 0:
            # Must live inside a measure: a part-level MetronomeMark is dropped
            # by music21's notation fixup and never reaches the MusicXML.
            measure.insert(0, m21tempo.MetronomeMark(number=tempo_bpm))
        events = bar_events[index]
        if use_inner_voice:
            melody_voice = stream.Voice(id="melody")
            created = _add_events(melody_voice, events, tonality)
            inner_voice = stream.Voice(id="inner")
            _add_events(
                inner_voice,
                _inner_voice_events(
                    lengths[index],
                    beat_units[index],
                    tonality,
                    melody_base,
                    span,
                    chords[index],
                    rng,
                ),
                tonality,
            )
            measure.insert(0, melody_voice)
            measure.insert(0, inner_voice)
            _apply_articulation(
                created, level=resolved["articulation"], rng=rng, container=melody_voice
            )
        else:
            created = _add_events(measure, events, tonality)
            _apply_articulation(created, level=resolved["articulation"], rng=rng, container=measure)
        melody_part.append(measure)

    # ---- accompaniment ---------------------------------------------------
    bass_part: stream.Part | None = None
    bass_pattern_id: str | None = None
    if two_hands:
        pattern = select_pattern(
            meters,
            texture_level,
            rng,
            prefer=tuple(texture.get("prefer") or ()),
        )
        bass_pattern_id = pattern.id
        bass_part = _make_part("P2", "I2", "Left Hand", clef.BassClef(), tonality.key)
        bass_base = tonality.base_midi("LH")

        melody_so_far: list[int] = []
        # Each part declares its own attributes, so this counter is separate
        # from the melody part's.
        previous_meter = None
        for index in range(bars):
            measure = stream.Measure(number=index + 1)
            if meters[index] != previous_meter:
                measure.append(m21meter.TimeSignature(meters[index]))
                previous_meter = meters[index]

            context = BassContext(
                bar_length=lengths[index],
                beat_unit=beat_units[index],
                meter=meters[index],
                tonality=tonality,
                base_midi=bass_base,
                chord_degree=chords[index],
                next_chord_degree=chords[index + 1] if index + 1 < bars else chords[index],
                span=span,
                rng=rng,
                bar_index=index,
                melody_events=bar_events[index],
                previous_melody_events=bar_events[index - 1] if index > 0 else (),
                melody_pitches=tuple(melody_so_far),
            )
            bass_events = _annotate_beats(pattern.build(context), beat_units[index])
            created = _add_events(measure, bass_events, tonality)
            _apply_articulation(
                created,
                level=min(3, resolved["articulation"]),
                rng=rng,
                container=measure,
            )
            bass_part.append(measure)

            offset = sum(len(bar) for bar in bar_events[: index + 1])
            melody_so_far = [midi for midi in melody_midis[:offset] if midi is not None]

    # ---- score -----------------------------------------------------------
    score = stream.Score()
    score.metadata = m21metadata.Metadata()
    score.metadata.title = f"Sight-reading exercise in {key_name}"
    score.insert(0, melody_part)
    if bass_part is not None:
        score.insert(0, bass_part)

    xml = musicxml.m21ToXml.GeneralObjectExporter(score).parse().decode("utf-8")
    return GeneratedExercise(
        score=score,
        musicxml=xml,
        key_name=chosen_key,
        meters=meters,
        tempo_bpm=tempo_bpm,
        bars=bars,
        seed=seed,
        levels=resolved,
        bass_pattern=bass_pattern_id,
    )
