#!/usr/bin/env bash
#
# Break: delete the `PRAGMA user_version` write at the end of `init_db`.
#
# The schema is still built correctly, so nothing else notices; the version tests in
# `test_migration_upgrade.py` are the guard, and they are what make "a current database
# reports the current version" a check rather than a comment.
#
#   ./falsify.sh backend/tools/falsifications/drop_user_version_write.sh "./check.sh --fast"
# CHECK: ./check.sh --fast
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/db.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")\n'
assert needle in text, "the line to break is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
