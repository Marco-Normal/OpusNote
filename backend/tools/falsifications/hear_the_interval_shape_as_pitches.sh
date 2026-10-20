#!/usr/bin/env bash
#
# Break: count the notes an interval *arrives on* instead of the interval between them.
#
# The interval term's whole claim is that it does not care which key the passage was played
# in. Counting pitch classes throws that away: the same tune transposed by three semitones
# then shares almost nothing with itself, and only the transposition assertion dies.
#
#   ./check.sh --falsify hear_the_interval_shape_as_pitches
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_similarity.py -k another_key
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/similarity.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "            intervals[(note.pitch - previous.pitch) % PITCH_CLASSES] += 1"
assert text.count(needle) == 1, "the interval build is not where this script expects it"
path.write_text(
    text.replace(needle, "            intervals[note.pitch % PITCH_CLASSES] += 1", 1)
)
PY
