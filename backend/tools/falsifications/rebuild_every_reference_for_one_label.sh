#!/usr/bin/env bash
#
# Break: make a version miss start over, so one changed label re-derives the whole set again.
#
# This is the state Phase 25 replaces. The miss path is reached correctly and the trigger is
# still exact, but instead of deriving only the segments whose inputs moved it re-reads every
# labelled sitting and re-derives all of them — ~1,000 ms of reads and ~1,900 ms of arithmetic
# on the owner's fixture to apply a one-row change, growing with the labelled notes.
#
# The test that must catch it is test_one_label_change_re_derives_only_that_segment, which
# counts the reads rather than timing them: with the whole set re-derived, the range read never
# runs and the whole-sitting read does.
#
#   ./falsify.sh backend/tools/falsifications/rebuild_every_reference_for_one_label.sh
# CHECK: cd backend && .venv/bin/python -m pytest -q tests/test_autotag.py
# EXPECT: test_one_label_change_re_derives_only_that_segment
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    removed = cached_inputs.keys() - current.keys()
"""
assert needle in text, "the incremental diff is not where this script expects it"
# Put the pre-Phase-25 miss path back, and only that: derive every labelled segment from the
# whole-sitting read and pool from scratch. That is the exact shape this phase replaced, so the
# answer it produces is *correct*, and every equivalence assertion still passes — only the
# work-count test can tell the difference. That is precisely why the guard counts reads.
break_it = """    examples, local = references_from(conn, rows)
    pooled = _pool_features(rows, local)
    return examples, local, pooled, current
    removed = cached_inputs.keys() - current.keys()
"""
path.write_text(text.replace(needle, break_it, 1))
PY
