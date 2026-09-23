#!/usr/bin/env bash
#
# Break: store blur positions relative to their segment instead of to the sitting.
#
# The other half of the same ambiguity, and the one a future "tidy-up" is most likely to reach for:
# if the renderer should not add the offset, the tempting fix is to make the *stored* value
# segment-relative instead. That would be wrong — the timeline divides a position by the sitting's
# length and draws it on the strip's own sitting-relative axis, so segment-relative storage would
# be drawn one segment-length too early — and it would silently reinterpret every stored row.
#
# The check that must catch it is
# `test_a_blur_position_is_measured_from_the_sitting_not_its_segment`, whose fixture puts the blur
# in a segment that does not start at zero. At offset zero the two conventions are the same number,
# which is exactly why nothing caught the original defect.
#
#   ./falsify.sh backend/tools/falsifications/store_blur_positions_per_segment.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_practice_store.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "                db.json_dump(list(pedalling.blur_at_ms)),"
replacement = (
    "                db.json_dump(\n"
    '                    [at - int(segment["start_ms"]) for at in pedalling.blur_at_ms]\n'
    "                ),"
)
assert needle in text, "the blur write is not where this script expects it"
path.write_text(text.replace(needle, replacement, 1))
PY
