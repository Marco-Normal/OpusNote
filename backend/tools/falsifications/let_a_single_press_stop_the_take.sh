#!/usr/bin/env bash
#
# Break: put take recording back on the single press.
#
# Phase 23 moved the one action that can destroy work — stopping a take — off the gesture that is
# easiest to fire by accident, and onto the hold. This break restores the old partition, which is
# exactly the arrangement the owner reported as a defect when the soft pedal carried it.
#
# The checks that must catch it are 'the default puts the benign action on the easiest gesture' in
# frontend/src/lib/pedalBindings.test.ts, and the bench scenario's "a single tap leaves take
# recording alone, because stopping a take needs a hold".
#
#   ./falsify.sh backend/tools/falsifications/let_a_single_press_stop_the_take.sh "cd frontend && npm test"
#
# The browser half of the same break, which needs its own build because `frontend/dist` is
# gitignored and `falsify.sh` cannot restore it:
#
#   ./falsify.sh backend/tools/falsifications/let_a_single_press_stop_the_take.sh \
#     "(cd frontend && npm run build) && backend/tools/run_e2e.sh bench"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/pedalBindings.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "  single: 'mark_review',"
assert needle in text, "the default partition is not where this script expects it"
path.write_text(text.replace(needle, "  single: 'toggle_audio_capture',", 1))
PY
