"""A minimal diatonic harmony engine.

Accompaniment patterns only sound like accompaniment if there is harmony for
them to outline. Alberti bass on a static tonic for four bars is not the figure
anyone means by the name, so the pattern library needs a chord per bar.

This is deliberately a small, diatonic, closed set: scale-degree progressions
chosen per difficulty, no chromaticism, no voice-leading analysis. It exists to
give the left hand something musical to arpeggiate, not to be a theory engine.
"""

from __future__ import annotations

from typing import Sequence

#: Scale-degree offsets forming a diatonic chord, starting at its root.
#: 0-2-4 is a triad, 0-2-4-6 a seventh.
CHORD_STEPS: tuple[int, ...] = (0, 2, 4, 6)

#: Chord-tone positions used when a pattern wants "the third" or "the fifth".
ROOT, THIRD, FIFTH, SEVENTH = 0, 2, 4, 6

#: Progressions by difficulty, as scale degrees of the chord root per bar:
#: 0=I 1=ii 2=iii 3=IV 4=V 5=vi 6=vii.
#:
#: Levels are grouped so a beginner meets the tonic and dominant long before a
#: mediant or a supertonic, which is roughly how method books sequence this.
PROGRESSIONS: dict[int, tuple[tuple[int, ...], ...]] = {
    1: ((0,),),
    2: ((0,), (0, 4)),
    3: ((0, 4, 0), (0, 4, 4, 0), (0, 0, 4, 0)),
    4: ((0, 3, 4, 0), (0, 4, 0, 4), (0, 4, 3, 4)),
    5: ((0, 3, 4, 0), (0, 5, 3, 4), (0, 4, 5, 3), (0, 3, 0, 4)),
    6: ((0, 5, 3, 4), (0, 3, 0, 4), (0, 4, 1, 4), (0, 5, 1, 4)),
    7: ((0, 3, 4, 0), (5, 3, 0, 4), (0, 2, 3, 4), (0, 4, 1, 4)),
    8: ((0, 5, 1, 4), (0, 3, 4, 0), (5, 1, 3, 4), (0, 4, 5, 3)),
    9: ((0, 3, 1, 4), (5, 1, 3, 4), (0, 2, 3, 4), (0, 5, 3, 4)),
    10: ((0, 5, 1, 4), (3, 1, 4, 0), (0, 2, 3, 4), (5, 3, 0, 4)),
}

MIN_LEVEL = 1
MAX_LEVEL = 10


def bar_chords(bars: int, level: int, rng) -> list[int]:
    """One chord root (a scale degree) per bar.

    The template is cycled to cover the requested length, then the cadence is
    forced: the progression lands on the dominant then the tonic so an exercise
    sounds finished rather than stopping mid-phrase.
    """
    if bars <= 0:
        return []
    template = rng.choice(PROGRESSIONS[max(MIN_LEVEL, min(MAX_LEVEL, int(level)))])
    chords = [template[index % len(template)] for index in range(bars)]

    chords[-1] = 0
    if bars >= 4:
        chords[-2] = 4
    return chords


def chord_steps(size: int) -> Sequence[int]:
    """Scale-degree offsets for a chord of ``size`` notes."""
    return CHORD_STEPS[: max(1, min(len(CHORD_STEPS), size))]


def nearest_chord_tone(degree: int, chord_root: int, window: int = 4) -> int:
    """Pull ``degree`` onto the chord rooted at ``chord_root``.

    Searched outward from the given degree so the melody keeps its register and
    only the pitch class changes — the alternative, snapping to the nearest chord
    tone above the root, would drag every phrase upward.
    """
    target = {(chord_root + step) % 7 for step in CHORD_STEPS[:3]}
    for distance in range(0, window + 1):
        for candidate in (degree - distance, degree + distance):
            if candidate % 7 in target:
                return candidate
    return degree
