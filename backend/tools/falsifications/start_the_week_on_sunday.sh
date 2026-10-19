#!/usr/bin/env bash
#
# Break: bucket weeks Sunday-first, the way SQLite's `weekday 0` naturally does, and drop
# the shift that turns it into a Monday.
#
# A Sunday-first bucket splits one weekend across two rows without anything having happened
# between Saturday and Sunday, and silently moves a Sunday's practice into the week that has
# not started yet. Nothing errors: the totals are identical, only the boundaries move.
#
# The test that must catch it is
# test_a_sunday_belongs_to_the_week_that_started_six_days_before.
#
#   ./falsify.sh backend/tools/falsifications/start_the_week_on_sunday.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_practice_rhythm.py"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_practice_rhythm.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "date(local_date, 'weekday 0', '-6 days') AS week_start"
assert needle in text, "the week bucket is not where this script expects it"
path.write_text(
    text.replace(needle, "date(local_date, 'weekday 0') AS week_start", 1)
)
PY
