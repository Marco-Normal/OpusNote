#!/usr/bin/env bash
#
# Break: go back to breaking the streak on the first missed day.
#
# The test that must catch it is test_one_missed_day_keeps_the_streak_and_is_reported.
#
#   ./falsify.sh backend/tools/falsifications/break_streak_on_one_miss.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """            if last_forgiven is not None and (last_forgiven - cursor).days < GRACE_WINDOW_DAYS:
                break
"""
assert needle in text, "the grace check is not where this script expects it"
path.write_text(text.replace(needle, "            break\n", 1))
PY
