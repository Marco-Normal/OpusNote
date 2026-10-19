#!/usr/bin/env bash
#
# Break: make "next segment" walk one second instead of to the boundary.
#
# The 30-second buttons already do this, and it is the tempting simplification when the
# segment list is empty or when a boundary looks wrong: add a second to the playhead and
# call it a step. It leaves the button landing inside the passage rather than on the
# boundary the screen is drawn in, which is the whole reason the segment buttons exist.
#
#   ./falsify.sh backend/tools/falsifications/jump_a_second_instead_of_a_segment.sh \
#     "(cd frontend && npm run build) && backend/tools/run_e2e.sh playback"
#
# The build is part of the check on purpose: the browser tier is served `frontend/dist`, so a
# source break that is not rebuilt is a break the browser never sees.
# CHECK: (cd frontend && npm run build) && backend/tools/run_e2e.sh playback
# EXPECT: a step forward lands on the next segment's start
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/SegmentTimeline.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    applySeek(segmentStep(detail.segments, position, direction, total), wholeSitting);\n"
assert text.count(needle) == 1, "the segment step is not where this script expects it"
path.write_text(
    text.replace(
        needle,
        "    applySeek(Math.min(position + direction * 1000, total), wholeSitting);\n",
        1,
    )
)
PY
