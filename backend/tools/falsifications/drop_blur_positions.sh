#!/usr/bin/env bash
#
# Break: report only the first blur position, so the places stop matching the count.
#
# The count is `len(blur_at_ms)`, so a truncated list makes the two disagree — which is the
# invariant `test_the_stored_blur_positions_are_where_the_stored_count_says` and
# `test_the_blur_positions_are_where_the_blurs_are` exist to keep.
#
#   ./falsify.sh backend/tools/falsifications/drop_blur_positions.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_pedal.py tests/test_practice_store.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/pedal.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    return found\n"
assert text.count(needle) == 1, "the return is not where this script expects it"
path.write_text(text.replace(needle, "    return found[:1]\n", 1))
PY
