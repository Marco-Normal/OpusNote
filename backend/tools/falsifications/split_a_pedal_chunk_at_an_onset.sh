#!/usr/bin/env bash
#
# Break: let a chunk boundary fall inside one millisecond.
#
# The merge finds a retried move by looking only at the chunks whose time range the batch
# touches, so two moves at the same onset in two different chunks could hide a duplicate in
# a chunk it never reads. Splitting on the record count alone is the smallest break, and it
# is caught by test_a_chunk_never_splits_one_onset rather than by the round trip, because the
# invariant is about the packing and not about what a decode returns.
#
#   ./falsify.sh backend/tools/falsifications/split_a_pedal_chunk_at_an_onset.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_pedal_stream.py -k splits_one_onset"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_pedal_stream.py -k splits_one_onset
# EXPECT: splits_one_onset
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/pedal_stream.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "        if len(current) >= limit and move[0] != current[-1][0]:"
assert needle in text, "the chunk boundary is not where this script expects it"
path.write_text(text.replace(needle, "        if len(current) >= limit:", 1))
PY
