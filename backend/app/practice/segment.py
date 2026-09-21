"""Where a stretch of playing turns over.

The rule this replaces was one fixed silence gap, and on the owner's own ten hours it fired
**60 times in 238,648 note transitions**: a 54-minute sitting became three segments, 42% of the
stored boundaries sat on no silence at all because they had been made by hand, and twelve segments
contained an internal silence longer than the rule that supposedly made them. One number cannot
describe both "I stopped to think for three seconds" and "I have not touched the piano since
Tuesday".

Three rules, each answering a different question:

* **The adaptive gap** asks whether this pause is long *for this passage*. A slow phrase breathes
  for a second between notes; a fast one does not. The floor stops a fast passage being chopped,
  and the multiplier stops a slow one being welded into a session.
* **The minimum size** asks whether the result is worth keeping. A one-note stray is a segment
  today; it should be part of its neighbour.
* **The maximum size** asks whether the result is usable. A 42-minute blob holds many passages, and
  splitting it at its largest internal gaps is what makes them visible.

The maximum is bounded by the pause rule rather than overriding it: a run with no internal silence
at all cannot be split without cutting a phrase in half, so it is left long and reported as one
attempt. Every real stretch of the measured ten hours that ran past two minutes contained a break
(34 of the 36 over five minutes held one longer than 2 s), so the refusal costs nothing on the
material this was built from.

Pure: no database, no clock, no configuration import. ``store.ensure_segments`` applies it; this
module decides. ``sessionize.py`` is left alone and still cuts sittings, because its whole value is
that the live and rebuild paths cannot drift and it is ported byte-for-byte.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence

from .sessionize import Note, Window


@dataclass(frozen=True)
class Config:
    """The four numbers, all of them chosen by ``tools/measure_real.py`` rather than by taste."""

    #: The shortest pause that can ever be a boundary. Measured: 2 s is the best of the
    #: thresholds tried, and it puts the median segment at drill scale (~314 notes).
    floor_ms: int = 2_000
    #: How many times the passage's own pulse a pause must be to count.
    multiplier: float = 2.5
    #: Past this, a pause is a break whatever the pulse says.
    ceiling_ms: int = 30_000
    #: Below this, a group is not worth being a segment.
    min_notes: int = 8
    #: Above this, a group is too coarse to be useful and gets split at its largest gaps.
    max_ms: int = 120_000
    #: How many recent inter-onset intervals define "this passage's pulse".
    window: int = 32


def cut(notes: Sequence[Note], *, config: Config = Config()) -> list[Window]:
    """The boundaries for one sitting's notes, oldest first."""
    ordered = sorted(notes, key=lambda note: (note.epoch_ms, note.pitch))
    if not ordered:
        return []
    groups = _by_adaptive_gap(ordered, config)
    groups = _merge_small(groups, config)
    groups = _split_large(groups, config)
    return [
        Window(group[0].epoch_ms, max(note.end_ms for note in group)) for group in groups
    ]


def _limit(config: Config, pulse_ms: float) -> float:
    if pulse_ms <= 0:
        return float(config.floor_ms)
    return min(float(config.ceiling_ms), max(float(config.floor_ms), config.multiplier * pulse_ms))


def _limits(ordered: Sequence[Note], config: Config) -> dict[int, float]:
    """A gap limit per distinct onset, from the pulse immediately before it."""
    onsets = sorted({note.epoch_ms for note in ordered})
    intervals = [second - first for first, second in zip(onsets, onsets[1:])]
    out: dict[int, float] = {}
    for index, onset in enumerate(onsets):
        recent = intervals[max(0, index - config.window) : index]
        out[onset] = _limit(config, statistics.median(recent) if recent else 0.0)
    return out


def _by_adaptive_gap(ordered: Sequence[Note], config: Config) -> list[list[Note]]:
    limits = _limits(ordered, config)
    groups: list[list[Note]] = [[ordered[0]]]
    end = ordered[0].end_ms
    for note in ordered[1:]:
        if note.epoch_ms - end > limits[note.epoch_ms]:
            groups.append([note])
        else:
            groups[-1].append(note)
        end = max(end, note.end_ms)
    return groups


def _merge_small(groups: list[list[Note]], config: Config) -> list[list[Note]]:
    """An undersized group joins the one before it, which is the simpler promise to keep."""
    out: list[list[Note]] = []
    for group in groups:
        if out and len(out[-1]) < config.min_notes:
            out[-1].extend(group)
        else:
            out.append(list(group))
    while len(out) > 1 and len(out[-1]) < config.min_notes:
        out[-2].extend(out.pop())
    return out


def _split_large(groups: list[list[Note]], config: Config) -> list[list[Note]]:
    out: list[list[Note]] = []
    for group in groups:
        out.extend(_split_one(group, config))
    return out


def _split_one(group: list[Note], config: Config) -> list[list[Note]]:
    span = max(note.end_ms for note in group) - group[0].epoch_ms
    if span <= config.max_ms or len(group) < 2:
        return [group]
    best_index, best_gap, end = 1, -1, group[0].end_ms
    for index, note in enumerate(group[1:], start=1):
        gap = note.epoch_ms - end
        if gap > best_gap:
            best_index, best_gap = index, gap
        end = max(end, note.end_ms)
    if best_gap <= 0:
        return [group]
    return _split_one(group[:best_index], config) + _split_one(group[best_index:], config)
