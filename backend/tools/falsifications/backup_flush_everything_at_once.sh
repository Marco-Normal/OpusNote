#!/usr/bin/env bash
#
# Break: buffer the entire document and hand it back as one piece.
#
# This is the memory defect with the writer still "streaming": the pieces become the document,
# so a 160 MB export is one 160 MB string plus the buffer that built it. The test that must
# catch it is test_the_export_is_written_in_bounded_pieces, which asks for pieces and gets one.
#
#   ./falsify.sh backend/tools/falsifications/backup_flush_everything_at_once.sh
# CHECK: ./check.sh --fast
# EXPECT: test_the_export_is_written_in_bounded_pieces
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/backup.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "        if pending >= chunk_bytes:"
assert needle in text, "the flush threshold is not where this script expects it"
path.write_text(text.replace(needle, "        if False:  # break: never flush", 1))
PY
