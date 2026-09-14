"""Sittings, segments and their mutations.

Ported from the standalone logger's ``test_segments.py``, with the additions this
app brings: metrics, real piece foreign keys, and sight-reading tagging.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.db import connect
from app.practice import store
from app.practice.models import EventBatch, WireNote, WirePedal

# 2023-11-15 01:30:00 UTC: safely in the past, so sittings read as "closed".
BASE_MS = 1_700_011_800_000
#: Long enough after BASE_MS that any sitting is closed.
LATER_MS = BASE_MS + 10_000_000


def batch(offsets: list[int], *, source: str = "web_midi", tz: int = 0) -> EventBatch:
    return EventBatch(
        tz_offset_minutes=tz,
        source=source,
        events=[
            WireNote(
                epoch_ms=BASE_MS + offset,
                pitch=60 + index,
                velocity=70,
                duration_ms=300,
                channel=0,
            )
            for index, offset in enumerate(offsets)
        ],
    )


def _prepared() -> int:
    return store.ingest(batch([0, 500, 1_000])).sitting_id


# --- ingest ---------------------------------------------------------------


def test_one_batch_creates_one_sitting(fresh_db) -> None:
    result = store.ingest(batch([0, 500, 1_000]))
    assert (result.accepted, result.duplicates) == (3, 0)
    sittings = store.list_sittings()
    assert len(sittings) == 1
    assert sittings[0].note_count == 3
    assert sittings[0].duration_s == 1.3


def test_reposting_a_batch_adds_nothing(fresh_db) -> None:
    first = store.ingest(batch([0, 500]))
    second = store.ingest(batch([0, 500]))
    assert (first.accepted, first.duplicates) == (2, 0)
    assert (second.accepted, second.duplicates) == (0, 2)
    assert second.sitting_id == first.sitting_id
    assert len(store.list_sittings()) == 1


def test_a_long_silence_splits_sittings(fresh_db) -> None:
    store.ingest(batch([0, 500]))
    store.ingest(batch([600_000, 600_500]))
    assert len(store.list_sittings()) == 2


def test_a_batch_spanning_the_gap_creates_two_sittings(fresh_db) -> None:
    store.ingest(batch([0, 500, 900_000]))
    assert len(store.list_sittings()) == 2


def test_replaying_a_batch_spanning_two_sittings_is_idempotent(fresh_db) -> None:
    """Regression: a retried older batch must not be appended to the newest
    sitting. Bounding only the upper gap did exactly that, storing the earlier
    notes with a negative onset and inventing a boundary."""
    payload = batch([0, 500, 900_000, 900_500])
    first = store.ingest(payload)
    second = store.ingest(payload)
    assert (first.accepted, first.duplicates) == (4, 0)
    assert (second.accepted, second.duplicates) == (0, 4)
    assert sorted(row.note_count for row in store.list_sittings()) == [2, 2]


def test_no_event_is_stored_before_its_sitting_start(fresh_db) -> None:
    payload = batch([0, 500, 900_000, 900_500])
    store.ingest(payload)
    store.ingest(payload)
    conn = connect()
    try:
        negative = conn.execute(
            "SELECT COUNT(*) FROM note_events WHERE onset_ms < 0"
        ).fetchone()[0]
    finally:
        conn.close()
    assert negative == 0


def test_timezone_offset_moves_the_local_date(fresh_db) -> None:
    # 2023-11-15 01:30:00 UTC is still 2023-11-14 in UTC-3. An instant that lands
    # on the same local day in both offsets would prove only that the column is
    # populated, not that the offset is applied.
    store.ingest(
        EventBatch(
            tz_offset_minutes=-180,
            events=[
                WireNote(
                    epoch_ms=BASE_MS, pitch=60, velocity=70, duration_ms=100, channel=0
                )
            ],
        )
    )
    assert store.list_sittings()[0].local_date == "2023-11-14"


def test_an_empty_batch_is_rejected(fresh_db) -> None:
    with pytest.raises(store.InvalidRequest):
        store.ingest(EventBatch(tz_offset_minutes=0, events=[]))


# --- the sustain pedal ----------------------------------------------------


def pedal_batch(offsets: list[int], *, value: int = 127, events: list[int] | None = None):
    """A batch of pedal moves, optionally with notes of its own."""
    return EventBatch(
        tz_offset_minutes=0,
        events=[
            WireNote(
                epoch_ms=BASE_MS + offset,
                pitch=60 + index,
                velocity=70,
                duration_ms=300,
                channel=0,
            )
            for index, offset in enumerate(events or [])
        ],
        pedals=[
            WirePedal(epoch_ms=BASE_MS + offset, value=value, channel=0) for offset in offsets
        ],
    )


def test_a_pedal_move_is_stored_against_its_sitting(fresh_db) -> None:
    sitting_id = _prepared()
    result = store.ingest(pedal_batch([400], value=127))

    assert result.pedals_accepted == 1
    assert result.pedals_ignored == 0
    assert result.sitting_id == sitting_id, "the pedal joins the sitting the notes opened"
    stored = store.sitting_notes(sitting_id)
    assert [(item.onset_ms, item.value) for item in stored.pedals] == [(400, 127)]


def test_notes_and_pedals_travel_in_one_batch(fresh_db) -> None:
    """The first batch of a sitting can carry both, and the pedal's onset has to
    be measured from the sitting the notes just created."""
    result = store.ingest(pedal_batch([200], events=[0, 500]))
    assert (result.accepted, result.pedals_accepted) == (2, 1)

    stored = store.sitting_notes(result.sitting_id)
    assert [item.onset_ms for item in stored.notes] == [0, 500]
    assert [item.onset_ms for item in stored.pedals] == [200]


def test_a_pedal_with_no_sitting_around_it_is_dropped(fresh_db) -> None:
    """Not practice, and not allowed to invent a sitting: a foot resting on the
    pedal while the player is away must not open one."""
    store.ingest(batch([0, 500]))
    before = len(store.list_sittings())

    result = store.ingest(pedal_batch([60 * 60 * 1000], value=127))

    assert result.pedals_ignored == 1
    assert result.pedals_accepted == 0
    assert result.sitting_id is None, "there is nothing to report a sitting for"
    assert len(store.list_sittings()) == before


def test_a_pedal_does_not_extend_a_sitting(fresh_db) -> None:
    """The sitting's end is the last *note*. Letting a pedal move push it out
    would keep a sitting open for as long as a foot rests on the pedal."""
    sitting_id = _prepared()
    before = next(row for row in store.list_sittings() if row.id == sitting_id).duration_s

    store.ingest(pedal_batch([60_000], value=127))

    after = next(row for row in store.list_sittings() if row.id == sitting_id).duration_s
    assert after == before


def test_a_retried_pedal_batch_does_not_double_the_moves(fresh_db) -> None:
    sitting_id = _prepared()
    assert store.ingest(pedal_batch([400], value=127)).pedals_accepted == 1
    assert store.ingest(pedal_batch([400], value=127)).pedals_accepted == 0

    assert len(store.sitting_notes(sitting_id).pedals) == 1


def test_both_halves_of_a_pedal_press_are_kept(fresh_db) -> None:
    """Down and up are two rows, not one interval: a release that never arrives
    must not leave a note sounding past the end of the sitting."""
    sitting_id = _prepared()
    store.ingest(pedal_batch([400], value=127))
    store.ingest(pedal_batch([1_200], value=0))

    stored = store.sitting_notes(sitting_id)
    assert [(item.onset_ms, item.value) for item in stored.pedals] == [(400, 127), (1_200, 0)]


def test_a_sitting_without_pedalling_reports_none(fresh_db) -> None:
    """The field is additive on the wire, so an old client must read as "no
    pedalling" rather than as a missing key."""
    sitting_id = _prepared()
    assert store.sitting_notes(sitting_id).pedals == []


