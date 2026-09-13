"""Queries for the repertoire domain.

Read-only for now: Phase 1 imports and displays, editing arrives in Phase 2.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Sequence

from ..config import settings


def _media_dir() -> Path:
    return Path(settings.media_dir)


def _legacy_media_dir() -> Path:
    """Where the Rust app kept its recordings, used only as a source.

    Reading from here is a convenience so recordings play before they have been
    copied. It is never written to, and once the copy has run there is no
    dependency on it.
    """
    return Path(settings.legacy_db).parent / "media"


def _safe_name(file_name: str) -> str | None:
    """Reject anything that is not a bare file name.

    Recording names are content hashes, so a separator or a parent reference
    means the database has been tampered with, not that a path is intended.
    """
    name = (file_name or "").strip()
    if not name or name in {".", ".."}:
        return None
    if "/" in name or "\\" in name or "\x00" in name:
        return None
    return name


def media_state(file_name: str) -> str:
    """Where a recording actually is.

    Three states, because "missing" was previously reported for a file that
    existed all along in the legacy directory and had simply not been copied
    yet — which reads as data loss.
    """
    name = _safe_name(file_name)
    if name is None:
        return "missing"
    if (_media_dir() / name).exists():
        return "present"
    if (_legacy_media_dir() / name).exists():
        return "pending"
    return "missing"


def resolve_media_path(file_name: str) -> Path | None:
    """The file to serve: ours if we have it, otherwise the legacy original."""
    name = _safe_name(file_name)
    if name is None:
        return None
    own = _media_dir() / name
    if own.exists():
        return own
    legacy = _legacy_media_dir() / name
    return legacy if legacy.exists() else None


def list_pieces(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    composer_id: int | None = None,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Pieces with the aggregates the library view needs, in one query.

    Aggregates are computed here rather than per-piece in the caller: 17 pieces
    would be 17 round trips, and the counts are what the list is for.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("p.status = ?")
        params.append(status)
    if composer_id is not None:
        clauses.append("p.composer_id = ?")
        params.append(composer_id)
    if search:
        clauses.append("(p.title LIKE ? OR c.name LIKE ? OR p.opus LIKE ?)")
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    rows = conn.execute(
        f"""
        SELECT p.id, p.title, p.composer_id, c.name AS composer_name, p.opus,
               p.difficulty, p.key, p.status, p.started_on, p.description,
               p.created_at,
               (SELECT COUNT(*) FROM piece_journal j WHERE j.piece_id = p.id)
                   AS journal_entries,
               (SELECT COALESCE(SUM(j.practice_minutes), 0) FROM piece_journal j
                 WHERE j.piece_id = p.id) AS logged_minutes,
               (SELECT COUNT(*) FROM media m
                 WHERE m.piece_id = p.id AND m.kind <> 'score')
                   AS recording_count,
               (SELECT COUNT(*) FROM media m
                 WHERE m.piece_id = p.id AND m.kind = 'score')
                   AS score_count
        FROM pieces p
        LEFT JOIN composers c ON c.id = p.composer_id
        {where}
        ORDER BY c.name COLLATE NOCASE, p.title COLLATE NOCASE
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def get_piece(conn: sqlite3.Connection, piece_id: int) -> dict[str, Any] | None:
    rows = list_pieces(conn)
    piece = next((row for row in rows if row["id"] == piece_id), None)
    if piece is None:
        return None
    piece["journal"] = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, piece_id, entry_date, content, practice_minutes, created_at
            FROM piece_journal WHERE piece_id = ?
            ORDER BY entry_date DESC, id DESC
            """,
            (piece_id,),
        )
    ]
    piece["media"] = list_media(conn, piece_id=piece_id)
    return piece


def list_media(conn: sqlite3.Connection, *, piece_id: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT id, piece_id, kind, file_name, original_name, title,
               duration_secs, size_bytes, codec, taken_on,
               loop_start_s, loop_end_s
        FROM media
    """
    params: Sequence[Any] = ()
    if piece_id is not None:
        sql += " WHERE piece_id = ?"
        params = (piece_id,)
    sql += " ORDER BY COALESCE(taken_on, created_at) DESC, id DESC"

    records = []
    for row in conn.execute(sql, params):
        record = dict(row)
        record["state"] = media_state(str(record["file_name"]))
        records.append(record)
    return records


