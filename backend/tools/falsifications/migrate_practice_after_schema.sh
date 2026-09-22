#!/usr/bin/env bash
#
# Break: run `migrate_practice` *after* `PRACTICE_SCHEMA`, reversing the ordering
# contract `db.py`'s docstring states.
#
# On an existing database the practice script creates a partial unique index on
# `sittings.legacy_id`, which cannot succeed until the migration has added the column.
# The upgrade test must fail rather than silently produce a database without the index.
#
#   ./falsify.sh backend/tools/falsifications/migrate_practice_after_schema.sh "./check.sh --fast"
# CHECK: ./check.sh --fast
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/db.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "        migrate_practice(conn)\n        conn.executescript(PRACTICE_SCHEMA)\n"
assert needle in text, "the lines to break are not where this script expects them"
path.write_text(
    text.replace(
        needle,
        "        conn.executescript(PRACTICE_SCHEMA)\n        migrate_practice(conn)\n",
        1,
    )
)
PY
