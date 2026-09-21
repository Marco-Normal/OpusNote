#!/usr/bin/env python
"""Measure the matcher on drill-shaped practice, and choose its weights.

The design in `practice-logger/docs/DESIGN.md` §5 fixed the three weights at
0.60/0.25/0.15 while assuming whole-piece run-throughs. Real practice is sections,
at whatever tempo the section needed, sometimes on one hand — so the weights are
measured here instead of inherited, and the result is what
`similarity.DEFAULT_WEIGHTS` holds.

The corpus comes from the app's own exercise generator rather than from invented
note lists, because the question is whether the matcher works on *this* music. Each
"piece" is a key plus a character, each drill is a few bars of it under one of the
transformations a player actually applies, and every drill is labelled with its
piece. Two pieces deliberately share a key, because that is the matcher's documented
failure mode and a corpus without it would flatter the result.

Nothing is graded on material it was trained on: the headline number is
leave-one-out, and the cold-start table trains on the first few drills of each piece
and tests on the rest, which is what the first weeks of use look like. A third table
truncates every drill to its first N notes, which is what a *shorter* segment would have
to be recognised from — the measurement behind keeping the segment threshold where it is
rather than cutting playing into two-bar pieces.

Usage::

    backend/.venv/bin/python backend/tools/measure_autotag.py [--verbose]

It reads no database and writes nothing: it is a measurement, not a migration.
"""

from __future__ import annotations

import argparse
import collections
import random
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.music import generator  # noqa: E402
from app.music.expected import extract_expected  # noqa: E402
from app.practice import shingles  # noqa: E402
from app.practice.sessionize import Note  # noqa: E402
from app.practice.similarity import (  # noqa: E402
    DEFAULT_WEIGHTS,
    Example,
    Weights,
    fingerprint,
    identify,
)

#: Keys cycled to synthesise a larger library than the eight hand-written pieces. Two
#: pieces sharing a key is the matcher's documented failure mode, so repetition is the
#: point rather than a compromise.
KEYS = ("C", "G", "D", "A", "E", "B", "F#", "Db", "Ab", "Eb", "Bb", "F",
        "a", "e", "b", "f#", "d", "g", "c", "bb")


def pieces_for(count: int) -> tuple[tuple[str, str, dict[str, int]], ...]:
    """``count`` distinct pieces, cycling keys and varying the character."""
    return tuple(
        (f"piece-{index:02d}", KEYS[index % len(KEYS)], {
            "hand_position": 3 + (index % 6),
            "intervals": 3 + ((index * 2) % 6),
            "rhythm": 3 + ((index * 3) % 6),
            "texture": 3 + ((index * 5) % 6),
            "key_signature": 1 + (index % 5),
        })
        for index in range(count)
    )


#: Each "piece" is a key and a character.
PIECES: tuple[tuple[str, str, dict[str, int]], ...] = (
    ("Bach", "C", {"hand_position": 3, "intervals": 3, "rhythm": 4, "texture": 3, "key_signature": 1}),
    ("Brahms", "a", {"hand_position": 4, "intervals": 4, "rhythm": 5, "texture": 6, "key_signature": 3}),
    ("Chopin", "Eb", {"hand_position": 5, "intervals": 5, "rhythm": 6, "texture": 5, "key_signature": 4}),
    ("Debussy", "C", {"hand_position": 6, "intervals": 6, "rhythm": 7, "texture": 6, "key_signature": 1}),
    ("Liszt", "Db", {"hand_position": 7, "intervals": 7, "rhythm": 8, "texture": 7, "key_signature": 5}),
    ("Mozart", "G", {"hand_position": 4, "intervals": 3, "rhythm": 3, "texture": 4, "key_signature": 1}),
    ("Prokofiev", "e", {"hand_position": 8, "intervals": 7, "rhythm": 6, "texture": 6, "key_signature": 3}),
    ("Ravel", "A", {"hand_position": 6, "intervals": 8, "rhythm": 7, "texture": 7, "key_signature": 4}),
)

#: How many drills per piece, and how many bars each. A drill is a *section*, so
#: shorter than the four-bar exercises the app serves.
DRILLS_PER_PIECE = 9
DRILL_BARS = 3
ATTACK_WINDOW_MS = 50

#: One drill in three repeats an earlier passage slower, which is what repeated
#: section practice looks like and what the matcher most needs to get right.
REPEAT_SHARE = 0.34


@dataclass(frozen=True)
class Drill:
    piece_id: int
    label: str
    notes: list[Note]
    transform: str


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------


