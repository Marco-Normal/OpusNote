#!/usr/bin/env bash
#
# Break: stop attaching a take whose segment appeared after the take was uploaded.
#
# A take is cut eight seconds after the player stops, while its sitting stays open for the
# five-minute gap, so the segment it belongs to does not exist yet. Removing the catch-up
# from the piece read leaves the take catalogued with no passage and no piece, which is
# exactly what the take is for. The tests that must catch it are
# test_a_take_recorded_while_its_sitting_is_open_is_attached_when_the_piece_is_read and
# test_a_take_finds_its_piece_when_the_segment_is_labelled_later.
#
#   ./falsify.sh backend/tools/falsifications/drop_take_catch_up.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py -k 'open_is_attached or labelled_later'"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py -k 'open_is_attached or labelled_later'
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/api.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    _catch_up_takes()\n    row = store.get_piece(conn, piece_id)"
assert needle in text, "the catch-up is not where this script expects it"
path.write_text(text.replace(needle, "    row = store.get_piece(conn, piece_id)", 1))
PY
