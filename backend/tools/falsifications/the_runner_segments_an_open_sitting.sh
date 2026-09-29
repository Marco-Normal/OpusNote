#!/usr/bin/env bash
#
# Break: let the sweep select a sitting that is still being played.
#
# `awaiting_segments` asks two questions — has this sitting stopped, and does it have no
# segments yet — and only the second is an optimisation. The first is a correctness boundary:
# a sitting still in progress has provisional boundaries, and because stored segments are
# never recomputed implicitly, provisional boundaries would become permanent, cutting a
# phrase in half. Dropping the `ended_ms + gap < now` half makes every sitting "finished".
#
# The test that must catch it is test_a_tick_leaves_an_open_sitting_alone, which ticks with
# the clock ten seconds after the last note and requires nothing to be queued.
#
#   ./falsify.sh backend/tools/falsifications/the_runner_segments_an_open_sitting.sh
# CHECK: backend/.venv/bin/python -m pytest backend/tests/test_jobs.py -q
# EXPECT: test_a_tick_leaves_an_open_sitting_alone
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '''            " WHERE (s.closed_ms IS NOT NULL OR s.ended_ms + ? < ?)"'''
assert needle in text, "the finished-sitting predicate is not where this script expects it"
path.write_text(text.replace(needle, '''            " WHERE (s.closed_ms IS NOT NULL OR ? < ?)"''', 1))
PY
