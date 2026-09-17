"""Queries for the repertoire domain.

Reading and writing both live here: the pieces, their journal, and their media.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Sequence

from .. import db
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
        # Journal prose is searchable too. "Where did I write about the coda?" is a
        # question the library should be able to answer, and the text is already
        # sitting in the database next to the piece.
        clauses.append(
            "(p.title LIKE ? OR c.name LIKE ? OR p.opus LIKE ?"
            " OR EXISTS (SELECT 1 FROM piece_journal j"
            "            WHERE j.piece_id = p.id AND j.content LIKE ?))"
        )
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern, pattern])
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
        _journal_row(row)
        for row in conn.execute(
            """
            SELECT id, piece_id, entry_date, content, practice_minutes,
                   sitting_id, tags, difficulty, fluency, media_id, created_at
            FROM piece_journal WHERE piece_id = ?
            ORDER BY entry_date DESC, id DESC
            """,
            (piece_id,),
        )
    ]
    piece["media"] = list_media(conn, piece_id=piece_id)
    piece["passages"] = list_passages(conn, piece_id)
    return piece


def list_passages(conn: sqlite3.Connection, piece_id: int) -> list[dict[str, Any]]:
    """A piece's focus passages, the least recently worked on first.

    Never-touched passages sort first: "I have not looked at this at all" is a stronger
    reason to be shown something than "I looked at it three weeks ago". Ties break on bar
    number so the order is stable between reads.
    """
    rows = conn.execute(
        """
        SELECT id, piece_id, start_bar, end_bar, label, source, media_id,
               created_at, last_worked_on
        FROM piece_passages
        WHERE piece_id = ?
        ORDER BY (last_worked_on IS NOT NULL), last_worked_on ASC, start_bar ASC, id ASC
        """,
        (piece_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def create_passage(conn: sqlite3.Connection, piece_id: int, fields: dict[str, Any]) -> int:
    cursor = conn.execute(
        """
        INSERT INTO piece_passages
            (piece_id, start_bar, end_bar, label, source, media_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            piece_id,
            fields["start_bar"],
            fields["end_bar"],
            fields.get("label"),
            fields.get("source", "manual"),
            fields.get("media_id"),
        ),
    )
    return int(cursor.lastrowid)


def get_passage(conn: sqlite3.Connection, passage_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, piece_id, start_bar, end_bar, label, source, media_id,"
        " created_at, last_worked_on FROM piece_passages WHERE id = ?",
        (passage_id,),
    ).fetchone()
    return dict(row) if row else None


def update_passage(conn: sqlite3.Connection, passage_id: int, changes: dict[str, Any]) -> int:
    allowed = ("start_bar", "end_bar", "label", "last_worked_on")
    updates = {key: value for key, value in changes.items() if key in allowed}
    if not updates:
        return conn.execute(
            "SELECT COUNT(*) FROM piece_passages WHERE id = ?", (passage_id,)
        ).fetchone()[0]
    assignments = ", ".join(f"{column} = :{column}" for column in updates)
    return conn.execute(
        f"UPDATE piece_passages SET {assignments} WHERE id = :passage_id",
        {**updates, "passage_id": passage_id},
    ).rowcount


def delete_passage(conn: sqlite3.Connection, passage_id: int) -> int:
    return conn.execute("DELETE FROM piece_passages WHERE id = ?", (passage_id,)).rowcount


