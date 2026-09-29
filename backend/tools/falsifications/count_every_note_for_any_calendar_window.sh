#!/usr/bin/env bash
#
# Break: make the calendar's window empty, so it filters nothing.
#
# This is the state before the fix: the window was applied only by `_fill_days` at the end, so a
# one-day calendar grouped every note event in the database and then kept a single day — 20 ms
# flat for any window, on a poll. Emptying `since` is the same defect with the bindings left
# intact. The test that must catch it is test_the_calendar_only_reads_its_own_window, which counts
# work: with no filter, one day costs exactly what forty days cost.
#
#   ./falsify.sh backend/tools/falsifications/count_every_note_for_any_calendar_window.sh
# CHECK: ./check.sh --fast
# EXPECT: test_the_calendar_only_reads_its_own_window
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    since = (_today() - timedelta(days=days - 1)).isoformat()
    days_rows = conn.execute("""
replacement = """    since = ""
    days_rows = conn.execute("""
assert needle in text, "the calendar's window is not where this script expects it"
path.write_text(text.replace(needle, replacement, 1))
PY
