"""HTTP surface of the practice domain, plus analytics over recorded sittings."""

from __future__ import annotations

from datetime import datetime

from app.config import settings
from app.db import connect
from app.practice import store
from app.practice.models import EventBatch, WireNote
from tests.conftest import phrase_offsets

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


def test_pedals_arrive_and_come_back_with_the_notes(client) -> None:
    """The whole wire path for the sustain pedal: a batch carrying notes and
    pedal moves together, then the playback payload."""
    payload = batch_payload([0, 500])
    payload["pedals"] = [
        {"epoch_ms": BASE_MS + 200, "value": 127, "channel": 0},
        {"epoch_ms": BASE_MS + 900, "value": 0, "channel": 0},
    ]
    body = client.post("/api/practice/events", json=payload).json()
    assert (body["pedals_accepted"], body["pedals_ignored"]) == (2, 0)

    notes = client.get(f"/api/practice/sittings/{body['sitting_id']}/notes").json()
    assert [(item["onset_ms"], item["value"]) for item in notes["pedals"]] == [
        (200, 127),
        (900, 0),
    ]


def test_a_batch_without_pedals_is_unchanged(client) -> None:
    """The field is optional on the wire: a client that predates it — or a
    keyboard with no pedal — keeps working, and reads back an empty list."""
    body = client.post("/api/practice/events", json=batch_payload([0, 500])).json()
    assert (body["pedals_accepted"], body["pedals_ignored"]) == (0, 0)

    notes = client.get(f"/api/practice/sittings/{body['sitting_id']}/notes").json()
    assert notes["pedals"] == []


def test_a_pedal_only_batch_is_accepted_and_can_be_ignored(client) -> None:
    """A pedal-only batch cannot be refused: the client would retry it forever,
    blocking every batch behind it. Inside a sitting it is stored; outside one it
    is dropped and counted, with no sitting invented for it."""
    opened = client.post("/api/practice/events", json=batch_payload([0, 500])).json()
    inside = client.post(
        "/api/practice/events",
        json={
            "tz_offset_minutes": 0,
            "pedals": [{"epoch_ms": BASE_MS + 700, "value": 127, "channel": 0}],
        },
    )
    assert inside.status_code == 200
    assert inside.json()["sitting_id"] == opened["sitting_id"]
    assert inside.json()["pedals_accepted"] == 1

    away = client.post(
        "/api/practice/events",
        json={
            "tz_offset_minutes": 0,
            "pedals": [{"epoch_ms": BASE_MS + 60 * 60 * 1000, "value": 127, "channel": 0}],
        },
    )
    assert away.status_code == 200
    assert away.json()["pedals_ignored"] == 1
    assert away.json()["sitting_id"] is None
    assert len(client.get("/api/practice/sittings").json()) == 1


def test_a_pedal_value_out_of_range_is_rejected(client) -> None:
    response = client.post(
        "/api/practice/events",
        json={
            "tz_offset_minutes": 0,
            "pedals": [{"epoch_ms": BASE_MS, "value": 200, "channel": 0}],
        },
    )
    assert response.status_code == 422


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
    # Two phrases a long pause apart: one sitting, two segments. Six minutes ago
    # so the sitting is closed, and each phrase is over the rule's minimum size so
    # neither is absorbed as a stray touch.
    offsets = phrase_offsets(-400_000, 8) + phrase_offsets(-371_000, 8)
    sitting_id = record_now(offsets).sitting_id
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


def test_the_piano_going_away_closes_the_sitting_through_the_api(client) -> None:
    """What the client calls on a MIDI disconnect, and why the dashboard updates as
    soon as the piano is switched off rather than five minutes later."""
    import time

    base = int(time.time() * 1000) - 10_000
    payload = {
        "tz_offset_minutes": 0,
        "events": [
            {"epoch_ms": base, "pitch": 60, "velocity": 70, "duration_ms": 200, "channel": 0},
            {"epoch_ms": base + 500, "pitch": 62, "velocity": 70, "duration_ms": 200, "channel": 0},
        ],
    }
    opened = client.post("/api/practice/events", json=payload).json()
    sitting_id = opened["sitting_id"]

    # Not yet: the sitting's own gap has not passed, so it has no segments.
    assert client.get(f"/api/practice/sittings/{sitting_id}").json()["segments"] == []

    closed = client.post("/api/practice/sittings/close")
    assert closed.status_code == 200, closed.text
    assert closed.json() == {"closed": True, "sitting_id": sitting_id, "reason": "closed"}

    detail = client.get(f"/api/practice/sittings/{sitting_id}").json()
    assert len(detail["segments"]) == 1, "segmented at once, not five minutes later"


