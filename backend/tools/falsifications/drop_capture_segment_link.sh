#!/usr/bin/env bash
#
# Break: stop attaching a take to the segment that was playing.
#
# The test that must catch it is test_a_take_is_attached_to_the_segment_it_was_played_in:
# with the link dropped the take is catalogued but cannot say what it was.
#
#   ./falsify.sh backend/tools/falsifications/drop_capture_segment_link.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/api.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "found = store.segment_at(conn, sitting_id, started_ms)"
assert needle in text, "the lookup is not where this script expects it"
path.write_text(text.replace(needle, "found = None", 1))
PY
