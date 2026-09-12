"""Repertoire domain: the legacy import, the API, and the cross-domain bridge."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import db
from app.config import settings
from app.repertoire import store
from app.repertoire.schema import migrate
from app.repertoire.importer import (
    LegacyDatabaseMissing,
    LegacySchemaUnexpected,
    import_legacy,
)


def _import(conn, path: Path, *, copy_media: bool = False, target_media: Path | None = None):
    return import_legacy(
        conn,
        source_path=path,
        source_media_dir=path.parent / "media",
        target_media_dir=target_media or path.parent / "imported-media",
        copy_media=copy_media,
    )


# --------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------


def test_import_copies_the_legacy_library(fresh_db, legacy_db):
    conn = db.connect(settings.db_path)
    try:
        report = _import(conn, legacy_db)
    finally:
        conn.close()

    assert (report.composers, report.pieces) == (2, 2)
    assert report.journal_entries == 2, "the orphaned journal row must not be counted"
    assert report.media_rows == 3

    conn = db.connect(settings.db_path)
    try:
        counts = store.counts(conn)
        assert counts == {
            "pieces": 2,
            "composers": 2,
            "journal_entries": 2,
            "media_rows": 3,
        }
    finally:
        conn.close()


def test_import_reports_the_orphaned_journal_row(fresh_db, legacy_db):
    conn = db.connect(settings.db_path)
    try:
        report = _import(conn, legacy_db)
    finally:
        conn.close()
    assert any("no piece" in item for item in report.skipped), report.skipped


def test_import_preserves_relationships(fresh_db, legacy_db):
    conn = db.connect(settings.db_path)
    try:
        _import(conn, legacy_db)
        piece = store.get_piece(conn, 1)
    finally:
        conn.close()

    assert piece is not None
    assert piece["composer_name"] == "Chopin"
    assert piece["opus"] == "Op. 23"
    assert len(piece["journal"]) == 2
    assert len(piece["media"]) == 3
    assert piece["logged_minutes"] == 30


def test_import_is_idempotent(fresh_db, legacy_db):
    """The Rust app keeps running during the transition, so this gets re-run."""
    conn = db.connect(settings.db_path)
    try:
        _import(conn, legacy_db)
        _import(conn, legacy_db)
        counts = store.counts(conn)
    finally:
        conn.close()
    assert counts["pieces"] == 2
    assert counts["journal_entries"] == 2
    assert counts["media_rows"] == 3


def test_import_picks_up_changes_made_in_the_legacy_app(fresh_db, legacy_db):
    conn = db.connect(settings.db_path)
    try:
        _import(conn, legacy_db)
    finally:
        conn.close()

    legacy = sqlite3.connect(legacy_db)
    legacy.execute("UPDATE pieces SET status = 'completed', title = 'Ballade No. 1' WHERE id = 1")
    legacy.execute(
        "INSERT INTO notes (id, piece_id, entry_date, content) VALUES (4, 1, '2026-03-01', 'Memorised.')"
    )
    legacy.commit()
    legacy.close()

    conn = db.connect(settings.db_path)
    try:
        _import(conn, legacy_db)
        piece = store.get_piece(conn, 1)
        counts = store.counts(conn)
    finally:
        conn.close()

    assert piece["title"] == "Ballade No. 1"
    assert piece["status"] == "completed"
    assert counts["journal_entries"] == 3
    assert counts["pieces"] == 2, "a re-import must not duplicate"


def test_import_refuses_a_missing_database(fresh_db, tmp_path):
    conn = db.connect(settings.db_path)
    try:
        with pytest.raises(LegacyDatabaseMissing):
            _import(conn, tmp_path / "nope.db")
    finally:
        conn.close()


def test_import_refuses_a_database_with_the_wrong_shape(fresh_db, tmp_path):
    impostor = tmp_path / "not-piano.db"
    conn = sqlite3.connect(impostor)
    conn.execute("CREATE TABLE unrelated (id INTEGER)")
    conn.commit()
    conn.close()

    conn = db.connect(settings.db_path)
    try:
        with pytest.raises(LegacySchemaUnexpected) as excinfo:
            _import(conn, impostor)
    finally:
        conn.close()
    assert "piano-progress" in str(excinfo.value)


def test_import_can_copy_recording_files(fresh_db, legacy_db, tmp_path):
    target = tmp_path / "media-out"
    conn = db.connect(settings.db_path)
    try:
        report = _import(conn, legacy_db, copy_media=True, target_media=target)
    finally:
        conn.close()

    assert report.media_copied == 2, "two real files"
    assert report.media_missing == 1, "the row whose file is absent"
    assert len(list(target.glob("*.ogg"))) == 2
    assert any("missing.ogg" in note for note in report.notes)


def test_import_does_not_copy_when_not_asked(fresh_db, legacy_db, tmp_path):
    target = tmp_path / "media-untouched"
    conn = db.connect(settings.db_path)
    try:
        report = _import(conn, legacy_db, copy_media=False, target_media=target)
    finally:
        conn.close()
    assert report.media_copied == 0
    assert not target.exists()


def test_import_never_writes_the_legacy_database(fresh_db, legacy_db):
    """The Rust app owns that file. A read-only snapshot is the whole contract."""
    before = legacy_db.read_bytes()
    conn = db.connect(settings.db_path)
    try:
        _import(conn, legacy_db)
    finally:
        conn.close()
    assert legacy_db.read_bytes() == before


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def test_status_reports_an_empty_library_and_finds_the_legacy_db(client, legacy_db):
    payload = client.get("/api/repertoire/status").json()
    assert payload["pieces"] == 0
    assert payload["legacy_found"] is True
    assert payload["media_dir"]


def test_import_endpoint_then_listing(client, legacy_db):
    report = client.post("/api/repertoire/import", json={}).json()
    assert report["source_found"] is True
    assert report["pieces"] == 2

    pieces = client.get("/api/repertoire/pieces").json()
    assert len(pieces) == 2
    titles = {row["title"] for row in pieces}
    assert titles == {"Ballade", "Prelude"}
    # The list is ordered by composer, so Bach precedes Chopin.
    assert pieces[0]["composer_name"] == "Bach"


def test_piece_detail_includes_journal_and_media(client, legacy_db):
    client.post("/api/repertoire/import", json={})
    detail = client.get("/api/repertoire/pieces/1").json()
    assert detail["title"] == "Ballade"
    assert len(detail["journal"]) == 2
    assert len(detail["media"]) == 3
    # Newest journal entry first.
    assert detail["journal"][0]["entry_date"] == "2026-02-02"


def test_unknown_piece_is_404(client):
    assert client.get("/api/repertoire/pieces/9999").status_code == 404


def test_filters_apply(client, legacy_db):
    client.post("/api/repertoire/import", json={})
    assert len(client.get("/api/repertoire/pieces", params={"status": "active"}).json()) == 1
    assert len(client.get("/api/repertoire/pieces", params={"search": "ballade"}).json()) == 1
    assert len(client.get("/api/repertoire/pieces", params={"composer_id": 2}).json()) == 1
    assert client.get("/api/repertoire/pieces", params={"search": "zzz"}).json() == []


def test_composers_listing_counts_pieces(client, legacy_db):
    client.post("/api/repertoire/import", json={})
    composers = client.get("/api/repertoire/composers").json()
    assert [c["name"] for c in composers] == ["Bach", "Chopin"]
    assert all(c["piece_count"] == 1 for c in composers)


def test_import_endpoint_is_404_without_a_legacy_database(client):
    Path(settings.legacy_db).unlink(missing_ok=True)
    response = client.post("/api/repertoire/import", json={})
    assert response.status_code == 404
    assert "SRT_LEGACY_DB" in response.json()["detail"]


# --------------------------------------------------------------------------
# Cross-domain bridge
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,expected",
    [
        ("B Major", ("B", "major")),
        ("C# Minor", ("c#", "minor")),
        ("Db Major", ("Db", "major")),
        ("Ab Major", ("Ab", "major")),
        ("c minor", ("c", "minor")),
        ("F# major", ("F#", "major")),
        ("BB Major", ("Bb", "major")),  # hand-written capitalisation
        ("bb minor", ("bb", "minor")),
        ("B♭ Major", ("Bb", "major")),
        ("E-flat Major", (None, None)),  # not a spelling we accept
        (None, (None, None)),
        ("", (None, None)),
        ("Major", (None, None)),  # a mode without a tonic is not a key
        ("C Lydian", (None, None)),
    ],
)
def test_key_normalisation(label, expected):
    from app.bridge import normalise_key

    assert normalise_key(label) == expected


def test_bridge_maps_every_imported_piece_to_a_key(client, legacy_db):
    client.post("/api/repertoire/import", json={})
    suggestions = client.get("/api/practice-suggestions").json()

    by_title = {row["title"]: row for row in suggestions}
    # The completed Prelude is excluded: you do not sight-read around a piece you
    # have finished.
    assert "Prelude" not in by_title
    ballade = by_title["Ballade"]
    assert ballade["suggested_key"] == "B"
    assert ballade["suggested_level"] == 6, "Intermediate"
    assert ballade["notes"] == []


def test_bridge_reports_what_it_could_not_map():
    from app.bridge import suggest_for_piece

    suggestion = suggest_for_piece(
        piece_id=1,
        title="Odd",
        composer_name=None,
        piece_key="H Major",
        difficulty="Impossible",
        status="active",
    )
    assert suggestion.suggested_key is None
    assert suggestion.suggested_level is None
    assert len(suggestion.notes) == 2, suggestion.notes


def test_bridge_flags_a_completed_piece():
    from app.bridge import suggest_for_piece

    suggestion = suggest_for_piece(
        piece_id=1,
        title="Done",
        composer_name=None,
        piece_key="C Major",
        difficulty="Beginner",
        status="completed",
    )
    assert any("completed" in note for note in suggestion.notes)


@pytest.mark.parametrize(
    "difficulty,expected",
    [
        ("Early Intermediate", 4),
        ("Intermediate", 6),
        ("Late Intermediate", 8),
        ("intermediate", 6),
        ("Advanced", 9),
        ("Nonsense", None),
    ],
)
def test_difficulty_mapping(difficulty, expected):
    from app.bridge import suggest_for_piece

    suggestion = suggest_for_piece(
        piece_id=1,
        title="X",
        composer_name=None,
        piece_key="C Major",
        difficulty=difficulty,
    )
    assert suggestion.suggested_level == expected


def test_every_known_key_maps_at_least_once():
    """Guards against a taxonomy change silently orphaning the bridge."""
    from app.bridge import _KNOWN_KEYS, normalise_key, suggest_for_piece

    for key in sorted(_KNOWN_KEYS):
        # "bb" (B-flat minor) must be spelled "Bb Minor", not "BB Minor".
        spelling = key[0].upper() + key[1:]
        mode = "Minor" if key.islower() else "Major"
        suggestion = suggest_for_piece(
            piece_id=1,
            title="X",
            composer_name=None,
            piece_key=f"{spelling} {mode}",
            difficulty=None,
        )
        assert suggestion.suggested_key == key, f"{key} did not round-trip"


# --------------------------------------------------------------------------
# Recordings: where they actually are, and serving them
# --------------------------------------------------------------------------


def test_recordings_read_pending_before_they_are_copied(fresh_db, legacy_db):
    """Regression: uncopied recordings were reported as 'missing', which reads
    as data loss when the file is sitting right there in the legacy library."""
    conn = db.connect(settings.db_path)
    try:
        _import(conn, legacy_db, copy_media=False)
        states = store.media_state_counts(conn)
        piece = store.get_piece(conn, 1)
    finally:
        conn.close()

    assert states == {"present": 0, "pending": 2, "missing": 1}, states
    by_name = {row["file_name"]: row["state"] for row in piece["media"]}
    assert by_name["hash00.ogg"] == "pending"
    assert by_name["missing.ogg"] == "missing", "absent from both places is genuinely missing"


def test_recordings_read_present_once_copied(fresh_db, legacy_db):
    conn = db.connect(settings.db_path)
    try:
        _import(conn, legacy_db, copy_media=True, target_media=Path(settings.media_dir))
        states = store.media_state_counts(conn)
    finally:
        conn.close()
    assert states == {"present": 2, "pending": 0, "missing": 1}, states


def test_import_copies_recordings_by_default(client, legacy_db):
    """A library whose recordings all read 'missing' is the wrong first impression."""
    report = client.post("/api/repertoire/import", json={}).json()
    assert report["media_copied"] == 2, report
    assert report["media_pending"] == 0, report
    assert report["media_missing"] == 1, "the row with no file anywhere"


def test_status_separates_the_three_states(client, legacy_db):
    client.post("/api/repertoire/import", json={"copy_media": False})
    payload = client.get("/api/repertoire/status").json()
    assert payload["media_present"] == 0
    assert payload["media_pending"] == 2
    assert payload["media_missing"] == 1


def test_recording_file_is_served(client, legacy_db):
    client.post("/api/repertoire/import", json={})
    response = client.get("/api/repertoire/media/1/file")
    assert response.status_code == 200
    assert response.content == b"fake audio"
    assert response.headers["content-type"].startswith("audio/")


def test_recording_plays_before_it_is_copied(client, legacy_db):
    """Streaming falls back to the legacy library so recordings are audible
    immediately; the copy is what removes the dependency, not what enables it."""
    client.post("/api/repertoire/import", json={"copy_media": False})
    assert client.get("/api/repertoire/status").json()["media_pending"] == 2
    assert client.get("/api/repertoire/media/1/file").status_code == 200


def test_recording_absent_everywhere_reports_gone(client, legacy_db):
    client.post("/api/repertoire/import", json={})
    # Local ids are assigned by this database, not copied from the legacy one,
    # so find the row rather than assuming the legacy id carried over.
    detail = client.get("/api/repertoire/pieces/1").json()
    gone = next(row for row in detail["media"] if row["state"] == "missing")
    response = client.get(f"/api/repertoire/media/{gone['id']}/file")
    assert response.status_code == 410
    assert "neither" in response.json()["detail"]


def test_unknown_recording_is_404(client):
    assert client.get("/api/repertoire/media/4242/file").status_code == 404


def test_a_tampered_file_name_cannot_escape_the_media_directory(fresh_db):
    """Names are content hashes, so a separator means the row was tampered with."""
    conn = db.connect(settings.db_path)
    try:
        conn.execute("INSERT INTO composers (id, name) VALUES (1, 'X')")
        conn.execute("INSERT INTO pieces (id, title) VALUES (1, 'Y')")
        conn.execute(
            "INSERT INTO media (id, piece_id, kind, file_name) VALUES (7, 1, 'audio', ?)",
            ("../../../../etc/passwd",),
        )
        assert store.media_state("../../../../etc/passwd") == "missing"
        assert store.resolve_media_path("../../../../etc/passwd") is None
        assert store.resolve_media_path("sub/dir.ogg") is None
        assert store.resolve_media_path("..") is None
        assert store.resolve_media_path("") is None
    finally:
        conn.close()


def test_media_states_are_reported_per_recording(client, legacy_db):
    client.post("/api/repertoire/import", json={"copy_media": False})
    detail = client.get("/api/repertoire/pieces/1").json()
    states = sorted(row["state"] for row in detail["media"])
    assert states == ["missing", "pending", "pending"], states


# --------------------------------------------------------------------------
# Editing
# --------------------------------------------------------------------------


def test_create_a_piece(client):
    response = client.post(
        "/api/repertoire/pieces",
        json={
            "title": "Nocturne",
            "opus": "Op. 9 No. 2",
            "key": "Eb Major",
            "difficulty": "Intermediate",
            "started_on": "2026-06-01",
        },
    )
    assert response.status_code == 201
    piece = response.json()
    assert piece["id"] > 0
    assert piece["title"] == "Nocturne"
    assert piece["status"] == "active", "status defaults rather than being required"
    assert piece["journal"] == [] and piece["media"] == []


def test_create_a_piece_with_an_unknown_composer_is_refused(client):
    response = client.post("/api/repertoire/pieces", json={"title": "X", "composer_id": 999})
    assert response.status_code == 422
    assert "no composer 999" in response.json()["detail"]


def test_create_a_piece_with_a_bad_date_is_refused(client):
    response = client.post(
        "/api/repertoire/pieces", json={"title": "X", "started_on": "1 June 2026"}
    )
    assert response.status_code == 422


def test_a_title_is_required(client):
    assert client.post("/api/repertoire/pieces", json={"title": ""}).status_code == 422


def test_patch_changes_only_what_was_sent(client):
    """PATCH semantics: an omitted field is untouched, an explicit null clears."""
    created = client.post(
        "/api/repertoire/pieces",
        json={"title": "Waltz", "opus": "Op. 64", "key": "Db Major", "difficulty": "Late Intermediate"},
    ).json()

    updated = client.patch(
        f"/api/repertoire/pieces/{created['id']}", json={"status": "completed"}
    ).json()
    assert updated["status"] == "completed"
    assert updated["opus"] == "Op. 64", "omitted fields survive"
    assert updated["key"] == "Db Major"

    cleared = client.patch(
        f"/api/repertoire/pieces/{created['id']}", json={"opus": None}
    ).json()
    assert cleared["opus"] is None, "an explicit null clears the field"
    assert cleared["key"] == "Db Major", "and nothing else moved"


def test_patch_with_no_fields_is_refused(client):
    created = client.post("/api/repertoire/pieces", json={"title": "X"}).json()
    response = client.patch(f"/api/repertoire/pieces/{created['id']}", json={})
    assert response.status_code == 422
    assert "no fields" in response.json()["detail"]


def test_patch_of_a_missing_piece_is_404(client):
    assert client.patch("/api/repertoire/pieces/999", json={"title": "X"}).status_code == 404


def test_a_piece_cannot_be_set_to_an_unknown_status(client):
    created = client.post("/api/repertoire/pieces", json={"title": "X"}).json()
    response = client.patch(
        f"/api/repertoire/pieces/{created['id']}", json={"status": "finished"}
    )
    assert response.status_code == 422


def test_deleting_a_piece_reports_what_went_with_it(client):
    piece = client.post("/api/repertoire/pieces", json={"title": "Doomed"}).json()
    client.post(
        f"/api/repertoire/pieces/{piece['id']}/journal",
        json={"entry_date": "2026-01-01", "content": "note"},
    )
    result = client.delete(f"/api/repertoire/pieces/{piece['id']}").json()
    assert result["deleted"] is True
    assert result["cascaded"] == {"journal_entries": 1, "media_rows": 0}
    assert client.get(f"/api/repertoire/pieces/{piece['id']}").status_code == 404


def test_deleting_a_piece_keeps_the_recording_files(client, legacy_db, tmp_path):
    """A library delete must not destroy the player's own recordings."""
    media_dir = tmp_path / "keep"
    client.post(
        "/api/repertoire/import",
        json={"copy_media": True},
    )
    detail = client.get("/api/repertoire/pieces/1").json()
    assert detail["media"], "the fixture piece has recordings"
    client.delete("/api/repertoire/pieces/1")
    # The rows are gone...
    assert client.get("/api/repertoire/pieces/1").status_code == 404
    # ...and the imported files are still on disk.
    assert list(Path(settings.media_dir).glob("*.ogg")), "files must survive the row delete"


