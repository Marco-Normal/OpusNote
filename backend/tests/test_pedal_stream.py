"""The pedal stream's codec and its chunk invariant.

The stream replaced a row per move because a continuous controller writes ~15 values a
second and 51 bytes of row and index for each. What is asserted here is what made that
safe: the bytes round-trip, a chunk never splits one millisecond, and writing the same
batch twice stores it once — the `UNIQUE(sitting_id, onset_ms, value)` guarantee that moved
out of the schema and into `insert_moves`.
"""

from __future__ import annotations

import pytest

from app import db
from app.practice import pedal_stream


def _sitting_id(started_ms: int = 1_700_000_000_000) -> int:
    with db.transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO sittings"
            " (started_ms, ended_ms, started_at, ended_at, local_date, source)"
            " VALUES (?1, ?2, '2023-11-14 22:13:20', '2023-11-14 22:13:20',"
            " '2023-11-14', 'web_midi')",
            (started_ms, started_ms + 60_000),
        )
        return int(cursor.lastrowid)


def _store(sitting_id: int, moves: list[pedal_stream.Move]) -> int:
    with db.transaction() as conn:
        return pedal_stream.insert_moves(conn, sitting_id, moves)


def _read(sitting_id: int) -> list[pedal_stream.Move]:
    conn = db.connect()
    try:
        return pedal_stream.moves(conn, sitting_id)
    finally:
        conn.close()


# --- the codec -------------------------------------------------------------


def test_a_move_round_trips_with_and_without_a_channel() -> None:
    moves: list[pedal_stream.Move] = [(0, 64, 0), (12_345, 127, 15), (20_000, 0, None)]
    assert pedal_stream.decode(pedal_stream.encode(moves)) == moves
    assert pedal_stream.encode(moves) != b"", "a record is not the empty string"


def test_a_record_is_six_bytes() -> None:
    """The size is the whole point: 51 bytes a row and index became 6 bytes a move."""
    assert pedal_stream.RECORD_BYTES == 6
    assert len(pedal_stream.encode([(1, 2, 3)])) == 6


def test_a_chunk_never_splits_one_onset() -> None:
    """Every move sharing a millisecond must stay together.

    The merge finds duplicates by looking only at chunks whose time range the batch touches,
    so a duplicate at an onset split across two chunks could sit in one it is not looking at.
    """
    moves: list[pedal_stream.Move] = [(5, 1, 0), (5, 2, 0), (5, 3, 0), (9, 0, 0)]
    split = pedal_stream.chunks(moves, limit=2)
    assert [list(chunk) for chunk in split] == [[(5, 1, 0), (5, 2, 0), (5, 3, 0)], [(9, 0, 0)]]


def test_a_truncated_chunk_is_named_rather_than_read() -> None:
    with pytest.raises(pedal_stream.CorruptPedalStream):
        pedal_stream.decode(b"\x01\x02\x03")


# --- the store -------------------------------------------------------------


def test_a_sitting_with_no_moves_reads_as_empty(fresh_db) -> None:
    assert _read(_sitting_id()) == []


def test_appending_after_the_tail_stays_one_chunk(fresh_db) -> None:
    sitting_id = _sitting_id()
    assert _store(sitting_id, [(0, 127, 0)]) == 1
    assert _store(sitting_id, [(100, 64, 0), (200, 0, 0)]) == 2
    assert _read(sitting_id) == [(0, 127, 0), (100, 64, 0), (200, 0, 0)]

    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT n FROM pedal_stream WHERE sitting_id = ?", (sitting_id,)
        ).fetchall()
    finally:
        conn.close()
    assert [row["n"] for row in rows] == [3], "one append, one chunk"


def test_a_retried_batch_stores_nothing_the_second_time(fresh_db) -> None:
    """The old table's unique index, restated where the stream can enforce it."""
    sitting_id = _sitting_id()
    batch: list[pedal_stream.Move] = [(0, 127, 0), (500, 64, 0), (900, 0, 0)]
    assert _store(sitting_id, batch) == 3
    assert _store(sitting_id, batch) == 0, "a retried batch is not a second performance"
    assert _read(sitting_id) == batch


def test_a_batch_that_starts_on_the_tails_last_millisecond_is_merged(fresh_db) -> None:
    """The boundary case the fast path deliberately refuses (`>` rather than `>=`).

    A batch beginning on the last stored onset may repeat a move that is already there, so it
    has to take the merge path; appending it blindly would store the duplicate.
    """
    sitting_id = _sitting_id()
    _store(sitting_id, [(100, 127, 0), (100, 64, 0)])
    assert _store(sitting_id, [(100, 64, 0), (300, 0, 0)]) == 1
    # The retried move keeps the position it already had: within one millisecond the stream
    # preserves arrival order, which is what the row-per-move table's rowids did. A value
    # that arrives again does not jump to the front of the millisecond.
    assert _read(sitting_id) == [(100, 127, 0), (100, 64, 0), (300, 0, 0)]


def test_a_batch_that_lands_in_the_middle_keeps_the_stream_ordered(fresh_db) -> None:
    """A retried or out-of-order request can deliver a span before the tail."""
    sitting_id = _sitting_id()
    _store(sitting_id, [(1_000, 127, 0), (2_000, 0, 0)])
    assert _store(sitting_id, [(500, 64, 0), (1_500, 32, 0)]) == 2
    assert _read(sitting_id) == [
        (500, 64, 0),
        (1_000, 127, 0),
        (1_500, 32, 0),
        (2_000, 0, 0),
    ]


def test_a_stream_longer_than_a_chunk_stays_ordered(fresh_db) -> None:
    sitting_id = _sitting_id()
    moves: list[pedal_stream.Move] = [
        (index * 10, index % 128, 0) for index in range(pedal_stream.CHUNK_RECORDS * 2 + 7)
    ]
    assert _store(sitting_id, moves) == len(moves)
    assert _read(sitting_id) == moves

    conn = db.connect()
    try:
        chunks = conn.execute(
            "SELECT n FROM pedal_stream WHERE sitting_id = ? ORDER BY first_ms",
            (sitting_id,),
        ).fetchall()
    finally:
        conn.close()
    assert len(chunks) >= 3, "it really did cross a chunk boundary"
    assert all(row["n"] <= pedal_stream.CHUNK_RECORDS for row in chunks)


def test_a_retry_spanning_a_chunk_boundary_is_not_doubled(fresh_db) -> None:
    """The reason the overlap search is by time range and not by the tail chunk alone."""
    sitting_id = _sitting_id()
    first: list[pedal_stream.Move] = [
        (index * 10, index % 128, 0) for index in range(pedal_stream.CHUNK_RECORDS + 1)
    ]
    _store(sitting_id, first)
    assert _store(sitting_id, first) == 0
    assert _read(sitting_id) == first
