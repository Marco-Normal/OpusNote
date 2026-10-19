#!/usr/bin/env bash
#
# Break: a press on the strip forgets that anything is playing, so it only moves the playhead.
#
# This is the exact state the owner reported: during playback a press moved the readout and the
# next progress tick put it straight back, because the sound had never moved — so clicking the
# strip looked like it did nothing at all while a two-hour sitting ran past.
#
# Every other part of the wiring is left correct: the pointer handlers still fire, `seekPlan` is
# still consulted, the transport buttons keep their fallback range. Only the fact that the strip
# is sounding is withheld, which is what makes this a narrow falsifier rather than a broken build.
#
# The assertion that must catch it is the browser scenario's
# `and carries the sound to where the press was aimed`: with the break the playhead is dragged
# back to wherever the sound still is, so the reading is about a second rather than 95% of the
# sitting's length.
#
#   ./check.sh --falsify forget_that_a_press_seeks
# CHECK: cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh playback
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/SegmentTimeline.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    const plan = seekPlan(
      playing,
      total,"""
assert needle in text, "the strip's seek call is not where this script expects it"
path.write_text(text.replace(needle, """    const plan = seekPlan(
      null,
      total,""", 1))
PY
