"""The upgrade path a real database takes.

`practice/schema.py`'s `ADDED_COLUMNS` loop and `repertoire/schema.py`'s were the one
code path that runs on the player's real database and had never executed in the suite.
The fixture beside this file is a pre-Phase-18 database frozen as SQL: the current CREATE
scripts minus exactly the `ADDED_COLUMNS` columns, with the old `NOT NULL ... ON DELETE
CASCADE` outcome reference and the old `performances` without `workout_id`. Upgrading it
is the test.

The frozen `EXPECTED_COLUMNS` below is deliberately a literal rather than a value derived
from `ADDED_COLUMNS`. An assertion that iterates the tuple cannot fail when an entry is
deleted, because the deleted entry leaves the loop — the acceptance criterion for this
slice only holds because the fresh-database shape is written down here.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import db
from app.practice.schema import migrate as migrate_practice
from app.repertoire.schema import migrate as migrate_repertoire

FIXTURE_SQL = Path(__file__).resolve().parent / "fixtures" / "pre_phase18_practice.sql"
#: `conftest.py`'s note applies: `/tmp` is not reliably writable here, so fixture
#: databases are built in the scratch directory the whole suite already uses.
WORK_DIR = Path(__file__).resolve().parent.parent / ".pytest-tmp"

#: Frozen. What a *fresh* database must look like, table by table. A column added in a
#: later phase is meant to fail this until it is named here on purpose.
EXPECTED_COLUMNS: dict[str, set[str]] = {
    "composers": {"id", "name", "notes", "legacy_id", "created_at"},
    "exercise_skills": {"exercise_id", "skill_id", "level"},
    "exercises": {
        "id", "musicxml_blob", "difficulty_elo", "key_name", "meter", "bars",
        "tempo_bpm", "generator_seed", "source", "params_json", "expected_json",
        "created_at",
    },
    "identification_outcomes": {
        "id", "segment_id", "guessed_piece_id", "resolved_piece_id", "action",
        "accepted", "score", "resolved_at",
    },
    "media": {
        "id", "piece_id", "kind", "file_name", "original_name", "title",
        "duration_secs", "size_bytes", "codec", "taken_on", "legacy_id",
        "loop_start_s", "loop_end_s", "created_at", "source", "sitting_id",
        "segment_id", "captured_start_ms",
    },
    "note_events": {
        "id", "sitting_id", "onset_ms", "duration_ms", "pitch", "velocity", "channel",
    },
    "pedal_events": {"id", "sitting_id", "onset_ms", "value", "channel"},
    "performances": {
        "id", "user_id", "exercise_id", "score", "pitch_accuracy", "rhythm_accuracy",
        "continuity_accuracy", "mode", "tempo_bpm", "latency_ms", "played_notes_json",
        "analysis_json", "performed_at", "workout_id",
    },
    "piece_journal": {
        "id", "piece_id", "entry_date", "content", "practice_minutes", "sitting_id",
        "legacy_id", "created_at", "tags", "difficulty", "fluency", "media_id",
    },
    "piece_passages": {
        "id", "piece_id", "start_bar", "end_bar", "label", "source", "media_id",
        "created_at", "last_worked_on",
    },
    "pieces": {
        "id", "composer_id", "title", "opus", "difficulty", "key", "started_on",
        "status", "description", "legacy_id", "created_at",
    },
    "rating_events": {
        "id", "user_id", "skill_id", "before", "after", "score", "performance_id",
        "created_at",
    },
    "reference_state": {"id", "version"},
    "segment_metrics": {
        "segment_id", "duration_s", "note_count", "median_tempo", "mean_velocity",
        "velocity_stddev", "restarts", "pedal_changes", "pedal_down_ratio",
        "pedal_blur", "pedal_blur_ms", "pedal_basis", "median_velocity", "velocity_range",
        "mean_velocity_low", "mean_velocity_high",
    },
    "segments": {
        "id", "sitting_id", "start_ms", "end_ms", "piece_id", "source", "workout_id",
        "confidence", "identified_by", "practice_kind", "practice_kind_basis",
    },
    "sittings": {
        "id", "started_ms", "ended_ms", "started_at", "ended_at", "local_date",
        "source", "closed_ms", "legacy_id",
    },
    "skills": {"id", "slug", "name", "description", "sort_order"},
    "user_skills": {
        "user_id", "skill_id", "elo_rating", "attempts", "last_practiced_at",
    },
    "users": {"id", "username", "created_at"},
    "workouts": {
        "id", "started_ms", "ended_ms", "local_date", "target_skill", "bars",
        "planned", "completed", "sitting_id", "created_at",
    },
}

#: Frozen alongside the columns. The manual `CREATE INDEX` statements are schema too,
#: and a dropped index (for example `idx_sittings_legacy`) leaves the columns untouched
#: — so without this literal the `upgraded ⊇ fresh` comparison would agree on its
#: absence from both sides and never notice.
EXPECTED_INDEXES: dict[str, set[str]] = {
    "composers": {"idx_composers_legacy"},
    "exercise_skills": {"idx_exercise_skills_skill"},
    "identification_outcomes": {"idx_outcomes_segment"},
    "media": {"idx_media_legacy", "idx_media_piece", "idx_media_segment", "idx_media_source"},
    "note_events": {"idx_events_dedupe", "idx_events_sitting"},
    "pedal_events": {"idx_pedals_dedupe", "idx_pedals_sitting"},
    "performances": {"idx_performances_user_time"},
    "piece_journal": {
        "idx_journal_date", "idx_journal_legacy", "idx_journal_piece",
        "idx_journal_sitting",
    },
    "piece_passages": {"idx_passages_piece"},
    "pieces": {"idx_pieces_composer", "idx_pieces_legacy", "idx_pieces_status"},
    "rating_events": {"idx_rating_events_skill"},
    "segments": {"idx_segments_piece", "idx_segments_sitting"},
    "sittings": {"idx_sittings_date", "idx_sittings_legacy"},
    "workouts": {"idx_workouts_date", "idx_workouts_open"},
}

#: The seven `segment_metrics` columns an earlier release had, before Phase 18b.
OLD_SEGMENT_METRIC_COLUMNS = {
    "segment_id", "duration_s", "note_count", "median_tempo", "mean_velocity",
    "velocity_stddev", "restarts",
}


def _fresh_path(name: str) -> Path:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    path = WORK_DIR / name
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    return path


def _build_fixture_db(name: str) -> Path:
    """Load the frozen pre-Phase-18 SQL into its own database file."""
    path = _fresh_path(name)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(FIXTURE_SQL.read_text())
        conn.commit()
    finally:
        conn.close()
    return path


def _tables(conn) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _indexes(conn, table: str) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ?"
            " AND name NOT LIKE 'sqlite_%'",
            (table,),
        )
    }


def _counts(conn) -> dict[str, int]:
    return {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in _tables(conn)
    }


def _schema_snapshot(conn) -> list[tuple]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        )
    ]


def _segment_fk(conn, table: str) -> tuple[str, str] | None:
    """The `(parent, on_delete)` of a `segment_id` reference, if there is one."""
    for row in conn.execute(f"PRAGMA foreign_key_list({table})"):
        if row[3] == "segment_id":
            return (row[2], row[6])
    return None


def _foreign_keys(conn, table: str) -> set[tuple[str, str, str, str]]:
    """`(child column, parent table, parent column, on_delete)` for a table."""
    return {
        (row[3], row[2], row[4], row[6])
        for row in conn.execute(f"PRAGMA foreign_key_list({table})")
    }


def test_the_fixture_is_the_pre_phase18_shape() -> None:
    """The fixture must stay old. A later 'fix the fixture' edit fails here.

    If this test is ever adjusted to match a newer schema, the upgrade test below stops
    exercising the migration and becomes a copy of `CREATE TABLE`.
    """
    path = _build_fixture_db("pre-shape.sqlite3")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0

        assert _columns(conn, "segment_metrics") == OLD_SEGMENT_METRIC_COLUMNS, (
            "the fixture's segment_metrics is the seven-column shape Phase 18b extended"
        )

        info = {row[1]: row for row in conn.execute("PRAGMA table_info(identification_outcomes)")}
        assert info["segment_id"][3] == 1, "the old outcome reference was NOT NULL"
        assert _segment_fk(conn, "identification_outcomes") == ("segments", "CASCADE"), (
            "and it cascaded, which is what the rebuild exists to stop"
        )

        assert {"sitting_id", "tags", "difficulty", "fluency", "media_id"}.isdisjoint(
            _columns(conn, "piece_journal")
        ), "the fixture predates every ADDED_COLUMNS entry for piece_journal"
        assert "workout_id" not in _columns(conn, "performances")
        assert {"legacy_id", "closed_ms"}.isdisjoint(_columns(conn, "sittings"))
        assert {"source", "workout_id", "practice_kind", "practice_kind_basis"}.isdisjoint(
            _columns(conn, "segments")
        ), "the fixture predates every ADDED_COLUMNS entry for segments"
        assert "legacy_id" not in _columns(conn, "pieces")
        assert {
            "legacy_id", "loop_start_s", "loop_end_s", "source", "sitting_id",
            "segment_id", "captured_start_ms",
        }.isdisjoint(_columns(conn, "media")), (
            "the fixture predates every ADDED_COLUMNS entry for media"
        )
    finally:
        conn.close()


def test_init_db_upgrades_the_fixture_without_losing_a_row() -> None:
    path = _build_fixture_db("upgrade.sqlite3")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        before = _counts(conn)
        before_outcome = dict(conn.execute("SELECT * FROM identification_outcomes").fetchone())
    finally:
        conn.close()
    assert before["identification_outcomes"] == 1
    assert before["segment_metrics"] == 1

    db.init_db(path)

    conn = db.connect(path)
    try:
        after = _counts(conn)
        # Compared over the fixture's own tables: a phase that *adds* a table (20d's
        # `piece_passages`) legitimately introduces a new key, and that is not a lost row.
        # Every table the fixture had must still hold exactly what it held.
        assert {table: after[table] for table in before} == before, (
            "the upgrade kept every table's rows"
        )
        after_outcome = dict(conn.execute("SELECT * FROM identification_outcomes").fetchone())
        assert after_outcome["segment_id"] == before_outcome["segment_id"] == 1, (
            "the rebuilt table kept the reference, not merely the row"
        )
        assert after_outcome["score"] == 0.91
        assert after_outcome["action"] == "confirmed"

        metrics = dict(conn.execute("SELECT * FROM segment_metrics").fetchone())
        assert metrics["duration_s"] == 20.0
        assert metrics["pedal_changes"] is None, "a new column starts NULL on old rows"

        after_info = {row[1]: row for row in conn.execute("PRAGMA table_info(identification_outcomes)")}
        assert after_info["segment_id"][3] == 0, "the rebuild made it nullable"
        assert _segment_fk(conn, "identification_outcomes") == ("segments", "SET NULL")

        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION

        assert migrate_practice(conn) == [], "the practice domain has nothing left to do"
        assert migrate_repertoire(conn) == [], "nor the repertoire domain"
    finally:
        conn.close()


def test_a_second_init_db_is_a_no_op() -> None:
    path = _build_fixture_db("idempotent.sqlite3")
    db.init_db(path)
    conn = db.connect(path)
    try:
        counts = _counts(conn)
        schema = _schema_snapshot(conn)
    finally:
        conn.close()

    db.init_db(path)

    conn = db.connect(path)
    try:
        assert _counts(conn) == counts
        assert _schema_snapshot(conn) == schema, "no table was rebuilt a second time"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    finally:
        conn.close()


def test_the_upgraded_database_has_every_column_and_index_a_fresh_one_does() -> None:
    """The parity assertion, as sets: ALTER appends, so order legitimately differs.

    A deleted `ADDED_COLUMNS` entry shows up here as a column the fresh database has
    and the upgraded one does not. Foreign keys are compared too, because the D1 defect
    was a *reference* missing from an `ADDED_COLUMNS` type string while the column name
    was present — a comparison of names alone would not see it.
    """
    upgraded_path = _build_fixture_db("parity-upgraded.sqlite3")
    db.init_db(upgraded_path)
    fresh_path = _fresh_path("parity-fresh.sqlite3")
    db.init_db(fresh_path)

    upgraded = db.connect(upgraded_path)
    fresh = db.connect(fresh_path)
    try:
        assert set(_tables(upgraded)) == set(_tables(fresh))
        for table in _tables(fresh):
            missing_columns = _columns(fresh, table) - _columns(upgraded, table)
            assert not missing_columns, (
                f"upgrading left {table} without {sorted(missing_columns)}"
            )
            missing_indexes = _indexes(fresh, table) - _indexes(upgraded, table)
            assert not missing_indexes, (
                f"upgrading left {table} without index(es) {sorted(missing_indexes)}"
            )
            missing_fks = _foreign_keys(fresh, table) - _foreign_keys(upgraded, table)
            assert not missing_fks, (
                f"upgrading left {table} without foreign key(s) {sorted(missing_fks)}"
            )
    finally:
        upgraded.close()
        fresh.close()


def test_the_upgraded_segments_workout_reference_is_kept() -> None:
    """D1: `segments.workout_id` arrives on an old database through ADDED_COLUMNS.

    The CREATE declares `ON DELETE SET NULL`; if the ADDED_COLUMNS type string omits the
    reference (as it did), an upgraded database has the column but not the constraint,
    and deleting a workout leaves `segments.workout_id` pointing at nothing.
    """
    path = _build_fixture_db("workout-reference.sqlite3")
    db.init_db(path)
    conn = db.connect(path)
    try:
        assert ("workout_id", "workouts", "id", "SET NULL") in _foreign_keys(conn, "segments")

        # And the reference works: deleting the workout clears it rather than dangling.
        conn.execute("INSERT INTO workouts (id, started_ms, local_date) VALUES (7, 1, '2026-01-05')")
        conn.execute("UPDATE segments SET workout_id = 7 WHERE id = 1")
        conn.execute("DELETE FROM workouts WHERE id = 7")
        assert conn.execute("SELECT workout_id FROM segments WHERE id = 1").fetchone()[0] is None
    finally:
        conn.close()


def test_a_fresh_database_has_exactly_the_frozen_shape() -> None:
    path = _fresh_path("frozen-fresh.sqlite3")
    db.init_db(path)
    conn = db.connect(path)
    try:
        assert set(_tables(conn)) == set(EXPECTED_COLUMNS), (
            "a table was added or removed; name it here deliberately"
        )
        for table, expected in EXPECTED_COLUMNS.items():
            assert _columns(conn, table) == expected, f"{table} columns drifted"
        for table, expected in EXPECTED_INDEXES.items():
            assert _indexes(conn, table) == expected, f"{table} indexes drifted"
    finally:
        conn.close()


def test_a_fresh_database_reports_the_schema_version() -> None:
    path = _fresh_path("version-fresh.sqlite3")
    db.init_db(path)
    conn = db.connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    finally:
        conn.close()


def test_the_fixture_reports_zero_until_it_is_upgraded() -> None:
    path = _build_fixture_db("version-fixture.sqlite3")
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0, (
            "a pre-version database claims no version, which is why 0 cannot mean "
            "'current'"
        )
    finally:
        conn.close()

    db.init_db(path)

    conn = db.connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    finally:
        conn.close()


def test_a_database_from_a_newer_app_is_refused() -> None:
    """The missing downgrade guard: refuse rather than read a shape we do not know."""
    path = _fresh_path("from-the-future.sqlite3")
    db.init_db(path)
    conn = db.connect(path)
    try:
        conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    finally:
        conn.close()

    with pytest.raises(db.SchemaTooNew, match="schema version"):
        db.init_db(path)


def test_a_transaction_without_a_commit_leaves_nothing_behind() -> None:
    """A crash between BEGIN and COMMIT must leave the file readable and unchanged."""
    path = _fresh_path("crash.sqlite3")
    db.init_db(path)

    conn = db.connect(path)
    try:
        conn.execute("BEGIN")
        conn.execute("INSERT INTO composers (name) VALUES ('Ghost')")
        assert conn.execute("SELECT COUNT(*) FROM composers").fetchone()[0] == 1
    finally:
        # No COMMIT. Closing is what a process that died mid-transaction effectively does.
        conn.close()

    conn = db.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM composers").fetchone()[0] == 0
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_the_database_is_in_wal_mode_and_can_checkpoint() -> None:
    """`DEPLOYMENT.md` § Backup depends on both halves of this."""
    path = _fresh_path("wal.sqlite3")
    db.init_db(path)
    conn = db.connect(path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        busy, _log, _checkpointed = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        assert busy == 0, "the checkpoint could not run"
    finally:
        conn.close()


def test_the_upgraded_database_gains_the_practice_kind_columns() -> None:
    """20a: how a segment was practised arrives on a database that predates it.

    The parity test above compares a fresh database against an upgraded one, so it
    already catches a missing `ADDED_COLUMNS` entry. This asserts the specific columns
    the slice is about, so a rename cannot pass by moving the drift somewhere parity
    happens to agree on.
    """
    path = _build_fixture_db("kind-columns.sqlite3")
    db.init_db(path)
    conn = db.connect(path)
    try:
        assert {"practice_kind", "practice_kind_basis"} <= _columns(conn, "segments")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    finally:
        conn.close()


def test_the_upgraded_database_gains_the_blur_positions() -> None:
    """Phase 21: where the blurs were, on a database that predates the column."""
    path = _build_fixture_db("blur-columns.sqlite3")
    db.init_db(path)
    conn = db.connect(path)
    try:
        assert "pedal_blur_ms" in _columns(conn, "segment_metrics")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    finally:
        conn.close()


def test_the_upgraded_database_gains_the_take_columns() -> None:
    """20e: where a captured take came from, on a library that predates capture."""
    path = _build_fixture_db("take-columns.sqlite3")
    db.init_db(path)
    conn = db.connect(path)
    try:
        assert {"source", "sitting_id", "segment_id", "captured_start_ms"} <= _columns(conn, "media")
    finally:
        conn.close()


def test_the_upgraded_database_gives_the_take_columns_a_not_null_source() -> None:
    """20e: the migration must produce the *same* column a fresh database's CREATE declares,
    default included. `media.source` is the one added column whose fresh form is NOT NULL, and a
    NULL on the upgraded side would be exported by name and then restored into a NOT NULL column
    on another machine — where `merge` drops the row silently and `replace` fails outright."""
    path = _build_fixture_db("take-source-default.sqlite3")
    seed = sqlite3.connect(path)
    try:
        seed.execute("INSERT INTO media (kind, file_name) VALUES ('audio', 'old.wav')")
        seed.commit()
    finally:
        seed.close()

    db.init_db(path)
    conn = db.connect(path)
    try:
        info = {row[1]: row for row in conn.execute("PRAGMA table_info(media)")}
        assert info["source"][3] == 1, "source arrives NOT NULL, as the fresh CREATE says"
        assert conn.execute("SELECT source FROM media").fetchone()[0] == "uploaded", (
            "and a row that predates capture says it was uploaded"
        )
    finally:
        conn.close()


def test_an_immediate_transaction_takes_the_write_lock_before_it_reads() -> None:
    """The take catch-up reads `media` and then writes the rows it read, and it runs on a plain
    piece read. A deferred transaction fixes its snapshot at the first SELECT, so a commit from
    another connection in between turns the write into `database is locked` — SQLITE_BUSY_SNAPSHOT,
    which `busy_timeout` does not retry. Taking the lock up front is what removes that window."""
    path = _fresh_path("immediate.sqlite3")
    db.init_db(path)

    other = db.connect(path)
    try:
        with db.transaction(path, immediate=True) as conn:
            conn.execute("INSERT INTO composers (name) VALUES ('first')")
            other.execute("PRAGMA busy_timeout = 100")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("INSERT INTO composers (name) VALUES ('second')")
    finally:
        other.rollback()
        other.close()

    conn = db.connect(path)
    try:
        assert [row[0] for row in conn.execute("SELECT name FROM composers")] == ["first"]
    finally:
        conn.close()


def test_the_upgraded_database_gains_the_journal_columns() -> None:
    """20d: tags, two ratings and a take link arrive on a library that predates them."""
    path = _build_fixture_db("journal-columns.sqlite3")
    db.init_db(path)
    conn = db.connect(path)
    try:
        assert {"tags", "difficulty", "fluency", "media_id"} <= _columns(conn, "piece_journal")
    finally:
        conn.close()


def test_the_passage_table_exists_on_fresh_and_upgraded_databases() -> None:
    """A new table needs no ADDED_COLUMNS entry: the CREATE runs on every init."""
    upgraded = _build_fixture_db("passages-upgraded.sqlite3")
    db.init_db(upgraded)
    fresh = _fresh_path("passages-fresh.sqlite3")
    db.init_db(fresh)

    for path in (upgraded, fresh):
        conn = db.connect(path)
        try:
            assert "piece_passages" in _tables(conn)
            assert _columns(conn, "piece_passages") == {
                "id", "piece_id", "start_bar", "end_bar", "label", "source",
                "media_id", "created_at", "last_worked_on",
            }
        finally:
            conn.close()
