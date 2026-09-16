#!/usr/bin/env bash
#
# Break: open every connection in rollback-journal mode instead of WAL.
#
# `DEPLOYMENT.md` § Backup documents WAL and the `wal_checkpoint(TRUNCATE)` that makes a
# file copy safe. `test_the_database_is_in_wal_mode_and_can_checkpoint` is the check.
#
#   ./falsify.sh backend/tools/falsifications/journal_mode_delete.sh "./check.sh --fast"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/db.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = 'conn.execute("PRAGMA journal_mode = WAL")'
assert needle in text, "the pragma to break is not where this script expects it"
path.write_text(text.replace(needle, 'conn.execute("PRAGMA journal_mode = DELETE")', 1))
PY