def test_deleting_a_missing_piece_is_404(client):
    assert client.delete("/api/repertoire/pieces/999").status_code == 404


def test_composer_lifecycle(client):
    created = client.post("/api/repertoire/composers", json={"name": "Satie"}).json()
    assert created["piece_count"] == 0

    renamed = client.patch(
        f"/api/repertoire/composers/{created['id']}", json={"name": "Erik Satie"}
    ).json()
    assert renamed["name"] == "Erik Satie"

    piece = client.post(
        "/api/repertoire/pieces", json={"title": "Gymnopedie", "composer_id": created["id"]}
    ).json()
    assert piece["composer_name"] == "Erik Satie"


def test_deleting_a_composer_keeps_their_pieces(client):
    """Losing a composer must never lose the repertoire attached to them."""
    composer = client.post("/api/repertoire/composers", json={"name": "Berg"}).json()
    piece = client.post(
        "/api/repertoire/pieces", json={"title": "Sonata", "composer_id": composer["id"]}
    ).json()

    result = client.delete(f"/api/repertoire/composers/{composer['id']}").json()
    assert result["cascaded"] == {"pieces_unattributed": 1}

    survivor = client.get(f"/api/repertoire/pieces/{piece['id']}").json()
    assert survivor["title"] == "Sonata"
    assert survivor["composer_id"] is None
    assert survivor["composer_name"] is None