# --- segmentation ---------------------------------------------------------


def test_a_closed_sitting_is_segmented_once(fresh_db) -> None:
    sitting_id = _prepared()
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    assert len(segments) == 1
    assert segments[0].start_ms == 0
    assert segments[0].end_ms == 1_300
    assert segments[0].note_count == 3


def test_segments_carry_their_metrics(fresh_db) -> None:
    sitting_id = _prepared()
    metrics = store.ensure_segments(sitting_id, now_ms=LATER_MS)[0].metrics
    assert metrics is not None
    assert metrics.note_count == 3
    assert metrics.duration_s == 1.3
    assert metrics.mean_velocity == 70.0
    # Three notes 500 ms apart are three attacks at 120 BPM.
    assert metrics.median_tempo == 120.0


def test_an_open_sitting_is_not_segmented(fresh_db) -> None:
    """Materialising boundaries mid-performance would freeze a partial view."""
    store.ingest(batch([0]))
    assert store.ensure_segments(1, now_ms=BASE_MS + 1_000) == []
    detail = store.sitting_detail(1, now_ms=BASE_MS + 1_000)
    assert detail.closed is False
    assert detail.segments == []


def test_two_phrases_become_two_segments(fresh_db) -> None:
    sitting_id = store.ingest(batch([0, 500, 30_000, 30_500])).sitting_id
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    assert len(segments) == 2
    assert [segment.note_count for segment in segments] == [2, 2]


