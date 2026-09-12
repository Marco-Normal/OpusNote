"""Sittings, segments and their mutations.

Ported from the standalone logger's ``test_segments.py``, with the additions this
app brings: metrics, real piece foreign keys, and sight-reading tagging.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.db import connect
from app.practice import store
from app.practice.models import EventBatch, WireNote

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
    """The port must not quietly retune the thresholds the behaviour rests on."""
    assert settings.sitting_gap_s == 300
    assert settings.segment_gap_s == 20
    assert settings.restart_gap_ms == 3000
    assert settings.attack_window_ms == 50
