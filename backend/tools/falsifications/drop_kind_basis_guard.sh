#!/usr/bin/env bash
#
# Break: drop the "an offer is not a label" rule from the kind split.
#
# The CASE is what maps an unanswered proposal onto the untagged bucket. Replacing it with
# the raw column counts an offer as a kind, which is exactly the silent guess the feature
# promises never to make. The test that must catch it is
# test_an_offer_is_a_question_until_it_is_answered.
#
#   ./falsify.sh backend/tools/falsifications/drop_kind_basis_guard.sh "./check.sh --fast"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """            SELECT CASE
                       WHEN g.practice_kind_basis IN ('manual', 'accepted')
                       THEN g.practice_kind
                       ELSE NULL
                   END AS kind,"""
assert needle in text, "the guard is not where this script expects it"
path.write_text(text.replace(needle, "            SELECT g.practice_kind AS kind,", 1))
PY
