#!/usr/bin/env bash
#
# Break: report zero share of the span in the partial pedal band.
#
# The measurement is what makes half-pedalling visible in the log rather than only in
# playback. The tests that must catch it are
# test_the_partial_ratio_is_the_share_of_the_span_between_the_bands and
# test_the_two_pedal_ratios_partition_the_time_the_pedal_did_anything in
# backend/tests/test_pedal.py.
#
#   ./falsify.sh backend/tools/falsifications/drop_the_partial_pedal_ratio.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_pedal.py"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_pedal.py
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
