#!/usr/bin/env bash
#
# Break: round the remainder instead of the total, so a minute can reach sixty.
#
# This is the shipped defect: `Math.round(minutes % 60)` is never carried, so 119.7 printed
# "1 h 60 min" and 59.6 printed "60 min" — a reading a person would take for a typo in the app
# rather than in their practice.
#
# The check that must catch it is "minutes round into the hour instead of reporting sixty of
# them" in `frontend/src/lib/types.test.ts`.
#
#   backend/tools/falsify.sh backend/tools/falsifications/carry_the_minute_into_the_hour.sh \
#     "cd frontend && npm test" --expect "minutes round into the hour"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/types.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """  const total = Math.round(minutes);
  if (total < 60) return `${total} min`;
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;"""
assert needle in text, "the minutes rule is not where this script expects it"
broken = """  const hours = Math.floor(minutes / 60);
  const rest = Math.round(minutes % 60);
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;"""
path.write_text(text.replace(needle, broken, 1))
PY
