#!/usr/bin/env bash
#
# Break: put the newest-N cap back on the matcher's reference set.
#
# This is the state before Phase 22b, and it is a correctness defect wearing a performance
# fix's clothes: once one piece is labelled more often than the others, a newest-N reference
# set contains only that piece. The quiet piece cannot be recognised, and — worse — it
# cannot be anyone's runner-up, so `margin` has nothing to compare against and the auto band
# stops firing. The test that must catch it is
# test_every_label_is_a_reference_however_lopsided_the_library: thirty new labels of one
# piece and one older label of another must still both be references.
#
#   ./falsify.sh backend/tools/falsifications/cap_the_reference_set.sh
# CHECK: ./check.sh --fast
# EXPECT: test_every_label_is_a_reference_however_lopsided_the_library
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '''    sql += " ORDER BY g.sitting_id, g.start_ms"
    return conn.execute(sql, params).fetchall()'''
assert needle in text, "the uncapped SELECT is not where this script expects it"
capped = '''    sql += " ORDER BY g.sitting_id DESC, g.start_ms DESC LIMIT 20"
    return list(reversed(conn.execute(sql, params).fetchall()))'''
path.write_text(text.replace(needle, capped, 1))
PY
