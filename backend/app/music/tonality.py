"""Scale-degree arithmetic for one key.

Shared by the melody generator, the harmony engine, and the left-hand pattern
library, which is why it lives on its own rather than inside any of them.
"""

from __future__ import annotations

from music21 import key as m21key


class Tonality:
    """Scale-degree arithmetic for one key."""

    def __init__(self, key_name: str) -> None:
        self.name = key_name
        self.key = m21key.Key(key_name)
        self.is_minor = self.key.mode == "minor"
        self.tonic_pc = self.key.tonic.pitchClass
        # ``key.pitches`` returns the seven degrees *plus* the octave tonic.
        self.pcs: list[int] = [(p.pitchClass - self.tonic_pc) % 12 for p in self.key.pitches][:7]

    def base_midi(self, hand: str) -> int:
        octave = 4 if hand == "RH" else 3
        return 12 * (octave + 1) + self.tonic_pc

    def midi_for_degree(self, base_midi: int, degree: int) -> int:
        octave_index, scale_index = divmod(degree, 7)
        return base_midi + 12 * octave_index + self.pcs[scale_index]

    def is_diatonic_midi(self, midi: int) -> bool:
        return (midi - self.tonic_pc) % 12 in self.pcs

    def chord_midis(self, base_midi: int, degree: int, size: int = 3) -> tuple[int, ...]:
        """A diatonic triad (or seventh) built on ``degree``."""
        from .harmony import CHORD_STEPS

        steps = CHORD_STEPS[: max(1, size)]
        return tuple(sorted({self.midi_for_degree(base_midi, degree + step) for step in steps}))
