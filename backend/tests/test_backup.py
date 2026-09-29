"""Backup export and import.

A backup that has never been restored is a file, not a backup, so the round trip
is tested rather than the endpoint.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app import backup, db
from app.practice import store as practice_store
from app.practice.models import EventBatch, WireNote, WirePedal
from tests.conftest import phrase_offsets

BASE_MS = 1_700_011_800_000
LATER_MS = BASE_MS + 10_000_000

#: Two phrases a long pause apart. Each is the minimum size `segment.cut` keeps, so the
#: sitting holds exactly two segments and a backup that dropped either is visible.
_OFFSETS = phrase_offsets(0, 8) + phrase_offsets(40_000, 8)


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
                for index, offset in enumerate(_OFFSETS)
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
        "identification_outcomes",
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
    assert before["note_events"] == 16
    # Two, not one: Phase 22a cuts on a pause that is long for the passage, so the fixture
    # is two phrases of the minimum size rather than four isolated notes. The count is
    # asserted because a backup that round-trips the wrong *number* of rows is the failure
    # this test exists for.
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


def test_a_replace_restore_leaves_the_matcher_its_cache_version(client) -> None:
    """`replace` empties every table, including the one row the reference cache is keyed on.

    A document exported before that table existed cannot put the row back, and the cache then
    reports "no table to ask" (-1) and is never used at all: about a second on every sitting
    open and every accuracy report, until the next restart happened to repair it. A restore
    must leave the row behind itself, because it does not restart anything.
    """
    _populate(client)
    document = client.get("/api/backup/export").json()
    # A document from before the row existed is, exactly, a document without that table.
    document["tables"].pop("reference_state", None)

    replaced = client.post(
        "/api/backup/import",
        json={"document": document, "mode": "replace", "confirm": True},
    )
    assert replaced.status_code == 200, replaced.text

    conn = db.connect()
    try:
        assert practice_store._reference_version(conn) >= 0, (
            "the reference cache must still have a version to be keyed on after a restore"
        )
    finally:
        conn.close()


def test_a_restore_drops_the_caches_derived_from_the_rows_it_replaced(
    client, monkeypatch
) -> None:
    """A restore rewrites the rows the derived caches are keyed on, in a live process.

    `init_db` drops them because it may have replaced the file underneath. An import replaces the
    *rows* and restarts nothing, so it has to say so itself — and the passage cache is keyed on a
    sitting's segment rows and its note count, which a `replace` restore reproduces exactly.
    Without this, a sitting's passages could stay as they were derived from whatever the database
    held when it was last read, which is the one stale answer the key is otherwise immune to.
    """
    _populate(client)
    sitting_id = int(client.get("/api/practice/sittings").json()[0]["id"])

    practice_store.forget_references()  # a cold cache, so the first read must derive
    derivations = {"n": 0}
    original = practice_store._segment_features

    def counted(conn, rows):
        derivations["n"] += 1
        return original(conn, rows)

    monkeypatch.setattr(practice_store, "_segment_features", counted)
    practice_store.sitting_detail(sitting_id, now_ms=LATER_MS, materialise=False)
    warm = derivations["n"]
    assert warm >= 1, "the first read has to derive them, or this asserts nothing"

    document = client.get("/api/backup/export").json()
    restored = client.post(
        "/api/backup/import",
        json={"document": document, "mode": "replace", "confirm": True},
    )
    assert restored.status_code == 200, restored.text

    practice_store.sitting_detail(sitting_id, now_ms=LATER_MS, materialise=False)
    assert derivations["n"] > warm, (
        "a restore must drop the passages derived from the rows it replaced: the segment rows "
        "and note count it is keyed on come back identical, so nothing else can tell them apart"
    )


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


# --------------------------------------------------------------------------
# The export is a stream, not a string
# --------------------------------------------------------------------------


def _explode(*args, **kwargs):
    raise AssertionError("the document must not be materialised to be exported")


def _ingest_notes(count: int = 5000) -> None:
    """Enough notes that the document cannot fit inside a single export piece."""
    practice_store.ingest(
        EventBatch(
            tz_offset_minutes=0,
            events=[
                WireNote(
                    epoch_ms=BASE_MS + index * 100,
                    pitch=60,
                    velocity=70,
                    duration_ms=50,
                    channel=0,
                )
                for index in range(count)
            ],
        )
    )


def test_the_streamed_export_is_the_same_document(client) -> None:
    """One owner for the shape: whatever the stream writes, `export_document` also builds.

    The two traversals are separate on purpose — one holds a whole table, the other one row —
    so this pins them together rather than trusting them to stay in step.
    """
    from datetime import datetime, timezone

    _populate(client)
    moment = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    conn = db.connect()
    try:
        streamed = json.loads("".join(backup.iter_export_json(conn, now=moment)))
        built = backup.export_document(conn, now=moment)
    finally:
        conn.close()
    assert streamed == built


def test_the_export_is_written_in_bounded_pieces(client) -> None:
    """No single piece approaches the size of the document, however large the document is.

    This is the point of the change: the nightly backup used to be one `json.dumps` call over
    every row, which peaked at **2.5 GB against a 4 GB machine** on the owner's real library.
    A guard that counted seconds would pass on a fast laptop with that bug present, so this
    counts the *shape* instead — the pieces a stream is made of.
    """
    _ingest_notes()
    conn = db.connect()
    try:
        pieces = list(backup.iter_export_json(conn, chunk_bytes=64 * 1024))
    finally:
        conn.close()
    assert len(pieces) > 3, "the export must arrive as a stream, not one string"
    assert max(len(piece) for piece in pieces) <= 64 * 1024 + 4096, (
        "every piece is the flush threshold plus at most one row"
    )


def test_the_nightly_backup_does_not_build_the_whole_document(
    monkeypatch, tmp_path, fresh_db, client
) -> None:
    """`write_backup` streams, and cannot reach `export_document` at all."""
    _populate(client)
    _ingest_notes()
    pieces = {"count": 0}
    original = backup.iter_export_json

    def counted(*args, **kwargs):
        for piece in original(*args, **kwargs):
            pieces["count"] += 1
            yield piece

    monkeypatch.setattr(backup, "iter_export_json", counted)
    monkeypatch.setattr(backup, "export_document", _explode)
    path = backup.write_backup(out_dir=tmp_path, keep=1)
    assert pieces["count"] > 1, "a backup is written as it is read, not in one string"
    # Compared against the table rather than a literal: the ingest is deduped, so the number of
    # notes that landed is the database's business and the backup's job is to match it.
    conn = db.connect()
    try:
        actual = conn.execute("SELECT COUNT(*) FROM note_events").fetchone()[0]
    finally:
        conn.close()
    assert json.loads(path.read_text())["counts"]["note_events"] == actual > 5000


def test_the_download_route_does_not_build_the_whole_document(monkeypatch, client) -> None:
    """The Download button is the same serializer, so it must stream too.

    Its peak was the smaller of the two — 948 MB — and the browser writes the body straight to
    disk, so the server is the only side that has to hold it.
    """
    _populate(client)
    monkeypatch.setattr(backup, "export_document", _explode)
    response = client.get("/api/backup/export")
    assert response.status_code == 200
    assert response.json()["counts"]["note_events"] == 16


# --------------------------------------------------------------------------
# Shape compatibility, and interrupted work
# --------------------------------------------------------------------------


def test_a_v1_document_in_the_old_shape_still_imports(client) -> None:
    """The guarantee is one-directional: fewer columns is fine, unknown ones refused.

    A document written before `segment_metrics` gained its pedal and touch columns has
    seven columns there, no `piece_journal.sitting_id`, no loop points and no
    `legacy_id`. `_insert` intersects each row with the live columns, so it must land —
    and the columns the document did not carry must stay NULL rather than be invented.
    `BACKUP_VERSION` is deliberately *not* bumped for this: the version refuses a
    *newer* document, it does not certify an older one column-for-column.
    """
    document = {
        "format": backup.FORMAT,
        "version": backup.BACKUP_VERSION,
        "tables": {
            "composers": [{"id": 1, "name": "Chopin", "notes": "Romantic"}],
            "pieces": [
                {
                    "id": 1,
                    "composer_id": 1,
                    "title": "Nocturne",
                    "opus": "Op. 9 No. 2",
                    "difficulty": "Late Intermediate",
                    "key": "E-flat Major",
                    "status": "active",
                    "description": None,
                }
            ],
            "sittings": [
                {
                    "id": 1,
                    "started_ms": BASE_MS,
                    "ended_ms": BASE_MS + 20_000,
                    "started_at": "2026-01-05 10:00:00",
                    "ended_at": "2026-01-05 10:00:20",
                    "local_date": "2026-01-05",
                    "source": "web_midi",
                }
            ],
            "segments": [
                {
                    "id": 1,
                    "sitting_id": 1,
                    "start_ms": 0,
                    "end_ms": 20_000,
                    "piece_id": 1,
                    "confidence": 1.0,
                    "identified_by": "manual",
                }
            ],
            "segment_metrics": [
                {
                    "segment_id": 1,
                    "duration_s": 20.0,
                    "note_count": 3,
                    "median_tempo": 100.0,
                    "mean_velocity": 70.0,
                    "velocity_stddev": 2.5,
                    "restarts": 0,
                }
            ],
            "piece_journal": [
                {
                    "id": 1,
                    "piece_id": 1,
                    "entry_date": "2026-01-05",
                    "content": "From a v1 backup.",
                    "practice_minutes": 10,
                }
            ],
        },
    }

    result = client.post("/api/backup/import", json={"document": document}).json()
    assert result["mode"] == "merge"
    assert result["total"] == 6
    assert result["written"]["segment_metrics"] == 1
    assert result["counts"]["segment_metrics"] == 1

    conn = db.connect()
    try:
        metrics = dict(
            conn.execute("SELECT * FROM segment_metrics WHERE segment_id = 1").fetchone()
        )
        assert metrics["duration_s"] == 20.0, "the column it did carry survived"
        assert metrics["pedal_changes"] is None
        assert metrics["median_velocity"] is None

        journal = dict(conn.execute("SELECT * FROM piece_journal WHERE id = 1").fetchone())
        assert journal["content"] == "From a v1 backup."
        assert journal["sitting_id"] is None
        assert journal["legacy_id"] is None
    finally:
        conn.close()


def test_an_import_that_fails_mid_insert_changes_nothing(client) -> None:
    """The first execution of `db.transaction`'s ROLLBACK in the suite.

    The document passes validation — every column is known — and then violates a NOT
    NULL while inserting. In replace mode every row has already been deleted by then, so
    a missing rollback would leave an empty database behind. The error is not caught:
    an import that half-happened must surface, not be swallowed into a smaller count.
    """
    _populate(client)
    before = client.get("/api/backup/export").json()["counts"]

    document = {
        "format": backup.FORMAT,
        "version": backup.BACKUP_VERSION,
        "tables": {
            # Written first, so it is a row that only survived because of the rollback.
            "composers": [{"id": 99, "name": "Ravel", "notes": None}],
            # `pieces.title` is NOT NULL and has no default, so this INSERT fails.
            "pieces": [{"id": 99, "opus": "Op. 99"}],
        },
    }
    with pytest.raises(sqlite3.IntegrityError):
        client.post(
            "/api/backup/import",
            json={"document": document, "mode": "replace", "confirm": True},
        )

    after = client.get("/api/backup/export").json()["counts"]
    assert after == before, "the failed import rolled back every delete and insert"
    assert after["pieces"] == 1
    assert after["composers"] == 1

