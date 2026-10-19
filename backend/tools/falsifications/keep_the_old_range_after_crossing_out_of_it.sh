#!/usr/bin/env bash
#
# Break: a seek that leaves the sounding range answers with the whole sitting instead of the
# segment the press landed in.
#
# The rule being removed is the one that makes crossing from one passage to another useful: you
# asked to hear where you pressed, not to sit through the rest of the passage you left and then
# the gap after it. The break is narrow on purpose — the press still seeks, the range is still
# honoured while the press stays inside it, and only the segment that should take over is lost.
#
# The assertion that must catch it is the unit test
# `a seek out of the sounding range moves the range to the segment it landed in`, which compares
# the resumed range field for field.
#
#   ./check.sh --falsify keep_the_old_range
# CHECK: cd frontend && npm test
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/timelineStrip.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """  if (segment !== null) {
    return {
      atMs: at,
      resume: { fromMs: segment.start_ms, toMs: segment.end_ms, segmentId: segment.id },
    };
  }"""
assert needle in text, "the segment hand-over is not where this script expects it"
path.write_text(text.replace(needle, """  if (segment !== null) {
    return { atMs: at, resume: { fromMs: 0, toMs: Math.max(totalMs, 0), segmentId: null } };
  }""", 1))
PY
