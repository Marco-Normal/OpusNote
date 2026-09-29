#!/usr/bin/env bash
#
# Break: make the detail route do the work even when a job is already doing it.
#
# This is the state before Phase 24's read change: the route always materialises, so a click
# on a sitting whose preparation is queued blocks for the whole ~700 ms instead of answering
# "preparing" and filling in a moment later. The sitting still ends up correct — which is
# exactly why the defect needs an assertion about *work*, not about the answer.
#
# The test that must catch it is
# test_a_scheduled_sitting_answers_preparing_instead_of_waiting, which counts calls to
# `ensure_segments` during that read and requires zero of them.
#
#   ./falsify.sh backend/tools/falsifications/the_read_waits_for_a_scheduled_job.sh
# CHECK: backend/.venv/bin/python -m pytest backend/tests/test_jobs.py -q
# EXPECT: test_a_scheduled_sitting_answers_preparing_instead_of_waiting
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/api.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "        store.sitting_detail, sitting_id, materialise=not jobs.scheduled(sitting_id)"
assert needle in text, "the detail route's materialise decision is not where this script expects it"
path.write_text(
    text.replace(needle, "        store.sitting_detail, sitting_id, materialise=True", 1)
)
PY
