#!/usr/bin/env bash
#
# Break: drop the `INSERT ... SELECT` that carries the outcome rows into the rebuilt
# table.
#
# The rebuild is a `CREATE`/`INSERT`/`DROP`/`RENAME`; without the copy it is a rebuild
# that deletes every row, which is worse than the old cascading constraint. The upgrade
# test asserts the outcome row survived with its `segment_id` and score.
#
#   ./falsify.sh backend/tools/falsifications/drop_outcome_rebuild_insert.sh "./check.sh --fast"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = (
    "        INSERT INTO identification_outcomes_rebuilt\n"
    "            (id, segment_id, guessed_piece_id, resolved_piece_id, action,\n"
    "             accepted, score, resolved_at)\n"
    "            SELECT id, segment_id, guessed_piece_id, resolved_piece_id, action,\n"
    "                   accepted, score, resolved_at\n"
    "            FROM identification_outcomes;\n"
)
assert needle in text, "the INSERT to break is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
