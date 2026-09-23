#!/usr/bin/env bash
#
# Break: stamp the review flag when it is dispatched, not when it was pressed.
#
# A single tap cannot be told from the first half of a double until the double window closes, so
# it resolves up to 300 ms late. Phase 23's reason for carrying the press's timestamp is that the
# lateness must cost only the on-screen confirmation, never the place that is recorded — and the
# whole "the easy gesture is the harmless one" trade only works because of it.
#
# The check that must catch this is 'a single tap on the sostenuto fires the single action,
# stamped when it was pressed' in frontend/src/lib/pedalGesture.test.ts.
#
#   ./falsify.sh backend/tools/falsifications/stamp_the_flag_when_it_fires.sh "cd frontend && npm test"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/pedalGesture.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "      const atMs = this.pendingTap.atMs;"
assert needle in text, "the single's timestamp is not where this script expects it"
path.write_text(text.replace(needle, "      const atMs = nowMs;", 1))
PY