def test_closing_with_nothing_open_says_so(client) -> None:
    body = client.post("/api/practice/sittings/close").json()
    assert body["closed"] is False
    assert body["reason"] == "nothing open"


def test_closing_while_still_playing_says_that_instead(client) -> None:
    """The two ways to close nothing are different facts.

    "Nothing open" means the piano had already gone quiet; "still playing" means
    notes arrived moments ago and the sitting is deliberately left alone. Both used
    to reach the client as the same answer, so a UI could not tell a finished session
    from a USB blip without guessing.
    """
    import time

    now = int(time.time() * 1000)
    client.post(
        "/api/practice/events",
        json={
            "tz_offset_minutes": 0,
            "events": [
                {
                    "epoch_ms": now - 200,
                    "pitch": 60,
                    "velocity": 70,
                    "duration_ms": 100,
                    "channel": 0,
                }
            ],
        },
    )
    body = client.post("/api/practice/sittings/close").json()
    assert body["closed"] is False
    assert body["reason"] == "still playing"


def test_status_is_open_only_while_a_note_would_still_join(client) -> None:
    """"Open" is not a clock reading: it is whether the next note would join the
    sitting, which is the question ingest asks. They disagreed as soon as a sitting
    could be closed by the piano going away."""
    import time

    base = int(time.time() * 1000) - 10_000
    client.post(
        "/api/practice/events",
        json={
            "tz_offset_minutes": 0,
            "events": [
                {"epoch_ms": base, "pitch": 60, "velocity": 70, "duration_ms": 200, "channel": 0}
            ],
        },
    )
    assert client.get("/api/practice/status").json()["open_sitting"] is True

    client.post("/api/practice/sittings/close")

    status = client.get("/api/practice/status").json()
    assert status["open_sitting"] is False, "closed by the device, not by the clock"
    assert status["last_note_ms"] is not None, "and the last note is still reported"


# --- practice kinds (Phase 20a) --------------------------------------------


def recent_sitting(client, offsets: list[int]) -> dict:
    """A sitting played a minute ago and closed, so it has segments *and* is in the window.

    Two constraints meet here. Stored segments are never recomputed implicitly, so a
    sitting still inside its own silence gap has none until it is closed. And every
    windowed analytics query starts from today, so the 2023 fixtures the store tests use
    would be asserted as correctly *excluded* rather than counted.
    """
    import time

    base = int(time.time() * 1000) - 60_000
    body = client.post(
        "/api/practice/events",
        json={
            "tz_offset_minutes": server_offset_minutes(),
            "events": [
                {
                    "epoch_ms": base + offset,
                    "pitch": 60 + index,
                    "velocity": 70,
                    "duration_ms": 300,
                    "channel": 0,
                }
                for index, offset in enumerate(offsets)
            ],
        },
    ).json()
    closed = client.post("/api/practice/sittings/close")
    assert closed.status_code == 200, closed.text
    detail = client.get(f"/api/practice/sittings/{body['sitting_id']}").json()
    return {"sitting_id": body["sitting_id"], "segments": detail["segments"]}


def seed_piece(conn, title: str = "Etude") -> int:
    piece_id = conn.execute(
        "INSERT INTO pieces (title, status) VALUES (?, 'active')", (title,)
    ).lastrowid
    conn.commit()
    return int(piece_id)


def segment_of(client, sitting: dict, index: int = 0) -> dict:
    """Re-read one segment through the API, which is the thing under test."""
    detail = client.get(f"/api/practice/sittings/{sitting['sitting_id']}").json()
    return detail["segments"][index]


#: Attacks every 500 ms - 120 BPM, a piece's ordinary rate in the offer tests.
FAST_OFFSETS = [0, 500, 1_000, 1_500]
#: Attacks every 1500 ms - 40 BPM, a third of the ordinary rate.
SLOW_OFFSETS = [0, 1_500, 3_000, 4_500]


