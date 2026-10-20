"""What a decoded confidence is worth, given how much material stood behind it.

The sequence reports a probability, but a probability is only as good as its evidence. A
ten-note fragment in a library of thirty pieces is explained nearly as well by a dozen of
them; the softmax over such thin evidence is smooth, and it is systematically sure of
itself. So the number a short segment reports is not the number of times it is right —
measured, it is not close.

``backend/tools/calibrate_bands.py`` ranks every labelled segment leave-one-out, decodes
each sitting in play order, and records ``(confidence, notes, whether it was right)``.
Pooled over the 8- and 32-piece corpora, whole drills and quarter fragments:

    pieces  notes   written at 0.99   best reachable at any threshold
      any   8-11        71.2 %              ~76 %   (a crowded library)
        8   8-11        85-100 %            100 %   (few pieces, so still unique)
      any   12-24       90.5-98.0 %         98.9 %  (at 0.995)
      any   25-49      100.0 %             100 %
      any   50+        100.0 %             100 %

Two axes, not one, decide it: how long the segment is, and how many pieces could explain
it. A short drill in a library of three pieces is still likely unique; the same drill
against thirty pieces is a coin toss between several. The thresholds below are those
measurements, rounded to the confidence the app already uses, and they only ever *raise*
the bar — a library configured with a stricter probability keeps it.
"""

from __future__ import annotations

#: Above this many pieces the decode is comparing against a crowded library, where a
#: short fragment's confidence stops meaning anything.
CROWDED_PIECES = 8

#: Below this many notes a crowded library cannot be told apart by the material alone.
SHORT_NOTES = 12

#: From this many notes upward the decode's own confidence measured 100% precise.
LONG_NOTES = 25

#: What a medium-length fragment in a crowded library needs instead: measured 98.9%.
CROWDED_CONFIDENCE = 0.995


def auto_probability(*, notes: int, pieces: int, base: float) -> float | None:
    """The confidence a segment of this shape needs before its label is written.

    ``None`` means "never": the measured best precision for that shape is far below what a
    written label is supposed to promise, so the segment is offered instead. ``base`` is
    the configured probability, and is returned unchanged where the measurement found the
    decode trustworthy — the calibration can only add caution.
    """
    if pieces <= CROWDED_PIECES:
        return base
    if notes < SHORT_NOTES:
        return None
    if notes < LONG_NOTES:
        return max(base, CROWDED_CONFIDENCE)
    return base


def writes(*, confidence: float, notes: int, pieces: int, base: float) -> bool:
    """Whether this decoded confidence is allowed to become a label without asking."""
    required = auto_probability(notes=notes, pieces=pieces, base=base)
    return required is not None and confidence >= required