def list_media(conn: sqlite3.Connection, *, piece_id: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT id, piece_id, kind, file_name, original_name, title,
               duration_secs, size_bytes, codec, taken_on,
               loop_start_s, loop_end_s,
               source, sitting_id, segment_id, captured_start_ms
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
               loop_start_s, loop_end_s,
               source, sitting_id, segment_id, captured_start_ms
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


def _journal_row(row: Any) -> dict[str, Any]:
    """One journal row in the wire shape: the tag array decoded, everything else as stored.

    Written with `db.json_load`, which raises on a corrupt row rather than degrading to an
    empty list — a tag set that silently became "no tags" is a filter that silently stops
    finding things, which is the failure mode Slice 1's T9 decision exists to prevent.
    """
    data = dict(row)
    data["tags"] = db.json_load(data.get("tags"), [])
    return data


def create_journal_entry(conn: sqlite3.Connection, piece_id: int, fields: dict[str, Any]) -> int:
    cursor = conn.execute(
        """
        INSERT INTO piece_journal
            (piece_id, entry_date, content, practice_minutes, sitting_id,
             tags, difficulty, fluency, media_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            piece_id,
            fields["entry_date"],
            fields["content"],
            fields.get("practice_minutes"),
            fields.get("sitting_id"),
            db.json_dump(fields.get("tags") or []),
            fields.get("difficulty"),
            fields.get("fluency"),
            fields.get("media_id"),
        ),
    )
    return int(cursor.lastrowid)


def update_journal_entry(conn: sqlite3.Connection, entry_id: int, changes: dict[str, Any]) -> int:
    allowed = (
        "entry_date", "content", "practice_minutes", "sitting_id",
        "tags", "difficulty", "fluency", "media_id",
    )
    updates = {key: value for key, value in changes.items() if key in allowed}
    if "tags" in updates:
        updates["tags"] = None if updates["tags"] is None else db.json_dump(updates["tags"])
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
        "SELECT id, piece_id, entry_date, content, practice_minutes, sitting_id,"
        " tags, difficulty, fluency, media_id"
        " FROM piece_journal WHERE id = ?",
        (entry_id,),
    ).fetchone()
    return _journal_row(row) if row else None


def media_exists(conn: sqlite3.Connection, media_id: int) -> bool:
    """Whether this recording is in the library. The same 422-not-500 rule as `sitting_id`."""
    return conn.execute("SELECT 1 FROM media WHERE id = ?", (media_id,)).fetchone() is not None


def sitting_exists(conn: sqlite3.Connection, sitting_id: int) -> bool:
    """Whether the practice log has a sitting with this id.

    The first of the repertoire domain's read-only looks at a practice table, and it is here
    because the journal points at the sitting an entry was written about. Checking it turns a
    stale id into a 422 instead of a foreign-key failure surfacing as a 500 with no
    explanation. The take attachment below reads practice tables for the same reason; none of
    them writes one.
    """
    return (
        conn.execute("SELECT 1 FROM sittings WHERE id = ?", (sitting_id,)).fetchone()
        is not None
    )


def sitting_at(conn: sqlite3.Connection, epoch_ms: int) -> int | None:
    """The sitting an instant falls in, or None.

    The window is the practice domain's own ingest rule — `started_ms` to `ended_ms` plus the
    sitting gap, the same predicate `_find_sitting` uses — rather than the bare note range.
    A take's epoch is the instant its recorder opened, which is a tick after the first note,
    and for a one-note phrase that tick can land past the note's release; the note range alone
    would refuse audio that plainly belongs to the sitting.

    `closed_ms` is deliberately *not* required to be NULL, unlike `_find_sitting`. A sitting
    closed by the piano going away still owns the take that was being recorded when it ended,
    and refusing it would throw the audio away.
    """
    row = conn.execute(
        """
        SELECT id FROM sittings
        WHERE ?1 >= started_ms AND ?1 <= ended_ms + ?2
        ORDER BY started_ms DESC
        LIMIT 1
        """,
        (epoch_ms, settings.sitting_gap_s * 1000),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def segment_at(
    conn: sqlite3.Connection, sitting_id: int, epoch_ms: int
) -> tuple[int, int | None] | None:
    """The segment an instant falls in, and the piece it is labelled with.

    Only segments that exist are found: a sitting that is still open has none, and that is a
    real answer (the take keeps its sitting and no segment) rather than an error. It is a
    transient answer, not a final one — `link_unlinked_takes` comes back for the take once the
    sitting has been segmented.
    """
    row = conn.execute(
        """
        SELECT g.id AS segment_id, g.piece_id
        FROM segments g JOIN sittings s ON s.id = g.sitting_id
        WHERE g.sitting_id = ?1
          AND ?2 >= s.started_ms + g.start_ms
          AND ?2 <= s.started_ms + g.end_ms
        ORDER BY g.start_ms
        LIMIT 1
        """,
        (sitting_id, epoch_ms),
    ).fetchone()
    return (int(row["segment_id"]), row["piece_id"]) if row is not None else None


def unlinked_take_sittings(conn: sqlite3.Connection) -> list[int]:
    """The sittings a captured take is still waiting on, read-only.

    A take cut while its sitting was still open has no segment to point at yet, and the
    practice domain only segments a sitting once it has closed. This names the sittings whose
    segmentation the caller should ask the practice domain to finish; see
    `repertoire.api._catch_up_takes`.
    """
    return [
        int(row["sitting_id"])
        for row in conn.execute(
            # Joined to `sittings` rather than trusting `media.sitting_id`: a sitting removed
            # by a maintenance path leaves a dangling id behind, and asking the practice domain
            # to segment a sitting that is not there would raise on a read.
            "SELECT DISTINCT m.sitting_id FROM media m JOIN sittings s ON s.id = m.sitting_id"
            " WHERE m.source = 'captured' AND m.sitting_id IS NOT NULL"
            "   AND m.captured_start_ms IS NOT NULL"
            "   AND (m.segment_id IS NULL OR m.piece_id IS NULL)"
        )
    ]


def link_unlinked_takes(conn: sqlite3.Connection) -> int:
    """Attach every captured take that can now be placed. Writes only `media`.

    A sweep rather than a per-sitting call, because the take that needs attaching is
    characteristically *not* the one being uploaded: the recorder cuts audio 8 seconds after
    the player stops, while the sitting stays open for the five-minute gap, so the segment is
    made long after the take arrived.

    The caller must have asked the practice domain to finish segmenting first; this does not
    materialise anything. A take is revisited while it has no segment *or* no piece, so a take
    whose segment is labelled with a piece later is picked up on the next read rather than
    staying invisible. Both assignments are `COALESCE`: a link already made is not overwritten,
    so a re-read can fill a missing piece without ever moving a take to another passage.
    """
    rows = conn.execute(
        "SELECT id, sitting_id, captured_start_ms FROM media"
        " WHERE source = 'captured' AND sitting_id IS NOT NULL"
        "   AND captured_start_ms IS NOT NULL"
        "   AND (segment_id IS NULL OR piece_id IS NULL)"
    ).fetchall()
    linked = 0
    for row in rows:
        found = segment_at(conn, int(row["sitting_id"]), int(row["captured_start_ms"]))
        if found is None:
            continue
        conn.execute(
            "UPDATE media SET segment_id = COALESCE(segment_id, ?),"
            " piece_id = COALESCE(piece_id, ?) WHERE id = ?",
            (found[0], found[1], int(row["id"])),
        )
        linked += 1
    return linked


def captured_bytes(conn: sqlite3.Connection) -> int:
    """Bytes of audio this app recorded, for the System panel.

    Reported rather than pruned: captured audio is the half of the library that may be
    deleted, and the player decides that, not a retention policy (20e-D6).
    """
    total = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) AS total FROM media WHERE source = 'captured'"
    ).fetchone()["total"]
    return int(total or 0)


def list_journal_entries(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
    search: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    """The newest entries across the whole library.

    `tag` matches a *label*, never the prose: the stored array is written with
    `db.json_dump`'s compact separators, so a tag always appears quoted and adjacent to its
    own quotation marks, and `%"coda"%` cannot match the word "coda" in a sentence.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if search:
        clauses.append("(j.content LIKE ? OR p.title LIKE ? OR c.name LIKE ?)")
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern])
    if tag:
        clauses.append("j.tags LIKE ?")
        params.append(f'%"{tag}"%')
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(limit, 500)))
    rows = conn.execute(
        f"""
        SELECT j.id, j.piece_id, j.entry_date, j.content, j.practice_minutes,
               j.sitting_id, j.tags, j.difficulty, j.fluency, j.media_id,
               j.created_at,
               p.title AS piece_title, c.name AS composer_name
        FROM piece_journal j
        JOIN pieces p ON p.id = j.piece_id
        LEFT JOIN composers c ON c.id = p.composer_id
        {where}
        ORDER BY j.entry_date DESC, j.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_journal_row(row) for row in rows]


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
    source: str = "uploaded",
    sitting_id: int | None = None,
    segment_id: int | None = None,
    captured_start_ms: int | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO media (piece_id, kind, file_name, original_name, title,
                           duration_secs, size_bytes, codec, taken_on,
                           source, sitting_id, segment_id, captured_start_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            piece_id, kind, file_name, original_name, title,
            duration_secs, size_bytes, codec, taken_on,
            source, sitting_id, segment_id, captured_start_ms,
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
