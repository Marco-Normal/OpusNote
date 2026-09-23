#!/usr/bin/env bash
#
# Break: let each suggestion read the sitting's notes for itself again.
#
# `segment_identification` falls back to `_notes_for_segments(conn, [row])` when it is not
# handed notes, and that query is by *sitting* — it returns every note in the sitting and
# keeps one segment's share. So this is the defect the user reported: while any section is
# unlabelled, a sitting read its own notes once per open section, on every edit's re-read of
# the detail, and the cost vanished the moment the last section was labelled. The test that
# must catch it is test_reading_a_sitting_does_not_read_its_notes_once_per_open_section.
#
#   ./falsify.sh backend/tools/falsifications/read_the_sitting_notes_per_segment.sh
# CHECK: ./check.sh --fast
# EXPECT: test_reading_a_sitting_does_not_read_its_notes_once_per_open_section
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "            notes=notes_by_segment.get(segment_id, []),\n"
assert needle in text, "the handed-down notes are not where this script expects them"
path.write_text(text.replace(needle, "", 1))
PY
