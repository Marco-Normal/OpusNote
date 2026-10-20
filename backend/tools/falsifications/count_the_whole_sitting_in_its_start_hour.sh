#!/usr/bin/env bash
#
# Break: put a sitting's whole duration in the hour it started in, instead of splitting it at
# the hour boundary.
#
# A 23:40 sitting of 80 minutes then reports 80 minutes at 23:00 and nothing at midnight. The
# total still adds up, so nothing looks wrong — only the shape of the day does.
#
# The test that must catch it is
# test_a_sitting_that_crosses_midnight_is_split_at_the_hour.
#
#   ./falsify.sh backend/tools/falsifications/count_the_whole_sitting_in_its_start_hour.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_practice_rhythm.py"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_practice_rhythm.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """        for hour, minutes in _hour_chunks(
            int(row["started_ms"]), int(row["ended_ms"]), offset
        ):
            hour_minutes[hour] += minutes
"""
assert needle in text, "the hour split is not where this script expects it"
path.write_text(
    text.replace(
        needle,
        '        hour_minutes[start_hour] += (int(row["ended_ms"]) - int(row["started_ms"])) / 60_000.0\n',
        1,
    )
)
PY
