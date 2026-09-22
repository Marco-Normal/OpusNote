#!/usr/bin/env bash
#
# Break: take the pin out of the exercise's identity, so reuse cannot tell pinned material
# apart from the material an ordinary request asked for.
#
# This is the defect class this project has now recorded four times — reuse matched on the
# target skill alone, then on the level profile, then on the bar count, then on the pinned key
# — and the pin is the field with the worst consequence yet, because a pinned exercise is *not
# rated*. Two things break at once: a request for the right hand is served the left-hand
# exercise, because those two requests produce an identical level profile; and an ordinary
# request can be served a pinned exercise, which would silently stop the attempt counting
# toward the ratings.
#
# The break removes the two conditions from the `WHERE` clause as well as the two arguments,
# because removing only the arguments does not test this: the clause would keep filtering on
# the defaults and so refuse to match a pinned row at all — the opposite defect, where pinned
# exercises can never be reused, caught by "reuse still serves the same pinned request twice"
# instead. Measured: the first version of this script did exactly that, and `falsify.sh
# --expect` refused to attribute the failure.
#
# The checks that must catch it are "reuse never crosses a pinned hand" and "reuse never
# crosses a pinned level" in `backend/tests/test_api.py`.
#
#   backend/tools/falsify.sh \
#     backend/tools/falsifications/forget_the_pin_when_reusing_an_exercise.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_api.py" \
#     --expect "the left-hand exercise was served for a request for the right hand"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()

where_needle = """          AND IFNULL(json_extract(e.params_json, '$.pinned_key'), '') = ?
          AND IFNULL(json_extract(e.params_json, '$.pinned_level'), '') = ?
          AND IFNULL(json_extract(e.params_json, '$.pinned_hand'), '') = ?
"""
where_broken = """          AND IFNULL(json_extract(e.params_json, '$.pinned_key'), '') = ?
"""
assert where_needle in text, "the pinned conditions are not where this script expects them"

params_needle = """        key_name or "",
        pinned_level if pinned_level is not None else "",
        pinned_hand or "",
    )"""
params_broken = """        key_name or "",
    )"""
assert params_needle in text, "the pinned parameters are not where this script expects them"

path.write_text(text.replace(where_needle, where_broken, 1).replace(params_needle, params_broken, 1))
PY