def test_deleting_a_missing_composer_is_404(client):
    assert client.delete("/api/repertoire/composers/999").status_code == 404


def test_journal_lifecycle(client):
    piece = client.post("/api/repertoire/pieces", json={"title": "P"}).json()
    created = client.post(
        f"/api/repertoire/pieces/{piece['id']}/journal",
        json={"entry_date": "2026-03-04", "content": "Slow practice.", "practice_minutes": 40},
    )
    assert created.status_code == 201
    entry = created.json()
    assert entry["practice_minutes"] == 40

    edited = client.patch(
        f"/api/repertoire/journal/{entry['id']}", json={"practice_minutes": 55}
    ).json()
    assert edited["practice_minutes"] == 55
    assert edited["content"] == "Slow practice.", "omitted fields survive"

    assert client.delete(f"/api/repertoire/journal/{entry['id']}").json()["deleted"] is True
    assert client.delete(f"/api/repertoire/journal/{entry['id']}").status_code == 404


def test_logged_minutes_reach_the_piece_summary(client):
    piece = client.post("/api/repertoire/pieces", json={"title": "P"}).json()
    for minutes in (20, 30):
        client.post(
            f"/api/repertoire/pieces/{piece['id']}/journal",
            json={"entry_date": "2026-03-04", "content": "x", "practice_minutes": minutes},
        )
    listing = next(p for p in client.get("/api/repertoire/pieces").json() if p["id"] == piece["id"])
    assert listing["journal_entries"] == 2
    assert listing["logged_minutes"] == 50


