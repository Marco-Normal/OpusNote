"""The deliberate-practice taxonomy, and what the log can honestly infer.

A segment already records *what* was played and for how long. This module owns the axis
it was missing — *how* it was practised — and the one rule that keeps it trustworthy:
an inference produces an **offer**, never a label. The autotag bands follow the same
restraint, and for the same reason: a guess written silently is a guess the player
cannot disagree with.

Nothing here persists anything. `store.offer_practice_kinds` calls :func:`offer_for` when
a sitting is segmented and again when a piece is labelled, and stores the result with
``practice_kind_basis = 'offered'``, which every aggregate ignores until a person
accepts it.
"""

from __future__ import annotations

from .models import PracticeKind

KINDS: tuple[PracticeKind, ...] = (
    "run_through",
    "slow",
    "section",
    "hands_separate",
    "memory",
    "warm_up",
    "other",
)

#: Bases that count as a label. `offered` is a question, so it counts in nothing.
COUNTED_BASES: frozenset[str] = frozenset({"manual", "accepted"})

#: A segment at or below this fraction of the piece's own typical note rate reads as
#: slower-than-usual practice. Relative to the piece, never to a metronome mark: the log
#: has no score, so there is no target tempo to be slower *than*.
SLOW_RATIO = 0.7

#: How many *other* segments of the piece are needed before "slower than usual" means
#: anything. Two segments are a difference, not a habit.
MIN_BASELINE_SEGMENTS = 3

#: Mid-segment silences that read as section work rather than phrasing.
RESTARTS_FOR_SECTION = 3

#: Below this many notes a segment is too short to characterise at all.
MIN_NOTES_FOR_OFFER = 4


def counted(basis: str | None) -> bool:
    """Is a stored kind a label, or still a question?"""
    return basis in COUNTED_BASES


def offer_for(
    *,
    note_count: int,
    is_sight_reading: bool,
    median_tempo: float | None,
    piece_typical_tempo: float | None,
    piece_baseline_segments: int,
    restarts: int | None,
) -> PracticeKind | None:
    """The one offer this app is willing to make about how a segment went.

    Two rules, both derived from numbers the log already stores:

    * ``slow`` — the segment is at or below :data:`SLOW_RATIO` of the piece's own
      typical note rate, with at least :data:`MIN_BASELINE_SEGMENTS` other segments to
      compare against.
    * ``section`` — the player stopped and started again at least
      :data:`RESTARTS_FOR_SECTION` times, which is what section work looks like from
      the outside.

    ``slow`` is decided first so there is exactly one answer, and **hands-separate is
    never decided at all**: ``mean_velocity_low``/``high`` is a register balance, not a
    measurement of the hands — the piano sends both hands on one channel — and Phase 18b
    refused that claim in the UI. Making it here would break the same promise from the
    other side. Sight-reading is refused for a different reason: ``source`` owns it.

    Register inputs are not parameters at all, which is the strongest form the refusal
    can take.
    """
    if is_sight_reading or note_count < MIN_NOTES_FOR_OFFER:
        return None
    if (
        median_tempo is not None
        and piece_typical_tempo is not None
        and piece_baseline_segments >= MIN_BASELINE_SEGMENTS
        and median_tempo <= piece_typical_tempo * SLOW_RATIO
    ):
        return "slow"
    if restarts is not None and restarts >= RESTARTS_FOR_SECTION:
        return "section"
    return None