def _slice(expected, *, bars: int):
    """The first `bars` bars of an exercise, as a section to drill."""
    measures = sorted({note.measure for note in expected})
    keep = set(measures[:bars])
    return [note for note in expected if note.measure in keep]


def _to_notes(
    expected, *, tempo_bpm: float, tempo_scale: float, base_ms: int, hands: set[str] | None
) -> list[Note]:
    """Expected notes as if played: a tempo, a hand or both, starting at `base_ms`."""
    seconds_per_quarter = 60.0 / tempo_bpm
    notes: list[Note] = []
    for item in expected:
        if hands is not None and item.hand not in hands:
            continue
        notes.append(
            Note(
                epoch_ms=base_ms + int(round(item.onset_s * 1000 * tempo_scale)),
                pitch=item.pitch,
                velocity=70,
                duration_ms=max(30, int(round(item.duration_q * seconds_per_quarter * 1000 * tempo_scale))),
                channel=0,
            )
        )
    return notes


def _with_slips(notes: list[Note], rng: random.Random) -> list[Note]:
    """A couple of wrong notes and a dropped one, because nobody plays clean."""
    out: list[Note] = []
    for note in notes:
        if rng.random() < 0.02:
            continue  # a note that did not sound
        pitch = note.pitch + (rng.choice((-1, 1)) if rng.random() < 0.05 else 0)
        out.append(
            Note(
                epoch_ms=note.epoch_ms,
                pitch=max(21, min(108, pitch)),
                velocity=note.velocity,
                duration_ms=note.duration_ms,
                channel=note.channel,
            )
        )
    return out


def build_corpus(seed: int = 20260913, pieces=None) -> list[Drill]:
    """Nine drills per piece, covering the transformations that actually happen."""
    global PIECES
    if pieces is not None:
        PIECES = tuple(pieces)
    rng = random.Random(seed)
    drills: list[Drill] = []
    base_ms = 1_700_011_800_000

    for piece_id, (label, key, levels) in enumerate(PIECES):
        sections: dict[int, tuple[list, float]] = {}
        for index in range(DRILLS_PER_PIECE):
            exercise = generator.generate_exercise(
                levels, bars=DRILL_BARS, seed=seed + piece_id * 100 + index, key_name=key
            )
            expected = _slice(
                extract_expected(exercise.score, exercise.tempo_bpm), bars=DRILL_BARS
            )
            sections[index] = (expected, exercise.tempo_bpm)

        for index, (expected, tempo) in sections.items():
            if index >= 3 and rng.random() < REPEAT_SHARE:
                source, source_tempo = sections[rng.randrange(0, index)]
                transform = "repeat, slower"
                notes = _to_notes(
                    source,
                    tempo_bpm=source_tempo,
                    tempo_scale=1.45,
                    base_ms=base_ms,
                    hands=None,
                )
            elif index % 4 == 1:
                transform = "right hand only"
                notes = _to_notes(
                    expected, tempo_bpm=tempo, tempo_scale=1.0, base_ms=base_ms, hands={"RH"}
                )
            elif index % 4 == 2:
                transform = "left hand only"
                notes = _to_notes(
                    expected, tempo_bpm=tempo, tempo_scale=1.2, base_ms=base_ms, hands={"LH"}
                )
            elif index % 4 == 3:
                transform = "slow, staccato"
                notes = [
                    Note(
                        epoch_ms=note.epoch_ms,
                        pitch=note.pitch,
                        velocity=note.velocity,
                        duration_ms=80,
                        channel=0,
                    )
                    for note in _to_notes(
                        expected, tempo_bpm=tempo, tempo_scale=1.6, base_ms=base_ms, hands=None
                    )
                ]
            else:
                transform = "at tempo"
                notes = _to_notes(
                    expected, tempo_bpm=tempo, tempo_scale=1.0, base_ms=base_ms, hands=None
                )

            notes = _with_slips(notes, rng)
            if len(notes) >= 4:
                drills.append(Drill(piece_id, label, notes, transform))
    return drills


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------


@dataclass
class Outcome:
    correct_top: int = 0
    correct_top3: int = 0
    total: int = 0
    auto_attempted: int = 0
    auto_correct: int = 0
    offered_attempted: int = 0
    offered_correct: int = 0
    unidentified: int = 0
    by_transform: dict = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        return self.correct_top / self.total if self.total else 0.0

    @property
    def top3_accuracy(self) -> float:
        return self.correct_top3 / self.total if self.total else 0.0

    @property
    def auto_coverage(self) -> float:
        return self.auto_attempted / self.total if self.total else 0.0

    @property
    def auto_precision(self) -> float:
        return self.auto_correct / self.auto_attempted if self.auto_attempted else 0.0

    @property
    def offered_coverage(self) -> float:
        return self.offered_attempted / self.total if self.total else 0.0

    @property
    def offered_precision(self) -> float:
        return self.offered_correct / self.offered_attempted if self.offered_attempted else 0.0


