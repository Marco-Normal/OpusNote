#!/usr/bin/env bash
#
# Break: schedule the `Tone.Part` and never start the Transport it rides.
#
# `Tone.Part` places its events on the Transport timeline, so a part on its own is silent:
# the interface says "playing", the position advances, the audio context reports
# `running`, and the master output stays at exactly zero. That was the state of the
# synthesiser and the sampled piano on every machine until 2026-09-20 (AGENT-LOG.md).
#
# The checks that must catch it are "the sampled piano puts sound on the master output"
# and "the synthesiser puts sound on the master output" in `scenario_playback`, which read
# the tap installed by the harness's `AUDIO_TAP`. `frontend/dist` is gitignored and is what
# the browser is actually served, so the check has to build first:
#
#   backend/tools/falsify.sh backend/tools/falsifications/let_the_part_ride_a_stopped_transport.sh \
#     "(cd frontend && npm run build >/dev/null) && backend/tools/run_e2e.sh playback"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/pianoPlayer.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    this.part.start(0);
    transport.start(Tone.now() + LEAD_IN_S);
"""
assert needle in text, "the transport start is not where this script expects it"
path.write_text(text.replace(needle, "    this.part.start(Tone.now() + LEAD_IN_S);\n", 1))
PY
