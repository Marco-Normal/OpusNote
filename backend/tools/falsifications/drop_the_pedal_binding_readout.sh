#!/usr/bin/env bash
#
# Break: stop the pedals panel saying what each pedal is bound to.
#
# The panel is the only place a player can find out that the soft pedal is unbound rather than
# broken, which is the confusion that produced this binding in the first place. The check that
# must catch it is "the panel says the soft pedal is unbound rather than broken" in
# backend/tools/e2e_browser.py's scenario_bench.
#
#   ./falsify.sh backend/tools/falsifications/drop_the_pedal_binding_readout.sh \
#     "(cd frontend && npm run build) && backend/tools/run_e2e.sh bench"
#
# `frontend/dist` is gitignored, so the check builds first and the tree afterwards holds a
# broken bundle until it is rebuilt.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/SetupPanel.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "          {pedal.label} · CC{pedal.cc} · {pedal.binding} · {pedalState(pedal.cc)}\n"
assert needle in text, "the pedal readout is not where this script expects it"
path.write_text(
    text.replace(
        needle,
        "          {pedal.label} · CC{pedal.cc} · {pedalState(pedal.cc)}\n",
        1,
    )
)
PY
