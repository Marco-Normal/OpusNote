#!/usr/bin/env bash
#
# Break: print a duration as minutes and seconds however long it is.
#
# This is the shipped defect: an hour-long recording read "60:00" while the playhead and the
# markers, which have always gone through `formatClock`, read "1:00:00" for the same length.
# Takes are about 14 MB an hour, so an hour is an ordinary recording to have.
#
#   backend/tools/falsify.sh backend/tools/falsifications/forget_that_a_duration_has_hours.sh \
#     "cd frontend && npm test" --expect "a duration past an hour reads as hours"
# CHECK: cd frontend && npm test
# EXPECT: a duration past an hour reads as hours
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/clock.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """  if (seconds === null || !Number.isFinite(seconds)) return '—';
  return formatClock(Math.round(seconds));"""
assert needle in text, "the duration wrapper is not where this script expects it"
broken = """  if (seconds === null || !Number.isFinite(seconds)) return '—';
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return `${minutes}:${String(remainder).padStart(2, '0')}`;"""
path.write_text(text.replace(needle, broken, 1))
PY
