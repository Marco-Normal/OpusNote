"""HTTP surface of the practice domain, plus analytics over recorded sittings."""

from __future__ import annotations

from app.config import settings
from app.db import connect
from app.practice import store
from app.practice.models import EventBatch, WireNote

BASE_MS = 1_700_011_800_000
LATER_MS = BASE_MS + 10_000_000


def batch_payload(offsets: list[int], *, source: str = "web_midi", tz: int = 0) -> dict:
    return {
        "tz_offset_minutes": tz,
        "source": source,
        "events": [
            {
                "epoch_ms": BASE_MS + offset,
                "pitch": 60 + index,
                "velocity": 70,
                "duration_ms": 300,
                "channel": 0,
            }
            for index, offset in enumerate(offsets)
        ],
    }


def record(offsets: list[int], *, source: str = "web_midi"):
    """Record notes relative to a fixed instant in 2023."""
    return _record(BASE_MS, offsets, source=source)


def server_offset_minutes() -> int:
    """The UTC offset of the machine running the tests.

    A browser sends its own offset, and the practice domain stores the *client's*
    calendar day while the analytics compare against the server's today. On the
    single-host deployment those are the same timezone by definition, so a test that
    hard-codes 0 is only correct for the part of the day where the UTC and local dates
    agree — which is exactly the trap that made this helper wrong for three hours a
    day at UTC-3.
    """
    from datetime import datetime

    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds() // 60) if offset else 0


def record_now(offsets: list[int], *, source: str = "web_midi"):
    """Record notes relative to now, as this machine's browser would.

    The windowed analytics — calendar, time per piece, source split — only see
    the last `days`, so a test that checks them against 2023 data would be
    asserting that old practice is correctly excluded, which is a different test.
    """
    import time

    return _record(int(time.time() * 1000), offsets, source=source, tz=server_offset_minutes())


