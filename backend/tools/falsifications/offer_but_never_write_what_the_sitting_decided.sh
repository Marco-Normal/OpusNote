#!/usr/bin/env bash
#
# Break: write the label the segment's own band would write, ignoring the sitting it sits in.
#
# This is the code as it was before the sequence pass, and the cost is the whole point of
# the pass: a drill too mixed to name on its own — the half-and-half case in the test — is
# written when its neighbours name it, and 93.7% of the owner's segments are written that
# way against 58.5% for the per-segment band. Putting the old band back leaves every score,
# every candidate and every other assertion untouched; only the written label disappears.
#
#   ./check.sh --falsify offer_but_never_write
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_autotag.py -k sitting
# EXPECT: the neighbour's piece
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "            band, _reason = _sequence_verdict(belief, identification)"
assert text.count(needle) == 1, "the write path is not where this script expects it"
path.write_text(
    text.replace(
        needle, "            band, _reason = identification.band, identification.reason", 1
    )
)
PY
