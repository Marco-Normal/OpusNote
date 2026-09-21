"""Workouts: the declared unit of sight-reading practice.

The point of the feature is that a deliberate workout and an emergent sitting are
linked, so "how much did I practise" and "how much did I work out" are two
readable numbers rather than one blurred one.
"""

from __future__ import annotations

import time

from app import db
from app.practice import store as practice_store
from app.practice.models import EventBatch, WireNote
from app.workout import store
from tests.conftest import phrase_offsets

BASE_MS = 1_700_011_800_000
LATER_MS = BASE_MS + 10_000_000


def notes_at(base_ms: int, offsets: list[int], *, source: str = "sight_reading"):
    return practice_store.ingest(
        EventBatch(
            tz_offset_minutes=0,
            source=source,
            events=[
                WireNote(
                    epoch_ms=base_ms + offset,
                    pitch=60 + index,
                    velocity=70,
                    duration_ms=300,
                    channel=0,
                )
                for index, offset in enumerate(offsets)
            ],
        )
    )


def test_starting_creates_a_running_workout(fresh_db) -> None:
    workout = store.start(tz_offset_minutes=0, target_skill="rhythm", bars=8, now_ms=BASE_MS)
    assert workout.running is True
    assert workout.completed is False
    # BASE_MS is 2023-11-15 01:30 UTC, so UTC and the player's day agree here.
    assert workout.local_date == "2023-11-15"
    assert workout.target_skill == "rhythm"
    assert workout.bars == 8
    assert store.current(now_ms=BASE_MS) is not None


def test_starting_twice_hands_back_the_same_workout(fresh_db) -> None:
    """Two open workouts would make "which workout is this attempt part of"
    ambiguous, and a double click is far likelier than an abandoned workout."""
    first = store.start(tz_offset_minutes=0, now_ms=BASE_MS)
    second = store.start(tz_offset_minutes=0, now_ms=BASE_MS + 1_000)
    assert second.id == first.id
    assert second.running is True


def test_there_is_no_current_workout_before_one_is_started(fresh_db) -> None:
    assert store.current(now_ms=BASE_MS) is None


def test_finishing_stops_and_dates_it(fresh_db) -> None:
    workout = store.start(tz_offset_minutes=0, now_ms=BASE_MS)
    finished = store.finish(workout.id, now_ms=BASE_MS + 600_000)
    assert finished.running is False
    assert finished.completed is True
    assert finished.ended_at is not None
    assert finished.minutes == 10.0
    assert store.current(now_ms=BASE_MS + 700_000) is None


def test_finishing_twice_is_harmless(fresh_db) -> None:
    workout = store.start(tz_offset_minutes=0, now_ms=BASE_MS)
    first = store.finish(workout.id, now_ms=BASE_MS + 600_000)
    second = store.finish(workout.id, now_ms=BASE_MS + 900_000)
    assert second.ended_ms == first.ended_ms
    assert second.minutes == first.minutes


def test_finishing_an_unknown_workout_is_not_found(fresh_db) -> None:
    import pytest

    with pytest.raises(store.NotFound):
        store.finish(999)


def test_a_workout_links_to_the_sitting_it_happened_inside(fresh_db) -> None:
    workout = store.start(tz_offset_minutes=0, now_ms=BASE_MS)
    sitting_id = notes_at(BASE_MS + 1_000, [0, 500, 1_000]).sitting_id
    finished = store.finish(workout.id, now_ms=BASE_MS + 120_000)
    assert finished.sitting_id == sitting_id


def test_a_workout_that_ended_long_after_its_last_note_still_links(fresh_db) -> None:
    """A workout is mostly spent reading; requiring the sitting to contain the
    whole workout would lose exactly the ones that ended in reflection."""
    workout = store.start(tz_offset_minutes=0, now_ms=BASE_MS)
    sitting_id = notes_at(BASE_MS + 1_000, [0, 500]).sitting_id
    finished = store.finish(workout.id, now_ms=BASE_MS + 40 * 60_000)
    assert finished.sitting_id == sitting_id


def test_a_workout_with_no_notes_links_to_nothing(fresh_db) -> None:
    """Rather than to whatever sitting happened to be nearest."""
    other = notes_at(BASE_MS - 3_600_000, [0, 500])
    workout = store.start(tz_offset_minutes=0, now_ms=BASE_MS)
    finished = store.finish(workout.id, now_ms=BASE_MS + 60_000)
    assert finished.sitting_id is None
    # The unrelated sitting is untouched.
    assert practice_store.list_sittings()[0].id == other.sitting_id


def test_the_segment_a_workout_overlapped_is_tagged_sight_reading(fresh_db) -> None:
    workout = store.start(tz_offset_minutes=0, now_ms=BASE_MS - 1_000)
    sitting_id = notes_at(BASE_MS, [0, 500, 1_000]).sitting_id
    store.finish(workout.id, now_ms=BASE_MS + 2_000)

    segments = practice_store.ensure_segments(sitting_id, now_ms=LATER_MS)
    assert segments[0].workout_id == workout.id
    assert segments[0].identified_by == "workout"
    assert segments[0].source == "sight_reading"


def test_a_segment_outside_the_workout_is_left_alone(fresh_db) -> None:
    """Two pieces in one sitting, only the second played during a workout."""
    phrases = phrase_offsets(0, 8) + phrase_offsets(20_000, 8)
    sitting_id = notes_at(BASE_MS, phrases, source="web_midi").sitting_id
    workout = store.start(tz_offset_minutes=0, now_ms=BASE_MS + 20_000)
    store.finish(workout.id, now_ms=BASE_MS + 21_000)

    segments = practice_store.ensure_segments(sitting_id, now_ms=LATER_MS)
    assert [segment.source for segment in segments] == [None, "sight_reading"]
    assert [segment.workout_id for segment in segments] == [None, workout.id]


