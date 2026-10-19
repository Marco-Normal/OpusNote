#!/usr/bin/env bash
#
# Break: stop counting the day's first sitting as "first", so every minute lands in the
# later-session bucket.
#
# This is the break the weekly decomposition cannot survive: with no first sitting, the
# "the volume fell because the second session of the day disappeared" reading is not merely
# wrong, it is invisible — first_minutes goes to zero and the extra bucket absorbs the day.
# The totals still add up, so only the split assertion can catch it.
#
# The test that must catch it is test_a_day_keeps_its_first_sitting_separate_from_the_rest.
#
#   ./falsify.sh backend/tools/falsifications/forget_which_sitting_was_first.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_practice_rhythm.py"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_practice_rhythm.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "SUM(CASE WHEN position = 1 THEN minutes ELSE 0 END) AS first_minutes"
assert needle in text, "the first-sitting bucket is not where this script expects it"
path.write_text(
    text.replace(
        needle,
        "SUM(CASE WHEN position = 0 THEN minutes ELSE 0 END) AS first_minutes",
        1,
    )
)
PY
