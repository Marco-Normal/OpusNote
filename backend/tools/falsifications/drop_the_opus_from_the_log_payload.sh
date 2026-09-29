#!/usr/bin/env bash
#
# Break: stop the log's payloads carrying the catalogue number.
#
# The label rule is only half of it. The other half is that the server has to send the opus at
# all — on the segment, on the passage it groups into, and on each matcher candidate — or the
# browser has nothing to name the piece with and falls back to the title. Every one of these
# fields is additive with a `None` default, so removing the wire value leaves a payload that is
# still valid and simply identifies nothing.
#
#   ./falsify.sh backend/tools/falsifications/drop_the_opus_from_the_log_payload.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py tests/test_autotag.py -k catalogue"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py tests/test_autotag.py -k catalogue
# EXPECT: test_the_log_names_a_piece_by_its_catalogue_number
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needles = [
    '                piece_opus=data["piece_opus"],\n',
    '                opus=label.get("opus"),\n',
    '                piece_opus=label.get("opus"),\n',
]
for needle in needles:
    assert text.count(needle) == 1, f"{needle.strip()} is not where this script expects it"
    text = text.replace(needle, "", 1)
path.write_text(text)
PY
