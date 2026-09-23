#!/usr/bin/env bash
#
# Break: point a README link at a document that does not exist.
#
# `check_docs.py`'s link check must catch it. This is the simplest of the four documentation
# gates and the one a hand-edit is most likely to break — renaming a document leaves its links
# behind, and nothing else in the suite would notice.
#
# CHECK: backend/.venv/bin/python backend/tools/check_docs.py
# EXPECT: link does not resolve
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/README.md"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "(docs/FEATURES.md)"
assert needle in text, "the FEATURES link is not where this script expects it"
path.write_text(text.replace(needle, "(docs/FEATURES-MISSING.md)", 1))
PY
