#!/usr/bin/env bash
#
# Break: stop the close route from queueing the sitting it just closed.
#
# The piano going away is the common end of a sitting, so it is the common trigger for
# preparing one — and the reason the queue exists at all. Without it the work still happens,
# but back on the first read that opens the sitting, which is exactly the ~700 ms wait the
# phase exists to remove.
#
# The test that must catch it is test_closing_a_sitting_queues_it_for_preparation: close a
# sitting through the route, then require it to be scheduled and to be segmented by the
# queued job.
#
#   ./falsify.sh backend/tools/falsifications/the_close_route_forgets_to_prepare.sh
# CHECK: backend/.venv/bin/python -m pytest backend/tests/test_jobs.py -q
# EXPECT: test_closing_a_sitting_queues_it_for_preparation
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/api.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "        jobs.submit(outcome.sitting_id)"
assert needle in text, "the close route's queue call is not where this script expects it"
path.write_text(text.replace(needle, "        pass  # the break: nothing is queued", 1))
PY
