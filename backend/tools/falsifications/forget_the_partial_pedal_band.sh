#!/usr/bin/env bash
#
# Break: read a part-depressed pedal as fully released again.
#
# This is the state before half-pedalling was implemented, and it is one line: the
# partial band stops contributing a residual ring. The tests that must catch it are
# "a pedal resting in the partial band rings on, in proportion to its depth" and the
# monotonicity test beside it in frontend/src/lib/playback.test.ts.
#
#   ./falsify.sh backend/tools/falsifications/forget_the_partial_pedal_band.sh \
#     "cd frontend && npm test"
# CHECK: cd frontend && npm test
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/playback.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    const depth = pedalDepthAt(positions, release);
    if (depth <= 0) return note;"""
assert needle in text, "the partial-band read is not where this script expects it"
path.write_text(
    text.replace(needle, """    const depth = 0;
    if (depth <= 0) return note;""", 1)
)
PY
