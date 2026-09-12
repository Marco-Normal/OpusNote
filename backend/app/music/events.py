"""Rhythmic events and bar-filling helpers.

An ``Event`` is one rhythmic slot of a line: a note (or chord), or a rest. Cells
are the reusable rhythmic units a bar is tiled from, kept in exact
:class:`~fractions.Fraction` arithmetic so a bar always fills exactly, including
with tuplets.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Sequence

#: A rhythm cell: ``(duration, kind)`` pairs where kind is ``"n"`` or ``"r"``.
Cell = tuple[tuple[Fraction, str], ...]


@dataclass
class Event:
    """One rhythmic slot of a line.

    ``rest`` is set when the *rhythm* is generated, because pitch is assigned in
    a later pass. Checking ``pitches`` before that pass would classify every slot
    as a rest.
    """

    duration: Fraction
    pitches: tuple[int, ...] = ()
    tuplet_group: int | None = None
    beat: float = 1.0
    rest: bool = False

    @property
    def is_rest(self) -> bool:
        return self.rest


def cell_length(cell: Cell) -> Fraction:
    return sum((duration for duration, _ in cell), Fraction(0))


def fill_bar(length: Fraction, cells: Sequence[Cell], rng) -> list[Cell]:
    """Greedily tile ``length`` with whole cells. Always terminates."""
    remaining = length
    chosen: list[Cell] = []
    guard = 0
    while remaining > 0 and guard < 64:
        guard += 1
        fits = [cell for cell in cells if cell_length(cell) <= remaining]
        if not fits:
            break
        cell = rng.choice(fits)
        chosen.append(cell)
        remaining -= cell_length(cell)
    if remaining > 0:
        chosen.append(((remaining, "n"),))
    return chosen


def events_from_cells(cells: Sequence[Cell], beat_unit: Fraction) -> list[Event]:
    """Turn cells into events, grouping runs of triplet eighths."""
    events: list[Event] = []
    position = Fraction(0)
    pending: list[Event] = []
    group_counter = 0
    for cell in cells:
        for duration, kind in cell:
            event = Event(duration=duration, rest=(kind == "r"))
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


def pulse_durations(bar_length: Fraction, unit: Fraction) -> list[Fraction]:
    """Split a bar into equal ``unit`` pulses, with the remainder last.

    Used by the left-hand patterns, which are defined as pulses rather than as
    rhythmic cells.
    """
    if unit <= 0:
        return [bar_length]
    durations: list[Fraction] = []
    remaining = bar_length
    while remaining > 0:
        step = unit if remaining >= unit else remaining
        durations.append(step)
        remaining -= step
    return durations


def even_durations(bar_length: Fraction, count: int) -> list[Fraction]:
    """Split a bar into ``count`` equal parts that sum exactly to it."""
    if count <= 0:
        return [bar_length]
    step = Fraction(bar_length, count)
    return [step] * count


def fit_to_length(events: Sequence[Event], length: Fraction) -> list[Event]:
    """Force a sequence of events to occupy exactly ``length``.

    Patterns that borrow their rhythm from the melody (imitation, similar-motion
    accompaniment) cannot assume the caller handed them a rhythm that already
    sums to the bar. Truncating or padding here keeps that assumption out of
    every such pattern, and a bar that under-fills would otherwise put the
    accompaniment silently out of step with the expected-note timeline.
    """
    fitted: list[Event] = []
    total = Fraction(0)
    for event in events:
        if total >= length:
            break
        remaining = length - total
        if event.duration > remaining:
            fitted.append(replace(event, duration=remaining))
            total = length
            break
        fitted.append(event)
        total += event.duration
    if total < length:
        fitted.append(Event(duration=length - total, rest=True))
    return fitted


def melody_events_to_pitches(events: Sequence[Event]) -> tuple[int, ...]:
    return tuple(pitch for event in events for pitch in event.pitches)
