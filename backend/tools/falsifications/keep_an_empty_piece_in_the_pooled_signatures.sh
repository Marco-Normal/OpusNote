#!/usr/bin/env bash
#
# Break: keep a piece whose signature came out empty in the pooled map.
#
# `Counter.subtract` leaves the keys it zeroed in place, and a Counter whose values are all zero
# is still *truthy* — so the obvious `if counts` keeps a piece that has just lost its last label.
# That piece is not inert: `shingles.idf` counts `max(1, len(signatures))` documents and weights
# every shingle by how many pieces contain it, so one extra empty "document" shifts every IDF
# weight in the library and therefore every score. There is no crash and no visible symptom; the
# matcher simply starts answering differently.
#
# The test that must catch it is
# test_a_piece_that_loses_its_last_label_leaves_the_pooled_signatures, which compares the pooled
# **key set** against a full rebuild rather than only the counters — a comparison that normalises
# empty signatures away would not see this at all.
#
#   ./falsify.sh backend/tools/falsifications/keep_an_empty_piece_in_the_pooled_signatures.sh
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_autotag.py
# EXPECT: test_a_piece_that_loses_its_last_label_leaves_the_pooled_signatures
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "        piece_id: counts for piece_id, counts in adjusted.items() if any(counts.values())"
assert needle in text, "the pooled prune is not where this script expects it"
# Truthiness of the Counter itself, which an all-zero Counter satisfies.
break_it = "        piece_id: counts for piece_id, counts in adjusted.items() if counts"
path.write_text(text.replace(needle, break_it, 1))
PY
