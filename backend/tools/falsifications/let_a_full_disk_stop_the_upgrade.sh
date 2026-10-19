#!/usr/bin/env bash
#
# Break: vacuum without guarding the disk, so a full one refuses to start.
#
# The pedal conversion commits before the vacuum, and the vacuum only reclaims pages the
# dropped table left on the freelist. Removing the guard makes a database on a nearly full
# disk fail `init_db` — a service that never starts, for space rather than for data.
#
#   ./falsify.sh backend/tools/falsifications/let_a_full_disk_stop_the_upgrade.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py -k failed_vacuum"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py -k failed_vacuum
# EXPECT: failed_vacuum
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/db.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
start = text.index("            try:\n                conn.execute(\"VACUUM\")")
close = "                )\n"
end = text.index(close, text.index("file=sys.stderr,", start)) + len(close)
assert "except sqlite3.OperationalError" in text[start:end]
assert text[start:end].rstrip().endswith(")"), "the guard's last line is the print's close"
path.write_text(text[:start] + '            conn.execute("VACUUM")\n' + text[end:])
PY
