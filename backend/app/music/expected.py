"""Extraction of the expected-note timeline from a score or MusicXML string.

The timeline is the contract between the generator and the scorer: a flat list
of notes, each carrying absolute onset in seconds *and* musical position. The
scorer never inspects music21, so a curated MusicXML library can be dropped in
later without changing a line of scoring code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from music21 import converter, meter as m21meter, stream, tempo as m21tempo

DEFAULT_BEAT_UNIT = 1.0


@dataclass(frozen=True)
class ExpectedNote:
    index: int
    event_id: int
    pitch: int
    onset_q: float
    duration_q: float
    onset_s: float
    hand: str
    measure: int
    beat: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ExpectedNote":
        return ExpectedNote(
            index=int(data["index"]),
            event_id=int(data["event_id"]),
            pitch=int(data["pitch"]),
            onset_q=float(data["onset_q"]),
            duration_q=float(data["duration_q"]),
            onset_s=float(data["onset_s"]),
            hand=str(data["hand"]),
            measure=int(data["measure"]),
            beat=float(data["beat"]),
        )


DEFAULT_TIME_SIGNATURE = m21meter.TimeSignature("4/4")


def measure_time_signature(
    measure: stream.Measure,
    previous: m21meter.TimeSignature | None = None,
) -> m21meter.TimeSignature:
    """Resolve the active time signature for a measure.

    ``getContextByClass`` does not see a signature that sits *inside* the
    measure at the same offset, and imported MusicXML only prints a signature
    where it changes — so we check the measure itself, then the surrounding
    context, then carry the previous measure's signature forward.
    """
    own = list(measure.getElementsByClass(m21meter.TimeSignature))
    if own:
        return own[0]
    context = measure.getContextByClass(m21meter.TimeSignature)
    if context is not None:
        return context
    return previous if previous is not None else DEFAULT_TIME_SIGNATURE


def _hand_for_part(part: stream.Stream, index: int) -> str:
    """Notation tells us the hand; MIDI never does.

    We prefer explicit naming, then fall back to part order (the generator
    always emits the melody hand first).
    """
    identifier = str(getattr(part, "id", "") or "").upper()
    name = str(getattr(part, "partName", "") or "").lower()
    if identifier.startswith("RH") or "right" in name:
        return "RH"
    if identifier.startswith("LH") or "left" in name:
        return "LH"
    return "RH" if index == 0 else "LH"


def measure_meta(score: stream.Score) -> list[dict[str, Any]]:
    """Per-bar meter facts the browser needs to run a count-in and metronome.

    Mixed meter means this cannot be derived from a single time signature, so
    it is computed here, where music21 already knows the answer.
    """
    meta: list[dict[str, Any]] = []
    for part in score.parts:
        measures = list(part.getElementsByClass(stream.Measure))
        if not measures:
            continue
        active: m21meter.TimeSignature | None = None
        for measure in measures:
            active = measure_time_signature(measure, active)
            beat_unit = float(active.beatDuration.quarterLength) or DEFAULT_BEAT_UNIT
            bar_quarters = float(active.barDuration.quarterLength)
            meta.append(
                {
                    "measure": int(measure.number) if measure.number is not None else len(meta) + 1,
                    "beats": max(1, int(round(bar_quarters / beat_unit))),
                    "beat_unit_q": beat_unit,
                    "bar_quarters": bar_quarters,
                }
            )
        break  # every part shares the same meter map
    return meta


def extract_expected(score: stream.Score, tempo_bpm: float) -> list[ExpectedNote]:
    seconds_per_quarter = 60.0 / float(tempo_bpm)
    notes: list[ExpectedNote] = []
    index = 0

    for part_index, part in enumerate(score.parts):
        hand = _hand_for_part(part, part_index)
        measures = list(part.getElementsByClass(stream.Measure))
        if not measures:
            continue
        active_signature: m21meter.TimeSignature | None = None
        for measure in measures:
            time_signature = measure_time_signature(measure, active_signature)
            active_signature = time_signature
            beat_unit = DEFAULT_BEAT_UNIT
            candidate = float(time_signature.beatDuration.quarterLength)
            if candidate > 0:
                beat_unit = candidate
            measure_offset = float(measure.offset)
            number = int(measure.number) if measure.number is not None else 0
            # ``flatten`` puts every voice of the measure on one timeline.
            for element in measure.flatten().notes:
                offset_in_measure = float(element.offset)
                onset_q = measure_offset + offset_in_measure
                durations = element.duration.quarterLength if hasattr(element, "duration") else 0
                pitches: Iterable[int]
                if hasattr(element, "pitches"):
                    pitches = [int(p.midi) for p in element.pitches]
                else:
                    pitches = [int(element.pitch.midi)]
                for pitch in pitches:
                    notes.append(
                        ExpectedNote(
                            index=index,
                            event_id=0,  # filled in below
                            pitch=pitch,
                            onset_q=onset_q,
                            duration_q=float(durations),
                            onset_s=onset_q * seconds_per_quarter,
                            hand=hand,
                            measure=number,
                            beat=offset_in_measure / beat_unit + 1.0,
                        )
                    )
                    index += 1

    notes.sort(key=lambda note: (round(note.onset_q, 6), note.hand, note.pitch))
    # Reassign indices after sorting and give simultaneous notes a shared event id.
    grouped: list[ExpectedNote] = []
    event_id = -1
    previous_key: tuple[float, str] | None = None
    for position, note in enumerate(notes):
        key = (round(note.onset_q, 6), note.hand)
        if key != previous_key:
            event_id += 1
            previous_key = key
        grouped.append(
            ExpectedNote(
                index=position,
                event_id=event_id,
                pitch=note.pitch,
                onset_q=note.onset_q,
                duration_q=note.duration_q,
                onset_s=note.onset_s,
                hand=note.hand,
                measure=note.measure,
                beat=note.beat,
            )
        )
    return grouped


def extract_expected_from_musicxml(xml: str, tempo_bpm: float | None = None) -> tuple[list[ExpectedNote], float]:
    score = converter.parseData(xml, format="musicxml")
    if tempo_bpm is None:
        marks = list(score.recurse().getElementsByClass(m21tempo.MetronomeMark))
        resolved: float | None = None
        for mark in marks:
            number = mark.number
            if number:
                resolved = float(number)
                break
            sounding = mark.numberSounding
            if sounding:
                resolved = float(sounding)
                break
        tempo_bpm = resolved if resolved else 90.0
    return extract_expected(score, tempo_bpm), float(tempo_bpm)


def expected_to_dicts(notes: Iterable[ExpectedNote]) -> list[dict[str, Any]]:
    return [note.to_dict() for note in notes]


def expected_from_dicts(data: Iterable[dict[str, Any]]) -> list[ExpectedNote]:
    return [ExpectedNote.from_dict(item) for item in data]
