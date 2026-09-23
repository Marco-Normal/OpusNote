#!/usr/bin/env bash
#
# Break: stop sending the marks with the batch.
#
# A review flag is buffered in the capture client and travels with the next ingest, exactly as a
# pedal move does. Removing it from the body leaves the buffer growing and the flag never reaching
# a sitting — the failure is silent, which is why the assertion exists.
#
# The check that must catch it is the bench scenario's "and a single tap flags the place instead",
# which reads the mark back from the sitting over HTTP.
#
#   ./falsify.sh backend/tools/falsifications/drop_the_mark_stream.sh \
#     "(cd frontend && npm run build) && backend/tools/run_e2e.sh bench"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/capture.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "        events: batch,\n        pedals,\n        marks,\n"
assert needle in text, "the ingest body is not where this script expects it"
path.write_text(text.replace(needle, "        events: batch,\n        pedals,\n", 1))
PY
