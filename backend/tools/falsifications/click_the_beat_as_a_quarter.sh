#!/usr/bin/env bash
#
# Break: time every beat as a quarter note.
#
# This is the defect this project actually shipped: the metronome was handed seconds-per-*quarter*
# and used it as seconds-per-*beat*, which coincides only when the beat happens to be a quarter. So
# 6/8, 9/8, 12/8, 2/2 and 3/8 all clicked at the wrong rate, counted in wrongly, and in 12/8 the
# run ended a quarter of the way early — silently truncating the performance, which is the worst
# way for a timing bug to fail because nothing reports it.
#
# The checks that must catch it are "every bar lasts its own length in quarters, whatever the beat
# is" and "a compound meter clicks the right number of times for its length" in
# `frontend/src/lib/beatGrid.test.ts`.
#
#   backend/tools/falsify.sh backend/tools/falsifications/click_the_beat_as_a_quarter.sh
# CHECK: cd frontend && npm test
# EXPECT: every bar lasts its own length in quarters
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/beatGrid.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "      elapsed += unit * plan.secondsPerQuarter;"
assert needle in text, "the exercise beat length is not where this script expects it"
path.write_text(text.replace(needle, "      elapsed += plan.secondsPerQuarter;", 1))
PY