def a_piece_with_a_slow_offer(client, conn) -> tuple[dict, int]:
    """Three ordinary segments give the piece a baseline; a slow one earns an offer.

    The offer arrives from *labelling the piece*, not from a button: "slower than usual"
    cannot mean anything until the app knows what usual is for that piece. That is also
    why `offer_practice_kinds` runs when a label is written, not only at segmentation.
    """
    piece_id = seed_piece(conn)
    for _ in range(3):
        sitting = recent_sitting(client, FAST_OFFSETS)
        client.patch(
            f"/api/practice/segments/{segment_of(client, sitting)['id']}",
            json={"piece_id": piece_id},
        )
    slow = recent_sitting(client, SLOW_OFFSETS)
    segment_id = segment_of(client, slow)["id"]
    response = client.patch(
        f"/api/practice/segments/{segment_id}", json={"piece_id": piece_id}
    )
    assert response.status_code == 200, response.text
    return slow, segment_id


def test_labelling_a_piece_offers_slow_against_that_pieces_own_tempo(client, conn) -> None:
    slow, segment_id = a_piece_with_a_slow_offer(client, conn)
    segment = segment_of(client, slow)
    assert segment["id"] == segment_id
    assert (segment["practice_kind"], segment["practice_kind_basis"]) == ("slow", "offered")


def test_an_offer_is_a_question_until_it_is_answered(client, conn) -> None:
    """The rule the whole feature rests on, over a real offer rather than a planted one."""
    _slow, segment_id = a_piece_with_a_slow_offer(client, conn)

    offered = client.get("/api/practice/analytics/summary?days=365").json()["kinds"]
    assert all(entry["kind"] is None for entry in offered), (
        f"an unanswered offer must not appear as a kind ({offered})"
    )

    accepted = client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "accept"}
    )
    assert accepted.status_code == 200, accepted.text
    segment = next(s for s in accepted.json() if s["id"] == segment_id)
    assert (segment["practice_kind"], segment["practice_kind_basis"]) == ("slow", "accepted")

    counted = client.get("/api/practice/analytics/summary?days=365").json()["kinds"]
    assert "slow" in {entry["kind"] for entry in counted}


def test_declining_clears_the_offer_so_it_cannot_linger(client, conn) -> None:
    slow, segment_id = a_piece_with_a_slow_offer(client, conn)
    declined = client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "decline"}
    )
    assert declined.status_code == 200, declined.text
    assert segment_of(client, slow)["practice_kind"] is None
    assert segment_of(client, slow)["practice_kind_basis"] is None


def test_a_practice_kind_is_set_read_and_cleared(client) -> None:
    sitting = recent_sitting(client, FAST_OFFSETS)
    segment_id = segment_of(client, sitting)["id"]

    setter = client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "set", "kind": "memory"}
    )
    assert setter.status_code == 200, setter.text
    segment = next(s for s in setter.json() if s["id"] == segment_id)
    assert (segment["practice_kind"], segment["practice_kind_basis"]) == ("memory", "manual")

    assert segment_of(client, sitting)["practice_kind"] == "memory", "and survives a re-read"

    cleared = client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "set", "kind": None}
    )
    cleared_segment = next(s for s in cleared.json() if s["id"] == segment_id)
    assert cleared_segment["practice_kind"] is None
    assert cleared_segment["practice_kind_basis"] is None


def test_an_unknown_practice_kind_is_a_422(client) -> None:
    sitting = recent_sitting(client, FAST_OFFSETS)
    segment_id = segment_of(client, sitting)["id"]
    response = client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "set", "kind": "banjo"}
    )
    assert response.status_code == 422


def test_accepting_with_no_offer_is_a_422_and_declining_nothing_is_harmless(client) -> None:
    sitting = recent_sitting(client, FAST_OFFSETS)
    segment_id = segment_of(client, sitting)["id"]
    accepted = client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "accept"}
    )
    assert accepted.status_code == 422
    declined = client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "decline"}
    )
    assert declined.status_code == 200, "a double-click must not 409"


