#!/usr/bin/env bash
#
# Break: derive the count-in from the meter again, ignoring the preference.
#
# This is the state before Phase 20b. The browser assertion that must catch it is
# "two bars of count-in is what the metronome plays" in scenario_bench.
#
#   ./falsify.sh backend/tools/falsifications/ignore_count_in_preference.sh \
#     "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh bench"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/PracticeView.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    const countInBeats = countInBeatsFor(app.countInBars, barsBeats);"
assert needle in text, "the derivation is not where this script expects it"
path.write_text(
    text.replace(needle, "    const countInBeats = barsBeats[0] ?? 4;", 1)
)
PY