def list_composers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT c.id, c.name, c.notes,
                   (SELECT COUNT(*) FROM pieces p WHERE p.composer_id = c.id)
                       AS piece_count
            FROM composers c
            ORDER BY c.name COLLATE NOCASE
            """
        )
    ]


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    def count(table: str) -> int:
        # Table names come from this module, never from input.
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    return {
        "pieces": count("pieces"),
        "composers": count("composers"),
        "journal_entries": count("piece_journal"),
        "media_rows": count("media"),
        "scores": int(
            conn.execute("SELECT COUNT(*) FROM media WHERE kind = 'score'").fetchone()[0]
        ),
    }


def get_media(conn: sqlite3.Connection, media_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, piece_id, kind, file_name, original_name, title,
               duration_secs, size_bytes, codec, taken_on,
               loop_start_s, loop_end_s
        FROM media WHERE id = ?
        """,
        (media_id,),
    ).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["state"] = media_state(str(record["file_name"]))
    return record


def media_state_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Where the *recordings* are, by state.

    Scores are excluded rather than counted as `present`. They arrive by upload
    and are never copied from the legacy library, so including them would make
    "recordings in library" include documents and the health panel's number would
    stop meaning what it says.
    """
    counts = {"present": 0, "pending": 0, "missing": 0}
    for row in conn.execute("SELECT file_name FROM media WHERE kind <> 'score'"):
        counts[media_state(str(row["file_name"]))] += 1
    return counts


def pending_media(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Recordings that exist in the legacy directory but not in ours."""
    return [
        dict(row)
        for row in conn.execute("SELECT id, file_name FROM media WHERE kind <> 'score'")
        if media_state(str(row["file_name"])) == "pending"
    ]


def find_media_by_file_name(conn: sqlite3.Connection, file_name: str) -> dict[str, Any] | None:
    """The row already holding a content-addressed file, if any.

    Needed because `media.file_name` is unique: a second upload of the same bytes
    is a duplicate entry, not a second file, and the insert would collide. Asking
    first lets the caller refuse it and say where it already lives.
    """
    row = conn.execute(
        """
        SELECT m.id, m.piece_id, m.kind, m.title, m.original_name, p.title AS piece_title
        FROM media m LEFT JOIN pieces p ON p.id = m.piece_id
        WHERE m.file_name = ?
        """,
        (file_name,),
    ).fetchone()
    return dict(row) if row is not None else None


# --------------------------------------------------------------------------
# Editing
#
# Every write returns the affected row count so a caller cannot mistake "no such
# row" for "updated nothing", and none of them commit: the request handler owns
# the transaction.
# --------------------------------------------------------------------------


class RepertoireConflict(RuntimeError):
    """The write is refused because it would damage existing data."""


def composer_exists(conn: sqlite3.Connection, composer_id: int) -> bool:
    return (
        conn.execute("SELECT 1 FROM composers WHERE id = ?", (composer_id,)).fetchone()
        is not None
    )


def create_piece(conn: sqlite3.Connection, fields: dict[str, Any]) -> int:
    cursor = conn.execute(
        """
        INSERT INTO pieces (composer_id, title, opus, difficulty, key,
                            started_on, status, description)
        VALUES (:composer_id, :title, :opus, :difficulty, :key,
                :started_on, :status, :description)
        """,
        {
            "composer_id": fields.get("composer_id"),
            "title": fields["title"],
            "opus": fields.get("opus"),
            "difficulty": fields.get("difficulty"),
            "key": fields.get("key"),
            "started_on": fields.get("started_on"),
            "status": fields.get("status") or "active",
            "description": fields.get("description"),
        },
    )
    return int(cursor.lastrowid)


