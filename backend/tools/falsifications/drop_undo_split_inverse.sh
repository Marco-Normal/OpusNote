#!/usr/bin/env bash
#
# Break: stop recognising a split, so the Undo control would offer a label edit instead.
#
# The test that must catch it is 'a split is undone by merging the two halves back' in
# frontend/src/lib/segmentUndo.test.ts.
#
#   ./falsify.sh backend/tools/falsifications/drop_undo_split_inverse.sh "cd frontend && npm test"
# CHECK: cd frontend && npm test
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/segmentUndo.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "  if (added.length === 1 && removed.length === 0) {"
assert needle in text, "the branch is not where this script expects it"
path.write_text(text.replace(needle, "  if (false) {", 1))
PY
