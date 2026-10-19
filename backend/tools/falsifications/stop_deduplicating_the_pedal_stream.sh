#!/usr/bin/env bash
#
# Break: store every move handed in, duplicates included.
#
# `UNIQUE(sitting_id, onset_ms, value)` used to refuse a repeated batch at the schema level.
# The stream has no such index, so `ordered()` is the only thing standing between a retried
# HTTP batch and a doubled performance. Returning the moves sorted but undeduplicated keeps
# the order correct and breaks exactly the guarantee that moved.
#
#   ./falsify.sh backend/tools/falsifications/stop_deduplicating_the_pedal_stream.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_pedal_stream.py -k retried"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_pedal_stream.py -k retried
# EXPECT: retried
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/pedal_stream.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    return sorted(_keyed(moves).values(), key=lambda move: move[0])"
assert needle in text, "the sort is not where this script expects it"
path.write_text(
    text.replace(needle, "    return sorted(moves, key=lambda move: move[0])", 1)
)
PY
