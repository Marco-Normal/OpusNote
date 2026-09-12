"""Exercise generation.

Turns a mapping of ``{skill_slug: level}`` into a notated exercise. The unit of
output is :class:`GeneratedExercise`, which carries both the music21 score and
its MusicXML serialisation.

Design notes
------------
* Rhythm is generated as *cells* of exact :class:`~fractions.Fraction` durations
  so a bar always fills exactly, including tuplets.
* Pitch is a walk over scale degrees: the permitted interval set comes from the
  ``intervals`` skill, and a per-bar degree window comes from ``hand_position``
  (which is what makes position shifts happen).
* Voicing comes from ``texture``: which parts exist and what the left hand does.
* Nothing here knows about Elo or HTTP, so the generator can be replaced by a
  curated library or a smarter composer without touching the API.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal, Sequence

from music21 import (
    articulations,
    chord as m21chord,
    clef,
    duration as m21duration,
    dynamics,
    instrument,
    key as m21key,
    metadata as m21metadata,
    meter as m21meter,
    musicxml,
    note as m21note,
    spanner,
    stream,
    tempo as m21tempo,
)
from music21.duration import Tuplet

from ..skills_data import (
    ACCIDENTAL_LEVELS,
    ARTICULATION_LEVELS,
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

# A rhythm cell is a tuple of (duration, kind) where kind is "n" or "r".
Cell = tuple[tuple[Fraction, str], ...]
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

    @property
    def meter_label(self) -> str:
        unique = list(dict.fromkeys(self.meters))
        return unique[0] if len(unique) == 1 else "mixed"


@dataclass
class _Event:
    """One rhythmic slot of a line: a note (or chord) or a rest.

    ``rest`` is set when the *rhythm* is generated, because pitch is assigned in
    a later pass. Checking ``pitches`` before that pass would classify every
    slot as a rest.
    """

    duration: Fraction
    pitches: tuple[int, ...] = ()
    tuplet_group: int | None = None
    beat: float = 1.0
    rest: bool = False

    @property
    def is_rest(self) -> bool:
        return self.rest


# --------------------------------------------------------------------------
# Tonality
# --------------------------------------------------------------------------


class Tonality:
    """Scale-degree arithmetic for one key."""

    #: Scale-degree steps that make up the chord used by arpeggio modes.
    CHORD_STEPS: tuple[int, ...] = (0, 2, 4, 6)

    def __init__(self, key_name: str) -> None:
        self.name = key_name
        self.key = m21key.Key(key_name)
        self.is_minor = self.key.mode == "minor"
        self.tonic_pc = self.key.tonic.pitchClass
        # ``key.pitches`` returns the seven degrees *plus* the octave tonic.
        self.pcs: list[int] = [(p.pitchClass - self.tonic_pc) % 12 for p in self.key.pitches][:7]

    def base_midi(self, hand: Hand) -> int:
        octave = 4 if hand == "RH" else 3
        return 12 * (octave + 1) + self.tonic_pc

    def midi_for_degree(self, base_midi: int, degree: int) -> int:
        octave_index, scale_index = divmod(degree, 7)
        return base_midi + 12 * octave_index + self.pcs[scale_index]

    def is_diatonic_midi(self, midi: int) -> bool:
        return (midi - self.tonic_pc) % 12 in self.pcs


# --------------------------------------------------------------------------
# Rhythm
# --------------------------------------------------------------------------


def _cell_length(cell: Cell) -> Fraction:
    return sum((duration for duration, _ in cell), Fraction(0))


def _fill_bar(length: Fraction, cells: Sequence[Cell], rng: random.Random) -> list[Cell]:
    """Greedily tile ``length`` with whole cells. Always terminates."""
    remaining = length
    chosen: list[Cell] = []
    guard = 0
    while remaining > 0 and guard < 64:
        guard += 1
        fits = [cell for cell in cells if _cell_length(cell) <= remaining]
        if not fits:
            break
        cell = rng.choice(fits)
        chosen.append(cell)
        remaining -= _cell_length(cell)
    if remaining > 0:
        chosen.append(((remaining, "n"),))
    return chosen


def _events_from_cells(cells: Sequence[Cell], beat_unit: Fraction) -> list[_Event]:
    events: list[_Event] = []
    position = Fraction(0)
    pending: list[_Event] = []
    group_counter = 0
    for cell in cells:
        for duration, kind in cell:
            event = _Event(duration=duration, rest=(kind == "r"))
            event.beat = float(position / beat_unit) + 1.0
            if duration == Fraction(1, 3):
                pending.append(event)
                if len(pending) == 3:
                    group_counter += 1
                    for member in pending:
                        member.tuplet_group = group_counter
                    pending = []
            else:
                pending = []
            events.append(event)
            position += duration
    return events


# --------------------------------------------------------------------------
# Pitch
# --------------------------------------------------------------------------


def _generate_degrees(
    events: Sequence[_Event],
    *,
    span: int,
    window_offsets: Sequence[int],
    interval_choices: Sequence[int],
    arpeggio: bool,
    scale_runs: bool,
    broken_octaves: bool,
    rng: random.Random,
    bar_of_event: Sequence[int],
) -> list[int]:
    """Walk scale degrees, one per event, honouring the per-bar windows."""
    degrees: list[int] = []
    current = window_offsets[0]
    run_remaining = 0
    run_direction = 1
    last_direction = 1
    awaiting_first_note = True

    for index, event in enumerate(events):
        if event.is_rest:
            degrees.append(current)
            continue

        bar_index = bar_of_event[index] if index < len(bar_of_event) else 0
        offset = window_offsets[min(bar_index, len(window_offsets) - 1)]
        lo, hi = offset, offset + span - 1

        if awaiting_first_note and not arpeggio and not broken_octaves:
            # Begin on the tonic of the current position.
            awaiting_first_note = False
            degrees.append(current)
            continue

        if run_remaining > 0 and scale_runs:
            current += run_direction
            run_remaining -= 1
        elif arpeggio and rng.random() < 0.6:
            current = rng.choice(tuple(offset + step for step in Tonality.CHORD_STEPS))
        elif broken_octaves and degrees and rng.random() < 0.5:
            current = degrees[-1] + 7 * rng.choice((-1, 1))
        else:
            delta = rng.choice(interval_choices)
            if delta == 0:
                degrees.append(current)
                continue
            # Momentum: melodies continue in a direction far more often than
            # they reverse, which is what makes lines read as phrases instead of
            # as a pinball between two neighbouring notes.
            direction = last_direction if rng.random() < 0.68 else -last_direction
            proposed = current + delta * direction
            if proposed < lo or proposed > hi:
                direction = -direction
                proposed = current + delta * direction
                if proposed < lo or proposed > hi:
                    proposed = max(lo, min(hi, proposed))
            last_direction = direction
            current = proposed
            if scale_runs and rng.random() < 0.12:
                run_remaining = rng.randint(3, 6)
                run_direction = direction

        current = max(lo, min(hi, current))
        degrees.append(current)

    return degrees


def _apply_accidentals(midis: list[int], *, tonality: Tonality, level: int, rng: random.Random) -> list[int]:
    params = ACCIDENTAL_LEVELS[level]
    count = int(params["count"])
    probability = float(params["chromatic_prob"])
    if count <= 0 and probability <= 0:
        return midis

    altered = list(midis)

    def alter(index: int) -> None:
        base = altered[index]
        for shift in (1, -1):
            candidate = base + shift
            if 21 <= candidate <= 108 and not tonality.is_diatonic_midi(candidate):
                altered[index] = candidate
                return

    if count > 0:
        for index in rng.sample(range(len(altered)), min(count, len(altered))):
            alter(index)
    else:
        for index in range(len(altered)):
            if rng.random() < probability:
                alter(index)
    return altered


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------


def _bar_plan(meter_level: int, bars: int, rng: random.Random) -> tuple[list[str], list[Fraction], list[Fraction]]:
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


def _clear_implied_accidentals(element: Notated, tonality: "Tonality | None") -> None:
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
    events: Sequence[_Event],
    tonality: "Tonality | None" = None,
) -> list[tuple[Notated, _Event]]:
    created: list[tuple[Notated, _Event]] = []
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


def _apply_articulation(
    created: Sequence[tuple[Notated, _Event]],
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


# --------------------------------------------------------------------------
# Accompaniment
# --------------------------------------------------------------------------


def _bass_events(
    style: str,
    *,
    bar_length: Fraction,
    beat_unit: Fraction,
    tonality: Tonality,
    base_midi: int,
    melodic_events: Sequence[_Event],
    imitation_pitches: Sequence[int],
    rng: random.Random,
) -> list[_Event]:
    def pitch(degree: int) -> int:
        return tonality.midi_for_degree(base_midi, degree)

    if style == "sustain":
        pulses = max(1, int(bar_length / (beat_unit * 2))) if beat_unit * 2 <= bar_length else 1
        duration = bar_length / pulses
        return [_Event(duration=duration, pitches=(pitch(0 if i % 2 == 0 else 4),)) for i in range(pulses)]

    if style == "mirror":
        events: list[_Event] = []
        for index, source in enumerate(melodic_events):
            if source.is_rest:
                events.append(_Event(duration=source.duration))
            else:
                events.append(_Event(duration=source.duration, pitches=(pitch(0 if index % 2 == 0 else 4),)))
        return events

    if style == "imitation":
        events = []
        pitches = list(imitation_pitches)
        cursor = 0
        for source in melodic_events:
            if source.is_rest or not pitches:
                events.append(_Event(duration=source.duration))
                continue
            midi = pitches[cursor % len(pitches)]
            cursor += 1
            while midi < 36:
                midi += 12
            while midi > 60:
                midi -= 12
            events.append(_Event(duration=source.duration, pitches=(midi,)))
        return events

    if style == "moving":
        steps = (0, 2, 4, 2, 1, 3, 5, 4)
        unit = beat_unit / 2 if beat_unit >= 1 else Fraction(1, 2)
        events = []
        remaining = bar_length
        index = 0
        while remaining >= unit:
            events.append(_Event(duration=unit, pitches=(pitch(steps[index % len(steps)]),)))
            remaining -= unit
            index += 1
        if remaining > 0:
            events.append(_Event(duration=remaining, pitches=(pitch(steps[index % len(steps)]),)))
        return events

    # "quarters": root/fifth pulse on the beat
    events = []
    remaining = bar_length
    index = 0
    while remaining > 0:
        step = beat_unit if remaining >= beat_unit else remaining
        events.append(_Event(duration=step, pitches=(pitch(0 if index % 2 == 0 else 4),)))
        remaining -= step
        index += 1
    return events


def _inner_voice_events(
    bar_length: Fraction,
    beat_unit: Fraction,
    tonality: Tonality,
    base_midi: int,
    span: int,
    rng: random.Random,
) -> list[_Event]:
    """A slow chord-tone line used as a second voice in the melody hand."""
    unit = beat_unit * 2 if beat_unit * 2 <= bar_length else bar_length
    events: list[_Event] = []
    remaining = bar_length
    index = 0
    while remaining > 0:
        step = unit if remaining >= unit else remaining
        degree = min((0, 2, 4, 2)[index % 4], max(0, span - 1))
        events.append(_Event(duration=step, pitches=(tonality.midi_for_degree(base_midi - 7, degree),)))
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
) -> GeneratedExercise:
    resolved = dict(DEFAULT_USER_LEVELS)
    if levels:
        for slug, level in levels.items():
            resolved[slug] = max(1, min(10, int(level)))

    seed = random.randrange(1, 2**31) if seed is None else int(seed)
    rng = random.Random(seed)

    texture = TEXTURE_LEVELS[resolved["texture"]]
    hand_params = HAND_POSITION_LEVELS[resolved["hand_position"]]
    interval_choices = INTERVAL_LEVELS[resolved["intervals"]]
    rhythm_cells = RHYTHM_CELLS[resolved["rhythm"]]
    key_name = rng.choice(KEY_SIGNATURE_LEVELS[resolved["key_signature"]])
    tonality = Tonality(key_name)

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

    # ---- rhythm ----------------------------------------------------------
    bar_events: list[list[_Event]] = []
    for index in range(bars):
        bar_events.append(_events_from_cells(_fill_bar(lengths[index], rhythm_cells, rng), beat_units[index]))

    flat_events: list[_Event] = [event for bar in bar_events for event in bar]
    bar_of_event: list[int] = [index for index, bar in enumerate(bar_events) for _ in bar]

    melody_hand: Hand = "LH" if texture["hands"] == ("LH",) else "RH"
    melody_base = tonality.base_midi(melody_hand)

    degrees = _generate_degrees(
        flat_events,
        span=span,
        window_offsets=window_offsets,
        interval_choices=interval_choices,
        arpeggio=bool(hand_params.get("arpeggio")),
        scale_runs=bool(hand_params.get("scale_runs")),
        broken_octaves=bool(hand_params.get("broken_octaves")),
        rng=rng,
        bar_of_event=bar_of_event,
    )
    raw_midis: list[int | None] = [
        None if event.is_rest else tonality.midi_for_degree(melody_base, degree)
        for event, degree in zip(flat_events, degrees)
    ]
    present = [midi for midi in raw_midis if midi is not None]
    altered = iter(_apply_accidentals(present, tonality=tonality, level=resolved["accidentals"], rng=rng))
    melody_midis: list[int | None] = [None if midi is None else next(altered) for midi in raw_midis]

    # ---- fill event pitches, adding chord tones where the texture asks ----
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

    # ---- melody part ------------------------------------------------------
    melody_part = _make_part(
        "P1",
        "I1",
        "Right Hand" if melody_hand == "RH" else "Left Hand",
        clef.TrebleClef() if melody_hand == "RH" else clef.BassClef(),
        tonality.key,
    )

    use_inner_voice = bool(texture.get("inner_voice")) or bool(texture.get("three_voices"))
    for index in range(bars):
        measure = stream.Measure(number=index + 1)
        measure.append(m21meter.TimeSignature(meters[index]))
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
                _inner_voice_events(lengths[index], beat_units[index], tonality, melody_base, span, rng),
                tonality,
            )
            measure.insert(0, melody_voice)
            measure.insert(0, inner_voice)
            _apply_articulation(created, level=resolved["articulation"], rng=rng, container=melody_voice)
        else:
            created = _add_events(measure, events, tonality)
            _apply_articulation(created, level=resolved["articulation"], rng=rng, container=measure)
        melody_part.append(measure)

    # ---- accompaniment ----------------------------------------------------
    bass_part: stream.Part | None = None
    if texture["hands"] == ("RH", "LH"):
        bass_style = "imitation" if texture.get("imitation") else str(texture.get("bass") or "quarters")
        bass_part = _make_part("P2", "I2", "Left Hand", clef.BassClef(), tonality.key)

        bar_pitches: list[list[int]] = []
        cursor = 0
        for bar in bar_events:
            chunk = melody_midis[cursor : cursor + len(bar)]
            bar_pitches.append([midi for midi in chunk if midi is not None])
            cursor += len(bar)

        for index in range(bars):
            measure = stream.Measure(number=index + 1)
            measure.append(m21meter.TimeSignature(meters[index]))
            created = _add_events(
                measure,
                _bass_events(
                    bass_style,
                    bar_length=lengths[index],
                    beat_unit=beat_units[index],
                    tonality=tonality,
                    base_midi=tonality.base_midi("LH"),
                    melodic_events=bar_events[index],
                    imitation_pitches=bar_pitches[index - 1] if index > 0 else [],
                    rng=rng,
                ),
                tonality,
            )
            _apply_articulation(
                created,
                level=min(3, resolved["articulation"]),
                rng=rng,
                container=measure,
            )
            bass_part.append(measure)

    # ---- score ------------------------------------------------------------
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
        key_name=key_name,
        meters=meters,
        tempo_bpm=tempo_bpm,
        bars=bars,
        seed=seed,
        levels=resolved,
    )
