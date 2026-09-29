#!/usr/bin/env bash
#
# Break: put the wide invalidation rule back on the reference cache.
#
# This is the state before Phase 24: every insert, delete and relevant-looking update on
# `segments` bumps `reference_state.version`, whether or not the row is training data. That
# makes segmenting a sitting throw away the matcher's references — `ensure_segments` inserts
# its new segments unlabelled and then tags them from any overlapping workout — so the first
# click on a fresh sitting pays ~985 ms to rebuild the material it is about to read. Measured
# on the owner's library: 1,755 ms with this rule, 770 ms with the narrow one.
#
# The test that must catch it is
# test_segmenting_a_sitting_does_not_rebuild_the_references, which counts how many times the
# references are derived while a sitting is segmented. Counted rather than timed, so a quiet
# machine cannot make it pass.
#
#   ./falsify.sh backend/tools/falsifications/widen_the_reference_invalidation.sh
# CHECK: backend/.venv/bin/python -m pytest backend/tests/test_autotag.py -q
# EXPECT: must not rebuild the references
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()

guards = [
    (
        "CREATE TRIGGER trg_segments_reference_insert\n"
        "AFTER INSERT ON segments\n"
        "WHEN NEW.piece_id IS NOT NULL AND COALESCE(NEW.identified_by, '') <> 'similarity'\n",
        "CREATE TRIGGER trg_segments_reference_insert\n"
        "AFTER INSERT ON segments\n",
    ),
    (
        "CREATE TRIGGER trg_segments_reference_delete\n"
        "AFTER DELETE ON segments\n"
        "WHEN OLD.piece_id IS NOT NULL AND COALESCE(OLD.identified_by, '') <> 'similarity'\n",
        "CREATE TRIGGER trg_segments_reference_delete\n"
        "AFTER DELETE ON segments\n",
    ),
    (
        "WHEN (OLD.piece_id IS NOT NULL AND COALESCE(OLD.identified_by, '') <> 'similarity')\n"
        "  OR (NEW.piece_id IS NOT NULL AND COALESCE(NEW.identified_by, '') <> 'similarity')\n",
        "",
    ),
]

for needle, replacement in guards:
    assert needle in text, "a trigger guard is not where this script expects it"
    text = text.replace(needle, replacement, 1)

path.write_text(text)
PY
