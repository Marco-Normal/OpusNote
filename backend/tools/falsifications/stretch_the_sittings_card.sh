#!/usr/bin/env bash
#
# Break: let the sittings card stretch to the row height again, which is a grid's default.
#
# The sitting list is capped at 22rem; the detail beside it (transport, ruler, segment list, roll)
# is far taller. With the default `stretch` the card is drawn as a bordered box hundreds of pixels
# below its last row, which reads as content that never loaded — the reported symptom. The fix is
# one declaration, `align-items: start`, so removing it puts the defect back with no markup change
# at all, which is the point: the markup was never what was wrong.
#
# The check that must catch it is the card-vs-list geometry assertion in `scenario_practice_log`:
#
#   backend/tools/falsify.sh backend/tools/falsifications/stretch_the_sittings_card.sh \
#     "backend/tools/run_e2e.sh practice_log" \
#     --expect "stops at its own list"
# CHECK: backend/tools/run_e2e.sh practice_log
# EXPECT: stops at its own list
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/PracticeLogView.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    align-items: start;\n    grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));"
assert text.count(needle) == 1, "the columns rule is not where this script expects it"
path.write_text(
    text.replace(needle, "    grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));", 1)
)
PY
