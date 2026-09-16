#!/usr/bin/env bash
#
# Break: move `migrate_workouts` above `SCHEMA`.
#
# `performances.workout_id` exists only because the workout migration adds it to a table
# `SCHEMA` creates. Run the migration first and it finds no `performances` table, skips,
# and `SCHEMA` then creates the table without the column. The frozen
# `EXPECTED_COLUMNS` check against a fresh database must catch it.
#
#   ./falsify.sh backend/tools/falsifications/migrate_workouts_before_schema.sh "./check.sh --fast"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/db.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
removed = "        migrate_workouts(conn)\n        conn.executescript(WORKOUT_SCHEMA)\n"
assert removed in text, "the lines to break are not where this script expects them"
text = text.replace(removed, "        conn.executescript(WORKOUT_SCHEMA)\n", 1)
moved = "        conn.executescript(SCHEMA)\n"
assert moved in text, "the schema script is not where this script expects it"
text = text.replace(
    moved, "        migrate_workouts(conn)\n        conn.executescript(SCHEMA)\n", 1
)
path.write_text(text)
PY
