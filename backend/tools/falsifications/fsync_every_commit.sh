#!/usr/bin/env bash
#
# Break: put every connection back on `synchronous = FULL`, the SQLite default.
#
# FULL fsyncs the write-ahead log on every COMMIT. It is the durable-across-a-power-cut
# setting, and it is what this repository paid until the owner accepted the weaker guarantee:
# measured on the real 512,010-note library, a COMMIT costs 1.165 ms at FULL against 0.012 ms
# at NORMAL, and a plain piece *read* performs two commits. The test that must catch this is
# test_a_commit_does_not_fsync_the_write_ahead_log, which reads the pragma back off a fresh
# connection.
#
#   ./falsify.sh backend/tools/falsifications/fsync_every_commit.sh
# CHECK: ./check.sh --fast
# EXPECT: test_a_commit_does_not_fsync_the_write_ahead_log
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/db.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = 'conn.execute("PRAGMA synchronous = NORMAL")'
assert needle in text, "the synchronous pragma is not where this script expects it"
path.write_text(text.replace(needle, 'conn.execute("PRAGMA synchronous = FULL")', 1))
PY
