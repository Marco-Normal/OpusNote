#!/usr/bin/env bash
#
# Break: never subtract a moved segment from the piece it left.
#
# When a label moves between pieces the old piece must *lose* that segment's features. Skipping
# the subtraction leaves the features counted under both pieces, so the piece that lost the label
# keeps a signature it no longer owns — and because `shingles.idf` and `containment` are both
# built from these signatures, every suggestion involving that piece is then scored against
# evidence the player moved away. It is a silent wrong answer, not a crash.
#
# The test that must catch it is test_moving_a_label_between_pieces_moves_its_contribution_only,
# which asserts the old piece's signature lost exactly that segment and the new one gained it.
#
#   ./falsify.sh backend/tools/falsifications/forget_the_old_piece_when_a_label_moves.sh
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_autotag.py
# EXPECT: test_moving_a_label_between_pieces_moves_its_contribution_only
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    for segment_id, features in old_features.items():
        piece_id = old_pieces[segment_id]
        if piece_id in adjusted:
            adjusted[piece_id].subtract(features)
"""
assert needle in text, "the pool subtraction is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
