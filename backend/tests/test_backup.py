"""Backup export and import.

A backup that has never been restored is a file, not a backup, so the round trip
is tested rather than the endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path

from app import backup
from app.practice import store as practice_store
from app.practice.models import EventBatch, WireNote, WirePedal

BASE_MS = 1_700_011_800_000
LATER_MS = BASE_MS + 10_000_000


def _populate(client) -> int:
    """A database with something in every domain, so the round trip means something."""
    composer = client.post("/api/repertoire/composers", json={"name": "Brahms"}).json()
    piece = client.post(
        "/api/repertoire/pieces",
        json={
            "title": "Intermezzo",
            "composer_id": composer["id"],
            "key": "A Major",
            "difficulty": "Late Intermediate",
            "opus": "Op. 118 No. 2",
        },
    ).json()
    client.post(
        f"/api/repertoire/pieces/{piece['id']}/journal",
        json={"entry_date": "2026-05-01", "content": "Inner voices uneven.", "practice_minutes": 25},
    )
    sitting_id = practice_store.ingest(
        EventBatch(
            tz_offset_minutes=0,
            events=[
                WireNote(
                    epoch_ms=BASE_MS + offset,
                    pitch=60 + index,
                    velocity=70,
                    duration_ms=300,
                    channel=0,
                )
                for index, offset in enumerate((0, 500, 20_000, 60_000))
            ],
            # Pedalling is data like any other, and a backup that dropped it would
            # still restore a database that looks complete.
            pedals=[WirePedal(epoch_ms=BASE_MS + 200, value=127, channel=0)],
        )
    ).sitting_id
    segments = practice_store.ensure_segments(sitting_id, now_ms=LATER_MS)
    practice_store.assign_piece(segments[0].id, piece["id"])
    client.post("/api/workout/start", json={"tz_offset_minutes": 0})
    client.post("/api/workout/1/finish")
    return piece["id"]


def test_an_export_covers_every_table(client) -> None:
    _populate(client)
    document = client.get("/api/backup/export").json()
    assert document["format"] == backup.FORMAT
    assert document["version"] == backup.BACKUP_VERSION
    assert document["includes_media_files"] is False

    # Derived from sqlite_master, so a table added later cannot be forgotten.
    from app.db import connect

    conn = connect()
    try:
        expected = set(backup.table_names(conn))
    finally:
        conn.close()
    assert set(document["tables"]) == expected
    assert {
        "composers",
        "pieces",
        "piece_journal",
        "sittings",
        "note_events",
        "pedal_events",
        "segments",
        "workouts",
        "exercises",
        "performances",
    } <= set(document["tables"])


def test_a_backup_round_trips_through_a_wipe(client) -> None:
    """The only test that proves a backup is a backup."""
    piece_id = _populate(client)
    document = client.get("/api/backup/export").json()
    before = document["counts"]
    assert before["pieces"] == 1
    assert before["note_events"] == 4
    assert before["segments"] == 2
    assert before["workouts"] == 1

    # Wipe it, the way a broken machine would: everything, not just one table.
    from app.db import connect

    conn = connect()
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        for table in backup.table_names(conn):
            conn.execute(f"DELETE FROM {table}")
    finally:
        conn.close()
    assert client.get("/api/practice/sittings").json() == []

    restored = client.post(
        "/api/backup/import",
        json={"document": document, "mode": "replace", "confirm": True},
    ).json()
    assert restored["mode"] == "replace"
    assert restored["written"]["pieces"] == 1

    reread = client.get("/api/backup/export").json()
    assert reread["counts"] == before, "every table came back with the same row count"
    assert reread["counts"]["pedal_events"] == 1, "including the pedalling"

    detail = client.get(f"/api/repertoire/pieces/{piece_id}").json()
    assert detail["title"] == "Intermezzo"
    assert detail["journal"][0]["practice_minutes"] == 25
    sitting = client.get("/api/practice/sittings/1").json()
    assert sitting["segments"][0]["piece_id"] == piece_id
    assert sitting["segments"][0]["metrics"]["median_tempo"] is not None
    assert client.get("/api/workout").json()["workouts_completed"] == 1


def test_merging_a_backup_keeps_what_is_already_here(client) -> None:
    """Importing last month's backup must not delete this month's practice."""
    _populate(client)
    document = client.get("/api/backup/export").json()

    # Something recorded after the backup was taken.
    sitting_id = practice_store.ingest(
        EventBatch(
            tz_offset_minutes=0,
            events=[
                WireNote(
                    epoch_ms=BASE_MS + 86_400_000,
                    pitch=60,
                    velocity=70,
                    duration_ms=300,
                    channel=0,
                )
            ],
        )
    ).sitting_id

    result = client.post("/api/backup/import", json={"document": document}).json()
    assert result["mode"] == "merge"
    assert result["written"]["pieces"] == 0, "an existing row is left alone, not duplicated"
    counts = result["counts"]
    assert counts["pieces"] == 1
    assert counts["sittings"] == 2, "the newer sitting survives the merge"
    assert client.get(f"/api/practice/sittings/{sitting_id}").status_code == 200


def test_merging_twice_changes_nothing(client) -> None:
    _populate(client)
    document = client.get("/api/backup/export").json()
    first = client.post("/api/backup/import", json={"document": document}).json()
    second = client.post("/api/backup/import", json={"document": document}).json()
    assert first["written"] == second["written"]
    assert first["counts"] == second["counts"]


def test_replace_refuses_without_confirmation(client) -> None:
    _populate(client)
    document = client.get("/api/backup/export").json()
    response = client.post(
        "/api/backup/import", json={"document": document, "mode": "replace"}
    )
    assert response.status_code == 422
    assert "confirm" in response.json()["detail"]
    # And nothing was destroyed by the refusal.
    assert client.get("/api/backup/export").json()["counts"]["pieces"] == 1


def test_a_document_from_another_app_is_refused(client) -> None:
    response = client.post(
        "/api/backup/import", json={"document": {"format": "something-else", "tables": {}}}
    )
    assert response.status_code == 422
    assert "not a" in response.json()["detail"]


def test_a_newer_document_is_refused(client) -> None:
    document = client.get("/api/backup/export").json()
    document["version"] = backup.BACKUP_VERSION + 1
    response = client.post("/api/backup/import", json={"document": document})
    assert response.status_code == 422
    assert "newer version" in response.json()["detail"]


def test_a_document_with_an_unknown_table_is_refused(client) -> None:
    """Half-importing it would lose that table's rows silently."""
    document = client.get("/api/backup/export").json()
    document["tables"]["mystery"] = [{"id": 1}]
    response = client.post("/api/backup/import", json={"document": document})
    assert response.status_code == 422
    assert "mystery" in response.json()["detail"]


