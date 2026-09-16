#!/usr/bin/env bash
#
# Break: delete one practice ADDED_COLUMNS entry.
#
# `segment_metrics.pedal_blur` is the Phase 18b column. Without its entry the ALTER never
# runs on an old database, so the upgraded schema is missing a column a fresh one has.
# The parity test in `test_migration_upgrade.py` is what must catch it — an assertion
# derived from ADDED_COLUMNS itself could not, because the deleted entry leaves the loop.
#
#   ./falsify.sh backend/tools/falsifications/drop_practice_added_column.sh "./check.sh --fast"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '    ("segment_metrics", "pedal_blur", "INTEGER"),\n'
assert needle in text, "the line to break is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
