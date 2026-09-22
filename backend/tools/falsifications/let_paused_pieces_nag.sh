#!/usr/bin/env bash
#
# Break: put the neglected query back to "everything that is not completed".
#
# The test that must catch it is test_a_paused_piece_does_not_nag.
#
#   ./falsify.sh backend/tools/falsifications/let_paused_pieces_nag.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "        WHERE p.status = 'active'"
assert needle in text, "the predicate is not where this script expects it"
path.write_text(text.replace(needle, "        WHERE p.status != 'completed'", 1))
PY
