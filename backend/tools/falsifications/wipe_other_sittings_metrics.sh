#!/usr/bin/env bash
#
# Break: restore the metrics DELETE that emptied every other sitting.
#
# The original condition was "not a segment of *this* sitting", which is every other
# sitting's segment — so segmenting one sitting silently deleted every earlier sitting's
# metrics, and with them the piece tempo trend and the per-segment pedal and touch
# figures. The test that must catch it is
# test_segmenting_a_second_sitting_does_not_erase_the_first_s_metrics.
#
#   ./falsify.sh backend/tools/falsifications/wipe_other_sittings_metrics.sh "./check.sh --fast"
# CHECK: ./check.sh --fast
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """        "DELETE FROM segment_metrics WHERE segment_id NOT IN (SELECT id FROM segments)"
    )"""
assert needle in text, "the DELETE is not where this script expects it"
replacement = """        "DELETE FROM segment_metrics WHERE segment_id NOT IN"
        " (SELECT id FROM segments WHERE sitting_id = ?)",
        (sitting_id,),
    )"""
path.write_text(text.replace(needle, replacement, 1))
PY
