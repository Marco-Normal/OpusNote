#!/usr/bin/env bash
#
# Break: score a note struck during the count-in.
#
# The count-in is playing time, not scored time. Capture is anchored at beat 1 on purpose — so a
# note played early is *measurably* early rather than silently fitted — which means a note struck
# while following the count-in clicks arrives with a negative onset. Admitting one is not a small
# error: the server matches nothing at a negative onset, so it becomes an unmatched *extra* that
# costs pitch precision for every note of the exercise, and in the browser the live matcher has no
# such guard, so a stray note can claim an expected note as correct and finish the run before the
# player has been counted in.
#
# The check that must catch it is "a note struck during the count-in is before the downbeat" in
# `frontend/src/lib/scoredAttempt.test.ts`.
#
#   backend/tools/falsify.sh backend/tools/falsifications/score_during_the_count_in.sh
# CHECK: cd frontend && npm test
# EXPECT: a note struck during the count-in is before the downbeat
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/scoredAttempt.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "  return note.onset < 0;"
assert needle in text, "the count-in guard is not where this script expects it"
# A note from this morning would then be "part of the attempt" too, which is the point: the rule
# has to be a boundary, not a tolerance.
path.write_text(text.replace(needle, "  return false;", 1))
PY
