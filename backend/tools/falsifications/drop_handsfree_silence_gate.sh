#!/usr/bin/env bash
#
# Break: let the damper double-tap gesture fire while the player is playing.
#
# Without the silence gate, ordinary pedalling can arm or stop audio capture. The test
# that must catch it is 'the sustain pedal arms capture on two taps, and only in silence'
# in frontend/src/lib/pedalGesture.test.ts.
#
#   ./falsify.sh backend/tools/falsifications/drop_handsfree_silence_gate.sh "cd frontend && npm test"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/pedalGesture.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """      const quiet = lastNoteMs === null || move.epochMs - lastNoteMs >= SILENCE_MS;
      if (!quiet) {
        this.lastTapMs = null;
        return null;
      }
"""
assert needle in text, "the gate is not where this script expects it"
path.write_text(text.replace(needle, "      const quiet = true;\n", 1))
PY
