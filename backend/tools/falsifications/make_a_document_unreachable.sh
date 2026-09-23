#!/usr/bin/env bash
#
# Break: drop the README's link to a document, leaving the document in the tree but unreachable.
#
# `check_docs.py`'s index check must catch it. A document nothing links to is a document nobody
# reads, which is how fifteen of this repository's twenty-one documents — including several of the
# stale ones — came to be unreachable from the front page.
#
# CHECK: backend/.venv/bin/python backend/tools/check_docs.py
# EXPECT: no link to docs/TEST-DATA.md
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/README.md"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "[docs/TEST-DATA.md](docs/TEST-DATA.md)"
assert needle in text, "the TEST-DATA index entry is not where this script expects it"
path.write_text(text.replace(needle, "`docs/TEST-DATA.md`", 1))
PY