def test_setting_a_kind_on_a_missing_segment_is_a_404(client) -> None:
    response = client.patch(
        "/api/practice/segments/999999/kind", json={"action": "set", "kind": "slow"}
    )
    assert response.status_code == 404


def test_the_kind_split_accounts_for_every_segment_minute(client) -> None:
    """The split is checkable against the rows it claims to summarise.

    Untagged is a bucket rather than an omission, and an unanswered offer lands in it: a
    split that dropped either would not reconcile with the log, and a number nobody can
    reconcile is a number nobody can trust.
    """
    sitting = recent_sitting(client, phrase_offsets(0, 8) + phrase_offsets(40_000, 8))
    detail = client.get(f"/api/practice/sittings/{sitting['sitting_id']}").json()
    segments = detail["segments"]
    assert len(segments) == 2, "the fixture must produce two segments to be worth asserting on"

    client.patch(
        f"/api/practice/segments/{segments[0]['id']}/kind",
        json={"action": "set", "kind": "slow"},
    )
    split = client.get("/api/practice/analytics/summary?days=365").json()["kinds"]
    split_minutes = sum(entry["minutes"] for entry in split)
    segment_minutes = round(sum((s["end_ms"] - s["start_ms"]) / 60_000.0 for s in segments), 1)
    assert abs(split_minutes - segment_minutes) <= 0.2, (
        f"the kind split must reconcile with the segment minutes ({split} vs {segment_minutes})"
    )
    by_kind = {entry["kind"]: entry for entry in split}
    assert by_kind["slow"]["segments"] == 1
    assert by_kind[None]["segments"] == 1, "the uncharacterised segment has its own bucket"


def test_inference_never_overwrites_a_kind_a_person_chose(client, conn) -> None:
    """Re-running the offer pass must be safe, which is what makes it automatic.

    The segment is deliberately one an offer *would* be produced for - it is the slow
    one, and the piece has a baseline - so deleting the guard changes the outcome. A test
    on a segment no offer would ever fire for would pass with the guard removed.
    """
    slow, segment_id = a_piece_with_a_slow_offer(client, conn)
    client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "set", "kind": "memory"}
    )
    written = store.offer_practice_kinds(conn, slow["sitting_id"])
    conn.commit()
    assert written == 0, "a labelled segment is not a candidate for an offer"
    segment = segment_of(client, slow)
    assert (segment["practice_kind"], segment["practice_kind_basis"]) == ("memory", "manual")


def test_segmenting_a_second_sitting_does_not_erase_the_first_s_metrics(client) -> None:
    """A regression guard for a defect that predates Phase 20a.

    `_refresh_metrics` ended with a DELETE whose condition was "not a segment of *this*
    sitting", which is every other sitting's segment: one practice session silently
    emptied every earlier session's metrics, and with them the piece tempo trend and the
    per-segment pedal and touch figures. Found by the 20a offer path, which needs another
    sitting's `median_tempo` to have survived at all.
    """
    first = recent_sitting(client, FAST_OFFSETS)
    before = segment_of(client, first)["metrics"]
    assert before is not None and before["median_tempo"] is not None

    recent_sitting(client, FAST_OFFSETS)

    after = segment_of(client, first)["metrics"]
    assert after is not None, "a second sitting must not erase the first one's metrics"
    assert after["median_tempo"] == before["median_tempo"]
    assert after["pedal_changes"] == before["pedal_changes"]


def test_a_kind_a_person_set_survives_a_split_on_both_halves(client) -> None:
    """A boundary edit is administrative; it must not erase half of a person's answer.

    Found while planning 20c: `split_segment` copied `source` and `workout_id` to the new
    half and not `practice_kind`, so tagging a segment and then splitting it silently
    dropped the tag on one half — and the undo in 20c could never restore what was never
    carried.
    """
    sitting = recent_sitting(client, [0, 7_000, 14_000])
    segment_id = segment_of(client, sitting)["id"]
    client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "set", "kind": "memory"}
    )
    split = client.post(f"/api/practice/segments/{segment_id}/split", json={"at_ms": 7_000})
    assert split.status_code == 200, split.text
    halves = {(s["practice_kind"], s["practice_kind_basis"]) for s in split.json()}
    assert halves == {("memory", "manual")}, f"both halves keep the tag ({halves})"


