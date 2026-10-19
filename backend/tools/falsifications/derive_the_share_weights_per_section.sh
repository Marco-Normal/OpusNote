#!/usr/bin/env bash
#
# Break: derive the share weights again for every open section.
#
# `shingles.idf` says how much each feature tells the labelled pieces apart. It is a property of
# the reference set, not of the section being identified, so the sitting's identification pass
# derives it once and hands it to every section. Passing `None` instead restores exactly the
# shape that was measured at 1.05 s to open a sitting: one walk over every piece's features per
# unlabelled section. The scores are identical either way, which is why only a work count sees it.
#
#   ./falsify.sh backend/tools/falsifications/derive_the_share_weights_per_section.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_autotag.py -k share_weights"
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_autotag.py -k share_weights
# EXPECT: share_weights
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    share_weights = shingles.idf(signatures)\n"
assert needle in text, "the hoisted derivation is not where this script expects it"
path.write_text(text.replace(needle, "    share_weights = None\n", 1))
PY
