#!/usr/bin/env bash
#
# Break: let the log poll run in a tab nobody is looking at.
#
# This is the state before the fix: the interval called `refreshQuietly` unconditionally, so a
# kiosk tab left behind another window asked the server for the dashboard every 20 s for nobody —
# 110 ms of SQLite per poll on the owner's library, on the laptop that is also capturing the
# piano. The browser assertion that must catch it is "a hidden tab asks the server for nothing" in
# scenario_practice_log.
#
# The check builds the frontend first: the browser tier serves `frontend/dist`, so a source break
# that is not rebuilt is a break the browser never sees, and the check would pass for the wrong
# reason.
#
#   ./falsify.sh backend/tools/falsifications/poll_a_hidden_log_tab.sh \
#     "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh practice_log"
# CHECK: cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh practice_log
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/PracticeLogView.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    const tick = () => {
      if (document.visibilityState === 'hidden') return;
      void refreshQuietly();
    };"""
unconditional = """    const tick = () => {
      void refreshQuietly();
    };"""
assert needle in text, "the visibility guard is not where this script expects it"
path.write_text(text.replace(needle, unconditional, 1))
PY