def test_merging_keeps_a_kind_from_whichever_half_carries_one(client) -> None:
    sitting = recent_sitting(client, [0, 7_000, 14_000])
    segment_id = segment_of(client, sitting)["id"]
    client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "set", "kind": "memory"}
    )
    halves = client.post(
        f"/api/practice/segments/{segment_id}/split", json={"at_ms": 7_000}
    ).json()
    left, right = halves[0], halves[1]
    # Clear the earlier half, so the later one is the only carrier and the merge has to
    # reach past its "earlier wins" preference to keep the answer at all.
    client.patch(f"/api/practice/segments/{left['id']}/kind", json={"action": "set", "kind": None})
    merged = client.post(
        f"/api/practice/segments/{left['id']}/merge", json={"other_id": right["id"]}
    )
    assert merged.status_code == 200, merged.text
    segment = next(s for s in merged.json() if s["id"] == left["id"])
    assert (segment["practice_kind"], segment["practice_kind_basis"]) == ("memory", "manual")


def test_an_unanswered_offer_is_not_carried_across_a_split(client, conn) -> None:
    """An offer is a question about the whole stretch; the halves are what makes it doubtful."""
    sitting = recent_sitting(client, [0, 7_000, 14_000])
    segment_id = segment_of(client, sitting)["id"]
    conn.execute(
        "UPDATE segments SET practice_kind = 'slow', practice_kind_basis = 'offered' WHERE id = ?",
        (segment_id,),
    )
    conn.commit()
    halves = client.post(
        f"/api/practice/segments/{segment_id}/split", json={"at_ms": 7_000}
    ).json()
    assert all(s["practice_kind"] is None for s in halves), (
        f"an unanswered proposal is not inherited by a half ({halves})"
    )


def test_the_practice_status_reports_the_segment_gap(client) -> None:
    """The client cuts recorded audio on this rule, so it must not be a second copy of it."""
    from app.config import settings

    body = client.get("/api/practice/status").json()
    assert body["segment_gap_s"] == settings.segment_gap_s


def test_a_paused_piece_does_not_nag(client, conn) -> None:
    """`paused` is a status the player chose; the neglected list must honour it.

    Found while planning 20d: the query filtered `!= 'completed'`, so a piece deliberately
    set aside was reported as neglected for ever — the opposite of what the status is for.
    """
    seed_piece(conn, "Active Etude")
    conn.execute("INSERT INTO pieces (title, status) VALUES ('Paused Etude', 'paused')")
    conn.commit()

    titles = [
        row["title"]
        for row in client.get("/api/practice/analytics/summary?days=30").json()["neglected"]
    ]
    assert "Active Etude" in titles
    assert "Paused Etude" not in titles, f"a paused piece must not be reported ({titles})"


def test_the_piece_practice_read_agrees_with_the_dashboard(client, conn) -> None:
    """Two reads of one number must be one number.

    The library sorts by this, and the Log draws it; if they disagree, one of them is lying
    about how much a piece has cost.
    """
    sitting = recent_sitting(client, FAST_OFFSETS)
    piece_id = seed_piece(conn, "Sorted Etude")
    client.patch(
        f"/api/practice/segments/{segment_of(client, sitting)['id']}",
        json={"piece_id": piece_id},
    )

    listed = client.get("/api/practice/pieces?days=365").json()
    from_dashboard = client.get("/api/practice/analytics/summary?days=365").json()["by_piece"]

    assert listed == from_dashboard, "the two reads agree, field for field"
    assert listed and listed[0]["title"] == "Sorted Etude"


def _record_on(client, day: str, offsets: list[int]) -> None:
    """A closed sitting filed on one calendar day."""
    import time

    stamp = f"{day}T12:00:00+00:00"
    base = int(datetime.fromisoformat(stamp).timestamp() * 1000)
    body = client.post(
        "/api/practice/events",
        json={
            "tz_offset_minutes": 0,
            "events": [
                {
                    "epoch_ms": base + offset,
                    "pitch": 60 + index,
                    "velocity": 70,
                    "duration_ms": 300,
                    "channel": 0,
                }
                for index, offset in enumerate(offsets)
            ],
        },
    ).json()
    assert body["sitting_id"] is not None
    client.post("/api/practice/sittings/close")