def _record(base_ms: int, offsets: list[int], *, source: str, tz: int = 0):
    return store.ingest(
        EventBatch(
            tz_offset_minutes=tz,
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


def test_ingest_through_http(client) -> None:
    body = client.post("/api/practice/events", json=batch_payload([0, 500, 1_000])).json()
    assert (body["accepted"], body["duplicates"]) == (3, 0)
    sittings = client.get("/api/practice/sittings").json()
    assert len(sittings) == 1
    assert sittings[0]["note_count"] == 3
    assert sittings[0]["source"] == "web_midi"


def test_empty_batch_over_http_is_rejected(client) -> None:
    response = client.post(
        "/api/practice/events", json={"tz_offset_minutes": 0, "events": []}
    )
    assert response.status_code == 422


def test_out_of_range_pitch_is_rejected(client) -> None:
    payload = batch_payload([0])
    payload["events"][0]["pitch"] = 200
    assert client.post("/api/practice/events", json=payload).status_code == 422


def test_an_unknown_source_is_rejected(client) -> None:
    """The source is a closed set, so a typo cannot invent a third category."""
    payload = batch_payload([0], source="sight_reading")
    payload["source"] = "sigth_reading"
    assert client.post("/api/practice/events", json=payload).status_code == 422


def test_client_id_is_no_longer_part_of_the_contract(client) -> None:
    """One app owns capture, so the field the ported logger validated and dropped
    is gone rather than carried as a value nothing reads."""
    payload = batch_payload([0])
    payload["client_id"] = "test"
    assert client.post("/api/practice/events", json=payload).status_code == 200
    response = client.post("/api/practice/events", json=payload)
    # Extra keys are ignored rather than rejected, so an old client keeps working.
    assert response.json()["duplicates"] == 1


def test_status_says_whether_a_sitting_is_still_open(client) -> None:
    """"Is capture working?" must be answerable without playing a note."""
    import time

    assert client.get("/api/practice/status").json()["sittings"] == 0

    now_ms = int(time.time() * 1000)
    store.ingest(
        EventBatch(
            tz_offset_minutes=0,
            events=[
                WireNote(
                    epoch_ms=now_ms, pitch=60, velocity=70, duration_ms=300, channel=0
                )
            ],
        )
    )
    body = client.get("/api/practice/status").json()
    assert body["sittings"] == 1
    assert body["notes"] == 1
    assert body["open_sitting"] is True

    # A sitting from years ago is closed: the flag means "notes arriving now",
    # not "a row exists".
    record([0])
    older = client.get("/api/practice/sittings").json()
    assert len(older) == 2


def test_sitting_detail_carries_segments(client) -> None:
    sitting_id = record([0, 500, 1_000]).sitting_id
    body = client.get(f"/api/practice/sittings/{sitting_id}").json()
    assert body["closed"] is True
    assert body["note_count"] == 3
    assert len(body["segments"]) == 1
    assert body["segments"][0]["note_count"] == 3
    assert body["segments"][0]["piece_title"] is None


def test_assign_then_read_back_over_http(client) -> None:
    sitting_id = record([0, 500, 1_000]).sitting_id
    segment_id = client.get(f"/api/practice/sittings/{sitting_id}").json()["segments"][0]["id"]
    piece_id = client.post(
        "/api/repertoire/pieces", json={"title": "Intermezzo", "key": "A"}
    ).json()["id"]

    updated = client.patch(
        f"/api/practice/segments/{segment_id}", json={"piece_id": piece_id}
    ).json()
    reread = client.get(f"/api/practice/sittings/{sitting_id}").json()
    assert updated[0]["piece_id"] == piece_id
    assert reread["segments"][0]["piece_id"] == piece_id
    assert reread["segments"][0]["piece_title"] == "Intermezzo"


def test_unknown_segment_is_404_and_unknown_piece_is_422(client) -> None:
    sitting_id = record([0, 500, 1_000]).sitting_id
    segment_id = client.get(f"/api/practice/sittings/{sitting_id}").json()["segments"][0]["id"]
    assert client.patch("/api/practice/segments/9999", json={"piece_id": 1}).status_code == 404
    assert (
        client.patch(
            f"/api/practice/segments/{segment_id}", json={"piece_id": 9999}
        ).status_code
        == 422
    )


def test_split_and_merge_round_trip(client) -> None:
    sitting_id = record([0, 500, 1_000]).sitting_id
    segment_id = client.get(f"/api/practice/sittings/{sitting_id}").json()["segments"][0]["id"]

    outside = client.post(
        f"/api/practice/segments/{segment_id}/split", json={"at_ms": 5_000}
    )
    split = client.post(
        f"/api/practice/segments/{segment_id}/split", json={"at_ms": 700}
    ).json()
    merged = client.post(
        f"/api/practice/segments/{split[1]['id']}/merge", json={"other_id": split[0]["id"]}
    ).json()
    assert outside.status_code == 422
    assert [segment["note_count"] for segment in split] == [2, 1]
    assert len(merged) == 1
    assert merged[0]["note_count"] == 3


def test_resegment_needs_confirmation_when_labelled(client) -> None:
    sitting_id = record([0, 500, 1_000]).sitting_id
    segment_id = client.get(f"/api/practice/sittings/{sitting_id}").json()["segments"][0]["id"]
    piece_id = client.post("/api/repertoire/pieces", json={"title": "Ballade"}).json()["id"]
    client.patch(f"/api/practice/segments/{segment_id}", json={"piece_id": piece_id})

    refused = client.post(
        f"/api/practice/sittings/{sitting_id}/resegment", json={"confirm": False}
    )
    forced = client.post(
        f"/api/practice/sittings/{sitting_id}/resegment", json={"confirm": True}
    )
    assert refused.status_code == 409
    assert forced.status_code == 200
    assert forced.json()[0]["piece_id"] is None


def test_unknown_sitting_is_404(client) -> None:
    assert client.get("/api/practice/sittings/9999").status_code == 404


# --- analytics ------------------------------------------------------------


def test_the_calendar_covers_every_day_in_the_window(client) -> None:
    """A heatmap drawn only from busy days renders a gap-free strip and loses the
    fact that nothing happened for a week."""
    body = client.get("/api/practice/analytics/summary?days=14").json()
    assert len(body["calendar"]) == 14
    assert all(day["minutes"] == 0 for day in body["calendar"])
    assert body["sources"] == []


def test_time_per_piece_counts_only_labelled_segments(client) -> None:
    # Two phrases half a minute apart: one sitting, two segments. Six minutes ago
    # so the sitting is closed, and long enough that the first segment's duration
    # survives rounding to a tenth of a minute.
    sitting_id = record_now([-400_000, -399_500, -395_000, -365_000]).sitting_id
    segments = client.get(f"/api/practice/sittings/{sitting_id}").json()["segments"]
    assert len(segments) == 2
    piece_id = client.post(
        "/api/repertoire/pieces", json={"title": "Intermezzo", "key": "A"}
    ).json()["id"]
    client.patch(f"/api/practice/segments/{segments[0]['id']}", json={"piece_id": piece_id})

    body = client.get("/api/practice/analytics/summary?days=365").json()
    labelled = body["by_piece"]
    assert len(labelled) == 1
    assert labelled[0]["piece_id"] == piece_id
    assert labelled[0]["segments"] == 1
    assert labelled[0]["minutes"] == 0.1
    # Only the labelled half: the other segment is attributed to nothing rather
    # than guessed at, so the sitting's 35 seconds and the labelled 5 disagree.
    assert body["total_minutes"] == 0.6


def test_the_piece_block_reports_tempo_over_time(client) -> None:
    piece_id = client.post(
        "/api/repertoire/pieces", json={"title": "Intermezzo", "key": "A"}
    ).json()["id"]
    sitting_id = record_now([-407_000, -406_500, -406_000, -400_000]).sitting_id
    segment_id = client.get(f"/api/practice/sittings/{sitting_id}").json()["segments"][0]["id"]
    client.patch(f"/api/practice/segments/{segment_id}", json={"piece_id": piece_id})

    body = client.get(f"/api/practice/pieces/{piece_id}").json()
    assert body["title"] == "Intermezzo"
    assert body["segments"] == 1
    assert body["notes"] == 4
    assert body["minutes"] > 0
    # Attacks at 0, 0.5, 1 and 7 s: the median interval is 500 ms.
    assert body["tempo"]["points"][0]["median_tempo"] == 120.0


def test_the_piece_block_works_for_a_piece_with_no_practice(client) -> None:
    piece_id = client.post("/api/repertoire/pieces", json={"title": "Untouched"}).json()["id"]
    body = client.get(f"/api/practice/pieces/{piece_id}").json()
    assert body["minutes"] == 0
    assert body["segments"] == 0
    assert body["last_played"] is None
    assert body["tempo"]["points"] == []


def test_an_unknown_piece_is_404(client) -> None:
    assert client.get("/api/practice/pieces/9999").status_code == 404


def test_journal_minutes_are_kept_beside_logged_minutes(client) -> None:
    """The two records of practice time are different facts and both are shown.

    A journal entry is a written claim about time; a segment is measured. Summing
    them would double-count a session that was both measured and written down.
    """
    piece_id = client.post(
        "/api/repertoire/pieces", json={"title": "Intermezzo"}
    ).json()["id"]
    client.post(
        f"/api/repertoire/pieces/{piece_id}/journal",
        json={"entry_date": "2023-11-14", "content": "Slow practice.", "practice_minutes": 25},
    )
    body = client.get(f"/api/practice/pieces/{piece_id}").json()
    assert body["journal_minutes"] == 25
    assert body["minutes"] == 0


def test_neglected_lists_never_played_pieces_first(client) -> None:
    played_id = client.post("/api/repertoire/pieces", json={"title": "Played"}).json()["id"]
    client.post("/api/repertoire/pieces", json={"title": "Never touched"})
    sitting_id = record([0, 500, 1_000]).sitting_id
    segment_id = client.get(f"/api/practice/sittings/{sitting_id}").json()["segments"][0]["id"]
    client.patch(f"/api/practice/segments/{segment_id}", json={"piece_id": played_id})

    body = client.get("/api/practice/analytics/summary?days=30").json()
    titles = [row["title"] for row in body["neglected"]]
    assert titles[0] == "Never touched"
    assert body["neglected"][0]["days_since"] is None
    played = next(row for row in body["neglected"] if row["title"] == "Played")
    assert played["days_since"] is not None


def test_completed_pieces_are_not_neglected(client) -> None:
    client.post(
        "/api/repertoire/pieces", json={"title": "Finished", "status": "completed"}
    )
    body = client.get("/api/practice/analytics/summary?days=30").json()
    assert [row["title"] for row in body["neglected"]] == []


def test_sources_split_sight_reading_from_ordinary_practice(client) -> None:
    record_now([-2_000, -1_500])
    record_now([-400_000, -399_500], source="sight_reading")
    body = client.get("/api/practice/analytics/summary?days=365").json()
    splits = {row["source"]: row for row in body["sources"]}
    assert set(splits) == {"web_midi", "sight_reading"}
    assert splits["sight_reading"]["notes"] == 2


def test_the_streak_counts_consecutive_practice_days(client) -> None:
    """Recorded in the recent past, so the streak is measured against today."""
    import time

    now_ms = int(time.time() * 1000)
    day = 86_400_000
    for offset in (0, day, 2 * day):
        store.ingest(
            EventBatch(
                tz_offset_minutes=server_offset_minutes(),
                events=[
                    WireNote(
                        epoch_ms=now_ms - offset,
                        pitch=60,
                        velocity=70,
                        duration_ms=100,
                        channel=0,
                    )
                ],
            )
        )
    body = client.get("/api/practice/analytics/summary?days=7").json()
    assert body["streak_days"] == 3
    assert body["calendar"][-1]["notes"] == 1


def test_a_streak_survives_a_day_that_has_not_been_practised_yet(client) -> None:
    """Yesterday counts, so the streak is not reset every midnight until you play."""
    import time

    now_ms = int(time.time() * 1000)
    store.ingest(
        EventBatch(
            tz_offset_minutes=server_offset_minutes(),
            events=[
                WireNote(
                    epoch_ms=now_ms - 86_400_000,
                    pitch=60,
                    velocity=70,
                    duration_ms=100,
                    channel=0,
                )
            ],
        )
    )
    assert client.get("/api/practice/analytics/summary?days=7").json()["streak_days"] == 1


def test_no_practice_means_no_streak(client) -> None:
    assert client.get("/api/practice/analytics/summary?days=7").json()["streak_days"] == 0


def test_analytics_are_readable_with_no_database_rows(client) -> None:
    body = client.get("/api/practice/analytics/summary").json()
    assert body["total_minutes"] == 0
    assert body["total_notes"] == 0
    assert body["by_piece"] == []
    assert body["recent"] == []
    assert body["workouts_completed"] == 0


def test_the_summary_counts_workouts_without_the_practice_domain_knowing(client) -> None:
    client.post("/api/workout/start", json={"tz_offset_minutes": 0})
    client.post("/api/workout/1/finish")
    assert client.get("/api/practice/analytics/summary").json()["workouts_completed"] == 1


def test_tempo_for_an_unknown_piece_is_404(client) -> None:
    assert client.get("/api/practice/analytics/tempo?piece_id=9999").status_code == 404


def test_settings_still_point_at_one_database(client) -> None:
    conn = connect()
    try:
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()
    assert {
        "sittings",
        "note_events",
        "segments",
        "segment_metrics",
        "workouts",
        "pieces",
    } <= names
    assert settings.db_path.name == "test.sqlite3"


# --- playback -------------------------------------------------------------


def test_the_notes_of_a_sitting_are_available_for_playback(client) -> None:
    """Everything a synthesiser needs, in playing order."""
    sitting_id = record([0, 500, 1_000]).sitting_id
    body = client.get(f"/api/practice/sittings/{sitting_id}/notes").json()
    assert body["sitting_id"] == sitting_id
    assert body["started_ms"] == BASE_MS
    assert [note["onset_ms"] for note in body["notes"]] == [0, 500, 1_000]
    assert all(note["duration_ms"] == 300 for note in body["notes"])
    assert all(note["velocity"] == 70 for note in body["notes"])
    assert [note["pitch"] for note in body["notes"]] == [60, 61, 62]


def test_the_notes_are_ordered_by_onset_not_by_insertion(client) -> None:
    """A batch can arrive out of order; playback must not replay it that way."""
    from app.practice.models import EventBatch, WireNote

    store.ingest(
        EventBatch(
            tz_offset_minutes=0,
            events=[
                WireNote(epoch_ms=BASE_MS + offset, pitch=pitch, velocity=70, duration_ms=100)
                for pitch, offset in ((72, 900), (60, 0), (67, 450))
            ],
        )
    )
    notes = client.get("/api/practice/sittings/1/notes").json()["notes"]
    assert [note["onset_ms"] for note in notes] == [0, 450, 900]


def test_playback_of_a_sitting_with_no_notes_is_empty_not_an_error(client) -> None:
    from app import db as db_module
    from app.config import settings

    conn = db_module.connect(settings.db_path)
    try:
        conn.execute("BEGIN")
        sitting_id = int(
            conn.execute(
                "INSERT INTO sittings (started_ms, ended_ms, started_at, ended_at, local_date)"
                " VALUES (0, 0, '1970-01-01 00:00:00', '1970-01-01 00:00:00', '1970-01-01')"
            ).lastrowid
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    body = client.get(f"/api/practice/sittings/{sitting_id}/notes").json()
    assert body["notes"] == []


def test_notes_for_an_unknown_sitting_are_404(client) -> None:
    assert client.get("/api/practice/sittings/9999/notes").status_code == 404