def _examples(drills: list[Drill], indices: list[int]) -> list[Example]:
    return [
        Example(
            segment_id=index,
            piece_id=drills[index].piece_id,
            fingerprint=fingerprint(drills[index].notes, attack_window_ms=ATTACK_WINDOW_MS),
        )
        for index in indices
    ]


def first_notes(drill: Drill, keep: int) -> Drill:
    """The same drill as if the player had stopped after ``keep`` notes.

    A segment is however long the player played without a long pause, which is a
    different thing from a section: this is what a *shorter* segment would have to
    be recognised from, and it is why a very fine segmentation is not free.
    """
    return Drill(drill.piece_id, drill.label, drill.notes[:keep], drill.transform)


def middle_notes(drill: Drill, fraction: float, rng: random.Random) -> Drill:
    """A contiguous middle chunk — a legitimate sub-snippet.

    This is the axis the existing truncation table does not cover: ``first_notes`` asks
    what a *shorter* drill would need, and this asks what a drill looks like when the
    boundary fell somewhere else. Acceptance 1 is about the second question.
    """
    if fraction >= 1.0:
        return drill
    count = len(drill.notes)
    keep = max(1, int(count * fraction))
    start = rng.randrange(0, max(1, count - keep + 1))
    return Drill(drill.piece_id, drill.label, drill.notes[start:start + keep], drill.transform)


def evaluate(
    drills: list[Drill],
    *,
    weights: Weights,
    score_auto: float = 0.85,
    score_prompt: float = 0.55,
    min_margin: float = 0.10,
    min_notes: int = 8,
    train_size: int | None = None,
    use_context: bool = False,
) -> Outcome:
    """Score every drill against labelled examples.

    ``train_size=None`` is leave-one-out over all of them. A number trains on that
    many drills per piece — the first ones, in play order — and tests only on the
    rest, which is the honest picture of a library that is still mostly untagged.
    """
    all_examples = _examples(drills, list(range(len(drills))))
    if train_size is None:
        train: list[Example] = all_examples
        test_indices = list(range(len(drills)))
        extra_exclusion = True
    else:
        per_piece: dict[int, list[int]] = {}
        for index, drill in enumerate(drills):
            per_piece.setdefault(drill.piece_id, []).append(index)
        keep: list[int] = []
        for indices in per_piece.values():
            keep.extend(indices[:train_size])
        train = _examples(drills, keep)
        test_indices = [index for index in range(len(drills)) if index not in set(keep)]
        extra_exclusion = False
        if not train or not test_indices:
            return Outcome()

    by_id = {example.segment_id: example for example in all_examples}
    outcome = Outcome()
    for index in test_indices:
        others = [
            example for example in train if not (extra_exclusion and example.segment_id == index)
        ]
        # What the sitting is already about: the previous segment's label, which in
        # one-piece-at-a-time practice is the same piece. Only a segment that is
        # already labelled can provide it, exactly as in the app.
        context = None
        if use_context and index > 0:
            previous = drills[index - 1]
            if previous.piece_id == drills[index].piece_id or True:
                context = previous.piece_id if index - 1 in {e.segment_id for e in train} else None

        identification = identify(
            by_id[index].fingerprint,
            others,
            score_auto=score_auto,
            score_prompt=score_prompt,
            min_margin=min_margin,
            min_notes=min_notes,
            weights=weights,
            context_piece_id=context,
        )
        truth = drills[index].piece_id
        top = identification.candidates[0].piece_id if identification.candidates else None
        outcome.total += 1
        outcome.by_transform.setdefault(drills[index].transform, Outcome()).total += 1
        outcome.by_transform[drills[index].transform].correct_top += int(top == truth)
        outcome.correct_top += int(top == truth)
        outcome.correct_top3 += int(truth in [c.piece_id for c in identification.candidates[:3]])
        if identification.band == "auto":
            outcome.auto_attempted += 1
            outcome.auto_correct += int(top == truth)
        elif identification.band == "suggest":
            outcome.offered_attempted += 1
            outcome.offered_correct += int(top == truth)
        else:
            outcome.unidentified += 1
    return outcome


