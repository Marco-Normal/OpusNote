"""The sustain pedal as a chunked binary stream, not one row per move.

CC64 is a *continuous* controller, and the log records every value it is sent — 1,151,770
moves across the owner's 33 pedalled sittings, 15.5 a second while playing. Stored as rows
that was 19.7 MB of table plus 39.4 MB of index: **59.1 MB, two thirds of the whole 89 MB
file**, and 51 bytes on disk for a fact whose payload is a four-byte moment and a one-byte
position. Every read that wanted the stream paid for both indexes; every write paid for
them too.

The same stream fits in 6 bytes a move when nothing is asking SQL to *index* it: onset as a
little-endian u32, value and channel as one byte each. `PERFORMANCE.md` §1.13 records the
measurement — the whole press history from a backup's JSON (two-value records, no channel)
came to 2,404,352 bytes, 2.05 bytes a move, and a fixed-width encoding decodes 3.5× faster
than the rows it replaces because there is no per-row object to build.

**Chunked on purpose.** One blob per sitting was the obvious shape and the wrong one: a
72-minute session would flush a growing blob 15 times a second, rewriting about 149 MB for
2.4 MB of data. Chunks of `CHUNK_RECORDS` moves bound every write to one chunk the size of
a pair of database pages, and the tail chunk is the only one an ordinary append touches.

**The stream is replaced, not appended to blindly.** The old table got its idempotence from
`UNIQUE(sitting_id, onset_ms, value)` and `INSERT OR IGNORE`. Here the guarantee moves to
`insert_moves`: a retried batch is merged against the chunk it overlaps and a move already
stored for the same onset and value is not stored twice. Channel is deliberately *not* part
of that key, exactly as it was not part of the old index — a retried batch must not double a
move, and the first copy of a move keeps its channel.

The chunk invariant: every move sharing an onset lives in one chunk, and the chunks of a
sitting are disjoint and increasing in time. That is what makes a read a concatenation
rather than a sort, and what lets a merge find every possible duplicate by looking only at
the chunks its own span touches.
"""

from __future__ import annotations

import sqlite3
import struct
from typing import Iterable, Sequence

#: Little-endian and packed (``<``), so the size is exactly the sum of the fields and the
#: bytes are the same on every machine this file travels to.
_RECORD = struct.Struct("<IBB")

#: One move: onset since the sitting's start, the CC value, the MIDI channel.
RECORD_BYTES = _RECORD.size

#: Stored in the channel byte when the device sent none. `LoggedPedal.channel` is nullable —
#: a document imported from a library that never recorded channels must still round-trip.
NO_CHANNEL = 0xFF

#: Moves per chunk. 512 × 6 bytes = 3 KiB, which SQLite keeps on the pages it already has to
#: write; a bigger chunk would make every append rewrite more than it appends.
CHUNK_RECORDS = 512

Move = tuple[int, int, int | None]


class CorruptPedalStream(ValueError):
    """A chunk's blob is not a whole number of records, so the stream cannot be read.

    Distinct from an empty stream: no chunks is "no pedalling recorded", which is a
    legitimate state for imported history. Bytes that do not divide by the record size are
    damage, and naming it is what stops it being read as a pedal that was never pressed.
    """


def encode(moves: Iterable[Move]) -> bytes:
    """The moves as one chunk's payload."""
    return b"".join(_RECORD.pack(onset, value, NO_CHANNEL if channel is None else channel)
                    for onset, value, channel in moves)


def decode(blob: bytes | memoryview) -> list[Move]:
    """The moves back, in the order they were encoded."""
    raw = bytes(blob)
    if len(raw) % RECORD_BYTES:
        raise CorruptPedalStream(
            f"a pedal chunk is {len(raw)} bytes, which is not a whole number of "
            f"{RECORD_BYTES}-byte records"
        )
    return [
        (onset, value, None if channel == NO_CHANNEL else channel)
        for onset, value, channel in _RECORD.iter_unpack(raw)
    ]


def chunks(moves: Sequence[Move], limit: int = CHUNK_RECORDS) -> list[Sequence[Move]]:
    """Split sorted moves into chunks of at most `limit`, never inside one onset.

    Splitting a run of moves that share a millisecond across two chunks would break the
    invariant the merge relies on: a duplicate at that onset could then sit in a chunk the
    merge is not looking at.
    """
    out: list[Sequence[Move]] = []
    current: list[Move] = []
    for move in moves:
        if len(current) >= limit and move[0] != current[-1][0]:
            out.append(current)
            current = []
        current.append(move)
    if current:
        out.append(current)
    return out


def _keyed(moves: Iterable[Move]) -> dict[tuple[int, int], Move]:
    """Moves by (onset, value), first occurrence winning — the old unique index's rule."""
    keyed: dict[tuple[int, int], Move] = {}
    for move in moves:
        keyed.setdefault((move[0], move[1]), move)
    return keyed