def test_existing_segments_are_never_recomputed(fresh_db) -> None:
    sitting_id = _prepared()
    first = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    conn = connect()
    try:
        conn.execute("BEGIN")
        conn.execute("UPDATE segments SET end_ms = 999 WHERE id = ?", (first[0].id,))
        conn.execute("COMMIT")
    finally:
        conn.close()
    again = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    assert again[0].end_ms == 999


def test_missing_sitting_is_not_found(fresh_db) -> None:
    with pytest.raises(store.NotFound):
        store.ensure_segments(999, now_ms=LATER_MS)


def test_missing_sitting_detail_is_not_found(fresh_db) -> None:
    with pytest.raises(store.NotFound):
        store.sitting_detail(999, now_ms=LATER_MS)


def test_zero_duration_note_stays_in_its_own_segment(fresh_db) -> None:
    result = store.ingest(
        EventBatch(
            tz_offset_minutes=0,
            events=[
                WireNote(
                    epoch_ms=BASE_MS, pitch=60, velocity=70, duration_ms=0, channel=0
                )
            ],
        )
    )
    segments = store.ensure_segments(result.sitting_id, now_ms=LATER_MS)
    assert segments[0].note_count == 1


# --- labelling ------------------------------------------------------------


def _piece(client, title: str, **extra) -> int:
    body = {"title": title, "status": "active", **extra}
    return client.post("/api/repertoire/pieces", json=body).json()["id"]


def test_assigning_a_piece_records_a_manual_label(fresh_db, client) -> None:
    sitting_id = _prepared()
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    piece_id = _piece(client, "Ballade No. 1", key="g")

    updated = store.assign_piece(segments[0].id, piece_id)
    assert updated[0].piece_id == piece_id
    assert updated[0].piece_title == "Ballade No. 1"
    assert updated[0].identified_by == "manual"
    assert updated[0].confidence == 1.0
    assert updated[0].source == "repertoire"


def test_assigning_an_unknown_piece_is_rejected(fresh_db) -> None:
    sitting_id = _prepared()
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    with pytest.raises(store.InvalidRequest):
        store.assign_piece(segments[0].id, 9999)


def test_clearing_a_label_removes_it(fresh_db, client) -> None:
    sitting_id = _prepared()
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    piece_id = _piece(client, "Ballade")
    store.assign_piece(segments[0].id, piece_id)
    cleared = store.assign_piece(segments[0].id, None)
    assert cleared[0].piece_id is None
    assert cleared[0].identified_by is None
    assert cleared[0].source is None


def test_deleting_a_piece_orphans_the_segment_not_the_history(fresh_db, client) -> None:
    sitting_id = _prepared()
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    piece_id = _piece(client, "Ballade")
    store.assign_piece(segments[0].id, piece_id)

    client.delete(f"/api/repertoire/pieces/{piece_id}")

    detail = store.sitting_detail(sitting_id, now_ms=LATER_MS)
    assert detail.segments[0].piece_id is None
    assert detail.segments[0].note_count == 3
    assert detail.note_count == 3


# --- split and merge ------------------------------------------------------


def test_split_creates_a_second_segment_from_the_same_notes(fresh_db) -> None:
    sitting_id = _prepared()
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)

    after = store.split_segment(segments[0].id, 700)
    assert len(after) == 2
    assert [segment.note_count for segment in after] == [2, 1]
    assert after[0].start_ms == 0
    assert after[0].end_ms == 800
    assert after[1].start_ms == 1_000
    assert sum(segment.note_count for segment in after) == 3