#: Columns a client may change. An allow-list rather than a deny-list: a field
#: added to the table later must not become writable by accident.
PIECE_COLUMNS = (
    "composer_id",
    "title",
    "opus",
    "difficulty",
    "key",
    "started_on",
    "status",
    "description",
)


def update_piece(conn: sqlite3.Connection, piece_id: int, changes: dict[str, Any]) -> int:
    updates = {key: value for key, value in changes.items() if key in PIECE_COLUMNS}
    if not updates:
        return conn.execute("SELECT COUNT(*) FROM pieces WHERE id = ?", (piece_id,)).fetchone()[0]
    assignments = ", ".join(f"{column} = :{column}" for column in updates)
    cursor = conn.execute(
        f"UPDATE pieces SET {assignments} WHERE id = :piece_id",
        {**updates, "piece_id": piece_id},
    )
    return cursor.rowcount


def delete_piece(conn: sqlite3.Connection, piece_id: int) -> tuple[int, dict[str, int]]:
    """Delete a piece and report everything that went with it.

    The recording *files* are deliberately left on disk. Deleting a piece is a
    library decision; silently destroying the player's own recordings is not
    something a delete should be able to do, and an orphaned file is
    recoverable where a deleted one is not.
    """
    counts = {
        "journal_entries": conn.execute(
            "SELECT COUNT(*) FROM piece_journal WHERE piece_id = ?", (piece_id,)
        ).fetchone()[0],
        "media_rows": conn.execute(
            "SELECT COUNT(*) FROM media WHERE piece_id = ?", (piece_id,)
        ).fetchone()[0],
    }
    cursor = conn.execute("DELETE FROM pieces WHERE id = ?", (piece_id,))
    return cursor.rowcount, counts


def create_composer(conn: sqlite3.Connection, fields: dict[str, Any]) -> int:
    cursor = conn.execute(
        "INSERT INTO composers (name, notes) VALUES (:name, :notes)",
        {"name": fields["name"], "notes": fields.get("notes")},
    )
    return int(cursor.lastrowid)


def update_composer(conn: sqlite3.Connection, composer_id: int, changes: dict[str, Any]) -> int:
    updates = {key: value for key, value in changes.items() if key in ("name", "notes")}
    if not updates:
        return conn.execute(
            "SELECT COUNT(*) FROM composers WHERE id = ?", (composer_id,)
        ).fetchone()[0]
    assignments = ", ".join(f"{column} = :{column}" for column in updates)
    cursor = conn.execute(
        f"UPDATE composers SET {assignments} WHERE id = :composer_id",
        {**updates, "composer_id": composer_id},
    )
    return cursor.rowcount


def delete_composer(conn: sqlite3.Connection, composer_id: int) -> tuple[int, dict[str, int]]:
    """Delete a composer. Its pieces survive with no composer, by design.

    Losing a composer must never lose the repertoire attached to them.
    """
    orphans = conn.execute(
        "SELECT COUNT(*) FROM pieces WHERE composer_id = ?", (composer_id,)
    ).fetchone()[0]
    cursor = conn.execute("DELETE FROM composers WHERE id = ?", (composer_id,))
    return cursor.rowcount, {"pieces_unattributed": orphans}


def create_journal_entry(conn: sqlite3.Connection, piece_id: int, fields: dict[str, Any]) -> int:
    cursor = conn.execute(
        """
        INSERT INTO piece_journal (piece_id, entry_date, content, practice_minutes)
        VALUES (?, ?, ?, ?)
        """,
        (
            piece_id,
            fields["entry_date"],
            fields["content"],
            fields.get("practice_minutes"),
        ),
    )
    return int(cursor.lastrowid)