def _days_ago(count: int) -> str:
    from datetime import date, timedelta

    return (date.today() - timedelta(days=count)).isoformat()


def test_an_unbroken_week_is_unchanged_by_the_grace_rule(client) -> None:
    """The rule must not move the number for anybody who never missed a day."""
    for offset in (2, 1, 0):
        _record_on(client, _days_ago(offset), [0, 500])
    body = client.get("/api/practice/analytics/summary?days=30").json()
    assert body["streak_days"] == 3
    assert body["streak_grace_used"] == 0


def test_one_missed_day_keeps_the_streak_and_is_reported(client) -> None:
    for offset in (3, 1, 0):
        _record_on(client, _days_ago(offset), [0, 500])
    body = client.get("/api/practice/analytics/summary?days=30").json()
    assert body["streak_days"] == 4, "the run covers four calendar days"
    assert body["streak_grace_used"] == 1, "and one of them was a rest day"


def test_two_missed_days_in_a_row_end_the_run(client) -> None:
    """One rest day is forgiven; the second ends the run rather than extending it.

    The run is "today plus one forgiven rest day", not "everything back to the practice four
    days ago": the second consecutive miss is where the run stops, which is the whole point
    of allowing only one rest day per rolling week.
    """
    for offset in (4, 0):
        _record_on(client, _days_ago(offset), [0, 500])
    body = client.get("/api/practice/analytics/summary?days=30").json()
    assert body["streak_days"] == 2, "today plus the one forgiven rest day"
    assert body["streak_grace_used"] == 1
    assert body["streak_days"] < 4, "and the practice before the gap is not in this run"


def test_a_streak_never_opens_on_a_rest_day(client) -> None:
    """A week away must not report a one-day streak on return."""
    _record_on(client, _days_ago(10), [0, 500])
    body = client.get("/api/practice/analytics/summary?days=30").json()
    assert body["streak_days"] == 0
    assert body["streak_grace_used"] == 0


def test_today_not_yet_played_does_not_count_against_you(client) -> None:
    for offset in (2, 1):
        _record_on(client, _days_ago(offset), [0, 500])
    body = client.get("/api/practice/analytics/summary?days=30").json()
    assert body["streak_days"] == 2
    assert body["streak_grace_used"] == 0, "an empty today is not a rest day, it is not over"


# --------------------------------------------------------------------------
# Passages: the derived row above the attempts (Phase 22c)
# --------------------------------------------------------------------------


def _passage_sitting(client) -> dict:
    """A sitting of three attempts at the *same* material, so they form one passage.

    Written out rather than reusing ``recent_sitting``: that helper numbers pitches by
    position, so a second phrase would carry different notes and be a different passage, and
    its offsets would run past *now*, which makes ``close`` refuse with "still playing" — the
    sitting would never be segmented at all.
    """
    import time

    base = int(time.time() * 1000) - 60_000
    phrase = [60, 62, 64, 65, 67, 69, 71, 72]
    events = [
        {
            "epoch_ms": base + start + step * 800,
            "pitch": pitch,
            "velocity": 70,
            "duration_ms": 300,
            "channel": 0,
        }
        for start in (0, 20_000, 40_000)
        for step, pitch in enumerate(phrase)
    ]
    body = client.post(
        "/api/practice/events",
        json={"tz_offset_minutes": server_offset_minutes(), "events": events},
    ).json()
    closed = client.post("/api/practice/sittings/close")
    assert closed.status_code == 200, closed.text

    detail = client.get(f"/api/practice/sittings/{body['sitting_id']}").json()
    assert len(detail["segments"]) == 3, "three attempts, each over the minimum size"
    assert len(detail["passages"]) == 1, "the same material three times is one passage"
    assert detail["passages"][0]["attempts"] == 3
    return detail


