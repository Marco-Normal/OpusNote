#!/usr/bin/env bash
#
# Break: delete the `("performances", "workout_id", ...)` ADDED_COLUMNS entry.
#
# This is the only place `performances.workout_id` is declared at all — `db.py`'s
# `performances` CREATE has no such column — so deleting the entry removes it from a
# *fresh* database too. The frozen `EXPECTED_COLUMNS` literal in
# `test_migration_upgrade.py` is what must catch that; this is the entry the parity
# comparison alone would still notice on an upgraded database.
#
#   ./falsify.sh backend/tools/falsifications/drop_workout_added_column.sh "./check.sh --fast"
# CHECK: ./check.sh --fast
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/workout/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = (
    "    (\n"
    '        "performances",\n'
    '        "workout_id",\n'
    '        "INTEGER REFERENCES workouts(id) ON DELETE SET NULL",\n'
    "    ),\n"
)
assert needle in text, "the entry to break is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