def test_split_refreshes_metrics_for_both_halves(fresh_db) -> None:
    sitting_id = _prepared()
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    after = store.split_segment(segments[0].id, 700)
    # Two metrics rows now exist, one per segment, and the total note count is
    # conserved — the check that a merge or split has not silently dropped notes.
    assert [segment.metrics.note_count for segment in after] == [2, 1]
    # Two notes 500 ms apart are 120 BPM; a single note has no tempo at all.
    assert after[0].metrics.median_tempo == 120.0
    assert after[1].metrics.median_tempo is None


def test_split_outside_the_segment_is_rejected(fresh_db) -> None:
    sitting_id = _prepared()
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    for bad in (0, 1_300, 5_000):
        with pytest.raises(store.InvalidRequest):
            store.split_segment(segments[0].id, bad)


def test_split_that_would_empty_a_side_is_rejected(fresh_db) -> None:
    sitting_id = _prepared()
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    with pytest.raises(store.InvalidRequest):
        store.split_segment(segments[0].id, 1_200)


def test_split_carries_the_sight_reading_label_to_both_halves(fresh_db) -> None:
    """A boundary is a statement about phrasing, not about what was practised."""
    sitting_id = store.ingest(batch([0, 500, 1_000], source="sight_reading")).sitting_id
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    assert segments[0].source == "sight_reading"
    after = store.split_segment(segments[0].id, 700)
    assert [segment.source for segment in after] == ["sight_reading", "sight_reading"]


def test_merge_rejoins_a_split_and_keeps_the_label(fresh_db, client) -> None:
    sitting_id = _prepared()
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    piece_id = _piece(client, "Ballade")
    store.assign_piece(segments[0].id, piece_id)

    parts = store.split_segment(segments[0].id, 700)
    left, right = parts[0], parts[1]
    merged = store.merge_segments(left.id, right.id)
    assert len(merged) == 1
    assert merged[0].start_ms == 0
    assert merged[0].end_ms == 1_300
    assert merged[0].piece_id == piece_id
    assert merged[0].note_count == 3


def test_merging_non_adjacent_segments_is_rejected(fresh_db) -> None:
    sitting_id = store.ingest(batch([0, 500, 30_000, 30_500, 60_000])).sitting_id
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    assert len(segments) == 3
    with pytest.raises(store.InvalidRequest):
        store.merge_segments(segments[0].id, segments[2].id)


def test_merge_rejects_itself_and_missing_segments(fresh_db) -> None:
    sitting_id = _prepared()
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    with pytest.raises(store.InvalidRequest):
        store.merge_segments(segments[0].id, segments[0].id)
    with pytest.raises(store.NotFound):
        store.merge_segments(segments[0].id, 9999)


def test_resegment_refuses_to_discard_labels_without_confirmation(fresh_db, client) -> None:
    sitting_id = _prepared()
    segments = store.ensure_segments(sitting_id, now_ms=LATER_MS)
    store.assign_piece(segments[0].id, _piece(client, "Ballade"))

    with pytest.raises(store.ConfirmationRequired):
        store.resegment_sitting(sitting_id, now_ms=LATER_MS)

    refreshed = store.resegment_sitting(sitting_id, confirm=True, now_ms=LATER_MS)
    assert len(refreshed) == 1
    assert refreshed[0].piece_id is None


def test_resegment_absorbs_notes_that_arrived_after_segmentation(fresh_db) -> None:
    """The stale-boundary case that makes the endpoint necessary."""
    sitting_id = _prepared()
    store.ensure_segments(sitting_id, now_ms=LATER_MS)
    store.ingest(batch([40_000]))  # a late note, after the 20 s segment gap

    detail = store.sitting_detail(sitting_id, now_ms=LATER_MS)
    covered = sum(segment.note_count for segment in detail.segments)
    assert covered == 3
    assert detail.note_count == 4

    refreshed = store.resegment_sitting(sitting_id, confirm=True, now_ms=LATER_MS)
    assert len(refreshed) == 2
    assert sum(segment.note_count for segment in refreshed) == 4


