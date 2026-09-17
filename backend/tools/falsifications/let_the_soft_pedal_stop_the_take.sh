#!/usr/bin/env bash
#
# Break: bind the soft pedal to capture as well as the sostenuto.
#
# The soft pedal is played mid-phrase, so binding it means an ordinary press ends the take
# being recorded. The check that must catch it is 'the soft pedal is deliberately unbound:
# it is played, so a press does nothing' in frontend/src/lib/pedalGesture.test.ts, and the
# bench scenario's "the soft pedal, which is played, leaves the armed take alone".
#
#   ./falsify.sh backend/tools/falsifications/let_the_soft_pedal_stop_the_take.sh "cd frontend && npm test"
#
# The browser half of the same break, which needs its own build because `frontend/dist` is
# gitignored and `falsify.sh` cannot restore it:
#
#   ./falsify.sh backend/tools/falsifications/let_the_soft_pedal_stop_the_take.sh \
#     "(cd frontend && npm run build) && backend/tools/run_e2e.sh bench"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/pedalGesture.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "export const HANDSFREE_CONTROLLERS: readonly number[] = [66];"
assert needle in text, "the binding is not where this script expects it"
path.write_text(
    text.replace(needle, "export const HANDSFREE_CONTROLLERS: readonly number[] = [66, 67];", 1)
)
PY
