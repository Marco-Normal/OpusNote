#!/usr/bin/env bash
#
# Break: let a tie in the silence between two segments go to the later one.
#
# A click in a gap has to resolve to *some* segment, and the rule is the nearer one — with a tie
# going to the earlier, so the answer does not depend on which side the loop visited first. `<=`
# hands every tie to the last segment the loop saw: the same click then jumps to a different
# attempt depending on nothing the player can see, and at the midpoint of a long silence it is the
# later passage rather than the one just played.
#
#   ./falsify.sh backend/tools/falsifications/let_a_gap_click_take_the_later_segment.sh \
#     "cd frontend && npm test"
# CHECK: cd frontend && npm test
# EXPECT: a click in the silence between two segments means the nearer one
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/timelineStrip.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    if (distance < nearestDistance) {\n"
assert text.count(needle) == 1, "the nearest-segment comparison is not where this script expects it"
path.write_text(text.replace(needle, "    if (distance <= nearestDistance) {\n", 1))
PY
