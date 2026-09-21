"""Groups above a segment: the passage, and the piece-session.

Six attempts at one passage are six unrelated rows today, and the owner's own library shows the
pattern plainly: of nineteen consecutive same-piece segment pairs, the musical material is
essentially identical in most of them.

The row the musician wants is the **passage**, with its attempts as the detail; the heading is the
**piece-session**. Both are derived and never stored (22-D1), and the label stays on the segments
(22-D2), so regrouping after an edit loses nothing — the same labels always produce the same groups.

Grouping uses content, not the label. A *differing* label is a hard boundary, because two pieces
are two passages whatever they sound like; a *matching* label is not sufficient on its own, or bars
1-16 and bars 40-60 of one piece would be welded together.

The threshold is measured on this library rather than chosen. Over its 19 same-piece and 20
different-piece adjacent pairs, containment against the *sitting's own* attempts scores a median of
0.886 for same-piece pairs and 0.202 for different-piece ones, and no different-piece pair reaches
0.466. At 0.85 that leaves **0 of the 20 different-piece pairs merged** and 11 of the 19 same-piece
pairs grouped.

The weights come from the sitting rather than from the whole library on purpose: the question is
"is this attempt the same material as the one before it, out of what this sitting contains", and a
library-wide weighting would leave a fresh library — the case where grouping is worth the most —
unable to group anything at all, because there are no labels to weigh features by yet.

Preferring the split is deliberate: two rows for one passage is the status quo and a click to fix,
where a false merge states an attempt count that never happened. So the threshold sits well above
every different-piece pair observed rather than in the middle of the two medians.

Pure: no database, no clock, no configuration import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .shingles import containment

#: Measured on this library: see the module docstring. Well clear of the highest
#: different-piece score observed (0.466) so an unseen piece has margin too.
PASSAGE_SIMILARITY = 0.85


@dataclass(frozen=True)
class Attempt:
    """One stored segment, as the grouping sees it."""

    id: int
    start_ms: int
    end_ms: int
    piece_id: int | None


@dataclass(frozen=True)
class Passage:
    """Adjacent attempts that are the same musical material, and how many there were."""

    start_ms: int
    end_ms: int
    piece_id: int | None
    attempt_ids: tuple[int, ...]

    @property
    def attempts(self) -> int:
        return len(self.attempt_ids)


def derive(
    attempts: Sequence[Attempt],
    signatures: Mapping[int, Mapping],
    weights: Mapping,
    *,
    threshold: float = PASSAGE_SIMILARITY,
) -> list[Passage]:
    """The passages of one sitting, oldest first."""
    if not attempts:
        return []
    groups: list[list[Attempt]] = [[attempts[0]]]
    for previous, attempt in zip(attempts, attempts[1:]):
        if _continues(previous, attempt, signatures, weights, threshold):
            groups[-1].append(attempt)
        else:
            groups.append([attempt])
    return [_passage(group) for group in groups]


def _continues(
    previous: Attempt,
    attempt: Attempt,
    signatures: Mapping[int, Mapping],
    weights: Mapping,
    threshold: float,
) -> bool:
    if previous.piece_id is not None and attempt.piece_id is not None:
        if previous.piece_id != attempt.piece_id:
            return False
        # Same piece is necessary but not sufficient — see the module docstring.
    first, second = signatures.get(previous.id), signatures.get(attempt.id)
    if not first or not second:
        return False
    return containment(second, first, weights) >= threshold


def _passage(group: list[Attempt]) -> Passage:
    return Passage(
        start_ms=group[0].start_ms,
        end_ms=max(attempt.end_ms for attempt in group),
        piece_id=next((a.piece_id for a in group if a.piece_id is not None), None),
        attempt_ids=tuple(attempt.id for attempt in group),
    )


def piece_sessions(passages: Sequence[Passage]) -> list[tuple[int | None, tuple[int, ...]]]:
    """Adjacent passages sharing a piece, as ``(piece_id, passage indices)``."""
    if not passages:
        return []
    out: list[tuple[int | None, list[int]]] = [(passages[0].piece_id, [0])]
    for index, passage in enumerate(passages[1:], start=1):
        if passage.piece_id is not None and passage.piece_id == out[-1][0]:
            out[-1][1].append(index)
        else:
            out.append((passage.piece_id, [index]))
    return [(piece, tuple(members)) for piece, members in out]
