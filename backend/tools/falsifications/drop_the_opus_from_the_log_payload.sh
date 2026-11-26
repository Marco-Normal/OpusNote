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
MAT="$ROOT/backend/app/practice/materialise.py"
AUTO="$ROOT/backend/app/practice/autotag.py"

python3 - "$MAT" "$AUTO" <<'PY'
import pathlib, sys

mat = pathlib.Path(sys.argv[1])
mat_text = mat.read_text()
for needle in [
    '                piece_opus=data["piece_opus"],\n',
    '                piece_opus=label.get("opus"),\n',
]:
    assert mat_text.count(needle) == 1, f"{needle.strip()} is not where this script expects it"
    mat_text = mat_text.replace(needle, "", 1)
mat.write_text(mat_text)

auto = pathlib.Path(sys.argv[2])
auto_text = auto.read_text()
needle = '                opus=label.get("opus"),\n'
assert auto_text.count(needle) == 1, f"{needle.strip()} is not where this script expects it"
auto.write_text(auto_text.replace(needle, "", 1))
PY