def update_journal_entry(conn: sqlite3.Connection, entry_id: int, changes: dict[str, Any]) -> int:
    updates = {
        key: value for key, value in changes.items() if key in ("entry_date", "content", "practice_minutes")
    }
    if not updates:
        return conn.execute(
            "SELECT COUNT(*) FROM piece_journal WHERE id = ?", (entry_id,)
        ).fetchone()[0]
    assignments = ", ".join(f"{column} = :{column}" for column in updates)
    cursor = conn.execute(
        f"UPDATE piece_journal SET {assignments} WHERE id = :entry_id",
        {**updates, "entry_id": entry_id},
    )
    return cursor.rowcount


def delete_journal_entry(conn: sqlite3.Connection, entry_id: int) -> int:
    return conn.execute("DELETE FROM piece_journal WHERE id = ?", (entry_id,)).rowcount


def get_journal_entry(conn: sqlite3.Connection, entry_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, piece_id, entry_date, content, practice_minutes FROM piece_journal WHERE id = ?",
        (entry_id,),
    ).fetchone()
    return dict(row) if row else None


def piece_exists(conn: sqlite3.Connection, piece_id: int) -> bool:
    return conn.execute("SELECT 1 FROM pieces WHERE id = ?", (piece_id,)).fetchone() is not None


def find_similar_recording(
    conn: sqlite3.Connection,
    *,
    duration_secs: float | None,
    tolerance_s: float = 0.5,
) -> dict[str, Any] | None:
    """A recording already in the library that looks like the one being added.

    Importing from the Rust app and then re-uploading its originals is the
    obvious way to end up with every recording twice, and the content hash cannot
    catch it: the hash identifies the *source* file, and there is no source to
    compare against once it has been converted.
    """
    if duration_secs is None:
        return None
    row = conn.execute(
        """
        SELECT id, piece_id, file_name, original_name, title, duration_secs
        FROM media
        WHERE duration_secs IS NOT NULL AND ABS(duration_secs - ?) <= ?
        ORDER BY ABS(duration_secs - ?) ASC
        LIMIT 1
        """,
        (float(duration_secs), tolerance_s, float(duration_secs)),
    ).fetchone()
    return dict(row) if row else None


def create_media(
    conn: sqlite3.Connection,
    *,
    piece_id: int | None,
    kind: str,
    file_name: str,
    original_name: str | None,
    title: str | None,
    duration_secs: float | None,
    size_bytes: int | None,
    codec: str | None,
    taken_on: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO media (piece_id, kind, file_name, original_name, title,
                           duration_secs, size_bytes, codec, taken_on)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            piece_id, kind, file_name, original_name, title,
            duration_secs, size_bytes, codec, taken_on,
        ),
    )
    return int(cursor.lastrowid)


def update_media(conn: sqlite3.Connection, media_id: int, changes: dict[str, Any]) -> int:
    # An allowlist, not `changes` wholesale: the request body is a client's, and a
    # column it does not own (a file name, say) must not be writable through a
    # generic PATCH. The loop markers are writable and are validated by the route.
    updates = {
        key: value
        for key, value in changes.items()
        if key in ("title", "piece_id", "loop_start_s", "loop_end_s")
    }
    if not updates:
        return conn.execute("SELECT COUNT(*) FROM media WHERE id = ?", (media_id,)).fetchone()[0]
    assignments = ", ".join(f"{column} = :{column}" for column in updates)
    cursor = conn.execute(
        f"UPDATE media SET {assignments} WHERE id = :media_id",
        {**updates, "media_id": media_id},
    )
    return cursor.rowcount


def delete_media(conn: sqlite3.Connection, media_id: int) -> tuple[int, str | None, bool]:
    """Delete a catalogue row.

    Returns ``(deleted, file_name, file_still_referenced)``. The file is only
    removed by the caller when nothing else points at it, because the same
    content-hashed file can legitimately be attached to more than one row.
    """
    row = conn.execute("SELECT file_name FROM media WHERE id = ?", (media_id,)).fetchone()
    if row is None:
        return 0, None, False
    file_name = str(row["file_name"])
    conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
    remaining = conn.execute(
        "SELECT COUNT(*) FROM media WHERE file_name = ?", (file_name,)
    ).fetchone()[0]
    return 1, file_name, remaining > 0
