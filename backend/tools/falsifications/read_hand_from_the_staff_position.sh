#!/usr/bin/env bash
#
# Break: go back to reading the hand from the position of the staff.
#
# The renderer used to decide the hand from `staffIndex` — index 0 is the right hand,
# index 1 the left — while the API labels every expected note from the part's own id
# and name. The two agree for a two-hand exercise and for a right-hand-alone exercise,
# and disagree for a left-hand-alone one, which is a single part named "Left Hand" on
# staff 0. Every lookup then missed and every notehead stayed black while the note
# strip below looked perfect, so the defect had no symptom except a console warning.
#
# The checks that must catch it are "every notehead is coloured as correct on the
# score" and the one-notehead-per-note check in `scenario_left_hand_alone` — the only
# scenario that runs texture level 2.
#
# This break edits `frontend/src`, and the browser is served the built bundle rather than the
# source, so `falsify.sh` builds with the break applied and rebuilds on the way out. The check
# command no longer has to do that itself:
#
#   backend/tools/falsify.sh \
#     backend/tools/falsifications/read_hand_from_the_staff_position.sh \
#     "backend/tools/run_e2e.sh left_hand" \
#     --expect "every notehead is coloured as correct"
# CHECK: backend/tools/run_e2e.sh left_hand
# EXPECT: every notehead is coloured as correct
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/score.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """          const instrument = measure.ParentStaff?.ParentInstrument;
          const hand = handForPart(instrument?.IdString, instrument?.Name, staffIndex);"""
assert needle in text, "the hand lookup is not where this script expects it"
path.write_text(text.replace(needle, "          const hand = staffIndex === 0 ? 'RH' : 'LH';", 1))
PY
