#!/usr/bin/env bash
#
# Break: add the segment's start to a blur position that is already sitting-relative.
#
# This is the defect Phase 21 shipped: `pedal_blur_ms` is measured from the sitting's start, and
# the timeline added `segment.start_ms` on top of it. A blur in the second segment was therefore
# drawn one segment-length too late — outside its own segment, and past the end of the strip
# altogether when the sitting was short enough that the doubled offset exceeded its length. The
# row's clock times were wrong the same way, in two more places.
#
# The checks that must catch it are the three in `scenario_practice_log` that seed a blur into the
# second segment: "the strip places the blur where it happened, not one segment later", "and the
# mark stays inside its own segment", and "and the row names the true time".
#
#   ./falsify.sh backend/tools/falsifications/double_count_the_segment_offset.sh \
#     "(cd frontend && npm run build) && backend/tools/run_e2e.sh practice_log"
#
# The build is part of the check on purpose: the browser tier is served `frontend/dist`, so a
# source break that is not rebuilt is a break the browser never sees.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/SegmentTimeline.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = 'style="left: {(blurMs / total) * 100}%"'
assert needle in text, "the blur marker is not where this script expects it"
path.write_text(
    text.replace(needle, 'style="left: {((segment.start_ms + blurMs) / total) * 100}%"', 1)
)
PY
