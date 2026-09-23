#!/usr/bin/env bash
#
# Break: put the old play-on-click back behind the new navigate-on-click.
#
# This is the shipped behaviour the change replaces, and the easiest way to "fix" a report that
# clicking the strip does nothing: call `play` as well. It restores the sound and the running
# playhead behind a gesture that is meant to be silent — the falling-notes view then animates away
# from the block that was clicked, which is half of what the change is for.
#
#   ./falsify.sh backend/tools/falsifications/play_on_a_strip_click.sh \
#     "(cd frontend && npm run build) && backend/tools/run_e2e.sh playback"
#
# The build is part of the check on purpose: the browser tier is served `frontend/dist`, so a
# source break that is not rebuilt is a break the browser never sees.
# CHECK: (cd frontend && npm run build) && backend/tools/run_e2e.sh playback
# EXPECT: clicking the strip plays nothing at all
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/SegmentTimeline.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    moveTo(ratio * total);\n"
assert text.count(needle) == 1, "the strip click is not where this script expects it"
path.write_text(text.replace(needle, "    void play(0, total, null, ratio * total);\n", 1))
PY