def ordered(moves: Iterable[Move]) -> list[Move]:
    """The moves deduplicated by (onset, value) and in time order.

    Within one millisecond the input order is kept rather than sorted by value: the old
    row-per-move table returned those rows in the order they arrived, and a segment's
    intervals depend on which move came last, so re-sorting an onset would be a behaviour
    change dressed as tidiness. Python's sort is stable, so sorting on the onset alone
    preserves arrival order everywhere it is not already unique.
    """
    return sorted(_keyed(moves).values(), key=lambda move: move[0])


def _write_chunks(
    conn: sqlite3.Connection, sitting_id: int, moves: Sequence[Move], start_no: int
) -> None:
    for offset, chunk in enumerate(chunks(moves)):
        conn.execute(
            "INSERT INTO pedal_stream (sitting_id, chunk_no, n, first_ms, last_ms, data)"
            " VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            (
                sitting_id,
                start_no + offset,
                len(chunk),
                chunk[0][0],
                chunk[-1][0],
                encode(chunk),
            ),
        )


def _next_chunk_no(conn: sqlite3.Connection, sitting_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(chunk_no), -1) + 1 FROM pedal_stream WHERE sitting_id = ?",
        (sitting_id,),
    ).fetchone()
    return int(row[0])


def moves(conn: sqlite3.Connection, sitting_id: int) -> list[Move]:
    """Every pedal move of a sitting, in time order.

    The chunks are disjoint and ordered because `insert_moves` keeps them so, which is why
    this is a concatenation: ordering a sitting's worth of moves on every read would put a
    sort between playback and the first note.
    """
    rows = conn.execute(
        "SELECT data FROM pedal_stream WHERE sitting_id = ? ORDER BY first_ms, chunk_no",
        (sitting_id,),
    )
    out: list[Move] = []
    for row in rows:
        out.extend(decode(row["data"]))
    return out


def insert_moves(
    conn: sqlite3.Connection, sitting_id: int, incoming: Iterable[Move]
) -> int:
    """Store the moves that are not already stored. Returns how many that was.

    The caller owns the transaction: this is one step of a batch that may also write notes
    and marks, and a half-applied batch is the state the ingest path exists to avoid.
    """
    batch = ordered(incoming)
    if not batch:
        return 0
    heads = conn.execute(
        "SELECT chunk_no, n, first_ms, last_ms FROM pedal_stream WHERE sitting_id = ?"
        " ORDER BY first_ms, chunk_no",
        (sitting_id,),
    ).fetchall()
    if not heads:
        _write_chunks(conn, sitting_id, batch, _next_chunk_no(conn, sitting_id))
        return len(batch)

    last = heads[-1]
    if batch[0][0] > int(last["last_ms"]):
        # The ordinary case: this batch happened after everything already stored, so it can
        # only extend the tail chunk. `>` rather than `>=` because a batch that starts on the
        # tail's last millisecond may repeat moves that are already in it.
        if int(last["n"]) + len(batch) <= CHUNK_RECORDS:
            # Decoded and re-encoded rather than `data || ?`: SQLite's concatenation operator
            # returns TEXT, and a text value holding arbitrary bytes is not the blob the next
            # reader asks for. One chunk is at most `CHUNK_RECORDS` records, so this costs less
            # than the index maintenance the old row-per-move stream paid for every write.
            tail = conn.execute(
                "SELECT data FROM pedal_stream WHERE sitting_id = ? AND chunk_no = ?",
                (sitting_id, int(last["chunk_no"])),
            ).fetchone()
            tail_moves = decode(tail["data"])
            conn.execute(
                "UPDATE pedal_stream SET data = ?1, n = ?2, last_ms = ?3"
                " WHERE sitting_id = ?4 AND chunk_no = ?5",
                (
                    encode([*tail_moves, *batch]),
                    len(tail_moves) + len(batch),
                    batch[-1][0],
                    sitting_id,
                    int(last["chunk_no"]),
                ),
            )
            return len(batch)
        _write_chunks(conn, sitting_id, batch, _next_chunk_no(conn, sitting_id))
        return len(batch)

    # Out of order, or a repeated batch: a retried request can deliver a span that starts
    # before the tail. Every move it can duplicate lives in a chunk whose time range it
    # touches, which is exactly the set searched here.
    overlapping = [
        head
        for head in heads
        if int(head["last_ms"]) >= batch[0][0] and int(head["first_ms"]) <= batch[-1][0]
    ]
    if not overlapping:
        _write_chunks(conn, sitting_id, batch, _next_chunk_no(conn, sitting_id))
        return len(batch)

    existing: list[Move] = []
    for head in overlapping:
        row = conn.execute(
            "SELECT data FROM pedal_stream WHERE sitting_id = ? AND chunk_no = ?",
            (sitting_id, int(head["chunk_no"])),
        ).fetchone()
        existing.extend(decode(row["data"]))
    merged = ordered([*existing, *batch])
    for head in overlapping:
        conn.execute(
            "DELETE FROM pedal_stream WHERE sitting_id = ? AND chunk_no = ?",
            (sitting_id, int(head["chunk_no"])),
        )
    _write_chunks(conn, sitting_id, merged, _next_chunk_no(conn, sitting_id))
    return len(merged) - len(existing)
