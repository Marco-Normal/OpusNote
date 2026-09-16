#!/usr/bin/env bash
#
# Break: put back the D1 defect — add `segments.workout_id` with no REFERENCES.
#
# The old database does not have the column, so the ALTER is what gives it the foreign
# key. Without the reference the column still appears, which is why a name-only parity
# check would pass; `test_the_upgraded_segments_workout_reference_is_kept` and the
# foreign-key half of the parity test must catch it.
#
#   ./falsify.sh backend/tools/falsifications/drop_segments_workout_reference.sh "./check.sh --fast"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '("segments", "workout_id", "INTEGER REFERENCES workouts(id) ON DELETE SET NULL"),'
assert needle in text, "the line to break is not where this script expects it"
path.write_text(text.replace(needle, '("segments", "workout_id", "INTEGER"),', 1))
PY
