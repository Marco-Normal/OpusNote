#!/usr/bin/env bash
#
# Break: read the hour off the stored UTC epoch instead of the player's clock, by throwing
# away the offset the sitting was recorded with.
#
# A Saturday evening in São Paulo is Sunday in UTC. With the offset gone, a 21:30 sitting is
# counted at 00:30 and the whole day chart shifts three hours west — the exact defect the
# `tz_offset_minutes` column was added to end.
#
# The test that must catch it is
# test_an_evening_is_read_on_the_players_clock_not_on_utc.
#
#   ./falsify.sh backend/tools/falsifications/forget_which_clock_the_hour_is_on.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_practice_rhythm.py"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_practice_rhythm.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """        offset = (
            int(row["tz_offset_minutes"])
            if row["tz_offset_minutes"] is not None
            else assumed_offset
        )
"""
assert needle in text, "the offset resolution is not where this script expects it"
path.write_text(text.replace(needle, "        offset = 0\n", 1))
PY
