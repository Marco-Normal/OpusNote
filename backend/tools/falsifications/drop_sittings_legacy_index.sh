#!/usr/bin/env bash
#
# Break: delete the `idx_sittings_legacy` index.
#
# The columns stay exactly where they are, so the column parity comparison is happy; it
# is the frozen `EXPECTED_INDEXES` literal that notices, and it is the reason that
# literal exists. The partial unique index is what makes a re-import match on the legacy
# id rather than duplicate a sitting.
#
#   ./falsify.sh backend/tools/falsifications/drop_sittings_legacy_index.sh "./check.sh --fast"
# CHECK: ./check.sh --fast
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sittings_legacy\n"
    "    ON sittings(legacy_id) WHERE legacy_id IS NOT NULL;\n"
)
assert needle in text, "the index to break is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
