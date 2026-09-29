#!/usr/bin/env bash
#
# Break: let the streamed document drift away from the shape `export_document` builds.
#
# The stream and the in-memory builder are two traversals of one shape, which is exactly the
# arrangement that goes stale silently — an import would then reject a key, or lose the notes.
# Dropping the notes from the stream is a small, plausible "simplification". The test that must
# catch it is test_the_streamed_export_is_the_same_document.
#
#   ./falsify.sh backend/tools/falsifications/backup_drift_the_streamed_shape.sh
# CHECK: ./check.sh --fast
# EXPECT: test_the_streamed_export_is_the_same_document
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/backup.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    yield f' "notes": {json.dumps(list(_NOTES))}\\n'"""
assert needle in text, "the streamed notes key is not where this script expects it"
path.write_text(text.replace(needle, """    yield ' "notes": []\\n'""", 1))
PY
