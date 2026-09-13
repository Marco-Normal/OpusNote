"""Whole-database export and import.

One JSON document holding every table, so a backup is one file to keep and a
machine move is one file to carry. Media files are deliberately *not* embedded:
138 MB of Opus recordings have no business inside a JSON document, and the
``media`` rows do travel, so restoring is "import the document, then copy
``media/``" — which is a directory copy that any file manager can do.

The table list is read from ``sqlite_master`` rather than written down here. A
hand-maintained list is a list that silently goes stale the first time somebody
adds a table, and a backup that quietly omits a table is worse than no backup.
That also means an unknown table in an incoming document is refused rather than
skipped: it means the file came from a different version, and half-importing it
would be the same silent loss from the other direction.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import db
from .hostinfo import require_loopback
from .store import open_connection

#: Bumped whenever the document's shape changes in a way an older reader could
#: not honour. Refusing a newer version is the point of having it.
BACKUP_VERSION = 1
FORMAT = "piano-ecosystem-backup"


class BackupError(Exception):
    """The document is not usable: wrong format, wrong version, or unknown tables."""


def table_names(conn: sqlite3.Connection) -> list[str]:
    """Every table this database owns, in a stable order."""
    return [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def export_document(conn: sqlite3.Connection) -> dict[str, Any]:
    tables: dict[str, list[dict[str, Any]]] = {}
    for name in table_names(conn):
        # Table names come from sqlite_master, never from input.
        tables[name] = [dict(row) for row in conn.execute(f"SELECT * FROM {name}")]
    return {
        "format": FORMAT,
        "version": BACKUP_VERSION,
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "includes_media_files": False,
        "tables": tables,
        "counts": {name: len(rows) for name, rows in tables.items()},
        "notes": [
            "Recording files are not inside this document. The media rows are, so "
            "copy the media directory alongside it to restore playback.",
        ],
    }


def _validate(document: Mapping[str, Any], known: set[str]) -> dict[str, list[dict]]:
    if not isinstance(document, Mapping):
        raise BackupError("the document must be a JSON object")
    if document.get("format") != FORMAT:
        raise BackupError(
            f"not a {FORMAT} document (format={document.get('format')!r})"
        )
    version = document.get("version")
    if not isinstance(version, int):
        raise BackupError("the document has no version")
    if version > BACKUP_VERSION:
        raise BackupError(
            f"the document was written by a newer version ({version} > {BACKUP_VERSION}); "
            "upgrade this app before importing it"
        )
    tables = document.get("tables")
    if not isinstance(tables, Mapping) or not tables:
        raise BackupError("the document has no tables")
    unknown = sorted(set(tables) - known)
    if unknown:
        raise BackupError(
            f"the document contains table(s) this database does not have: "
            f"{', '.join(unknown)}"
        )
    for name, rows in tables.items():
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            raise BackupError(f"table {name!r} is not a list of objects")
    return {name: [dict(row) for row in rows] for name, rows in tables.items()}


def _insert(conn: sqlite3.Connection, table: str, rows: list[dict], *, merge: bool) -> int:
    if not rows:
        return 0
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    written = 0
    for row in rows:
        unknown = sorted(set(row) - set(columns))
        if unknown:
            raise BackupError(
                f"table {table!r} has no column(s) {', '.join(unknown)}; the document "
                "does not match this schema"
            )
        names = [name for name in columns if name in row]
        if not names:
            continue
        placeholders = ", ".join("?" for _ in names)
        verb = "INSERT OR IGNORE" if merge else "INSERT"
        cursor = conn.execute(
            f"{verb} INTO {table} ({', '.join(names)}) VALUES ({placeholders})",
            tuple(row[name] for name in names),
        )
        written += max(cursor.rowcount, 0)
    return written


def import_document(
    conn: sqlite3.Connection,
    document: Mapping[str, Any],
    *,
    mode: str = "merge",
    confirm: bool = False,
) -> dict[str, Any]:
    """Load a backup.

    ``merge`` adds rows whose primary key is not already present and leaves
    everything else alone, which is the safe default: importing a backup you made
    last month must not delete this month's practice.

    ``replace`` empties every table first. It is the only destructive path and
    needs ``confirm``, because it is the wrong answer to "I want to see what is in
    this file".
    """
    if mode not in {"merge", "replace"}:
        raise BackupError(f"unknown mode {mode!r}")
    if mode == "replace" and not confirm:
        raise BackupError("replace discards the current database; pass confirm=true")

    known = set(table_names(conn))
    tables = _validate(document, known)
    written: dict[str, int] = {}
    # All constraints are checked once, at COMMIT, against the finished state.
    # Inserting parent-first would otherwise be a property of the alphabetical
    # order of table names, which is exactly the kind of accident that breaks the
    # day somebody adds a table. The caller owns the transaction, so a failure
    # here rolls the whole import back.
    conn.execute("PRAGMA defer_foreign_keys = ON")
    if mode == "replace":
        for name in known:
            conn.execute(f"DELETE FROM {name}")
    for name, rows in tables.items():
        written[name] = _insert(conn, name, rows, merge=mode == "merge")
    return {
        "mode": mode,
        "written": written,
        "total": sum(written.values()),
        "counts": {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                   for name in sorted(known)},
    }


def write_backup(
    *,
    out_dir: Path | None = None,
    keep: int | None = None,
    db_path: Path | None = None,
    now: datetime | None = None,
) -> Path:
    """Write one dated export and prune the oldest beyond `keep`.

    Named by date rather than by time: a nightly job that runs twice, or a manual run
    on the same day, should replace the day's file rather than grow a directory of
    near-identical copies — and "the backup from the 3rd" is what a person looks for.
    """
    from .config import settings as app_settings

    directory = Path(out_dir or app_settings.backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y-%m-%d")
    target = directory / f"piano-ecosystem-{stamp}.json"

    conn = db.connect(db_path)
    try:
        document = export_document(conn)
    finally:
        conn.close()
    target.write_text(json.dumps(document, indent=1))

    limit = max(1, int(keep if keep is not None else app_settings.backup_keep))
    # Newest first by name, which is chronological because the name is a date.
    existing = sorted(directory.glob("piano-ecosystem-*.json"), reverse=True)
    for stale in existing[limit:]:
        stale.unlink(missing_ok=True)
    return target


def latest_backup(out_dir: Path | None = None) -> Path | None:
    from .config import settings as app_settings

    directory = Path(out_dir or app_settings.backup_dir)
    try:
        files = sorted(directory.glob("piano-ecosystem-*.json"), reverse=True)
    except OSError:
        return None
    return files[0] if files else None


def main(argv: list[str] | None = None) -> int:
    """`python -m app.backup` — what the systemd timer runs."""
    import argparse

    parser = argparse.ArgumentParser(description="Write a JSON export of the whole database.")
    parser.add_argument("--out", type=Path, default=None, help="directory to write into")
    parser.add_argument("--keep", type=int, default=None, help="how many to keep")
    args = parser.parse_args(argv)
    path = write_backup(out_dir=args.out, keep=args.keep)
    print(path)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())


# --------------------------------------------------------------------------
# HTTP surface
# --------------------------------------------------------------------------


class BackupImportRequest(BaseModel):
    document: dict[str, Any] = Field(description="A document produced by /api/backup/export")
    mode: Literal["merge", "replace"] = Field(
        default="merge",
        description=(
            "merge adds rows that are not already present and keeps local ones; "
            "replace empties every table first and needs confirm"
        ),
    )
    confirm: bool = False


class BackupImportResult(BaseModel):
    mode: str
    written: dict[str, int]
    total: int
    counts: dict[str, int]


router = APIRouter(prefix="/api/backup", tags=["backup"])


def get_conn():
    conn = open_connection()
    try:
        yield conn
    finally:
        conn.close()


@router.get("/export")
def export(conn: sqlite3.Connection = Depends(get_conn)) -> JSONResponse:
    document = export_document(conn)
    return JSONResponse(
        document,
        headers={
            "Content-Disposition": 'attachment; filename="piano-ecosystem-backup.json"'
        },
    )


@router.post("/import", response_model=BackupImportResult)
def import_backup(request: Request, body: BackupImportRequest) -> BackupImportResult:
    # Conditional, because the same route is safe in one mode: a merge adds what is
    # missing and destroys nothing, so it stays available over the LAN.
    if body.mode == "replace":
        require_loopback(request)
    try:
        with db.transaction() as conn:
            return BackupImportResult(
                **import_document(
                    conn, body.document, mode=body.mode, confirm=body.confirm
                )
            )
    except BackupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
