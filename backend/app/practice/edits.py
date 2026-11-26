"""Segment edits: labelling, practice kinds, splitting, merging, and re-segmenting."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import db
from ..config import settings
from . import kinds
from . import passages
from . import segment
from . import store as _store
from .materialise import (
    _refresh_metrics,
    _segment_config,
    _segment_rows,
    _tag_from_workouts,
    offer_practice_kinds,
)
from .models import PracticeKind, SegmentSummary
from .store_core import (
    _SETTLED,
    ConfirmationRequired,
    InvalidRequest,
    NotFound,
    _sitting_notes,
)

def _segment_or_raise(conn: sqlite3.Connection, segment_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, sitting_id, start_ms, end_ms, piece_id, source, workout_id,"
        " confidence, identified_by, practice_kind, practice_kind_basis"
        " FROM segments WHERE id = ?",
        (segment_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"no segment {segment_id}")
    return row


def _counted_kind(row: sqlite3.Row) -> tuple[str | None, str | None]:
    """A row's practice kind, but only when a person actually settled it.

    An ``offered`` kind is the app's question about the *whole* stretch, so it is not
    something a boundary edit may carry to either half — the halves are exactly what makes
    the question doubtful, and the offer pass will ask again on its own terms. A kind a
    person chose is theirs, and cutting a segment administratively must not silently drop
    half their answer.
    """
    if row["practice_kind_basis"] in ("manual", "accepted"):
        return row["practice_kind"], row["practice_kind_basis"]
    return None, None


def _settle_label(
    conn: sqlite3.Connection, row: sqlite3.Row, piece_id: int | None
) -> None:
    """Write a person's decision about a segment, and record what became of the guess.

    The single owner of "someone has decided": whether the decision arrives from the
    piece dropdown, from accepting a match or from refusing one, the label is written
    here and the outcome is recorded here. Two call sites writing labels is how one
    of them ends up forgetting to record a rejection, and a live accuracy figure
    that only counts some of the mistakes is worse than none.
    """
    previous = row["piece_id"]
    inferred = row["identified_by"] == "similarity"

    conn.execute(
        "UPDATE segments SET piece_id = ?1, confidence = ?2, identified_by = ?3,"
        " source = ?4 WHERE id = ?5",
        (
            piece_id,
            None if piece_id is None else 1.0,
            None if piece_id is None else "manual",
            None if piece_id is None else "repertoire",
            int(row["id"]),
        ),
    )

    if not inferred:
        return  # there was no guess, so there is nothing to be right or wrong about
    same = piece_id is not None and previous is not None and int(previous) == int(piece_id)
    if piece_id is None:
        action, accepted = "rejected", False
    elif same:
        action, accepted = "confirmed", True
    else:
        action, accepted = "changed", False
    _store._record_outcome(
        conn,
        segment_id=int(row["id"]),
        guessed_piece_id=int(previous) if previous is not None else None,
        resolved_piece_id=piece_id,
        action=action,
        accepted=accepted,
        score=row["confidence"],
    )


def set_practice_kind(
    segment_id: int,
    action: str,
    kind: PracticeKind | None,
    db_path: Path | None = None,
) -> list[SegmentSummary]:
    """Record how a segment was practised, or answer the offer about it.

    The single owner of "someone has decided about the kind", the same way
    ``_settle_label`` is the one owner of a piece decision:

    * ``set`` is the player's own choice. It writes ``basis = 'manual'`` and may replace a
      previous choice, because changing your mind is not a mistake.
    * ``accept`` promotes a pending offer. It is refused when there is no offer, so a
      stale button cannot manufacture one.
    * ``decline`` clears an offer. Declining nothing is a deliberate no-op rather than a
      409: a double-click is not an error.
    """
    # `immediate`: every one of these reads a row and then writes what it read, and the app's
    # own design has two machines writing this file. A deferred transaction would fix its snapshot
    # at the first SELECT and then fail the write as "database is locked" if anything committed in
    # between — SQLITE_BUSY_SNAPSHOT, which `busy_timeout` does not retry.
    with db.transaction(db_path, immediate=True) as conn:
        row = conn.execute(
            "SELECT id, sitting_id, practice_kind, practice_kind_basis FROM segments WHERE id = ?",
            (segment_id,),
        ).fetchone()
        if row is None:
            raise NotFound(f"no segment {segment_id}")

        if action == "accept":
            if row["practice_kind_basis"] != "offered" or row["practice_kind"] is None:
                raise InvalidRequest("this segment has no offer to accept")
            conn.execute(
                "UPDATE segments SET practice_kind_basis = 'accepted' WHERE id = ?",
                (segment_id,),
            )
        elif action == "decline":
            conn.execute(
                "UPDATE segments SET practice_kind = NULL, practice_kind_basis = NULL"
                " WHERE id = ?",
                (segment_id,),
            )
        else:
            conn.execute(
                "UPDATE segments SET practice_kind = ?1, practice_kind_basis = ?2"
                " WHERE id = ?3",
                (kind, None if kind is None else "manual", segment_id),
            )
        return _segment_rows(conn, int(row["sitting_id"]))


def assign_piece(
    segment_id: int, piece_id: int | None, db_path: Path | None = None
) -> list[SegmentSummary]:
    """Tag a segment with a piece, or clear it with ``piece_id = None``."""
    # `immediate`: every one of these reads a row and then writes what it read, and the app's
    # own design has two machines writing this file. A deferred transaction would fix its snapshot
    # at the first SELECT and then fail the write as "database is locked" if anything committed in
    # between — SQLITE_BUSY_SNAPSHOT, which `busy_timeout` does not retry.
    with db.transaction(db_path, immediate=True) as conn:
        row = _segment_or_raise(conn, segment_id)
        if piece_id is not None:
            known = conn.execute("SELECT 1 FROM pieces WHERE id = ?", (piece_id,)).fetchone()
            if known is None:
                raise InvalidRequest(f"no piece {piece_id} in the library")
        _settle_label(conn, row, piece_id)
        # A label can make a kind offer possible that was not before: "slower than usual"
        # needs a piece. Safe to call every time — it writes only where nothing is set.
        offer_practice_kinds(conn, int(row["sitting_id"]))
        return _segment_rows(conn, int(row["sitting_id"]))


def split_segment(
    segment_id: int, at_ms: int, db_path: Path | None = None
) -> list[SegmentSummary]:
    """Split at a sitting-relative instant; boundaries stay tight to notes."""
    # `immediate`: every one of these reads a row and then writes what it read, and the app's
    # own design has two machines writing this file. A deferred transaction would fix its snapshot
    # at the first SELECT and then fail the write as "database is locked" if anything committed in
    # between — SQLITE_BUSY_SNAPSHOT, which `busy_timeout` does not retry.
    with db.transaction(db_path, immediate=True) as conn:
        row = _segment_or_raise(conn, segment_id)
        start_ms = int(row["start_ms"])
        end_ms = int(row["end_ms"])
        if not start_ms < at_ms < end_ms:
            raise InvalidRequest(
                f"at_ms must fall strictly inside the segment ({start_ms}..{end_ms})"
            )

        sitting_id = int(row["sitting_id"])
        notes = conn.execute(
            "SELECT onset_ms, duration_ms FROM note_events"
            " WHERE sitting_id = ? AND onset_ms >= ? AND onset_ms <= ?"
            " ORDER BY onset_ms, pitch",
            (sitting_id, start_ms, end_ms),
        ).fetchall()
        left = [item for item in notes if int(item["onset_ms"]) < at_ms]
        right = [item for item in notes if int(item["onset_ms"]) >= at_ms]
        if not left or not right:
            raise InvalidRequest("the split point leaves one side with no notes")

        left_end = max(int(item["onset_ms"]) + int(item["duration_ms"]) for item in left)
        right_end = max(int(item["onset_ms"]) + int(item["duration_ms"]) for item in right)

        inherit_kind, inherit_basis = _counted_kind(row)
        conn.execute(
            "UPDATE segments SET start_ms = ?1, end_ms = ?2,"
            " practice_kind = ?3, practice_kind_basis = ?4 WHERE id = ?5",
            (int(left[0]["onset_ms"]), left_end, inherit_kind, inherit_basis, segment_id),
        )
        # The new half inherits *what the activity was* — source and workout —
        # because splitting a boundary says nothing about which piece it is, and
        # a piece label would have to arbitrarily belong to one side.
        conn.execute(
            "INSERT INTO segments (sitting_id, start_ms, end_ms, source, workout_id,"
            " practice_kind, practice_kind_basis)"
            " VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            (
                sitting_id,
                int(right[0]["onset_ms"]),
                right_end,
                row["source"],
                row["workout_id"],
                inherit_kind,
                inherit_basis,
            ),
        )
        _refresh_metrics(conn, sitting_id)
        return _segment_rows(conn, sitting_id)


def merge_segments(
    segment_id: int, other_id: int, db_path: Path | None = None
) -> list[SegmentSummary]:
    """Merge two adjacent segments of one sitting."""
    if segment_id == other_id:
        raise InvalidRequest("cannot merge a segment with itself")
    # `immediate`: every one of these reads a row and then writes what it read, and the app's
    # own design has two machines writing this file. A deferred transaction would fix its snapshot
    # at the first SELECT and then fail the write as "database is locked" if anything committed in
    # between — SQLITE_BUSY_SNAPSHOT, which `busy_timeout` does not retry.
    with db.transaction(db_path, immediate=True) as conn:
        first = _segment_or_raise(conn, segment_id)
        second = _segment_or_raise(conn, other_id)
        if int(first["sitting_id"]) != int(second["sitting_id"]):
            raise InvalidRequest("segments belong to different sittings")

        sitting_id = int(first["sitting_id"])
        low, high = sorted((first, second), key=lambda row: int(row["start_ms"]))
        between = conn.execute(
            "SELECT COUNT(*) FROM segments WHERE sitting_id = ?1"
            " AND id NOT IN (?2, ?3) AND start_ms > ?4 AND start_ms < ?5",
            (
                sitting_id,
                segment_id,
                other_id,
                int(low["start_ms"]),
                int(high["start_ms"]),
            ),
        ).fetchone()[0]
        if between:
            raise InvalidRequest("segments are not adjacent")

        from_low = low["piece_id"] is not None
        # The kind follows the same rule as the piece label: whichever half carries one
        # wins, and the earlier half is preferred when both do. An offer is not carried,
        # for the reason `_counted_kind` gives.
        low_kind, low_basis = _counted_kind(low)
        high_kind, high_basis = _counted_kind(high)
        merged_kind = low_kind if low_kind is not None else high_kind
        merged_basis = low_basis if low_kind is not None else high_basis
        conn.execute(
            "UPDATE segments SET start_ms = ?1, end_ms = ?2, piece_id = ?3,"
            " confidence = ?4, identified_by = ?5, practice_kind = ?6,"
            " practice_kind_basis = ?7 WHERE id = ?8",
            (
                int(low["start_ms"]),
                int(high["end_ms"]),
                low["piece_id"] if from_low else high["piece_id"],
                low["confidence"] if from_low else high["confidence"],
                low["identified_by"] if from_low else high["identified_by"],
                merged_kind,
                merged_basis,
                int(low["id"]),
            ),
        )
        conn.execute("DELETE FROM segments WHERE id = ?", (int(high["id"]),))
        _refresh_metrics(conn, sitting_id)
        return _segment_rows(conn, sitting_id)


def resegment_sitting(
    sitting_id: int,
    confirm: bool = False,
    now_ms: int | None = None,
    db_path: Path | None = None,
) -> list[SegmentSummary]:
    """Recompute boundaries, discarding them. The only destructive path."""
    # `immediate`: every one of these reads a row and then writes what it read, and the app's
    # own design has two machines writing this file. A deferred transaction would fix its snapshot
    # at the first SELECT and then fail the write as "database is locked" if anything committed in
    # between — SQLITE_BUSY_SNAPSHOT, which `busy_timeout` does not retry.
    with db.transaction(db_path, immediate=True) as conn:
        sitting = conn.execute(
            "SELECT id FROM sittings WHERE id = ?", (sitting_id,)
        ).fetchone()
        if sitting is None:
            raise NotFound(f"no sitting {sitting_id}")
        labelled = conn.execute(
            "SELECT COUNT(*) FROM segments WHERE sitting_id = ? AND piece_id IS NOT NULL",
            (sitting_id,),
        ).fetchone()[0]
        if labelled and not confirm:
            raise ConfirmationRequired(
                f"{labelled} segment(s) carry a piece; confirm=true discards that"
            )
        conn.execute("DELETE FROM segments WHERE sitting_id = ?", (sitting_id,))
    return _store.ensure_segments(sitting_id, now_ms=now_ms, db_path=db_path)

