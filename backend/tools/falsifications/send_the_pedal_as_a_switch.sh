#!/usr/bin/env bash
#
# Break: stop sending the sustain pedal to the piano at all.
#
# This is the state before this change — the piano played the notes and nothing else, so
# a pedalled chord stopped dead and every value in the log was decoration. The browser
# assertions that must catch it are "the recorded half-pedal position reaches the piano
# verbatim" and "the recorded pedal-up is scheduled on the piano's clock" in
# scenario_playback.
#
# The check builds the frontend first: the browser tier serves `frontend/dist`, so a
# source break that is not rebuilt is a break the browser never sees.
#
#   ./falsify.sh backend/tools/falsifications/send_the_pedal_as_a_switch.sh \
#     "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh playback"
# CHECK: cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh playback
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/pianoPlayer.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
# The restored position and the recorded curve are the two halves of the stream; removing
# both is what "the pedal was never sent" actually looked like.
needle = """    if (this.startPedal !== null) {
      // Put the damper where the sitting left it, once, at the instant playback begins.
      this.sink.send([0xb0, 64, this.startPedal]);
      this.startPedal = null;
    }"""
assert needle in text, "the restored pedal position is not where this script expects it"
text = text.replace(needle, "    this.startPedal = null;", 1)
needle = """      this.sink.send([0xb0, 64, pedal.value], this.startedAt + pedal.onset_ms);"""
assert needle in text, "the pedal stream is not where this script expects it"
path.write_text(text.replace(needle, "      void pedal;", 1))
PY