def evaluate_fragments(
    drills: list[Drill],
    *,
    fraction: float,
    weights: Weights = DEFAULT_WEIGHTS,
    containment_weight: float = 0.0,
    score_auto: float = 0.85,
    score_prompt: float = 0.55,
    min_margin: float = 0.10,
    min_notes: int = 8,
    seed: int = 7,
) -> Outcome:
    """Leave-one-out top-1 when the query is a *middle chunk* of a whole drill.

    This is the axis the "first N notes" table does not cover. There, the query is a drill
    that stopped early and the reference is equally short; here the reference is the whole
    drill and the query is what the same playing looks like when the segment boundary fell
    somewhere else. It is the question acceptance 1 and 2 are actually about.

    ``containment_weight=0.0`` is the current global fingerprint alone; anything above it
    adds Phase 22b's local content term, mixed exactly as the live matcher mixes it — the
    coefficients and the ranking both come from ``similarity``, so this table measures the
    shipped scorer rather than a second implementation of it.
    """
    rng = random.Random(seed)
    queries = [middle_notes(drill, fraction, rng) for drill in drills]
    references = _examples(drills, list(range(len(drills))))
    features = [shingles.features(drill.notes) for drill in drills]
    pooled: dict[int, collections.Counter] = {}
    for index, drill in enumerate(drills):
        pooled.setdefault(drill.piece_id, collections.Counter()).update(features[index])

    outcome = Outcome()
    for index, query in enumerate(queries):
        truth = drills[index].piece_id
        signatures = {piece: sig for piece, sig in pooled.items() if piece != truth}
        remainder = pooled[truth] - features[index]
        if remainder:
            signatures[truth] = remainder
        shares = None
        if containment_weight > 0 and signatures:
            feature_weights = shingles.idf(signatures)
            query_features = shingles.features(query.notes)
            shares = {
                piece_id: shingles.containment(query_features, signature, feature_weights)
                for piece_id, signature in signatures.items()
            }
        identification = identify(
            fingerprint(query.notes, attack_window_ms=ATTACK_WINDOW_MS),
            [example for example in references if example.segment_id != index],
            score_auto=score_auto,
            score_prompt=score_prompt,
            min_margin=min_margin,
            min_notes=min_notes,
            weights=weights,
            shares=shares,
            containment_weight=containment_weight,
        )
        top = identification.candidates[0].piece_id if identification.candidates else None
        outcome.total += 1
        outcome.correct_top += int(top == truth)
        outcome.correct_top3 += int(
            truth in [candidate.piece_id for candidate in identification.candidates[:3]]
        )
        if identification.band == "auto":
            outcome.auto_attempted += 1
            outcome.auto_correct += int(top == truth)
        elif identification.band == "suggest":
            outcome.offered_attempted += 1
            outcome.offered_correct += int(top == truth)
        else:
            outcome.unidentified += 1
    return outcome


