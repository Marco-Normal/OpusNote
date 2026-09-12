"""Melodic line generation.

A scale-degree walk whose permitted intervals, register window, and contour come
from the skill levels, optionally anchored to a chord progression so the result
is tonal rather than merely diatonic.
"""

from __future__ import annotations

import random
from typing import Sequence

from .events import Event
from .harmony import CHORD_STEPS, nearest_chord_tone
from .tonality import Tonality

#: Steps that make up the arpeggio figures.
CHORD_STEPS_LOCAL = CHORD_STEPS


def generate_degrees(
    events: Sequence[Event],
    *,
    span: int,
    window_offsets: Sequence[int],
    interval_choices: Sequence[int],
    arpeggio: bool,
    scale_runs: bool,
    broken_octaves: bool,
    rng: random.Random,
    bar_of_event: Sequence[int],
    chord_degrees: Sequence[int] | None = None,
) -> list[int]:
    """Walk scale degrees, one per event, honouring the per-bar windows.

    When ``chord_degrees`` is supplied, the first note of each bar is pulled onto
    a chord tone. Without it a technically diatonic melody wanders against its own
    accompaniment, which is the difference between an exercise that sounds
    composed and one that sounds generated.
    """
    degrees: list[int] = []
    current = window_offsets[0]
    run_remaining = 0
    run_direction = 1
    last_direction = 1
    awaiting_first_note = True
    previous_bar = -1

    for index, event in enumerate(events):
        if event.is_rest:
            degrees.append(current)
            continue

        bar_index = bar_of_event[index] if index < len(bar_of_event) else 0
        offset = window_offsets[min(bar_index, len(window_offsets) - 1)]
        lo, hi = offset, offset + span - 1

        # Anchor the downbeat to the harmony.
        if (
            chord_degrees is not None
            and bar_index != previous_bar
            and bar_index < len(chord_degrees)
        ):
            previous_bar = bar_index
            anchored = nearest_chord_tone(current, chord_degrees[bar_index], window=span)
            current = max(lo, min(hi, anchored))
            degrees.append(current)
            awaiting_first_note = False
            continue

        if awaiting_first_note and not arpeggio and not broken_octaves:
            # Begin on the tonic of the current position.
            awaiting_first_note = False
            degrees.append(current)
            continue

        if run_remaining > 0 and scale_runs:
            current += run_direction
            run_remaining -= 1
        elif arpeggio and rng.random() < 0.6:
            current = rng.choice(tuple(offset + step for step in CHORD_STEPS_LOCAL))
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


def apply_accidentals(
    midis: list[int], *, tonality: Tonality, level: int, rng: random.Random
) -> list[int]:
    """Introduce chromatic notes according to the ``accidentals`` skill level."""
    from ..skills_data import ACCIDENTAL_LEVELS

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
