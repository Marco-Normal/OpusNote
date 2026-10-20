#!/usr/bin/env bash
#
# Break: drop the notes from the portrait cache key, so a recording that arrived since the
# last read is answered with the portrait built before it.
#
# This is the failure a cache makes invisible: the numbers stay plausible, they are just from
# the library as it was. The sitting half of the key still moves when a new sitting is created,
# which is why only the note-level test catches it.
#
# The test that must catch it is
# test_a_new_note_rebuilds_the_portrait_it_changed.
#
#   ./falsify.sh backend/tools/falsifications/let_the_portrait_answer_for_a_stale_library.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_practice_portrait.py"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_practice_portrait.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/portrait.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "return (since, offset, days, int(notes[0]), int(notes[1]), int(sittings[0]), int(sittings[1]))"
assert needle in text, "the portrait signature is not where this script expects it"
path.write_text(
    text.replace(
        needle,
        "return (since, offset, days, 0, 0, int(sittings[0]), int(sittings[1]))",
        1,
    )
)
PY
