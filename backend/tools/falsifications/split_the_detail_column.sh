#!/usr/bin/env bash
#
# Break: give the detail column's wrapper no box, so its children are grid children again.
#
# The undo offer used to be a bare child of `.columns.wide-left`, and a grid child is a
# *column*: the notice took the wide one and the timeline was auto-placed into the sitting
# list's cell, under it and at the list's width, while the column it vacated held nothing but
# the notice. Wrapping the notice and the card in one element is the fix; `display: contents`
# removes that element's box without disturbing the markup, which is the same defect reaching
# the same geometry.
#
# The check that must catch it is the geometry assertion in `scenario_practice_log` — the
# layout, not the markup, which is the only thing that was ever wrong here:
#
#   backend/tools/falsify.sh backend/tools/falsifications/split_the_detail_column.sh \
#     "backend/tools/run_e2e.sh practice_log" \
#     --expect "stays in the wide column beside the list"
# CHECK: backend/tools/run_e2e.sh practice_log
# EXPECT: stays in the wide column beside the list
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/PracticeLogView.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '<div class="stack">'
assert text.count(needle) == 1, "the detail column is not where this script expects it"
path.write_text(
    text.replace(needle, '<div class="stack" style="display: contents">', 1)
)
PY