def report(label: str, outcome: Outcome) -> None:
    """Percentages with their counts beside them.

    A precision of 100% over thirteen decisions and over three hundred are not the
    same claim, and a report that hides which one it is invites the wrong reading.
    """
    print(
        f"  {label:<26} top-1 {outcome.accuracy:6.1%} ({outcome.correct_top}/{outcome.total})  "
        f"top-3 {outcome.top3_accuracy:6.1%}  "
        f"auto {outcome.auto_coverage:5.1%} @ {outcome.auto_precision:6.1%} "
        f"({outcome.auto_correct}/{outcome.auto_attempted})  "
        f"offered {outcome.offered_coverage:5.1%} @ {outcome.offered_precision:6.1%} "
        f"({outcome.offered_correct}/{outcome.offered_attempted})  "
        f"silent {outcome.unidentified}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--seed", type=int, default=20260913)
    args = parser.parse_args()

    drills = build_corpus(args.seed)
    by_piece: dict[str, int] = {}
    for drill in drills:
        by_piece[drill.label] = by_piece.get(drill.label, 0) + 1
    shapes = [len(drill.notes) for drill in drills]
    print(f"Corpus: {len(drills)} drills over {len(by_piece)} pieces, seed {args.seed}")
    print("  " + ", ".join(f"{name} {count}" for name, count in sorted(by_piece.items())))
    print(
        f"  notes per drill: min {min(shapes)} median {statistics.median(shapes):.0f} "
        f"max {max(shapes)}"
    )
    counts: dict[str, int] = {}
    for drill in drills:
        counts[drill.transform] = counts.get(drill.transform, 0) + 1
    print("  " + ", ".join(f"{name}: {count}" for name, count in sorted(counts.items())))

    print("\nWeights, leave-one-out:")
    results: list[tuple[str, Weights, Outcome]] = []
    for label, weights in (
        ("design 0.60/0.25/0.15", Weights(0.60, 0.25, 0.15)),
        ("tempo halved", Weights(0.70, 0.12, 0.18)),
        ("tempo light", Weights(0.75, 0.10, 0.15)),
        ("tempo off", Weights(0.85, 0.00, 0.15)),
        ("pitch only", Weights(1.00, 0.00, 0.00)),
        ("register heavy", Weights(0.65, 0.10, 0.25)),
    ):
        outcome = evaluate(drills, weights=weights)
        results.append((label, weights, outcome))
        report(label, outcome)

    print(f"\nBands at the shipped weights, with the sitting context applied:")
    for auto, prompt, margin in (
        (0.90, 0.60, 0.12),
        (0.85, 0.55, 0.10),
        (0.85, 0.55, 0.05),
        (0.80, 0.50, 0.05),
        (0.75, 0.50, 0.00),
    ):
        outcome = evaluate(
            drills,
            weights=DEFAULT_WEIGHTS,
            score_auto=auto,
            score_prompt=prompt,
            min_margin=margin,
            use_context=True,
        )
        report(f"auto {auto} margin {margin}", outcome)

    print(f"\nBy kind of drill, leave-one-out at the shipped weights:")
    broken_down = evaluate(drills, weights=DEFAULT_WEIGHTS)
    for transform, outcome in sorted(broken_down.by_transform.items()):
        print(f"  {transform:<18} {outcome.correct_top:2d}/{outcome.total:<2d} correct")

    print(
        "\nHow much playing one segment needs, leave-one-out at the shipped weights"
        f" (a drill is {DRILL_BARS} bars, {int(statistics.median(shapes))} notes at the median):"
    )
    for keep in (4, 8, 12, 16, 24, 32, None):
        subset = drills if keep is None else [first_notes(drill, keep) for drill in drills]
        report(
            "whole drill" if keep is None else f"first {keep} notes",
            evaluate(subset, weights=DEFAULT_WEIGHTS),
        )

    print(f"\nWhat the sitting is already about (near-ties broken towards it):")
    for label, use_context in (("without context", False), ("with context", True)):
        outcome = evaluate(drills, weights=DEFAULT_WEIGHTS, use_context=use_context)
        report(label, outcome)

    print(f"\nCold start at the shipped weights and bands ({DEFAULT_WEIGHTS}):")
    for train_size in (1, 2, 4, 6):
        outcome = evaluate(drills, weights=DEFAULT_WEIGHTS, train_size=train_size)
        report(f"{train_size} drill(s) per piece", outcome)

    best = max(results, key=lambda item: (item[2].correct_top, item[2].auto_precision))
    print(f"\nBest top-1 among the schemes tried: {best[0]} ({best[2].accuracy:.1%})")
    print(f"Shipped default: {DEFAULT_WEIGHTS}")

    print(
        "\nHow much of the score should come from content rather than from the whole-segment"
        "\naverage (22-D7 chooses `autotag_containment_weight` from this). The query is a middle"
        f"\nchunk of a whole drill, at eight pieces, seed {args.seed}:"
    )
    print(f"  {'containment':>11} | {'whole':>7} {'quarter':>8} {'auto@whole':>10} {'auto@quarter':>12}")
    for containment in (0.0, 0.15, 0.25, 0.40, 0.50):
        whole = evaluate_fragments(drills, fraction=1.0, containment_weight=containment)
        quarter = evaluate_fragments(drills, fraction=0.25, containment_weight=containment)
        print(
            f"  {containment:>11.2f} | {whole.accuracy:>7.1%} {quarter.accuracy:>8.1%} "
            f"{whole.auto_precision:>10.1%} {quarter.auto_precision:>12.1%}"
        )

    print(
        "\nAcceptance 2 — does the mix survive a growing library? References are whole drills,"
        f"\nthe query is a middle chunk of one, seed {args.seed}, containment "
        f"{settings.autotag_containment_weight}:"
    )
    print(f"  {'pieces':>6} {'frag':>6} | {'current':>8} {'hybrid':>8} {'gain':>7}")
    for count in (8, 16, 32):
        corpus = build_corpus(pieces=pieces_for(count))
        for fraction in (1.0, 0.25):
            current = evaluate_fragments(corpus, fraction=fraction, containment_weight=0.0)
            hybrid = evaluate_fragments(
                corpus, fraction=fraction, containment_weight=settings.autotag_containment_weight
            )
            print(
                f"  {count:>6} {fraction:>6.0%} | {current.accuracy:>8.1%} "
                f"{hybrid.accuracy:>8.1%} {hybrid.accuracy - current.accuracy:>+7.1%}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
