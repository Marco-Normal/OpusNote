#!/usr/bin/env python
"""Measure the matcher on the real library, and how much segmentation moves it.

Reads a backup document **if it is there** and prints one line and exits 0 if it is not, because
the fixture is local-only (`docs/TEST-DATA.md`) and a tool that fails on a clean checkout is worse
than no tool.

The axis that matters is acceptance 1. Re-cut every sitting at other gap floors, inherit each new
window's piece from the stored segment its midpoint falls inside, and report top-1. A
representation is only "robust to segmentation" if that curve is flat. The `hybrid` column is
acceptance 3's floor — the same number the app's own quality report computes.

Both columns come from ``similarity.rank``, so this measures the scorer that ships rather than a
second copy of the arithmetic.

Nothing is written and no database is read: it is a measurement.

Usage::

    backend/.venv/bin/python backend/tools/measure_real.py [--path PATH] [--alpha 0.75]
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.practice import segment, shingles
from app.practice.sessionize import Note
from app.practice import similarity as S

#: The corpus is local-only and lives beside the repository, exactly as `docs/TEST-DATA.md`
#: documents it (`../piano-ecosystem-backup(3).json`), so the default is the repo root's parent.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO_ROOT.parent / "piano-ecosystem-backup(3).json"

#: The floors to re-cut at. The chosen one should sit in the flat part of the curve.
FLOORS_MS = (1_000, 2_000, 4_000, 8_000, 16_000)


def load(path: Path):
    document = json.loads(path.read_text())
    tables = document["tables"]
    notes: dict[int, list[Note]] = collections.defaultdict(list)
    for row in tables["note_events"]:
        notes[row["sitting_id"]].append(
            Note(row["onset_ms"], row["pitch"], row["velocity"], row["duration_ms"], row["channel"])
        )
    return tables, notes


def recut(notes, stored, config: segment.Config):
    """Re-cut one sitting, inheriting the piece of the stored segment each window lands in."""
    ordered = sorted(notes, key=lambda note: (note.epoch_ms, note.pitch))
    out: list[tuple[list[Note], int]] = []
    for window in segment.cut(ordered, config=config):
        middle = (window.start_ms + window.end_ms) // 2
        owner = next(
            (row["piece_id"] for row in stored if row["start_ms"] <= middle < row["end_ms"]), None
        )
        inside = [n for n in ordered if window.start_ms <= n.epoch_ms < window.end_ms]
        if owner is not None and inside:
            out.append((inside, owner))
    return out


def evaluate(items, *, containment_weight: float):
    """Leave-one-out top-1 and band outcomes for the current score and for the hybrid.

    ``containment_weight=0.0`` is the global term alone, which is what the app shipped before
    Phase 22b; anything above it mixes in the local content term. Leave-one-out over the pooled
    signatures too, so the segment being asked about is never part of the evidence answering it.

    The auto figures are the ones acceptance 4 turns on: coverage is how many attempts the
    matcher would label without asking, and precision is how many of those it would get right.
    """
    prints = [S.fingerprint(notes, attack_window_ms=settings.attack_window_ms) for notes, _ in items]
    local = [shingles.features(notes) for notes, _ in items]
    pooled: dict[int, collections.Counter] = {}
    for (_, piece), features in zip(items, local):
        pooled.setdefault(piece, collections.Counter()).update(features)

    current = hybrid = auto_attempted = auto_correct = 0
    for index, (_, piece) in enumerate(items):
        examples = [
            S.Example(segment_id=other, piece_id=other_piece, fingerprint=prints[other])
            for other, (_, other_piece) in enumerate(items)
            if other != index
        ]
        signatures = {found: sig for found, sig in pooled.items() if found != piece}
        remainder = pooled[piece] - local[index]
        if remainder:
            signatures[piece] = remainder
        shares: dict[int, float] = {}
        if signatures:
            feature_weights = shingles.idf(signatures)
            shares = {
                found: shingles.containment(local[index], signature, feature_weights)
                for found, signature in signatures.items()
            }
        plain = S.rank(prints[index], examples)
        mixed = S.identify(
            prints[index],
            examples,
            score_auto=settings.autotag_score_auto,
            score_prompt=settings.autotag_score_prompt,
            min_margin=settings.autotag_min_margin,
            min_notes=settings.autotag_min_notes,
            shares=shares,
            containment_weight=containment_weight,
        )
        top = mixed.best.piece_id if mixed.best else None
        current += bool(plain) and plain[0].piece_id == piece
        hybrid += top == piece
        if mixed.band == "auto":
            auto_attempted += 1
            auto_correct += top == piece
    count = max(1, len(items))
    return {
        "current": current / count,
        "hybrid": hybrid / count,
        "items": len(items),
        "auto_coverage": auto_attempted / count,
        "auto_precision": (auto_correct / auto_attempted) if auto_attempted else 0.0,
        "auto_attempted": auto_attempted,
        "auto_correct": auto_correct,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument(
        "--alpha",
        type=float,
        default=1.0 - settings.autotag_containment_weight,
        help="weight on the global term; the rest goes to containment (default: the shipped one)",
    )
    args = parser.parse_args()

    if not args.path.exists():
        print(f"no real corpus at {args.path}; skipping (see docs/TEST-DATA.md)")
        return 0

    tables, notes = load(args.path)
    stored: dict[int, list[dict]] = collections.defaultdict(list)
    for row in tables["segments"]:
        stored[row["sitting_id"]].append(row)

    print(f"REAL library: {len(notes)} sittings, {len(tables['segments'])} stored segments")
    band = (
        f"auto {settings.autotag_score_auto} / prompt {settings.autotag_score_prompt}"
        f" / margin {settings.autotag_min_margin}"
    )
    print(f"alpha={args.alpha:.2f} (weight on the global term); shipped band {band}\n")
    print(f"{'floor':>7} {'segments':>9} {'median notes':>13} | {'current':>8} {'hybrid':>8}"
          f" | {'auto cov':>8} {'auto prec':>9}")
    rows: list[tuple[int, int, float, float, float]] = []
    for floor in FLOORS_MS:
        items: list[tuple[list[Note], int]] = []
        for sitting_id, sitting_notes in notes.items():
            items.extend(
                recut(sitting_notes, stored.get(sitting_id, []), segment.Config(floor_ms=floor))
            )
        if len(items) < 5:
            continue
        sizes = sorted(len(names) for names, _ in items)
        found = evaluate(items, containment_weight=1.0 - args.alpha)
        rows.append(
            (floor, found["items"], found["hybrid"], found["auto_coverage"],
             found["auto_precision"])
        )
        print(f"{floor:>6}ms {found['items']:>9} {sizes[len(sizes) // 2]:>13} | "
              f"{found['current']:>8.1%} {found['hybrid']:>8.1%} | "
              f"{found['auto_coverage']:>8.1%} {found['auto_precision']:>9.1%}")

    chosen = next((row for row in rows if row[0] == settings.segment_floor_ms), None)
    if chosen is None:
        print(f"\nno row at the shipped floor {settings.segment_floor_ms}ms; cannot judge acceptance 1")
        return 0
    neighbours = [row for row in rows if row[0] in {chosen[0] // 2, chosen[0] * 2}]
    print(f"\nacceptance 1 at the shipped {chosen[0]}ms floor: hybrid {chosen[2]:.1%}")
    for floor, _count, hybrid, _cov, _prec in neighbours:
        spread = abs(hybrid - chosen[2])
        verdict = "within" if spread <= 0.03 else "OUTSIDE"
        print(f"  vs {floor:>6}ms {hybrid:.1%}: {spread * 100:.1f} points — {verdict} the 3-point bound")
    print(f"\nacceptance 3: hybrid top-1 {chosen[2]:.1%} against a 94% floor")
    print(f"acceptance 4: auto coverage {chosen[3]:.1%} (floor 50%), "
          f"precision {chosen[4]:.1%} (floor 95%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
