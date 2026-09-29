#!/usr/bin/env bash
#
# Break: let a restore leave the derived caches as they were.
#
# `init_db` drops them because it may have replaced the file underneath, but an import replaces the
# *rows* and restarts nothing. The passage cache is keyed on a sitting's segment rows and its note
# count, and a `replace` restore reproduces both exactly — so without this call the cache cannot
# tell the restored database from the one it derived from, and keeps serving the old passages. The
# test that must catch it is
# test_a_restore_drops_the_caches_derived_from_the_rows_it_replaced.
#
#   ./falsify.sh backend/tools/falsifications/keep_the_derived_caches_across_a_restore.sh
# CHECK: ./check.sh --fast
# EXPECT: test_a_restore_drops_the_caches_derived_from_the_rows_it_replaced
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/backup.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    from .practice.store import forget_references

    forget_references()
    return {"""
replacement = """    return {"""
assert needle in text, "the cache drop is not where this script expects it"
path.write_text(text.replace(needle, replacement, 1))
PY
