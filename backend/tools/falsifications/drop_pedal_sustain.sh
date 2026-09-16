#!/usr/bin/env bash
#
# Break: stop the sustain pedal from holding anything.
#
# `sustained()` is the function that extends a released note to the pedal-up, and the
# frontend unit suite has six assertions about it. Returning the notes untouched is the
# smallest break that should be caught by all of them.
#
# Run with the fast tier, which includes `npm test`:
#
#   ./falsify.sh backend/tools/falsifications/drop_pedal_sustain.sh "./check.sh --fast"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/playback.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "  if (notes.length === 0 || pedals.length === 0) return [...notes];"
assert needle in text, "the line to break is not where this script expects it"
path.write_text(text.replace(needle, "  if (true) return [...notes];", 1))
PY
