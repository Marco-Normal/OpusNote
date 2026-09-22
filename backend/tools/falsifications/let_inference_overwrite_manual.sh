#!/usr/bin/env bash
#
# Break: let the offer pass write over a segment that already carries a kind.
#
# That is the bug that turns an offer into a silent overwrite of the player's own
# decision. The test that must catch it is test_inference_never_overwrites_a_kind_a_person_chose,
# which is built on the slow segment precisely so an offer is produced when the guard goes.
#
#   ./falsify.sh backend/tools/falsifications/let_inference_overwrite_manual.sh "./check.sh --fast"
# CHECK: ./check.sh --fast
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """        if row["practice_kind"] is not None or row["practice_kind_basis"] is not None:
            continue
"""
assert needle in text, "the guard is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
