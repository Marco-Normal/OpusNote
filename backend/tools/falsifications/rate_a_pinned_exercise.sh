#!/usr/bin/env bash
#
# Break: rate a pinned exercise like any other.
#
# The owner's decision is that deliberate practice is scored and logged but does not move the
# ratings: drilling easy material should not inflate the number that chooses the automatic
# material. A perfect run at pinned level 1 against a rating of 900 is still worth about +2.6
# under Elo, so twenty of them would move the rating ~50 points while the player was doing
# easier work than usual — the opposite of what they asked for.
#
# The checks that must catch it are "a pinned exercise is scored and logged but moves no
# rating" and "pinning only the hand also makes it practice" in `backend/tests/test_api.py`.
#
#   backend/tools/falsify.sh \
#     backend/tools/falsifications/rate_a_pinned_exercise.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_api.py" \
#     --expect "deliberate practice must not move the ratings"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_api.py
# EXPECT: deliberate practice must not move the ratings
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/services.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '    rated = exercise.get("pinned_level") is None and exercise.get("pinned_hand") is None'
assert needle in text, "the rating decision is not where this script expects it"
path.write_text(text.replace(needle, "    rated = True", 1))
PY
