"""Importing practice history from the standalone practice-logger's database.

The tables may be absent — the logger may never have been used — and a
half-migrated history is worse than none, so both cases are tested.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config import settings
from app.db import connect
from app.practice.legacy import import_legacy_practice
from tests.conftest import add_legacy_practice, build_legacy_db


def _import_repertoire(client) -> dict:
    response = client.post("/api/repertoire/import", json={"copy_media": False})
    assert response.status_code == 200, response.text
    return response.json()


def _counts() -> dict[str, int]:
    conn = connect()
    try:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("sittings", "note_events", "segments")
        }
    finally:
        conn.close()


def test_practice_history_is_copied_with_its_times(fresh_db, legacy_db: Path, client) -> None:
    add_legacy_practice(legacy_db)
    _import_repertoire(client)

    report = client.post("/api/practice/import-legacy").json()
    assert report["available"] is True
    assert (report["sittings"], report["note_events"], report["segments"]) == (2, 5, 1)
    assert _counts() == {"sittings": 2, "note_events": 5, "segments": 1}

    sittings = client.get("/api/practice/sittings").json()
    assert [row["local_date"] for row in sittings] == ["2023-11-22", "2023-11-15"]
    assert [row["note_count"] for row in sittings] == [2, 3]
    assert [row["source"] for row in sittings] == ["web_midi", "web_midi"]


def test_an_imported_segment_points_at_our_piece(fresh_db, legacy_db: Path, client) -> None:
    """The legacy label was a Rust-app piece id; it must resolve through
    `legacy_id`, not be copied across raw."""
    add_legacy_practice(legacy_db)
    _import_repertoire(client)
    client.post("/api/practice/import-legacy")

    conn = connect()
    try:
        local = conn.execute(
            "SELECT id FROM pieces WHERE legacy_id = 1"
        ).fetchone()["id"]
    finally:
        conn.close()

    detail = client.get("/api/practice/sittings/1").json()
    assert detail["segments"][0]["piece_id"] == local
    assert detail["segments"][0]["piece_title"] == "Ballade"
    assert detail["segments"][0]["identified_by"] == "manual"


def test_importing_twice_adds_nothing(fresh_db, legacy_db: Path, client) -> None:
    add_legacy_practice(legacy_db)
    _import_repertoire(client)
    client.post("/api/practice/import-legacy")
    second = client.post("/api/practice/import-legacy").json()
    assert second["sittings"] == 0
    assert second["note_events"] == 0
    assert second["segments"] == 0
    assert second["note"] == "practice history was already imported"
    assert _counts() == {"sittings": 2, "note_events": 5, "segments": 1}


def test_a_database_without_practice_tables_reports_nothing_to_import(
    fresh_db, legacy_db: Path, client
) -> None:
    """The logger may never have been run, which is not an error."""
    report = client.post("/api/practice/import-legacy").json()
    assert report["available"] is False
    assert report["sittings"] == 0
    assert report["note"] == "no practice history in this database"
    assert _counts() == {"sittings": 0, "note_events": 0, "segments": 0}


def test_imported_notes_keep_playing_order_and_dedupe(fresh_db, legacy_db: Path) -> None:
    add_legacy_practice(legacy_db)
    import_legacy_practice(legacy_db)

    conn = connect()
    try:
        rows = conn.execute(
            "SELECT onset_ms, pitch FROM note_events WHERE sitting_id = 1 ORDER BY onset_ms"
        ).fetchall()
    finally:
        conn.close()
    assert [(row["onset_ms"], row["pitch"]) for row in rows] == [
        (0, 60),
        (500, 61),
        (1000, 62),
    ]


def test_a_missing_legacy_database_is_reported_not_guessed(fresh_db) -> None:
    from app.repertoire.importer import LegacyDatabaseMissing

    missing = Path(settings.legacy_db).with_name("not-there.db")
    with pytest.raises(LegacyDatabaseMissing):
        import_legacy_practice(missing)


def test_the_legacy_database_is_never_written(fresh_db, legacy_db: Path, client) -> None:
    """The source is a snapshot: the Rust app keeps working while parity is
    incomplete, so a practice import must not touch it."""
    add_legacy_practice(legacy_db)
    before = legacy_db.read_bytes()
    _import_repertoire(client)
    client.post("/api/practice/import-legacy")
    assert legacy_db.read_bytes() == before

    conn = sqlite3.connect(legacy_db)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_a_legacy_sitting_with_no_source_column_still_imports(
    fresh_db, legacy_db: Path, client
) -> None:
    """The earliest logger databases predate `source`; a missing column must not
    fail the import."""
    add_legacy_practice(legacy_db)
    conn = sqlite3.connect(legacy_db)
    try:
        conn.execute("ALTER TABLE practice_sessions RENAME TO old_sessions")
        conn.execute(
            "CREATE TABLE practice_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " started_ms INTEGER NOT NULL, ended_ms INTEGER NOT NULL, started_at TEXT NOT NULL,"
            " ended_at TEXT NOT NULL, local_date TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO practice_sessions SELECT id, started_ms, ended_ms, started_at,"
            " ended_at, local_date FROM old_sessions"
        )
        conn.execute("DROP TABLE old_sessions")
        conn.commit()
    finally:
        conn.close()

    report = client.post("/api/practice/import-legacy").json()
    assert report["sittings"] == 2
    assert all(row["source"] == "web_midi" for row in client.get("/api/practice/sittings").json())


def test_build_legacy_db_alone_has_no_practice_tables(tmp_path: Path) -> None:
    path = build_legacy_db(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    try:
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()
    assert "practice_sessions" not in names
