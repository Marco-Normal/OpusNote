#!/usr/bin/env bash
#
# Break: delete the 20e ADDED_COLUMNS entry for media.source.
#
# The parity test in test_migration_upgrade.py is what must catch it.
#
#   ./falsify.sh backend/tools/falsifications/drop_media_source_column.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '    ("media", "source", "TEXT NOT NULL DEFAULT \'uploaded\'"),\n'
assert needle in text, "the line to break is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
