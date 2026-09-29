#!/usr/bin/env bash
#
# Break: name a piece by its title and composer only, and drop the catalogue number.
#
# This is the reported defect put back: two Beethoven sonatas are both "Sonata", so a picker
# that names them "Sonata · Beethoven" offers two rows nobody can choose between. Everything
# still renders, every other test still passes, and the label is simply ambiguous.
#
#   ./falsify.sh backend/tools/falsifications/drop_the_opus_from_a_pieces_name.sh \
#     "cd frontend && npm test"
# CHECK: cd frontend && npm test
# EXPECT: Sonata · Beethoven · Op. 27 No. 2
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/pieceLabel.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """  const composer = present(piece.composer_name);
  const opus = present(piece.opus);
  if (composer !== null) parts.push(composer);
  if (opus !== null) parts.push(opus);
"""
assert needle in text, "the credits are not where this script expects them"
path.write_text(
    text.replace(
        needle,
        """  const composer = present(piece.composer_name);
  if (composer !== null) parts.push(composer);
""",
        1,
    )
)
PY
