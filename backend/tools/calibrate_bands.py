#!/usr/bin/env python
"""How trustworthy is a decoded confidence, by how much material stood behind it?

The band asks one question — "is this decode probably right?" — and answers it with the
decode's own probability. That probability is only as good as its evidence: a ten-note
fragment in a library of thirty pieces is explained nearly as well by a dozen of them, and
the softmax over such thin evidence is smooth and sure of itself. This script measures the
gap between the number and the frequency.

The corpora are the app's own generator (`measure_autotag.py`), because the question is
what happens on *this* music. Each drill is ranked leave-one-out exactly as the store ranks
a segment (22e weights, containment 0.25), the drills are grouped into sittings of eight,
and each sitting is decoded with the shipped switch and temperature. The result is one
sample per segment — ``(decoded confidence, note count, whether the decode was right)`` —
tabulated by note count against a few confidence thresholds.

The real library contributes only its long band, because 429 of the owner's 443 labelled
segments hold 25 notes or more, where the decode measured 100% precise at 0.99; the short
bands, which is where the recorded false write lives (quarter-length fragments at 32 pieces:
24% coverage at 72.5% precision), are what this script is for. The numbers it produces are
what `app/practice/calibration.py` holds.

Usage::

    backend/.venv/bin/python backend/tools/calibrate_bands.py

It reads no database and writes nothing: it is a measurement, not a migration.
"""

from __future__ import annotations

import collections
import random
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS.parent))
sys.path.insert(0, str(_TOOLS))

from app.practice import sequence, shingles, similarity  # noqa: E402
from measure_autotag import (  # noqa: E402
    ATTACK_WINDOW_MS,
    build_corpus,
    middle_notes,
    pieces_for,
)

BANDS = ((8, 11), (12, 24), (25, 49), (50, 10**9))
THRESHOLDS = (0.90, 0.95, 0.99, 0.995, 0.999)


def band_of(notes: int) -> str:
    for low, high in BANDS:
        if low <= notes <= high:
            return f"{low}-{high if high < 10**9 else '+'}"
    return "short"


def samples(pieces: int, *, fraction: float) -> list[tuple[float, int, bool]]:
    corpus = build_corpus(pieces=pieces_for(pieces))
    rng = random.Random(7)
    queries = [middle_notes(drill, fraction, rng) for drill in corpus]
    prints = [
        similarity.fingerprint(q.notes, attack_window_ms=ATTACK_WINDOW_MS) for q in queries
    ]
    features = [shingles.features(q.notes) for q in queries]
    examples = [
        similarity.Example(
            segment_id=index,
            piece_id=drill.piece_id,
            fingerprint=similarity.fingerprint(
                drill.notes, attack_window_ms=ATTACK_WINDOW_MS
            ),
        )
        for index, drill in enumerate(corpus)
    ]
    pooled: dict[int, collections.Counter] = {}
    for index, drill in enumerate(corpus):
        pooled.setdefault(drill.piece_id, collections.Counter()).update(features[index])

    out: list[tuple[float, int, bool]] = []
    order = list(range(len(corpus)))
    for start in range(0, len(order), 8):  # sittings of eight drills
        keys = order[start : start + 8]
        fragments = []
        for index in keys:
            truth = corpus[index].piece_id
            signatures = {
                piece: (pooled[piece] - features[index]) if piece == truth else sig
                for piece, sig in pooled.items()
            }
            signatures = {piece: sig for piece, sig in signatures.items() if sig}
            weights = shingles.idf(signatures)
            shares = {
                piece: shingles.containment(features[index], signature, weights)
                for piece, signature in signatures.items()
            }
            ranked = similarity.rank(
                prints[index],
                [e for e in examples if e.segment_id != index],
                shares=shares,
                containment_weight=0.25,
            )
            fragments.append(
                sequence.Fragment(
                    key=index,
                    options=tuple(sequence.Option(c.piece_id, c.score) for c in ranked),
                    notes=prints[index].note_count,
                )
            )
        for belief in sequence.decode(fragments, switch=0.10, temperature=0.02):
            truth = corpus[belief.key].piece_id
            out.append((belief.confidence, belief.notes, belief.chosen == truth))
    return out


def table(samples_: list[tuple[float, int, bool]]) -> None:
    grouped: dict[str, list[tuple[float, bool]]] = collections.defaultdict(list)
    for confidence, notes, correct in samples_:
        grouped[band_of(notes)].append((confidence, correct))
    print(f"{'notes':>8} {'n':>5} | " + " ".join(f"{t:>14}" for t in THRESHOLDS))
    for band in [f"{a}-{b if b < 10**9 else '+'}" for a, b in BANDS]:
        rows = grouped.get(band, [])
        if not rows:
            continue
        cells = []
        for threshold in THRESHOLDS:
            kept = [correct for confidence, correct in rows if confidence >= threshold]
            cells.append(
                f"{len(kept):>4}@{sum(kept) / len(kept):>5.1%}"
                if kept
                else "     -        "
            )
        print(f"{band:>8} {len(rows):>5} | " + " ".join(cells))


if __name__ == "__main__":
    everything: list[tuple[float, int, bool]] = []
    for pieces in (8, 32):
        for fraction in (1.0, 0.25):
            got = samples(pieces, fraction=fraction)
            print(
                f"\n=== {pieces} pieces, query {fraction:.0%} of a drill ({len(got)} samples)"
            )
            table(got)
            everything.extend(got)
    print("\n=== pooled")
    table(everything)
