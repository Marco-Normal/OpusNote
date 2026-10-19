#!/usr/bin/env bash
#
# Break: let the refresh start again while the last one is still in flight.
#
# One flag is the whole difference between "a twenty-second poll" and "an unbounded queue of
# reads". Measured on the owner's server: the first detail read of a large sitting after a
# restart took 70 s against a 2.6 s warm read, and with the gate removed every interval added
# another request on top of the one that had not finished — which is the several-minute stall
# that was reported, not the single slow read.
#
# The check that must catch it is the unit test in `pollGate.test.ts`: a second `fire()` while
# the first is held open must not reach the wrapped function. It is a unit test because a
# browser cannot be made to serve a slow read on demand without a test-only delay in production
# code, and an assertion that cannot be provoked is not evidence.
#
#   backend/tools/falsify.sh backend/tools/falsifications/let_the_polls_overlap.sh \
#     "cd frontend && npm test" --expect "the second call must not reach the server"
# CHECK: cd frontend && npm test
# EXPECT: the second call must not reach the server
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/pollGate.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "      if (running) return;\n"
assert text.count(needle) == 1, "the in-flight guard is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