def test_resegment_missing_sitting_is_not_found(fresh_db) -> None:
    with pytest.raises(store.NotFound):
        store.resegment_sitting(999, confirm=True, now_ms=LATER_MS)


# --- configuration --------------------------------------------------------


def test_the_ported_gaps_are_still_the_ported_defaults() -> None:
    """The port must not quietly retune the thresholds the behaviour rests on.

    `segment_gap_s` is the deliberate exception: 20 s was measured against a real
    session and missed every piece change in it (they sat on 9.5 s and 11.7 s gaps),
    so it is 8 s. It is listed here explicitly rather than dropped from the test, so
    that the difference reads as a decision instead of as drift.
    """
    assert settings.sitting_gap_s == 300
    assert settings.restart_gap_ms == 3000
    assert settings.attack_window_ms == 50
    assert settings.segment_gap_s == 8, "deliberately retuned — see config.py"


# --- closing a sitting because the piano went away -------------------------


def test_a_sitting_can_be_closed_without_waiting_out_the_silence(fresh_db) -> None:
    """Switching the piano off is a far sooner answer to "are they done?" than five
    minutes of silence, and it is what makes the sitting appear on the dashboard."""
    sitting_id = store.ingest(batch([0, 500, 1_000])).sitting_id
    # Far too soon for the silence to have closed it: the gap is five minutes.
    assert store.ensure_segments(sitting_id, now_ms=BASE_MS + 10_000) == []

    # Ten seconds of quiet, which is past `close_quiet_ms` and nowhere near the
    # five-minute silence the sitting would otherwise wait for.
    assert store.close_open_sitting(now_ms=BASE_MS + 10_000) == sitting_id

    segments = store.ensure_segments(sitting_id, now_ms=BASE_MS + 10_000)
    assert len(segments) == 1, "closed means closed: the boundaries exist at once"


def test_closing_takes_no_more_notes(fresh_db) -> None:
    """A note after the piano comes back is a *new* sitting, not a continuation of
    the one the player ended by switching off."""
    first = store.ingest(batch([0, 500])).sitting_id
    assert store.close_open_sitting(now_ms=BASE_MS + 10_000) == first

    second = store.ingest(batch([2_000, 2_500])).sitting_id
    assert second != first
    assert len(store.list_sittings()) == 2


def test_closing_while_notes_are_still_arriving_is_refused(fresh_db) -> None:
    """A device blip mid-session — a USB hiccup, a statechange race — must not cut a
    sitting in half. `close_quiet_ms` is the guard, and it is the reason the client
    can report the event without judging it."""
    import time

    base = int(time.time() * 1000)
    events = [
        WireNote(epoch_ms=base - 500, pitch=60, velocity=70, duration_ms=200, channel=0),
        WireNote(epoch_ms=base - 200, pitch=62, velocity=70, duration_ms=200, channel=0),
    ]
    sitting_id = store.ingest(EventBatch(tz_offset_minutes=0, events=events)).sitting_id

    assert store.close_open_sitting(now_ms=base) is None, "still playing"
    assert store.close_open_sitting(now_ms=base, quiet_ms=0) == sitting_id, (
        "and the guard can be dropped when the caller knows better"
    )


def test_nothing_to_close_is_not_an_error(fresh_db) -> None:
    assert store.close_open_sitting(now_ms=BASE_MS) is None

    store.ingest(batch([0, 500]))
    assert store.close_open_sitting(now_ms=BASE_MS + 10_000) is not None, (
        "the first call closes it"
    )
    assert store.close_open_sitting(now_ms=BASE_MS + 10_000) is None, (
        "and the second finds nothing open"
    )


def test_a_long_forgotten_sitting_is_not_closed_by_a_stray_device_event(fresh_db) -> None:
    """The piano being plugged back in days later must not "close" a sitting that the
    silence closed long ago — there is nothing to close by then."""
    store.ingest(batch([0, 500]))
    assert store.close_open_sitting(now_ms=BASE_MS + 10_000) is not None

    # Days later the device reappears. The sitting is long closed, and the lookback
    # is what stops a stray event from reaching back and touching it.
    assert store.close_open_sitting(now_ms=BASE_MS + 3 * 24 * 60 * 60 * 1000) is None
