#!/usr/bin/env bash
#
# Break: delete one repertoire ADDED_COLUMNS entry.
#
# `media.loop_end_s` is one of the two loop columns. Without it, an existing library is
# upgraded without the column although a fresh one has it; the parity test in
# `test_migration_upgrade.py` and the extended migration test in `test_repertoire.py`
# both name the missing column.
#
#   ./falsify.sh backend/tools/falsifications/drop_repertoire_added_column.sh "./check.sh --fast"
# CHECK: ./check.sh --fast
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '    ("media", "loop_end_s", "REAL"),\n'
assert needle in text, "the line to break is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
