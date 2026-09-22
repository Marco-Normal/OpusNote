#!/usr/bin/env bash
#
# Break: put the rhythm back into the local feature key, so a slower repeat of the same
# passage hashes to different features than the passage itself.
#
# This is the measured mistake the module exists to avoid: carrying the inter-onset bin in
# the key cost 7-15 points on this app's corpus, because "repeat, slower" is a third of what
# a real practice session contains.
#
# The test that must catch it is
# `test_the_same_passage_at_half_speed_is_the_same_features`. The other tests in the file
# still pass with the break applied — a fragment stays a subset of its whole and a
# transposition is still different — which is what makes this test the one that guards the
# tempo-invariance claim rather than the file in general.
#
#   ./falsify.sh backend/tools/falsifications/drop_tempo_invariance.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_shingles.py"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_shingles.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/shingles.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()

# The onset has to be kept to compute the inter-onset interval at all.
loop = "    for index, (_, pitches) in enumerate(events):"
assert loop in text, "the event loop is not where this script expects it"
text = text.replace(loop, "    for index, (onset, pitches) in enumerate(events):", 1)

key = """                    step = max(-12, min(12, second - first))
                    out[("m", _hand(first), first % PITCH_CLASSES,
                         second % PITCH_CLASSES, step)] += 1"""
assert key in text, "the melodic key is not where this script expects it"
text = text.replace(key, """                    step = max(-12, min(12, second - first))
                    # The bin is coarse on purpose: even a coarse one breaks the claim,
                    # which is why the measured variant was dropped rather than tuned.
                    ioi = events[index + 1][0] - onset
                    bucket = 0 if ioi < 150 else (1 if ioi < 300 else 2)
                    out[("m", _hand(first), first % PITCH_CLASSES,
                         second % PITCH_CLASSES, step, bucket)] += 1""", 1)

path.write_text(text)
PY
