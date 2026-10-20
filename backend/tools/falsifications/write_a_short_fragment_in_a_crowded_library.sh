#!/usr/bin/env bash
#
# Break: let the decoded confidence stand as the whole truth, whatever the segment's shape.
#
# This is the failure the calibration exists to prevent. A nine-note fragment against thirty
# pieces measured 67-76% precise at every confidence threshold, so its smooth probability is
# not the frequency with which it is right — but with the crowded guard removed the app
# writes it anyway, and a wrong label is silently accepted as a label. The decode and the
# sitting are both correct, so only the calibration assertion dies.
#
#   ./check.sh --falsify write_a_short_fragment
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_calibration.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/calibration.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    if pieces <= CROWDED_PIECES:
        return base
    if notes < SHORT_NOTES:
        return None
"""
assert text.count(needle) == 1, "the crowded guard is not where this script expects it"
path.write_text(text.replace(needle, "    return base\n", 1))
PY
