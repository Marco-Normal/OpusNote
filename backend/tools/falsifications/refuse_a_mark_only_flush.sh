#!/usr/bin/env bash
#
# Break: refuse a flush that carries nothing but a review mark.
#
# A mark is pressed between phrases, so the flush that carries it is usually a batch of its own —
# that is the ordinary case, not an edge one. `EventBatch` was widened for marks and `ingest` was
# widened for them, but the API-level emptiness guard was not, so a mark-only flush came back 422
# and the client retried it forever.
#
# The check that must catch it is 'a mark pressed between phrases is a batch of its own' in
# backend/tests/test_practice_api.py.
#
#   ./falsify.sh backend/tools/falsifications/refuse_a_mark_only_flush.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/api.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    if not batch.events and not batch.pedals and not batch.marks:"
assert needle in text, "the emptiness guard is not where this script expects it"
path.write_text(
    text.replace(needle, "    if not batch.events and not batch.pedals:", 1)
)
PY
