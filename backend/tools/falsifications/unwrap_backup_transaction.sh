#!/usr/bin/env bash
#
# Break: unwrap the backup import route from `db.transaction`.
#
# The connection is opened directly instead, so every statement autocommits. An import
# that fails after the `replace` mode has deleted the tables then leaves the database
# empty rather than rolling back. `test_an_import_that_fails_mid_insert_changes_nothing`
# is the check that must notice.
#
#   ./falsify.sh backend/tools/falsifications/unwrap_backup_transaction.sh "./check.sh --fast"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/backup.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    try:
        with db.transaction() as conn:
            return BackupImportResult(
                **import_document(
                    conn, body.document, mode=body.mode, confirm=body.confirm
                )
            )
    except BackupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
"""
replacement = """    try:
        conn = db.connect()
        result = BackupImportResult(
            **import_document(
                conn, body.document, mode=body.mode, confirm=body.confirm
            )
        )
        conn.close()
        return result
    except BackupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
"""
assert needle in text, "the route body to break is not where this script expects it"
path.write_text(text.replace(needle, replacement, 1))
PY