def test_a_manual_piece_label_is_not_overwritten_by_a_workout(fresh_db, client) -> None:
    workout = store.start(tz_offset_minutes=0, now_ms=BASE_MS - 1_000)
    sitting_id = notes_at(BASE_MS, [0, 500, 1_000]).sitting_id
    store.finish(workout.id, now_ms=BASE_MS + 2_000)
    segments = practice_store.ensure_segments(sitting_id, now_ms=LATER_MS)

    piece_id = client.post("/api/repertoire/pieces", json={"title": "Intermezzo"}).json()["id"]
    labelled = practice_store.assign_piece(segments[0].id, piece_id)
    assert labelled[0].identified_by == "manual"
    assert labelled[0].source == "repertoire"


def _insert_performance(conn) -> int:
    """A performance row with the minimum its foreign keys require."""
    user_id = db.get_or_create_user(conn)
    exercise_id = int(
        conn.execute(
            "INSERT INTO exercises (musicxml_blob, difficulty_elo) VALUES ('<score/>', 700.0)"
        ).lastrowid
    )
    return int(
        conn.execute(
            "INSERT INTO performances (user_id, exercise_id, mode) VALUES (?1, ?2, 'practice')",
            (user_id, exercise_id),
        ).lastrowid
    )


def test_attempts_are_attributed_to_the_running_workout(fresh_db) -> None:
    workout = store.start(tz_offset_minutes=0, now_ms=BASE_MS)
    conn = practice_store.db.connect()
    try:
        conn.execute("BEGIN")
        performance_id = _insert_performance(conn)
        conn.execute("COMMIT")
        assert store.attach_performance(conn, performance_id) == workout.id
        row = conn.execute(
            "SELECT workout_id FROM performances WHERE id = ?", (performance_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row["workout_id"] == workout.id


def test_an_attempt_with_no_workout_running_is_left_alone(fresh_db) -> None:
    conn = practice_store.db.connect()
    try:
        conn.execute("BEGIN")
        performance_id = _insert_performance(conn)
        conn.execute("COMMIT")
        assert store.attach_performance(conn, performance_id) is None
        row = conn.execute(
            "SELECT workout_id FROM performances WHERE id = ?", (performance_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row["workout_id"] is None


def test_stats_count_only_finished_workouts(fresh_db) -> None:
    finished = store.start(tz_offset_minutes=0, now_ms=BASE_MS)
    store.finish(finished.id, now_ms=BASE_MS + 1_000)
    store.start(tz_offset_minutes=0, now_ms=BASE_MS + 2_000)

    body = store.stats(practice_store.db.connect())
    assert body["workouts_completed"] == 1
    assert body["last_workout_date"] == "2023-11-15"


def test_the_http_surface_round_trips(client) -> None:
    home = client.get("/api/workout").json()
    assert home["current"] is None
    assert home["recent"] == []

    started = client.post("/api/workout/start", json={"tz_offset_minutes": 0}).json()
    assert started["running"] is True
    assert started["planned"] == 8

    again = client.post("/api/workout/start", json={"tz_offset_minutes": 0}).json()
    assert again["id"] == started["id"]

    assert client.get("/api/workout/current").json()["id"] == started["id"]

    finished = client.post(f"/api/workout/{started['id']}/finish").json()
    assert finished["completed"] is True
    assert client.get("/api/workout/current").json() is None

    home = client.get("/api/workout").json()
    assert home["current"] is None
    assert home["workouts_completed"] == 1
    assert home["recent"][0]["id"] == started["id"]


def test_an_unknown_skill_is_rejected(client) -> None:
    response = client.post(
        "/api/workout/start", json={"tz_offset_minutes": 0, "target_skill": "nonsense"}
    )
    assert response.status_code == 422


def test_finishing_an_unknown_workout_is_404(client) -> None:
    assert client.post("/api/workout/999/finish").status_code == 404


def test_a_workout_records_the_players_local_date(client) -> None:
    """Required, not defaulted: an 11 pm session west of Greenwich belongs to
    today, not tomorrow."""
    workout = store.start(tz_offset_minutes=-180, now_ms=BASE_MS)
    assert workout.local_date == "2023-11-14"
    utc = store.start(tz_offset_minutes=0, now_ms=BASE_MS)
    assert utc.id == workout.id  # one open workout, so compare the column directly
    conn = practice_store.db.connect()
    try:
        row = conn.execute("SELECT local_date FROM workouts WHERE id = ?", (workout.id,)).fetchone()
    finally:
        conn.close()
    assert row["local_date"] == "2023-11-14"


def test_completing_a_workout_does_not_touch_the_clock_of_the_sitting(fresh_db) -> None:
    """Finishing is a statement about the workout, not about the notes."""
    workout = store.start(tz_offset_minutes=0, now_ms=BASE_MS)
    notes_at(BASE_MS, [0, 500])
    before = practice_store.list_sittings()[0]
    store.finish(workout.id, now_ms=BASE_MS + 120_000)
    after = practice_store.list_sittings()[0]
    assert after.ended_at == before.ended_at
    assert after.note_count == 2


def test_a_real_sitting_is_still_open_while_the_workout_runs(fresh_db) -> None:
    now_ms = int(time.time() * 1000)
    workout = store.start(tz_offset_minutes=0, now_ms=now_ms)
    notes_at(now_ms, [0, 500], source="sight_reading")
    status = practice_store.list_sittings()[0]
    assert status.source == "sight_reading"
    finished = store.finish(workout.id, now_ms=now_ms + 1_000)
    assert finished.sitting_id == status.id