def test_journal_on_a_missing_piece_is_404(client):
    response = client.post(
        "/api/repertoire/pieces/999/journal",
        json={"entry_date": "2026-01-01", "content": "x"},
    )
    assert response.status_code == 404


def test_negative_practice_minutes_are_refused(client):
    piece = client.post("/api/repertoire/pieces", json={"title": "P"}).json()
    response = client.post(
        f"/api/repertoire/pieces/{piece['id']}/journal",
        json={"entry_date": "2026-01-01", "content": "x", "practice_minutes": -5},
    )
    assert response.status_code == 422


def test_editing_survives_a_re_import_of_the_legacy_library(client, legacy_db):
    """The import upserts on legacy ids, so local edits to *other* pieces stay.

    Worth pinning: re-running the import while the Rust app is still in use must
    not silently undo work done in this app.
    """
    mine = client.post("/api/repertoire/pieces", json={"title": "My own piece"}).json()
    client.post("/api/repertoire/import", json={"copy_media": False})
    still_there = client.get(f"/api/repertoire/pieces/{mine['id']}").json()
    assert still_there["title"] == "My own piece"


# --------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------


def test_migration_adds_legacy_id_to_an_existing_database(fresh_db):
    """An existing library predates `legacy_id`, and CREATE TABLE IF NOT EXISTS
    cannot add a column. The migration must upgrade in place without touching
    the player's data."""
    conn = db.connect(settings.db_path)
    try:
        # A database as an earlier version left it: no legacy_id anywhere.
        for table in ("media", "piece_journal", "pieces", "composers"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.executescript(
            """
            CREATE TABLE composers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, notes TEXT);
            CREATE TABLE pieces (
                id INTEGER PRIMARY KEY AUTOINCREMENT, composer_id INTEGER, title TEXT NOT NULL,
                opus TEXT, difficulty TEXT, key TEXT, started_on TEXT,
                status TEXT NOT NULL DEFAULT 'active', description TEXT
            );
            CREATE TABLE piece_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT, piece_id INTEGER NOT NULL,
                entry_date TEXT NOT NULL, content TEXT NOT NULL, practice_minutes INTEGER
            );
            CREATE TABLE media (
                id INTEGER PRIMARY KEY AUTOINCREMENT, piece_id INTEGER, kind TEXT NOT NULL,
                file_name TEXT NOT NULL UNIQUE, original_name TEXT, title TEXT,
                duration_secs REAL, size_bytes INTEGER, codec TEXT, taken_on TEXT
            );
            INSERT INTO composers (id, name) VALUES (1, 'Pre-existing');
            INSERT INTO pieces (id, composer_id, title) VALUES (1, 1, 'Kept piece');
            """
        )
    finally:
        conn.close()

    # Re-opening runs the initialiser, which applies the additive migration.
    db.init_db(settings.db_path)

    conn = db.connect(settings.db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(pieces)")}
        assert "legacy_id" in columns, "the column was added"
        kept = conn.execute("SELECT title, composer_id FROM pieces WHERE id = 1").fetchone()
        assert kept["title"] == "Kept piece", "existing data survived the migration"
        assert kept["composer_id"] == 1
    finally:
        conn.close()


def test_migration_is_idempotent(fresh_db):
    conn = db.connect(settings.db_path)
    try:
        assert migrate(conn) == [], "a current database needs no migration"
        conn.execute("INSERT INTO composers (id, name) VALUES (1, 'X')")
        assert migrate(conn) == []
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Recording import
# --------------------------------------------------------------------------


@pytest.fixture
def tone_wav(tmp_path):
    """A real, short WAV generated by ffmpeg.

    Generated rather than faked: the whole point of this path is that ffprobe and
    ffmpeg accept the file, and a hand-written bytes blob would prove nothing.
    """
    import subprocess

    path = tmp_path / "take.wav"
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"ffmpeg unavailable: {result.stderr[:200]}")
    return path


def test_probe_reads_real_properties(tone_wav):
    from app.repertoire.media_pipeline import probe

    info = probe(tone_wav)
    assert info.has_audio and not info.has_video
    assert info.kind == "audio"
    assert info.duration_secs == pytest.approx(2.0, abs=0.2)
    assert info.size_bytes > 0


def test_importing_a_recording_converts_and_hashes_it(client, tone_wav):
    piece = client.post("/api/repertoire/pieces", json={"title": "Target"}).json()
    with tone_wav.open("rb") as handle:
        response = client.post(
            f"/api/repertoire/pieces/{piece['id']}/media",
            files={"file": ("take.wav", handle, "audio/wav")},
            data={"title": "First take"},
        )
    assert response.status_code == 201, response.text
    recording = response.json()
    assert recording["kind"] == "audio"
    assert recording["codec"] == "opus", "audio is converted to Opus"
    assert recording["file_name"].endswith(".ogg")
    assert recording["duration_secs"] == pytest.approx(2.0, abs=0.2)
    assert recording["state"] == "present"
    assert recording["original_name"] == "take.wav"
    assert (Path(settings.media_dir) / recording["file_name"]).exists()


def test_re_importing_the_same_audio_does_not_duplicate_storage(client, tone_wav):
    from app.repertoire.media_pipeline import store_recording

    first = store_recording(tone_wav, media_dir=Path(settings.media_dir))
    second = store_recording(tone_wav, media_dir=Path(settings.media_dir))
    assert first.file_name == second.file_name
    assert second.reused is True
    assert len(list(Path(settings.media_dir).glob("*.ogg"))) == 1


def test_a_duplicate_upload_is_refused_with_a_reason(client, tone_wav):
    """Re-uploading what the import already brought across is the obvious way to
    end up with everything twice."""
    piece = client.post("/api/repertoire/pieces", json={"title": "T"}).json()
    upload = lambda: client.post(  # noqa: E731
        f"/api/repertoire/pieces/{piece['id']}/media",
        files={"file": ("take.wav", tone_wav.open("rb"), "audio/wav")},
    )
    assert upload().status_code == 201
    refused = upload()
    assert refused.status_code == 409, refused.text
    assert "already in the library" in refused.json()["detail"]
    # The message names the existing recording, so the client can point at it.
    assert "id " in refused.json()["detail"]
    assert len(list(Path(settings.media_dir).glob("*.ogg"))) == 1


def test_uploading_to_a_missing_piece_is_404(client, tone_wav):
    response = client.post(
        "/api/repertoire/pieces/999/media",
        files={"file": ("take.wav", tone_wav.open("rb"), "audio/wav")},
    )
    assert response.status_code == 404


def test_uploading_an_empty_file_is_refused(client):
    piece = client.post("/api/repertoire/pieces", json={"title": "T"}).json()
    response = client.post(
        f"/api/repertoire/pieces/{piece['id']}/media",
        files={"file": ("nothing.wav", b"", "audio/wav")},
    )
    assert response.status_code == 422


def test_uploading_a_non_media_file_is_refused(client, tmp_path):
    piece = client.post("/api/repertoire/pieces", json={"title": "T"}).json()
    junk = tmp_path / "notes.txt"
    junk.write_text("this is not audio")
    response = client.post(
        f"/api/repertoire/pieces/{piece['id']}/media",
        files={"file": ("notes.txt", junk.open("rb"), "text/plain")},
    )
    assert response.status_code == 422


def test_recording_can_be_retitled_and_moved(client, legacy_db):
    client.post("/api/repertoire/import", json={})
    detail = client.get("/api/repertoire/pieces/1").json()
    recording = next(row for row in detail["media"] if row["state"] != "missing")

    renamed = client.patch(
        f"/api/repertoire/media/{recording['id']}", json={"title": "Best take"}
    ).json()
    assert renamed["title"] == "Best take"

    other = client.post("/api/repertoire/pieces", json={"title": "Elsewhere"}).json()
    moved = client.patch(
        f"/api/repertoire/media/{recording['id']}", json={"piece_id": other["id"]}
    ).json()
    assert moved["piece_id"] == other["id"], "a recording can be re-attached"


def test_moving_a_recording_to_a_missing_piece_is_refused(client, legacy_db):
    client.post("/api/repertoire/import", json={})
    response = client.patch("/api/repertoire/media/1", json={"piece_id": 999})
    assert response.status_code == 422


def test_deleting_a_recording_removes_our_file(client, tone_wav):
    piece = client.post("/api/repertoire/pieces", json={"title": "T"}).json()
    recording = client.post(
        f"/api/repertoire/pieces/{piece['id']}/media",
        files={"file": ("take.wav", tone_wav.open("rb"), "audio/wav")},
    ).json()
    path = Path(settings.media_dir) / recording["file_name"]
    assert path.exists()

    result = client.delete(f"/api/repertoire/media/{recording['id']}").json()
    assert result["cascaded"] == {"files_removed": 1}
    assert not path.exists(), "our own copy goes with the row"


def test_deleting_a_recording_keeps_the_legacy_file(client, legacy_db):
    """The old app's media directory is not ours to delete from."""
    client.post("/api/repertoire/import", json={"copy_media": False})
    detail = client.get("/api/repertoire/pieces/1").json()
    recording = next(row for row in detail["media"] if row["state"] == "pending")
    legacy_file = Path(settings.legacy_db).parent / "media" / recording["file_name"]
    assert legacy_file.exists()

    client.delete(f"/api/repertoire/media/{recording['id']}")
    assert legacy_file.exists(), "the legacy library was not touched"


def test_deleting_a_missing_recording_is_404(client):
    assert client.delete("/api/repertoire/media/999").status_code == 404


def test_deleting_an_empty_body_recording_is_404(client):
    assert client.delete("/api/repertoire/media").status_code in (404, 405)
