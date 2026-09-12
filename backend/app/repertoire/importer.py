"""One-time import from the legacy `piano-progress` database.

The source is opened **read-only** and never written. That app keeps working
untouched while the web replacement reaches parity, and the import can be run
again to pick up whatever it has gained in the meantime — which is why every
write here is an upsert keyed on the original primary key rather than an insert.

Preserving the legacy ids keeps `pieces.composer_id` and `media.piece_id`
meaningful without an id-mapping table, and makes a re-import idempotent.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

#: Tables the import expects to find, so a wrong file fails loudly rather than
#: silently importing nothing.
REQUIRED_SOURCE_TABLES = ("composers", "pieces", "notes", "media")


class LegacyDatabaseMissing(RuntimeError):
    """The legacy database is not where configuration says it should be."""


class LegacySchemaUnexpected(RuntimeError):
    """The file exists but does not look like a piano-progress database."""


@dataclass
class ImportReport:
    source_db: str
    composers: int = 0
    pieces: int = 0
    journal_entries: int = 0
    media_rows: int = 0
    media_copied: int = 0
    media_missing: int = 0
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _open_source(path: Path) -> sqlite3.Connection:
    """Read-only, and tolerant of the source being in WAL mode.

    `mode=ro` alone fails when the writer's `-wal` file is present but `-shm` is
    not creatable, which is exactly the situation when the legacy app is closed.
    `immutable=1` tells SQLite the file cannot change under us, so it will not
    try to recover the WAL — safe here because the import is a snapshot and any
    re-run picks up newer data.
    """
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        return conn
    except sqlite3.OperationalError:
        conn = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
        conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        return conn


def _source_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _upsert(
    target: sqlite3.Connection,
    *,
    table: str,
    legacy_id: int,
    columns: dict[str, object],
) -> int:
    """Insert or update one legacy row, matched on `legacy_id`.

    Matching on the primary key was the obvious thing and it was wrong: local
    rows and legacy rows draw from the same autoincrement sequence, so importing
    could overwrite a piece the player had created here. The two id spaces are
    independent and are kept that way.
    """
    existing = target.execute(
        f"SELECT id FROM {table} WHERE legacy_id = ?", (legacy_id,)
    ).fetchone()
    if existing is not None:
        assignments = ", ".join(f"{name} = :{name}" for name in columns)
        target.execute(
            f"UPDATE {table} SET {assignments} WHERE id = :local_id",
            {**columns, "local_id": existing["id"]},
        )
        return int(existing["id"])

    names = ", ".join(columns)
    placeholders = ", ".join(f":{name}" for name in columns)
    cursor = target.execute(
        f"INSERT INTO {table} (legacy_id, {names}) VALUES (:legacy_id, {placeholders})",
        {**columns, "legacy_id": legacy_id},
    )
    return int(cursor.lastrowid)


def _upsert_composers(
    target: sqlite3.Connection, source: sqlite3.Connection, report: ImportReport
) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for row in source.execute("SELECT id, name, notes FROM composers"):
        mapping[row["id"]] = _upsert(
            target,
            table="composers",
            legacy_id=int(row["id"]),
            columns={"name": row["name"], "notes": row["notes"]},
        )
        report.composers += 1
    return mapping


def _upsert_pieces(
    target: sqlite3.Connection,
    source: sqlite3.Connection,
    report: ImportReport,
    composer_map: dict[int, int],
) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for row in source.execute(
        """
        SELECT id, composer_id, title, opus, difficulty, key, started_on,
               status, description, created_at
        FROM pieces
        """
    ):
        mapping[row["id"]] = _upsert(
            target,
            table="pieces",
            legacy_id=int(row["id"]),
            columns={
                # Relationships are remapped, not copied: the local composer may
                # have a different id from the legacy one.
                "composer_id": composer_map.get(row["composer_id"]) if row["composer_id"] else None,
                "title": row["title"],
                "opus": row["opus"],
                "difficulty": row["difficulty"],
                "key": row["key"],
                "started_on": row["started_on"],
                "status": row["status"] or "active",
                "description": row["description"],
                "created_at": row["created_at"],
            },
        )
        report.pieces += 1
    return mapping


def _upsert_journal(
    target: sqlite3.Connection,
    source: sqlite3.Connection,
    report: ImportReport,
    piece_map: dict[int, int],
) -> None:
    """`piano-progress.notes` holds prose about a piece, not musical notes.

    Renamed on the way in — see `app.repertoire.schema`.
    """
    for row in source.execute(
        "SELECT id, piece_id, entry_date, content, practice_minutes, created_at FROM notes"
    ):
        local_piece = piece_map.get(row["piece_id"]) if row["piece_id"] else None
        if local_piece is None:
            report.skipped.append(f"journal entry {row['id']} has no piece")
            continue
        _upsert(
            target,
            table="piece_journal",
            legacy_id=int(row["id"]),
            columns={
                "piece_id": local_piece,
                "entry_date": row["entry_date"],
                "content": row["content"] or "",
                "practice_minutes": row["practice_minutes"],
                "created_at": row["created_at"],
            },
        )
        report.journal_entries += 1


def _upsert_media(
    target: sqlite3.Connection,
    source: sqlite3.Connection,
    report: ImportReport,
    piece_map: dict[int, int],
    *,
    copy_media: bool,
    source_media_dir: Path,
    target_media_dir: Path,
) -> None:
    if copy_media:
        # Only when there is something to put in it: creating an empty media
        # directory as a side effect of a metadata-only import is surprising.
        target_media_dir.mkdir(parents=True, exist_ok=True)
    seen_files: set[str] = set()
    for row in source.execute(
        """
        SELECT id, piece_id, kind, file_name, original_name, title,
               duration_secs, size_bytes, codec, taken_on, created_at
        FROM media
        """
    ):
        record = dict(row)
        name = str(record["file_name"])
        if name not in seen_files:
            seen_files.add(name)
            origin = source_media_dir / name
            if copy_media:
                if origin.exists():
                    destination = target_media_dir / name
                    if not destination.exists():
                        shutil.copy2(origin, destination)
                    report.media_copied += 1
                else:
                    report.media_missing += 1
                    report.notes.append(f"recording file missing: {name}")

        _upsert(
            target,
            table="media",
            legacy_id=int(record["id"]),
            columns={
                "piece_id": piece_map.get(record["piece_id"]) if record["piece_id"] else None,
                "kind": record["kind"],
                "file_name": name,
                "original_name": record["original_name"],
                "title": record["title"],
                "duration_secs": record["duration_secs"],
                "size_bytes": record["size_bytes"],
                "codec": record["codec"],
                "taken_on": record["taken_on"],
                "created_at": record["created_at"],
            },
        )
        report.media_rows += 1


def import_legacy(
    target: sqlite3.Connection,
    *,
    source_path: Path,
    source_media_dir: Path | None = None,
    target_media_dir: Path | None = None,
    copy_media: bool = False,
) -> ImportReport:
    """Copy the legacy library into our schema. Idempotent; safe to re-run."""
    source_path = Path(source_path)
    if not source_path.exists():
        raise LegacyDatabaseMissing(
            f"{source_path} does not exist. Set SRT_LEGACY_DB to the piano-progress "
            "database, or leave it unset if you never used that app."
        )

    source = _open_source(source_path)
    source.row_factory = sqlite3.Row
    try:
        present = _source_tables(source)
        missing = [table for table in REQUIRED_SOURCE_TABLES if table not in present]
        if missing:
            raise LegacySchemaUnexpected(
                f"{source_path} has no {', '.join(missing)} table(s), so it is not a "
                "piano-progress database."
            )

        report = ImportReport(source_db=str(source_path))
        # Relationships are remapped, so each stage must precede the one that
        # references it.
        composer_map = _upsert_composers(target, source, report)
        piece_map = _upsert_pieces(target, source, report, composer_map)
        _upsert_journal(target, source, report, piece_map)
        _upsert_media(
            target,
            source,
            report,
            piece_map,
            copy_media=copy_media,
            source_media_dir=Path(source_media_dir or source_path.parent / "media"),
            target_media_dir=Path(target_media_dir or source_path.parent / "media"),
        )
        return report
    finally:
        source.close()
