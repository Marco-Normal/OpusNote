#!/usr/bin/env bash
#
# Break: compute the partial band and then throw it away.
#
# The measurement is what makes half-pedalling visible in the log rather than only in
# playback, and it is only visible if it reaches the row: `segment_pedal` builds the
# metrics, the store writes them and `sitting_detail` reads them back. Dropping the value
# at the one place it is assembled leaves the pure function correct and the app blind,
# which is why the test that must catch it is the round trip —
# test_a_partly_depressed_pedal_is_measured_and_kept — rather than the unit tests.
#
#   ./falsify.sh backend/tools/falsifications/drop_the_partial_pedal_ratio.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_practice_store.py -k partly"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_practice_store.py -k partly
# EXPECT: pedal_partial_ratio
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/pedal.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "        partial_ratio=partial_ratio(pedals, span),"
assert needle in text, "the partial ratio is not where this script expects it"
path.write_text(text.replace(needle, "        partial_ratio=0.0,", 1))
PY
