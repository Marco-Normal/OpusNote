"""Tempo-invariant local content features, and containment over them.

A whole-segment average is a different vector depending on where the cut fell, and it stops
discriminating once the library is large. Measured on this app's own corpus, cutting a query to a
quarter of its length dropped top-1 from 90.3% to 63.9% at eight pieces and from 61.8% to 26.4% at
thirty-two. A bag of local features does not have that problem, because a fragment's features are a
*subset* of the whole's rather than an average of it.

Two details are load-bearing and both were measured:

* **Rhythm is not in the key.** Putting the inter-onset bin into the feature identity cost 7-15
  points, because a slower repeat of the same passage hashed to different keys. Tempo is carried by
  ``similarity.compare`` as its own term instead.
* **Features are pooled per piece, not per segment.** Matching then costs O(pieces) rather than
  O(labels), which is what lets the 600-segment reference window be retired.

Pure: no database, no clock, no configuration import.
"""

from __future__ import annotations

import collections
import math
from typing import Iterable, Mapping, Sequence

from .sessionize import Note

#: Notes this close together are one chord rather than a melody.
CHORD_MS = 60

PITCH_CLASSES = 12

#: Middle C. Below it is the left hand, which is what tells a right-hand drill from a
#: left-hand drill of the same passage.
HAND_SPLIT = 60


def _events(notes: Sequence[Note]) -> list[list]:
    """``[onset, pitches]``, with notes within ``CHORD_MS`` of each other merged."""
    events: list[list] = []
    for note in sorted(notes, key=lambda item: (item.epoch_ms, item.pitch)):
        if events and note.epoch_ms - events[-1][0] <= CHORD_MS:
            events[-1][1].append(note.pitch)
        else:
            events.append([note.epoch_ms, [note.pitch]])
    return events


def _hand(pitch: int) -> str:
    return "L" if pitch < HAND_SPLIT else "R"


def features(notes: Sequence[Note]) -> collections.Counter:
    """The multiset of local content features. Tempo-invariant by construction."""
    events = _events(notes)
    out: collections.Counter = collections.Counter()
    for index, (_, pitches) in enumerate(events):
        for pitch in pitches:
            out[("n", _hand(pitch), pitch % PITCH_CLASSES)] += 1
        if len(pitches) > 1:
            out[("c", frozenset(pitch % PITCH_CLASSES for pitch in pitches))] += 1
        if index + 1 < len(events):
            for first in pitches:
                for second in events[index + 1][1]:
                    if _hand(first) != _hand(second):
                        continue
                    step = max(-12, min(12, second - first))
                    out[("m", _hand(first), first % PITCH_CLASSES,
                         second % PITCH_CLASSES, step)] += 1
    return out


def pooled(parts: Iterable[collections.Counter]) -> collections.Counter:
    """One signature from every part of one piece."""
    total: collections.Counter = collections.Counter()
    for part in parts:
        total.update(part)
    return total


def idf(signatures: Mapping[int, collections.Counter]) -> dict:
    """How much each feature tells pieces apart, over the pieces that exist right now.

    A feature in every piece carries almost nothing; one in a single piece is close to a
    name. This is why the representation gets *better* as the library grows rather than
    worse, and it is the mechanism behind the future-proofing claim.
    """
    document_frequency: collections.Counter = collections.Counter()
    for signature in signatures.values():
        for key in signature:
            document_frequency[key] += 1
    count = max(1, len(signatures))
    return {
        key: math.log((count + 1) / (frequency + 1)) + 0.05
        for key, frequency in document_frequency.items()
    }


def _mass(counter: collections.Counter, weights: Mapping) -> float:
    return sum(weights.get(key, 0.0) * value for key, value in counter.items())


def containment(query: collections.Counter, reference: collections.Counter,
                weights: Mapping) -> float:
    """What share of the *smaller* side's information the two explain.

    Containment rather than cosine, because a drill is a snippet of a piece: cosine would
    punish the query for every feature the piece has that the query does not, which is
    almost all of them.
    """
    numerator = 0.0
    for key, value in query.items():
        weight = weights.get(key, 0.0)
        if weight:
            numerator += weight * min(value, reference.get(key, 0))
    denominator = min(_mass(query, weights), _mass(reference, weights))
    return numerator / denominator if denominator > 0 else 0.0
