#!/usr/bin/env bash
#
# Break: hand out colours in the order the pieces arrive instead of by the piece's own id.
#
# This is the tempting implementation, and the one the request described: walk the sitting's
# pieces and give the first one slot 1, the next slot 2. It produces the blue/green/red strip the
# user asked to see, and it is wrong for the reason they asked for it — the same piece is a
# different colour in the next sitting, so the colour stops meaning "this piece" and starts
# meaning "the nth piece you happened to play today".
#
# Ordering the walk by id is what makes the answer depend on *which* pieces are present and not on
# the arrangement a split or a re-segment left behind, so removing the sort dissolves both.
#
#   backend/tools/falsify.sh backend/tools/falsifications/colour_a_piece_by_appearance.sh \
#     "cd frontend && npm test" --expect "does not depend on the order"
# CHECK: cd frontend && npm test
# EXPECT: the answer does not depend on the order the sitting lists its pieces
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/timelineStrip.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "  const ordered = [...new Set(pieceIds)].sort((left, right) => left - right);\n"
assert text.count(needle) == 1, "the ordered walk is not where this script expects it"
path.write_text(text.replace(needle, "  const ordered = [...new Set(pieceIds)];\n", 1))
PY
