#!/usr/bin/env bash
#
# Break: recompute a sitting's passages on every read.
#
# This is the state before the cache: `passages.derive` runs once per `sitting_detail`, and the
# derivation is a pass over the sitting's notes — 130 ms of a 165 ms open on the owner's largest
# sitting, paid again on every open, every edit's re-read and every dashboard poll. The test that
# must catch it is test_reading_a_sitting_again_does_not_derive_its_passages_again, which counts
# derivations: with the early return gone the second read derives them a second time.
#
#   ./falsify.sh backend/tools/falsifications/recompute_the_passages_on_every_read.sh
# CHECK: ./check.sh --fast
# EXPECT: test_reading_a_sitting_again_does_not_derive_its_passages_again
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    cached = _PASSAGES.get(_database_name(conn), {}).get(sitting_id)
    if cached is not None and cached[0] == key:
        return cached[1], cached[2]

"""
assert needle in text, "the passage cache hit is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
