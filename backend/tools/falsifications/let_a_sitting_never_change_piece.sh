#!/usr/bin/env bash
#
# Break: make a move between pieces impossible, so a sitting decodes as one piece throughout.
#
# This is the failure mode the switch rate exists to prevent. With the move priced at
# negative infinity no path can ever change piece, and every segment in a sitting takes the
# piece its first confident neighbour named — a label written over practice that really did
# change piece. All the per-segment scores stay correct, so only the switch assertion dies.
#
#   ./check.sh --falsify let_a_sitting_never_change
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_autotag.py -k piece_change
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/sequence.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    move = math.log(switch / (count - 1))"
assert text.count(needle) == 1, "the switch price is not where this script expects it"
path.write_text(
    text.replace(needle, "    move = float('-inf')", 1)
)
PY
