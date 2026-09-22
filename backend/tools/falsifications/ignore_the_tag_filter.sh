#!/usr/bin/env bash
#
# Break: make the tag filter match prose instead of labels.
#
# The test that must catch it is test_the_tag_filter_finds_tags_and_not_prose: with the
# content added to the predicate, the entry whose *content* says "the coda is hard" matches
# the tag "coda" too.
#
#   ./falsify.sh backend/tools/falsifications/ignore_the_tag_filter.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    if tag:
        clauses.append(
            "j.tags IS NOT NULL AND EXISTS"
            " (SELECT 1 FROM json_each(j.tags) WHERE json_each.value = ? COLLATE NOCASE)"
        )
        params.append(tag)
"""
assert needle in text, "the tag filter is not where this script expects it"
replacement = """    if tag:
        clauses.append("(j.content LIKE ?)")
        params.append(f"%{tag}%")
"""
path.write_text(text.replace(needle, replacement, 1))
PY
