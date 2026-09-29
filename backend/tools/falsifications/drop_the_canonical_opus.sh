#!/usr/bin/env bash
#
# Break: store the catalogue number exactly as it arrives, which is the state the field was
# in before it had a canonical form.
#
# This is the reported defect put back: the same catalogue number written four ways
# (`Op 10. No. 4`, `Op. 10 No. 3`, `Op . 78`, `w264`) and one of them twice in two cases, so the
# library looks like it holds more pieces than it does and a search for `Op. 10` misses half of
# them. Nothing crashes and every other test still passes.
#
#   ./falsify.sh backend/tools/falsifications/drop_the_canonical_opus.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_opus.py"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_opus.py
# EXPECT: test_a_new_piece_stores_the_canonical_form
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '            "opus": normalise_opus(fields.get("opus")),'
assert needle in text, "the canonical write is not where this script expects it"
path.write_text(text.replace(needle, '            "opus": fields.get("opus"),', 1))
PY
