#!/usr/bin/env bash
#
# Break: stop bringing an upgraded sitting's blur positions up to date on the first read.
#
# Without it, a sitting segmented before Phase 21 keeps the blur count and no places — which is
# exactly the state the user's own library is in, and exactly what the feature exists to fix. The
# test that must catch it is
# test_a_sitting_from_before_the_column_gets_its_places_on_the_first_read.
#
#   ./falsify.sh backend/tools/falsifications/drop_blur_backfill.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_practice_store.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "            _backfill_blur_positions(conn, sitting_id)\n"
assert text.count(needle) == 1, "the backfill call is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
