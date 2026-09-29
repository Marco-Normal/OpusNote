#!/usr/bin/env bash
#
# Break: canonicalise new writes but never touch the rows already stored.
#
# The library this app was built from holds its catalogue numbers in four spellings, so a rule
# that only applies from now on leaves the owner's own 21 pieces inconsistent for ever — which
# is most of what "normalise the opus" means for an existing library.
#
#   ./falsify.sh backend/tools/falsifications/forget_the_stored_opus.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_opus.py"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_opus.py
# EXPECT: test_the_migration_rewrites_the_spellings_already_stored
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    normalised = _normalise_stored_opus(conn)"
assert needle in text, "the data migration is not where this script expects it"
path.write_text(text.replace(needle, "    normalised = 0", 1))
PY
