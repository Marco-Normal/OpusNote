#!/usr/bin/env bash
#
# Break: leave the pin out of the exercise's identity, so reuse serves the wrong material.
#
# This is the defect class this project has now recorded four times: reuse matched on the
# target skill alone, then on the level profile, then on the bar count, then on the pinned
# key. A pinned hand is the fifth field with the same hazard, and it is the worst of them,
# because a pinned exercise is *not rated* — so serving one for an ordinary request would not
# merely hand the player the wrong material, it would silently stop their attempt counting.
#
# The checks that must catch it are "reuse never crosses a pinned hand" and "reuse never
# crosses a pinned level" in `backend/tests/test_api.py`, which ask for two pins that produce
# an identical level profile and require different exercises back.
#
#   backend/tools/falsify.sh \
#     backend/tools/falsifications/forget_the_pin_when_reusing_an_exercise.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_api.py" \
#     --expect "the left-hand exercise was served for a request for the right hand"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/services.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """            key_name=key_name,
            pinned_level=plan.pinned_level,
            pinned_hand=plan.forced_hand,
        )"""
assert needle in text, "the reuse call is not where this script expects it"
path.write_text(
    text.replace(
        needle,
        """            key_name=key_name,
        )""",
        1,
    )
)
PY
