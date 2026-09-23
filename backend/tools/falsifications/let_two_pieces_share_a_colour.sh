#!/usr/bin/env bash
#
# Break: give every piece the slot its id hashes to, and let two of them collide.
#
# The hash spreads ids well but does not promise that two pieces of one sitting land apart — with
# seven slots, a coincidence is ordinary. Two pieces of one sitting wearing one colour is the
# ambiguity the whole feature exists to remove, and it is invisible in the data: nothing is wrong
# with either piece, the palette is simply asking one colour to mean two things.
#
#   ./falsify.sh backend/tools/falsifications/let_two_pieces_share_a_colour.sh \
#     "cd frontend && npm test"
# CHECK: cd frontend && npm test
# EXPECT: a clash moves the later piece, and leaves the earlier one where it was
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/timelineStrip.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    let slot = base;
    for (let step = 0; step < PIECE_COLOR_COUNT; step += 1) {
      const candidate = (base + step) % PIECE_COLOR_COUNT;
      if (!taken.has(candidate)) {
        slot = candidate;
        break;
      }
    }
"""
assert text.count(needle) == 1, "the free-slot search is not where this script expects it"
path.write_text(text.replace(needle, "    const slot = base;\n", 1))
PY
