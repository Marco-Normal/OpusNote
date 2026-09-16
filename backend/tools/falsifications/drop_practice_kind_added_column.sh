#!/usr/bin/env bash
#
# Break: delete the 20a ADDED_COLUMNS entry for segments.practice_kind.
#
# Without it the ALTER never runs on a database that predates Phase 20a, so the upgraded
# schema is missing a column a fresh one has. The parity test in test_migration_upgrade.py
# is what must catch it — an assertion derived from ADDED_COLUMNS itself could not, because
# the deleted entry leaves the loop.
#
#   ./falsify.sh backend/tools/falsifications/drop_practice_kind_added_column.sh "./check.sh --fast"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '    ("segments", "practice_kind", "TEXT"),\n'
assert needle in text, "the line to break is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
