"""Catalogue numbers: one canonical form for the field, and one guardrail on it.

The owner's real library has the same catalogue number written four different ways
(`Op 10. No. 4`, `Op. 10 No. 3`, `Op . 78`, `w264`), which is what the field was asked to
stop doing. `LIBRARY_OPUSES` below is that library, and it is the contract:
`frontend/src/lib/pieceOpus.ts` mirrors this rule for the editor's preview and its test
pins the same pairs, so a change here is a change there.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.repertoire import store
from app.repertoire.opus import (
    OPUS_NEEDS_A_NUMBER,
    normalise_opus,
    opus_problem,
)
from app.repertoire.schema import migrate


#: Every distinct spelling in the owner's library (21 pieces, 2026-09-29) with the form the
#: field should hold. Not tidied: these are the strings that were actually stored.
LIBRARY_OPUSES = [
    ("Op 10. No. 4", "Op. 10 No. 4"),
    ("Op 10. No. 1", "Op. 10 No. 1"),
    ("Op 10 No. 3", "Op. 10 No. 3"),
    ("Op 15", "Op. 15"),
    ("Op 19 No. 1", "Op. 19 No. 1"),
    ("Op 19 No. 2", "Op. 19 No. 2"),
    ("Op 26 No. 1", "Op. 26 No. 1"),
    ("Op 28 No. 15", "Op. 28 No. 15"),
    ("Op 57", "Op. 57"),
    ("Op 58", "Op. 58"),
    ("Op 64. No. 3", "Op. 64 No. 3"),
    ("Op 69 No. 1", "Op. 69 No. 1"),
    ("Op 90 No. 3", "Op. 90 No. 3"),
    ("Op 118 No. 2", "Op. 118 No. 2"),
    ("Op . 78", "Op. 78"),
    ("D. 817", "D. 817"),
    ("D. 984", "D. 984"),
    ("S.566a", "S. 566a"),
    # The same catalogue number, written two ways by two rows of the same library.
    ("w264", "W264"),
    ("W264", "W264"),
]


# --------------------------------------------------------------------------
# The canonical form
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "canonical"), LIBRARY_OPUSES)
def test_a_real_spelling_becomes_the_canonical_form(raw, canonical):
    assert normalise_opus(raw) == canonical


@pytest.mark.parametrize(("raw", "canonical"), LIBRARY_OPUSES)
def test_normalising_twice_changes_nothing(raw, canonical):
    # The migration runs on every startup, so this is not a nicety: a rule that is not
    # idempotent would rewrite the column every boot and report the schema as changed.
    assert normalise_opus(canonical) == canonical


def test_case_is_ignored_for_the_abbreviations():
    assert normalise_opus("op. 27 no. 2") == "Op. 27 No. 2"
    assert normalise_opus("OP 27 NO 2") == "Op. 27 No. 2"


def test_whitespace_is_collapsed_and_trimmed():
    assert normalise_opus("  Op.   27   No.   2  ") == "Op. 27 No. 2"


def test_a_missing_number_is_the_same_as_no_value():
    # An empty field means "no catalogue number", which is an ordinary state for a piece
    # written from memory or a method book. It is stored as NULL rather than "".
    assert normalise_opus(None) is None
    assert normalise_opus("") is None
    assert normalise_opus("   ") is None


def test_something_that_is_not_a_catalogue_number_is_left_alone_apart_from_spacing():
    # The rule knows the abbreviations this library uses and does not invent others: a
    # value it does not recognise must survive rather than be mangled.
    assert normalise_opus("see the Henle edition") == "see the Henle edition"
    assert normalise_opus("Book 2") == "Book 2"


# --------------------------------------------------------------------------
# The guardrail
# --------------------------------------------------------------------------


def test_a_value_without_a_number_is_refused():
    problem = opus_problem("Op.")
    assert problem == OPUS_NEEDS_A_NUMBER


def test_words_are_refused_because_they_cannot_tell_two_pieces_apart():
    assert opus_problem("Sonata") == OPUS_NEEDS_A_NUMBER
    assert opus_problem("???") == OPUS_NEEDS_A_NUMBER


def test_an_acceptable_value_has_no_problem():
    for raw, _canonical in LIBRARY_OPUSES:
        assert opus_problem(raw) is None, raw


def test_an_absent_value_has_no_problem():
    # Clearing the field is legitimate, and `PieceUpdate` sends an explicit null to do it.
    assert opus_problem(None) is None
    assert opus_problem("") is None


# --------------------------------------------------------------------------
# Through the API
# --------------------------------------------------------------------------


def test_a_new_piece_stores_the_canonical_form(client):
    created = client.post(
        "/api/repertoire/pieces", json={"title": "Ballade", "opus": "Op 10. No. 4"}
    )
    assert created.status_code == 201
    # The route re-reads the row, so this asserts what was *stored*, not what was sent.
    assert created.json()["opus"] == "Op. 10 No. 4"

    listed = client.get("/api/repertoire/pieces").json()
    assert [piece["opus"] for piece in listed] == ["Op. 10 No. 4"]


def test_an_edit_stores_the_canonical_form(client):
    piece_id = client.post(
        "/api/repertoire/pieces", json={"title": "Waltz", "opus": "Op 64. No. 3"}
    ).json()["id"]

    patched = client.patch(f"/api/repertoire/pieces/{piece_id}", json={"opus": "Op . 78"})
    assert patched.status_code == 200
    assert patched.json()["opus"] == "Op. 78"


def test_a_numberless_opus_is_a_422_that_says_what_to_do(client):
    response = client.post(
        "/api/repertoire/pieces", json={"title": "Sonata", "opus": "Sonata"}
    )
    assert response.status_code == 422
    assert OPUS_NEEDS_A_NUMBER in response.text
    # And nothing was written: the refusal is a validation, not a partial insert.
    assert client.get("/api/repertoire/pieces").json() == []


def test_a_numberless_opus_is_refused_on_edit_too(client):
    piece_id = client.post("/api/repertoire/pieces", json={"title": "Sonata"}).json()["id"]
    response = client.patch(f"/api/repertoire/pieces/{piece_id}", json={"opus": "Op."})
    assert response.status_code == 422
    assert client.get(f"/api/repertoire/pieces/{piece_id}").json()["opus"] is None


def test_clearing_the_opus_is_allowed(client):
    piece_id = client.post(
        "/api/repertoire/pieces", json={"title": "Prelude", "opus": "Op. 28 No. 15"}
    ).json()["id"]
    cleared = client.patch(f"/api/repertoire/pieces/{piece_id}", json={"opus": None})
    assert cleared.status_code == 200
    assert cleared.json()["opus"] is None


def test_an_empty_string_is_stored_as_no_value(client):
    created = client.post("/api/repertoire/pieces", json={"title": "Study", "opus": "  "})
    assert created.status_code == 201
    assert created.json()["opus"] is None


# --------------------------------------------------------------------------
# Existing rows
# --------------------------------------------------------------------------


def test_the_migration_rewrites_the_spellings_already_stored(conn):
    for title, raw in (("Ballade", "Op 10. No. 4"), ("Waltz", "Op . 78"), ("BB", "w264")):
        conn.execute("INSERT INTO pieces (title, opus) VALUES (?, ?)", (title, raw))

    applied = migrate(conn)

    assert any("opus" in entry for entry in applied), applied
    rows = conn.execute("SELECT title, opus FROM pieces ORDER BY id").fetchall()
    assert [row["opus"] for row in rows] == ["Op. 10 No. 4", "Op. 78", "W264"]


def test_the_migration_leaves_a_canonical_library_alone(conn):
    conn.execute("INSERT INTO pieces (title, opus) VALUES ('Berceuse', 'Op. 57')")
    assert migrate(conn) == [], "nothing to do, so nothing is reported"


def test_the_migration_keeps_no_catalogue_number_as_no_value(conn):
    conn.execute("INSERT INTO pieces (title, opus) VALUES ('Exercises', NULL)")
    migrate(conn)
    row = conn.execute("SELECT opus FROM pieces WHERE title = 'Exercises'").fetchone()
    assert row["opus"] is None


def test_the_importer_stores_the_canonical_form(conn, legacy_db):
    # The fixture ships tidy values, so one is made messy on purpose: the importer writes
    # through the same store path the API uses, and a legacy spelling must not survive the
    # import as a second canonical form. Restoring an old backup is the other way a messy
    # value gets in, and the startup migration is what catches that one.
    legacy = sqlite3.connect(legacy_db)
    try:
        legacy.execute("UPDATE pieces SET opus = 'Op 10. No. 4' WHERE id = 1")
        legacy.commit()
    finally:
        legacy.close()

    from app.repertoire.importer import import_legacy

    import_legacy(
        conn,
        source_path=legacy_db,
        source_media_dir=legacy_db.parent / "media",
        target_media_dir=legacy_db.parent / "imported-media",
        copy_media=False,
    )

    stored = {
        row["title"]: row["opus"] for row in conn.execute("SELECT title, opus FROM pieces")
    }
    assert stored == {"Ballade": "Op. 10 No. 4", "Prelude": "BWV 846"}, stored
    assert store.counts(conn)["pieces"] == 2
