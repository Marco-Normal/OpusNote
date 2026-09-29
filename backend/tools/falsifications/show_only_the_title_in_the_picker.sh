#!/usr/bin/env bash
#
# Break: put the picker back to naming a piece by its title and composer alone.
#
# The unit tier cannot catch this one. `pieceLabel` is still correct and `npm test` is green —
# what is broken is that the component does not *use* it, which only a browser can see. So the
# check is the scenario, not the unit file.
#
#   ./falsify.sh backend/tools/falsifications/show_only_the_title_in_the_picker.sh \
#     "(cd frontend && npm run build) && backend/tools/run_e2e.sh practice_log"
# CHECK: (cd frontend && npm run build) && backend/tools/run_e2e.sh practice_log
# EXPECT: the picker names a sonata by its catalogue number
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/SegmentTimeline.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """              <option value="">— unidentified —</option>
              {#each pieces as piece (piece.id)}
                <option value={piece.id}>{pieceNames.get(piece.id) ?? pieceLabel(piece)}</option>
              {/each}
"""
assert text.count(needle) == 1, "the segment picker is not where this script expects it"
replacement = """              <option value="">— unidentified —</option>
              {#each pieces as piece (piece.id)}
                <option value={piece.id}>{piece.title}{piece.composer_name
                    ? ` · ${piece.composer_name}`
                    : ''}</option>
              {/each}
"""
path.write_text(text.replace(needle, replacement, 1))
PY
