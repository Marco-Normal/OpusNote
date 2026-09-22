#!/usr/bin/env bash
#
# Break: delete the 20d ADDED_COLUMNS entry for piece_journal.tags.
#
# Without it the ALTER never runs on a library that predates the column, so the upgraded
# schema is missing a column a fresh one has. The parity test in test_migration_upgrade.py
# is what must catch it.
#
#   ./falsify.sh backend/tools/falsifications/drop_journal_added_column.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '    ("piece_journal", "tags", "TEXT"),\n'
assert needle in text, "the line to break is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
