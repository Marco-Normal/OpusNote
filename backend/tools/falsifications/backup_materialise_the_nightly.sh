#!/usr/bin/env bash
#
# Break: put the nightly backup back on `export_document` + one `json.dumps`.
#
# This is the state that peaked at **2,539 MB on a 4 GB machine** on the owner's library — the
# document in memory, then a second multi-hundred-megabyte string for its text. The test that
# must catch it is test_the_nightly_backup_does_not_build_the_whole_document, which replaces
# `export_document` with a function that raises, so a return to this shape cannot be silent.
#
#   ./falsify.sh backend/tools/falsifications/backup_materialise_the_nightly.sh
# CHECK: ./check.sh --fast
# EXPECT: test_the_nightly_backup_does_not_build_the_whole_document
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/backup.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '''    conn = db.connect(db_path)
    staging = target.parent / (target.name + ".part")
    try:
        with staging.open("w", encoding="utf-8") as handle:
            for piece in iter_export_json(conn, now=now):
                handle.write(piece)
    finally:
        conn.close()'''
assert needle in text, "the streamed writer is not where this script expects it"
old = '''    conn = db.connect(db_path)
    try:
        document = export_document(conn, now=now)
    finally:
        conn.close()
    target.write_text(json.dumps(document, indent=1))'''
path.write_text(text.replace(needle, old, 1))
PY
