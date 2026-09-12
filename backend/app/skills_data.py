"""The difficulty model: nine independent skill dimensions, each level 1-10.

This module is the single source of truth for *what* a level means. It is used
by three consumers:

* the DB seeding layer (``skills`` table)
* the exercise generator (concrete parameter tables)
* the API (so the UI can show level descriptions without duplicating prose)

Hard rule: every table here is indexed by an ``int`` level in ``1..10``.
``LEVELS`` is exactly ``(1, 2, ..., 10)`` and every parameter table must define
all ten keys, which :func:`validate_taxonomy` asserts at import time.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

LEVELS: tuple[int, ...] = tuple(range(1, 11))


@dataclass(frozen=True)
class SkillSpec:
    slug: str
    name: str
    description: str
    levels: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.levels) != 10:
            raise ValueError(f"skill {self.slug!r} must declare exactly 10 levels")


SKILLS: tuple[SkillSpec, ...] = (
    SkillSpec(
        slug="key_signature",
        name="Key signatures",
        description="Reading in increasingly remote keys.",
        levels=(
            "C major only",
            "G major, F major",
            "D major, B-flat major",
            "A major, E-flat major",
            "E major, A-flat major",
            "B major, D-flat major",
            "F-sharp major, G-flat major",
            "C-sharp major, C-flat major",
            "Minor keys with up to 2 accidentals",
            "Minor keys with 3+ accidentals",
        ),
    ),
    SkillSpec(
        slug="meter",
        name="Meter",
        description="Feeling simple, compound, and irregular meters.",
        levels=(
            "4/4 only",
            "3/4 and 2/4",
            "Cut time (2/2)",
            "6/8",
            "3/8 and 9/8",
            "12/8",
            "5/4 and 3/2",
            "7/8 and 5/8",
            "Alternating simple meters",
            "Alternating irregular meters",
        ),
    ),
    SkillSpec(
        slug="rhythm",
        name="Rhythm",
        description="From quarters and halves to syncopation and tuplets.",
        levels=(
            "Quarters, halves, wholes",
            "Eighth-note pairs",
            "Mixed eighths and dotted halves",
            "Dotted quarter + eighth",
            "Sixteenth-note pairs",
            "Dotted eighth + sixteenth",
            "Syncopation and ties across beats",
            "Continuous sixteenth runs",
            "Eighth-note triplets",
            "Mixed tuplets and complex syncopation",
        ),
    ),
    SkillSpec(
        slug="intervals",
        name="Intervals",
        description="Size of the melodic leaps you can read at sight.",
        levels=(
            "Steps only (seconds)",
            "Up to thirds",
            "Up to fourths and fifths",
            "Up to sixths",
            "Up to sevenths and the octave",
            "Compound intervals beyond an octave",
            "Wide leaps mixed with steps",
            "Disjunct lines across two octaves",
            "Leaps of a tenth or more",
            "Fully disjunct, chromatic approach",
        ),
    ),
    SkillSpec(
        slug="hand_position",
        name="Hand position",
        description="Staying put, extending, shifting, and arpeggiating.",
        levels=(
            "Five-finger position, right hand",
            "Five-finger position, left hand",
            "Sixth extensions in one hand",
            "One clean position shift per phrase",
            "Frequent shifts in both hands",
            "Triad arpeggios across an octave",
            "Seventh-chord arpeggios",
            "Broken octaves",
            "Two-octave scale runs",
            "Free position changes across the range",
        ),
    ),
    SkillSpec(
        slug="texture",
        name="Texture",
        description="Single lines through to chords and polyphony.",
        levels=(
            "Right hand alone",
            "Left hand alone",
            "Melody with sustained bass notes",
            "Hands together in similar rhythm",
            "Melody over a moving bass line",
            "Chords in the right hand",
            "Two voices in one hand",
            "Imitation between the hands",
            "Three independent voices",
            "Dense four-voice writing",
        ),
    ),
    SkillSpec(
        slug="accidentals",
        name="Accidentals",
        description="Reading outside the key signature.",
        levels=(
            "Diatonic only",
            "One accidental",
            "Two accidentals",
            "Three accidentals",
            "Four accidentals",
            "Chromatic passing tones",
            "Chromatic neighbour tones",
            "Applied dominants",
            "Modal mixture",
            "Highly chromatic writing",
        ),
    ),
    SkillSpec(
        slug="tempo",
        name="Tempo",
        description="Comfortable reading speed at the keyboard.",
        levels=(
            "50-60 BPM",
            "60-70 BPM",
            "70-80 BPM",
            "80-92 BPM",
            "92-104 BPM",
            "104-116 BPM",
            "116-128 BPM",
            "128-140 BPM",
            "140-160 BPM",
            "160-200 BPM",
        ),
    ),
    SkillSpec(
        slug="articulation",
        name="Articulation and dynamics",
        description="Legato, staccato, slurs, and dynamic shaping.",
        levels=(
            "Legato, no marks",
            "Staccato notes",
            "Accents on strong beats",
            "Two-note slurs",
            "Phrase slurs",
            "Tenuto and portato",
            "p and f markings",
            "Crescendo and diminuendo",
            "Slurs combined with dynamics",
            "Full expressive marking set",
        ),
    ),
)

SKILLS_BY_SLUG: dict[str, SkillSpec] = {spec.slug: spec for spec in SKILLS}
SKILL_SLUGS: tuple[str, ...] = tuple(spec.slug for spec in SKILLS)


# --------------------------------------------------------------------------
# Generator parameter tables
# --------------------------------------------------------------------------

#: Keys available at each key-signature level. Minor keys are spelled with a
#: lowercase tonic so music21 picks the minor mode.
KEY_SIGNATURE_LEVELS: dict[int, tuple[str, ...]] = {
    1: ("C",),
    2: ("G", "F"),
    3: ("D", "Bb"),
    4: ("A", "Eb"),
    5: ("E", "Ab"),
    6: ("B", "Db"),
    7: ("F#", "Gb"),
    8: ("C#", "Cb"),
    9: ("a", "e", "d", "g"),
    10: ("b", "f#", "c", "f", "bb"),
}

#: Meters available at each level. Levels 9-10 return *sequences*: the
#: generator alternates them bar by bar.
METER_LEVELS: dict[int, tuple[str, ...]] = {
    1: ("4/4",),
    2: ("3/4", "2/4"),
    3: ("2/2",),
    4: ("6/8",),
    5: ("3/8", "9/8"),
    6: ("12/8",),
    7: ("5/4", "3/2"),
    8: ("7/8", "5/8"),
    9: ("4/4", "3/4"),
    10: ("7/8", "5/8", "4/4"),
}

#: Levels at which the meter changes every bar.
MIXED_METER_LEVELS: frozenset[int] = frozenset({9, 10})

#: BPM range per tempo level.
TEMPO_LEVELS: dict[int, tuple[int, int]] = {
    1: (50, 60),
    2: (60, 70),
    3: (70, 80),
    4: (80, 92),
    5: (92, 104),
    6: (104, 116),
    7: (116, 128),
    8: (128, 140),
    9: (140, 160),
    10: (160, 200),
}

#: Melodic range (in scale degrees away from the tonic) per hand-position level.
#: ``(low_degree, high_degree, shifts)`` where shifts is the number of distinct
#: positions the hand visits.
HAND_POSITION_LEVELS: dict[int, dict[str, object]] = {
    1: {"span": 5, "centre": "tonic", "shifts": 1, "arpeggio": False},
    2: {"span": 5, "centre": "tonic", "shifts": 1, "arpeggio": False},
    3: {"span": 6, "centre": "tonic", "shifts": 1, "arpeggio": False},
    4: {"span": 7, "centre": "tonic", "shifts": 2, "arpeggio": False},
    5: {"span": 8, "centre": "tonic", "shifts": 3, "arpeggio": False},
    6: {"span": 10, "centre": "tonic", "shifts": 2, "arpeggio": True, "chord": "triad"},
    7: {"span": 14, "centre": "tonic", "shifts": 2, "arpeggio": True, "chord": "seventh"},
    8: {"span": 15, "centre": "tonic", "shifts": 2, "arpeggio": False, "broken_octaves": True},
    9: {"span": 15, "centre": "tonic", "shifts": 2, "arpeggio": False, "scale_runs": True},
    10: {"span": 19, "centre": "tonic", "shifts": 4, "arpeggio": False, "free": True},
}

#: Which hands play and how, per texture level.
#: ``hands``  - parts to emit
#: ``bass``   - left-hand accompaniment style ("" when the LH carries melody)
#: ``rh_chord_every`` - add a chord tone in the RH every N melody notes (0 = never)
#: ``imitation`` / ``inner_voice`` / ``three_voices`` toggle the polyphonic modes
TEXTURE_LEVELS: dict[int, dict[str, object]] = {
    1: {"hands": ("RH",), "bass": ""},
    2: {"hands": ("LH",), "bass": ""},
    3: {"hands": ("RH", "LH"), "bass": "sustain", "bass_duration": 4.0},
    4: {"hands": ("RH", "LH"), "bass": "mirror"},
    5: {"hands": ("RH", "LH"), "bass": "quarters"},
    6: {"hands": ("RH", "LH"), "bass": "quarters", "rh_chord_every": 3},
    7: {"hands": ("RH", "LH"), "bass": "quarters", "inner_voice": True},
    8: {"hands": ("RH", "LH"), "bass": "quarters", "imitation": True},
    9: {"hands": ("RH", "LH"), "bass": "quarters", "inner_voice": True, "three_voices": True},
    10: {"hands": ("RH", "LH"), "bass": "moving", "rh_chord_every": 2, "inner_voice": True},
}

#: Allowed melodic scale-degree intervals per interval level. ``0`` means a
#: repeated note; degree 1 is a second, 2 a third, 4 a fifth, 7 an octave.
INTERVAL_LEVELS: dict[int, tuple[int, ...]] = {
    1: (1,),
    2: (1, 2),
    3: (1, 2, 3, 4),
    4: (1, 2, 3, 4, 5),
    5: (1, 2, 3, 4, 5, 6, 7),
    6: (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    7: (1, 2, 3, 4, 5, 6, 7, 8, 10, 12),
    8: (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12),
    9: (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14),
    10: (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16),
}

#: Rhythmic cells per level. A cell is a tuple of ``(Fraction quarterLength,
#: kind)`` items where kind is ``"n"`` (note) or ``"r"`` (rest). Every cell sums
#: to a dyadic value except the triplet cell, which sums to exactly 1 quarter,
#: so greedy bar filling never leaves an unwritable remainder.
_N, _R = "n", "r"


def _cell(*items: tuple[Fraction, str]) -> tuple[tuple[Fraction, str], ...]:
    return tuple(items)


def _notes(*durations: str) -> tuple[tuple[Fraction, str], ...]:
    return _cell(*[(Fraction(d), _N) for d in durations])


def _mixed(*pairs: tuple[str, str]) -> tuple[tuple[Fraction, str], ...]:
    return _cell(*[(Fraction(d), k) for d, k in pairs])


RHYTHM_CELLS: dict[int, tuple[tuple[tuple[Fraction, str], ...], ...]] = {
    1: (_notes("1"), _notes("1", "1"), _notes("2"), _notes("4"), _notes("2", "2")),
    2: (
        _notes("1", "1"), _notes("0.5", "0.5"), _notes("0.5", "0.5", "1"),
        _notes("2"), _notes("1", "1", "1", "1"),
    ),
    3: (
        _notes("1", "1"), _notes("1.5", "0.5"), _notes("0.5", "0.5", "1"),
        _notes("3", "1"), _notes("2", "1", "1"),
    ),
    4: (
        _notes("1.5", "0.5"), _notes("0.5", "1.5"), _notes("1.5", "0.5", "1", "1"),
        _notes("1.5", "0.5", "1.5", "0.5"), _notes("2", "1.5", "0.5"),
    ),
    5: (
        _notes("0.25", "0.25", "0.5"), _notes("0.25", "0.25", "0.25", "0.25"),
        _notes("0.5", "0.5"), _notes("1", "0.25", "0.25", "0.5"), _notes("2", "1", "1"),
    ),
    6: (
        _notes("0.75", "0.25"), _notes("0.25", "0.75"), _notes("0.75", "0.25", "1", "1"),
        _notes("1.5", "0.5", "0.75", "0.25"), _notes("0.25", "0.25", "0.25", "0.25"),
    ),
    7: (
        # off-beat attacks: a rest pushes the following note off the beat
        _mixed(("0.5", _R), ("0.5", _N), ("1", _N)),
        _mixed(("0.5", _R), ("1", _N), ("0.5", _N)),
        _notes("0.5", "0.5", "0.5", "0.5"),
        _notes("1.5", "0.5"), _notes("1", "1", "1", "1"),
    ),
    8: (
        _notes("0.25", "0.25", "0.25", "0.25"),
        _notes("0.25", "0.25", "0.5", "0.25", "0.25", "0.5"),
        _notes("0.5", "0.25", "0.25", "1", "1"),
        _notes("0.25", "0.25", "0.25", "0.25", "0.5", "0.5"),
    ),
    9: (
        _notes("1/3", "1/3", "1/3", "1"),
        _notes("1", "1/3", "1/3", "1/3"),
        _notes("1/3", "1/3", "1/3",
               "1/3", "1/3", "1/3"),
        _notes("0.5", "0.5", "1", "1"),
    ),
    10: (
        _notes("1/3", "1/3", "1/3", "1"),
        _notes("0.25", "0.25", "0.25", "0.25", "1", "1"),
        _mixed(("0.5", _R), ("0.5", _N), ("1", _N), ("0.5", _N), ("0.5", _N)),
        _notes("0.75", "0.25", "0.75", "0.25"),
        _notes("1.5", "0.5", "0.5", "0.5"),
    ),
}

#: Accidental budget per level. Levels 1-5 are exact counts of chromatic notes.
#: Levels 6-10 use a probability of altering a diatonic note instead.
ACCIDENTAL_LEVELS: dict[int, dict[str, float]] = {
    1: {"count": 0, "chromatic_prob": 0.0},
    2: {"count": 1, "chromatic_prob": 0.0},
    3: {"count": 2, "chromatic_prob": 0.0},
    4: {"count": 3, "chromatic_prob": 0.0},
    5: {"count": 4, "chromatic_prob": 0.0},
    6: {"count": 0, "chromatic_prob": 0.12},
    7: {"count": 0, "chromatic_prob": 0.18},
    8: {"count": 0, "chromatic_prob": 0.22},
    9: {"count": 0, "chromatic_prob": 0.28},
    10: {"count": 0, "chromatic_prob": 0.40},
}

#: Articulation behaviour per level.
ARTICULATION_LEVELS: dict[int, dict[str, object]] = {
    1: {},
    2: {"staccato_prob": 0.5},
    3: {"accent_strong_beats": True},
    4: {"slur_len": 2},
    5: {"slur_len": 4},
    6: {"staccato_prob": 0.3, "tenuto_prob": 0.3},
    7: {"dynamic": ("p", "f")},
    8: {"dynamic": ("p", "f"), "hairpins": True},
    9: {"slur_len": 4, "dynamic": ("p", "mf", "f"), "staccato_prob": 0.25},
    10: {"slur_len": 6, "dynamic": ("pp", "p", "mf", "f"), "hairpins": True,
         "staccato_prob": 0.3, "accent_strong_beats": True},
}

#: Baseline level for every skill when a brand-new user starts. Deliberately
#: easy so the first session cannot intimidate, and the Elo updates take over.
DEFAULT_USER_LEVELS: dict[str, int] = {
    "key_signature": 1,
    "meter": 1,
    "rhythm": 1,
    "intervals": 1,
    "hand_position": 1,
    "texture": 1,
    "accidentals": 1,
    "tempo": 2,
    "articulation": 1,
}


def validate_taxonomy() -> None:
    """Fail loudly at import time if a parameter table is incomplete."""
    tables: dict[str, dict[int, object]] = {
        "KEY_SIGNATURE_LEVELS": KEY_SIGNATURE_LEVELS,
        "METER_LEVELS": METER_LEVELS,
        "TEMPO_LEVELS": TEMPO_LEVELS,
        "HAND_POSITION_LEVELS": HAND_POSITION_LEVELS,
        "TEXTURE_LEVELS": TEXTURE_LEVELS,
        "INTERVAL_LEVELS": INTERVAL_LEVELS,
        "RHYTHM_CELLS": RHYTHM_CELLS,
        "ACCIDENTAL_LEVELS": ACCIDENTAL_LEVELS,
        "ARTICULATION_LEVELS": ARTICULATION_LEVELS,
    }
    for name, table in tables.items():
        missing = [level for level in LEVELS if level not in table]
        extra = [key for key in table if key not in LEVELS]
        if missing or extra:
            raise ValueError(f"{name}: missing={missing} extra={extra}")
    for spec in SKILLS:
        if spec.slug not in DEFAULT_USER_LEVELS:
            raise ValueError(f"skill {spec.slug!r} has no default starting level")


validate_taxonomy()
