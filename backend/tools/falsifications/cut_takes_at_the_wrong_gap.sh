#!/usr/bin/env bash
#
# Break: cut a take a second early, so it clips the end of the playing it belongs to.
#
# The test that must catch it is the boundary case in audioCut.test.ts.
#
#   ./falsify.sh backend/tools/falsifications/cut_takes_at_the_wrong_gap.sh "cd frontend && npm test"
# CHECK: cd frontend && npm test
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/audioCut.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "  const silence = input.lastNoteMs === null || input.nowMs - input.lastNoteMs >= input.segmentGapMs;"
assert needle in text, "the gap rule is not where this script expects it"
path.write_text(
    text.replace(
        needle,
        "  const silence = input.lastNoteMs === null || input.nowMs - input.lastNoteMs >= input.segmentGapMs - 1000;",
        1,
    )
)
PY
