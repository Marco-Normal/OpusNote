#!/usr/bin/env bash
#
# Break: fetch the open sitting's detail on every poll, changed or not.
#
# This is the shape the code had before `lib/pollGate.ts`: the poll read the summary, the list
# and then unconditionally the detail of whichever sitting was selected. The detail is the
# expensive read — on the owner's library 30 000 notes' worth of derived work, measured at 70 s
# on the notebook's cold disk after a restart — so a twenty-second interval against it stacks
# and drains a disk that is also capturing the piano.
#
# The check that must catch it is the browser scenario's *absence* assertion: with a sitting
# loaded and nothing changed, a forced poll may not re-read its detail. Removing the staleness
# test leaves every other assertion green, which is exactly why this one exists.
#
#   backend/tools/falsify.sh backend/tools/falsifications/poll_the_sitting_every_tick.sh \
#     "backend/tools/run_e2e.sh practice_log" --expect "an unchanged sitting alone"
# CHECK: backend/tools/run_e2e.sh practice_log
# EXPECT: an unchanged sitting alone
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/PracticeLogView.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "if (row !== undefined && detailIsStale(row, detail)) {"
assert text.count(needle) == 1, "the staleness test is not where this script expects it"
path.write_text(text.replace(needle, "if (row !== undefined) {", 1))
PY
