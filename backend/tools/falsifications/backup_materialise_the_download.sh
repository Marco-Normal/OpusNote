#!/usr/bin/env bash
#
# Break: put the download route back on `JSONResponse(export_document(conn))`.
#
# The same defect on the other owner: the server builds the document and its text in full, then
# hands the text to Starlette. Measured through TestClient that was 948 MB, most of it the server
# side. The test that must catch it is
# test_the_download_route_does_not_build_the_whole_document.
#
#   ./falsify.sh backend/tools/falsifications/backup_materialise_the_download.sh
# CHECK: ./check.sh --fast
# EXPECT: test_the_download_route_does_not_build_the_whole_document
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/backup.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '''    def body() -> Iterator[str]:
        conn = open_connection()
        try:
            yield from iter_export_json(conn)
        finally:
            conn.close()

    return StreamingResponse(
        body(),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="piano-ecosystem-backup.json"'
        },
    )'''
assert needle in text, "the streamed route is not where this script expects it"
old = '''    from fastapi.responses import JSONResponse

    conn = open_connection()
    try:
        document = export_document(conn)
    finally:
        conn.close()
    return JSONResponse(
        document,
        headers={
            "Content-Disposition": 'attachment; filename="piano-ecosystem-backup.json"'
        },
    )'''
path.write_text(text.replace(needle, old, 1))
PY
