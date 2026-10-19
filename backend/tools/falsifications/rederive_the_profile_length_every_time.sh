#!/usr/bin/env bash
#
# Break: derive a profile's length inside every comparison again.
#
# A cosine divides by both profiles' lengths. The lengths are properties of the fingerprints and
# nothing in a ranking changes them, so they are derived once and carried. Reverting the call to
# the public `cosine` re-derives two lengths per comparison — 112,504 square roots on the
# owner's library, three times the `sum` calls, and the single largest reason a sitting with 49
# open sections took a second to open.
#
#   ./falsify.sh backend/tools/falsifications/rederive_the_profile_length_every_time.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_similarity.py -k re_derive_a_length"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_similarity.py -k re_derive_a_length
# EXPECT: lengths that had not changed
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/similarity.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    pitch_class = _cosine(
        segment.pc_profile,
        candidate.pc_profile,
        segment.profile_norm,
        candidate.profile_norm,
    )
"""
assert needle in text, "the prepared cosine call is not where this script expects it"
path.write_text(
    text.replace(needle, "    pitch_class = cosine(segment.pc_profile, candidate.pc_profile)\n", 1)
)
PY
