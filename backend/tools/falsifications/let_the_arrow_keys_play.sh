#!/usr/bin/env bash
#
# Break: leave the arrow keys on the transport, so they play while a click does not.
#
# The keys and the pointer are the same affordance — one slider, and the `aria-label` promises the
# same thing for both — so a strip that navigates on a click and starts the sitting on `→` is one
# control behaving as two. The key is also the one pressed by accident, and it makes a sound:
# having just moved the playhead to a passage, `→` would begin playing the rest of the sitting
# behind a gesture meant to step five seconds.
#
#   ./falsify.sh backend/tools/falsifications/let_the_arrow_keys_play.sh \
#     "(cd frontend && npm run build) && backend/tools/run_e2e.sh playback"
#
# The build is part of the check on purpose: the browser tier is served `frontend/dist`, so a
# source break that is not rebuilt is a break the browser never sees.
# CHECK: (cd frontend && npm run build) && backend/tools/run_e2e.sh playback
# EXPECT: and the arrow keys move without playing either
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/SegmentTimeline.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """        if (event.key === 'ArrowRight') seekBy(5);
        if (event.key === 'ArrowLeft') seekBy(-5);
"""
assert text.count(needle) == 1, "the strip's key handling is not where this script expects it"
replacement = """        if (event.key === 'ArrowRight') jump(5);
        if (event.key === 'ArrowLeft') jump(-5);
"""
path.write_text(text.replace(needle, replacement, 1))
PY
