#!/usr/bin/env bash
#
# Break: stop recording where a seeded passage came from.
#
# The test that must catch it is test_a_passage_seeded_from_a_loop_records_the_recording.
#
#   ./falsify.sh backend/tools/falsifications/forget_the_passage_provenance.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '            fields.get("source", "manual"),'
assert needle in text, "the provenance is not where this script expects it"
path.write_text(text.replace(needle, '            "manual",', 1))
PY
