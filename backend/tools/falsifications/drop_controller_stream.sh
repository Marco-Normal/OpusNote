#!/usr/bin/env bash
#
# Break: stop reporting controllers other than CC64.
#
# This is the state before Phase 20b: `handleMessage` saw only the damper, so the
# sostenuto could not be bound. The browser assertion that must catch it is
# "pressing the sostenuto is offered as a pedal the piano sends" in scenario_bench.
#
# The check builds the frontend first: the browser tier serves `frontend/dist`, so a
# source break that is not rebuilt is a break the browser never sees, and the check
# would pass for the wrong reason.
#
#   ./falsify.sh backend/tools/falsifications/drop_controller_stream.sh \
#     "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh bench"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/midi.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """      this.controllerHandlers.forEach((handler) => handler(controller));

"""
assert needle in text, "the emit is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
