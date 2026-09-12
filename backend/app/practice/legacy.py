"""Import practice history from the standalone practice-logger's database.

The standalone app wrote into the Rust app's ``piano.db``. That database is
opened **read-only** here and never written, exactly like the repertoire import,
and the import is idempotent: sittings are matched on their legacy id, note
events on the existing dedupe index.

The practice tables may not exist at all — the logger may never have been used —
so that is a reported "nothing to import", not an error. The same applies per
table: a logger database from before segmentation existed has no ``segments``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import db
from ..repertoire.importer import LegacyDatabaseMissing, _open_source
from .models import PracticeImportReport


def _piece_map(conn: sqlite3.Connection) -> dict[int, int]:
    """legacy piece id -> our piece id, for segments that carried a label."""
    return {
        int(row["legacy_id"]): int(row["id"])
        for row in conn.execute("SELECT id, legacy_id FROM pieces WHERE legacy_id IS NOT NULL")
    }


def import_legacy_practice(
    source_path: Path, db_path: Path | None = None
) -> PracticeImportReport:
    """Copy practice history into our schema. Idempotent; safe to re-run.

    Opens its own write transaction, like the repertoire import, so a failure
    half-way through leaves no partial sitting behind.
    """
    source_path = Path(source_path)
    if not source_path.exists():
        raise LegacyDatabaseMissing(
            f"{source_path} does not exist. Set SRT_LEGACY_DB to the practice-logger "
            "database, or leave it unset if you never used that app."
        )
    with db.transaction(db_path) as conn:
        return _copy(conn, source_path)


def _copy(conn: sqlite3.Connection, source_path: Path) -> PracticeImportReport:
    source = _open_source(source_path)
    source.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in source.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        report = PracticeImportReport(source_db=str(source_path), available=True)
        if "practice_sessions" not in tables or "note_events" not in tables:
            report.available = False
            report.note = "no practice history in this database"
            return report

        pieces = _piece_map(conn)
        sitting_map: dict[int, int] = {}
        for row in source.execute("SELECT * FROM practice_sessions ORDER BY started_ms"):
            legacy_id = int(row["id"])
            start = int(row["started_ms"])
            existing = conn.execute(
                "SELECT id FROM sittings WHERE legacy_id = ?", (legacy_id,)
            ).fetchone()
            if existing is not None:
                sitting_map[legacy_id] = int(existing["id"])
                continue
            created = conn.execute(
                "INSERT INTO sittings (started_ms, ended_ms, started_at, ended_at,"
                " local_date, source, legacy_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                (
                    start,
                    int(row["ended_ms"]),
                    row["started_at"],
                    row["ended_at"],
                    row["local_date"],
                    row["source"] if "source" in row.keys() else "web_midi",
                    legacy_id,
                ),
            )
            sitting_map[legacy_id] = int(created.lastrowid)
            report.sittings += 1

        for row in source.execute("SELECT * FROM note_events"):
            sitting_id = sitting_map.get(int(row["session_id"]))
            if sitting_id is None:
                continue
            cursor = conn.execute(
                "INSERT OR IGNORE INTO note_events"
                " (sitting_id, onset_ms, duration_ms, pitch, velocity, channel)"
                " VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                (
                    sitting_id,
                    int(row["onset_ms"]),
                    int(row["duration_ms"]),
                    int(row["pitch"]),
                    int(row["velocity"]),
                    row["channel"],
                ),
            )
            report.note_events += cursor.rowcount

        if "segments" in tables:
            for row in source.execute("SELECT * FROM segments ORDER BY start_ms"):
                sitting_id = sitting_map.get(int(row["session_id"]))
                if sitting_id is None:
                    continue
                labels = row.keys()
                piece_id = row["piece_id"] if "piece_id" in labels else None
                # A segment only exists once per sitting and boundaries, so this
                # mirrors the dedupe index rather than needing one of its own.
                already = conn.execute(
                    "SELECT 1 FROM segments WHERE sitting_id = ? AND start_ms = ?"
                    " AND end_ms = ?",
                    (sitting_id, int(row["start_ms"]), int(row["end_ms"])),
                ).fetchone()
                if already is not None:
                    continue
                conn.execute(
                    "INSERT INTO segments (sitting_id, start_ms, end_ms, piece_id,"
                    " source, confidence, identified_by)"
                    " VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                    (
                        sitting_id,
                        int(row["start_ms"]),
                        int(row["end_ms"]),
                        pieces.get(int(piece_id)) if piece_id is not None else None,
                        None,
                        row["confidence"] if "confidence" in labels else None,
                        row["identified_by"] if "identified_by" in labels else None,
                    ),
                )
                report.segments += 1

        if report.sittings == 0 and report.note_events == 0:
            report.note = "practice history was already imported"
        return report
    finally:
        source.close()

#: Re-exported so the API layer has one import site for error mapping.
__all__ = ["LegacyDatabaseMissing", "import_legacy_practice"]
