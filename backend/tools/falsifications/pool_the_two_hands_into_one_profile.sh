#!/usr/bin/env bash
#
# Break: score the hands together, so a one-hand drill is diluted by the other hand's notes.
#
# This is exactly the failure Phase 22e exists to remove. Pooled, a right-hand drill of a
# two-handed passage scores 0.77 against it instead of 1.0, and a one-hand drill stops
# looking like the passage it is. Only the hand assertion dies: the pitch-class profile the
# other tests use is untouched.
#
#   ./check.sh --falsify pool_the_two_hands_into_one_profile
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_similarity.py -k two_hands
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/similarity.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    total = 0.0
    weighted = 0.0"""
assert text.count(needle) == 1, "hand_overlap is not where this script expects it"
text = text.replace(
    needle,
    """    return cosine(left.pc_profile, right.pc_profile)
    total = 0.0
    weighted = 0.0""",
    1,
)
path.write_text(text)
PY
