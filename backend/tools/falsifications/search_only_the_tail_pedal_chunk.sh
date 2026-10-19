#!/usr/bin/env bash
#
# Break: look for a retried move only in the last chunk.
#
# The overlap search is by time range on purpose: a retried span can cover several chunks,
# and searching the tail alone leaves the earlier duplicates untouched while the test that
# replays a batch longer than a chunk (test_a_retry_spanning_a_chunk_boundary_is_not_doubled)
# passes its "first store" half and fails its second.
#
#   ./falsify.sh backend/tools/falsifications/search_only_the_tail_pedal_chunk.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_pedal_stream.py -k spanning"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_pedal_stream.py -k spanning
# EXPECT: spanning_a_chunk_boundary
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/pedal_stream.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    overlapping = [
        head
        for head in heads
        if int(head["last_ms"]) >= batch[0][0] and int(head["first_ms"]) <= batch[-1][0]
    ]"""
assert needle in text, "the overlap search is not where this script expects it"
path.write_text(text.replace(needle, "    overlapping = [heads[-1]]", 1))
PY
