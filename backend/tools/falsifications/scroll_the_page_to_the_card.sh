#!/usr/bin/env bash
#
# Break: reach the card with `scrollIntoView` instead of moving the list's own `scrollTop`.
#
# The one-liner everyone writes, and it is the defect this feature was asked for: `scrollIntoView`
# scrolls *every* scrollable ancestor, so the page moves as well as the list. The falling notes sit
# above the list, so the page jumping under the pointer takes the strip away from where it was
# clicked — and on a long sitting the strip is the thing you are aiming at.
#
# The browser assertion is set up so this cannot pass by luck: the list is scrolled to its end and
# the page to its bottom, which puts the target card out of sight of both. `scrollIntoView` must
# therefore move the page to satisfy it, which is what "the page does not move at all" catches.
#
#   ./falsify.sh backend/tools/falsifications/scroll_the_page_to_the_card.sh \
#     "(cd frontend && npm run build) && backend/tools/run_e2e.sh practice_log"
#
# The build is part of the check on purpose: the browser tier is served `frontend/dist`, so a
# source break that is not rebuilt is a break the browser never sees.
# CHECK: (cd frontend && npm run build) && backend/tools/run_e2e.sh practice_log
# EXPECT: and the page does not move at all
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/SegmentTimeline.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    list.scrollTop = Math.max(0, Math.min(centred, list.scrollHeight - list.clientHeight));\n"
assert text.count(needle) == 1, "the list scroll is not where this script expects it"
path.write_text(text.replace(needle, "    card.scrollIntoView({ block: 'center' });\n", 1))
PY
