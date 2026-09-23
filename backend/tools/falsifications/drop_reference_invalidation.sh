#!/usr/bin/env bash
#
# Break: stop a relabel from invalidating the matcher's cached reference material.
#
# `assign_piece` changes a column, not a row, so a cache keyed on the labelled count or
# the segment ids would keep serving the old piece and the matcher would go on training on
# a label the player had already corrected. The trigger on `segments` is what makes that
# impossible, and the test that must catch its absence is
# test_relabelling_a_segment_invalidates_the_cached_references — with this removed it reads
# the stale list from `cached_references` and finds piece A where it expects piece B.
#
#   ./falsify.sh backend/tools/falsifications/drop_reference_invalidation.sh
# CHECK: ./check.sh --fast
# EXPECT: test_relabelling_a_segment_invalidates_the_cached_references
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '''CREATE TRIGGER IF NOT EXISTS trg_segments_reference_update
AFTER UPDATE OF piece_id, identified_by, start_ms, end_ms ON segments
BEGIN
    UPDATE reference_state SET version = version + 1 WHERE id = 1;
END;
'''
assert needle in text, "the update trigger is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