def test_a_row_with_an_unknown_column_is_refused(client) -> None:
    """A schema that moved on, rather than a table that never existed."""
    document = client.get("/api/backup/export").json()
    document["tables"]["composers"].append({"id": 99, "name": "Ravel", "invented": True})
    response = client.post("/api/backup/import", json={"document": document})
    assert response.status_code == 422
    assert "invented" in response.json()["detail"]


def test_an_empty_table_list_is_refused(client) -> None:
    response = client.post(
        "/api/backup/import", json={"document": {"format": backup.FORMAT, "version": 1}}
    )
    assert response.status_code == 422


def test_an_unknown_mode_is_refused(client) -> None:
    document = client.get("/api/backup/export").json()
    response = client.post(
        "/api/backup/import", json={"document": document, "mode": "append"}
    )
    assert response.status_code == 422


def test_an_export_of_an_empty_database_is_still_a_document(client) -> None:
    document = client.get("/api/backup/export").json()
    assert document["counts"]["pieces"] == 0
    assert document["tables"]["pieces"] == []
    # And restoring it is a no-op rather than an error.
    result = client.post("/api/backup/import", json={"document": document}).json()
    assert result["total"] == 0


def test_the_export_offers_itself_as_a_download(client) -> None:
    response = client.get("/api/backup/export")
    assert "attachment" in response.headers["content-disposition"]
    assert "piano-ecosystem-backup.json" in response.headers["content-disposition"]


def test_the_document_reports_that_media_files_are_not_in_it(client) -> None:
    document = client.get("/api/backup/export").json()
    assert any("media" in note for note in document["notes"])


def test_a_backup_is_written_and_rotated(tmp_path, fresh_db, client) -> None:
    """The directory keeps the newest N, and names by date so a re-run replaces."""
    _populate(client)
    first = backup.write_backup(out_dir=tmp_path, keep=2)
    assert first.exists()
    assert first.name.startswith("piano-ecosystem-")
    document = json.loads(first.read_text())
    assert document["counts"]["pieces"] == 1, "a backup is a full export"

    # Same day again: one file, not two.
    again = backup.write_backup(out_dir=tmp_path, keep=2)
    assert again == first
    assert len(list(tmp_path.glob("piano-ecosystem-*.json"))) == 1


def test_rotation_keeps_the_newest(tmp_path, fresh_db) -> None:
    from datetime import datetime

    for day in range(1, 5):
        backup.write_backup(
            out_dir=tmp_path, keep=2, now=datetime(2026, 9, day)
        )
    kept = sorted(path.name for path in tmp_path.glob("piano-ecosystem-*.json"))
    assert kept == ["piano-ecosystem-2026-09-03.json", "piano-ecosystem-2026-09-04.json"]
    assert backup.latest_backup(tmp_path).name == "piano-ecosystem-2026-09-04.json"


def test_latest_backup_is_none_when_there_are_no_backups(tmp_path) -> None:
    assert backup.latest_backup(tmp_path) is None


def test_the_cli_writes_a_backup(tmp_path, fresh_db, capsys) -> None:
    assert backup.main(["--out", str(tmp_path), "--keep", "3"]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed.endswith(".json")
    assert Path(printed).exists()