def test_a_passage_confirmation_writes_every_member_attempt(client) -> None:
    """Acceptance 5: the row is a view, the label is durable, and re-deriving is stable.

    Labelling a passage is the per-segment route sent once per member — there is no group to
    keep in step and no new endpoint — so this asserts the outcome that matters: every member
    attempt carries the piece, and the same labels produce the same groups.
    """
    detail = _passage_sitting(client)
    sitting_id = detail["id"]
    attempt_ids = detail["passages"][0]["attempt_ids"]
    assert set(attempt_ids) == {segment["id"] for segment in detail["segments"]}

    piece_id = client.post("/api/repertoire/pieces", json={"title": "Etude"}).json()["id"]
    for segment_id in attempt_ids:
        response = client.patch(
            f"/api/practice/segments/{segment_id}", json={"piece_id": piece_id}
        )
        assert response.status_code == 200, response.text

    after = client.get(f"/api/practice/sittings/{sitting_id}").json()
    assert all(segment["piece_id"] == piece_id for segment in after["segments"]), (
        "every member attempt carries the piece"
    )
    assert [passage["attempt_ids"] for passage in after["passages"]] == [attempt_ids], (
        "the same labels produce the same groups"
    )
    assert after["passages"][0]["piece_id"] == piece_id
    assert after["passages"][0]["piece_title"] == "Etude"
    assert after["passages"][0]["attempts"] == 3
    assert after["passages"][0]["session"] == 0, "one piece, one piece-session"

    # Re-reading is what re-derives, so asking twice must not move anything.
    again = client.get(f"/api/practice/sittings/{sitting_id}").json()
    assert again["passages"] == after["passages"]


def test_merging_two_attempts_regroups_them_rather_than_storing_anything(client) -> None:
    """The derived layer follows an edit instead of being kept in step with it."""
    detail = _passage_sitting(client)
    sitting_id = detail["id"]
    left, right = detail["segments"][0]["id"], detail["segments"][1]["id"]
    response = client.post(f"/api/practice/segments/{left}/merge", json={"other_id": right})
    assert response.status_code == 200, response.text

    after = client.get(f"/api/practice/sittings/{sitting_id}").json()
    assert len(after["segments"]) == 2, "two attempts left"
    assert sum(passage["attempts"] for passage in after["passages"]) == 2
    assert all(
        segment_id in sum((p["attempt_ids"] for p in after["passages"]), [])
        for segment_id in {segment["id"] for segment in after["segments"]}
    ), "every attempt still belongs to a passage"


def test_a_sitting_detail_without_passages_still_validates() -> None:
    """Acceptance 6: the field is additive with a default, so old readers still hold."""
    from app.practice.models import SittingDetail

    detail = SittingDetail(
        id=1,
        started_at="2026-01-01 00:00:00",
        ended_at="2026-01-01 00:01:00",
        local_date="2026-01-01",
        source="web_midi",
        note_count=0,
        duration_s=60.0,
        closed=True,
        segments=[],
    )
    assert detail.passages == []


def test_the_detail_payload_carries_the_review_marks(client) -> None:
    # Additive, so every reader written before Phase 23 still holds; asserted here because the
    # field is the whole user-visible point of the mark stream.
    payload = batch_payload([0, 500, 1_000])
    payload["marks"] = [{"epoch_ms": BASE_MS + 800, "channel": 0}]
    sitting_id = client.post("/api/practice/events", json=payload).json()["sitting_id"]

    body = client.get(f"/api/practice/sittings/{sitting_id}").json()
    assert body["review_marks_ms"] == [800]


def test_a_mark_pressed_between_phrases_is_a_batch_of_its_own(client) -> None:
    # The ordinary case rather than an edge one: the flag is pressed between phrases, so the
    # flush carrying it usually has nothing else in it. Refusing it leaves the client retrying
    # the same batch forever, exactly as a pedal-only flush would.
    record([0, 500, 1_000])

    response = client.post(
        "/api/practice/events",
        json={
            "tz_offset_minutes": 0,
            "source": "web_midi",
            "events": [],
            "marks": [{"epoch_ms": BASE_MS + 2_000, "channel": 0}],
        },
    )

    assert response.status_code == 200
    assert response.json()["marks_accepted"] == 1


def test_a_genuinely_empty_batch_is_still_refused(client) -> None:
    response = client.post(
        "/api/practice/events",
        json={"tz_offset_minutes": 0, "source": "web_midi", "events": [], "marks": []},
    )

    assert response.status_code == 422
