#!/usr/bin/env bash
#
# Break: stop a split from carrying a person's practice kind to the new half.
#
# This is the state Phase 20a shipped in: `split_segment` copied `source` and
# `workout_id` and not `practice_kind`, so tagging a segment and then splitting it
# silently dropped the tag on one half. The test that must catch it is
# test_a_kind_a_person_set_survives_a_split_on_both_halves.
#
#   ./falsify.sh backend/tools/falsifications/drop_split_kind_inheritance.sh "./check.sh --fast"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '''            "INSERT INTO segments (sitting_id, start_ms, end_ms, source, workout_id,"
            " practice_kind, practice_kind_basis)"
            " VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            (
                sitting_id,
                int(right[0]["onset_ms"]),
                right_end,
                row["source"],
                row["workout_id"],
                inherit_kind,
                inherit_basis,
            ),'''
assert needle in text, "the INSERT is not where this script expects it"
replacement = '''            "INSERT INTO segments (sitting_id, start_ms, end_ms, source, workout_id)"
            " VALUES (?1, ?2, ?3, ?4, ?5)",
            (
                sitting_id,
                int(right[0]["onset_ms"]),
                right_end,
                row["source"],
                row["workout_id"],
            ),'''
path.write_text(text.replace(needle, replacement, 1))
PY
