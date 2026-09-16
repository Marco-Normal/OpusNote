"""HTTP routes for practice logging, mounted by the main app."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..config import settings
from ..hostinfo import require_loopback
from ..store import open_connection
from ..workout import store as workout_store
from . import capture_status, store
from .capture_status import CaptureReport
from .legacy import LegacyDatabaseMissing, import_legacy_practice
from .models import (
    AnalyticsSummary,
    AssignRequest,
    AutotagReport,
    EventBatch,
    IdentificationQuality,
    IngestResult,
    MergeRequest,
    CaptureReportIn,
    PracticeImportReport,
    PracticeKindRequest,
    PracticeStatus,
    PiecePracticeDetail,
    ResegmentRequest,
    SegmentSummary,
    SittingCloseResult,
    SittingDetail,
    SittingNotes,
    SittingSummary,
    SplitRequest,
    TempoSeries,
)

router = APIRouter(prefix="/api/practice", tags=["practice"])


def get_conn():
    conn = open_connection()
    try:
        yield conn
    finally:
        conn.close()


# --- error mapping ---------------------------------------------------------
# Only these three domain exceptions are mapped. Mapping bare ValueError or
# LookupError would turn an unrelated bug into a 422 and hide it.


def _handle(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except store.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except store.InvalidRequest as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except store.ConfirmationRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# --- capture ---------------------------------------------------------------


@router.post("/events", response_model=IngestResult)
def post_events(batch: EventBatch) -> IngestResult:
    # Pedals alone are a legitimate batch. The client flushes every two seconds
    # and keeps a failed batch queued, so refusing a pedal-only flush would block
    # every note behind it until the player happened to play again.
    if not batch.events and not batch.pedals:
        raise HTTPException(status_code=422, detail="events must not be empty")
    return _handle(store.ingest, batch)


@router.post("/sittings/close", response_model=SittingCloseResult)
def close_sitting() -> SittingCloseResult:
    """Finish the open sitting now, because the piano went away.

    The player switching the piano off is a much sooner answer to "are they done?"
    than waiting out the whole silence gap, and it is the difference between the
    dashboard showing the sitting now and showing it five minutes from now.
    """
    outcome = _handle(store.close_open_sitting)
    return SittingCloseResult(
        closed=outcome.sitting_id is not None,
        sitting_id=outcome.sitting_id,
        reason=outcome.reason,
    )


@router.get("/status", response_model=PracticeStatus)
def status(conn: sqlite3.Connection = Depends(get_conn)) -> PracticeStatus:
    """Enough to tell "nothing recorded yet" from "capture is broken"."""
    totals = conn.execute(
        "SELECT COUNT(*) AS sittings, MIN(local_date) AS first_date,"
        " MAX(local_date) AS last_date, MAX(ended_ms) AS last_end"
        " FROM sittings"
    ).fetchone()
    notes = conn.execute("SELECT COUNT(*) FROM note_events").fetchone()[0]
    last_end = totals["last_end"]
    # "Open" means a note arriving now would join that sitting — so it is asked of the
    # same predicate the ingest uses, rather than re-derived from the clock. The two
    # disagreed the moment a sitting could be closed by the piano going away: this
    # still called it open because the five minutes had not passed.
    open_sitting = (
        store._find_sitting(conn, int(time.time() * 1000), settings.sitting_gap_s * 1000)
        is not None
    )
    return PracticeStatus(
        sittings=int(totals["sittings"] or 0),
        notes=int(notes or 0),
        first_date=totals["first_date"],
        last_date=totals["last_date"],
        open_sitting=open_sitting,
        # The end of the last note the server stored. Read from the database, so it
        # is a fact rather than something a client claims.
        last_note_ms=int(last_end) if last_end is not None else None,
        capture=capture_status.snapshot(),
    )


# --- sittings --------------------------------------------------------------


@router.post("/capture-status", response_model=CaptureReport)
def report_capture(body: CaptureReportIn) -> CaptureReport:
    """A client saying "I am capturing". Cheap on purpose: it is sent every 15 s."""
    return capture_status.record(
        origin=body.origin, enabled=body.enabled, pending=body.pending
    )


@router.get("/sittings", response_model=list[SittingSummary])
def sittings(
    limit: int = Query(default=20, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_conn),
) -> list[SittingSummary]:
    return store.list_sittings_conn(conn, limit)


@router.get("/sittings/{sitting_id}", response_model=SittingDetail)
def sitting_detail(sitting_id: int) -> SittingDetail:
    return _handle(store.sitting_detail, sitting_id)


@router.get("/sittings/{sitting_id}/notes", response_model=SittingNotes)
def sitting_notes(sitting_id: int) -> SittingNotes:
    """The notes of one sitting, for playback.

    Read on demand rather than folded into the detail: this is the one payload in the
    practice domain that grows with how long you played, and every segment edit re-reads
    the detail without needing a single note.
    """
    return _handle(store.sitting_notes, sitting_id)


@router.post("/sittings/{sitting_id}/resegment", response_model=list[SegmentSummary])
def resegment(
    sitting_id: int, body: ResegmentRequest, request: Request
) -> list[SegmentSummary]:
    # `confirm=false` recomputes unlabelled boundaries and destroys nothing;
    # `confirm=true` throws labels away, so only that variant is restricted.
    if body.confirm:
        require_loopback(request)
    return _handle(store.resegment_sitting, sitting_id, confirm=body.confirm)


# --- segments --------------------------------------------------------------


@router.patch("/segments/{segment_id}", response_model=list[SegmentSummary])
def assign_segment(segment_id: int, body: AssignRequest) -> list[SegmentSummary]:
    return _handle(store.assign_piece, segment_id, body.piece_id)


@router.patch("/segments/{segment_id}/kind", response_model=list[SegmentSummary])
def set_segment_kind(segment_id: int, body: PracticeKindRequest) -> list[SegmentSummary]:
    """Say how a segment was practised, or answer the app's offer about it.

    A route of its own rather than a field on ``PATCH /segments/{id}``. The piece label
    and the practice kind are different decisions with different rules — one overrules a
    matcher and records what became of the guess, the other overrules nothing — and a body
    carrying both would have to explain which of the two a null meant.
    """
    return _handle(store.set_practice_kind, segment_id, body.action, body.kind)


@router.post("/segments/{segment_id}/split", response_model=list[SegmentSummary])
def split(segment_id: int, body: SplitRequest) -> list[SegmentSummary]:
    return _handle(store.split_segment, segment_id, body.at_ms)


@router.post("/segments/{segment_id}/merge", response_model=list[SegmentSummary])
def merge(segment_id: int, body: MergeRequest) -> list[SegmentSummary]:
    return _handle(store.merge_segments, segment_id, body.other_id)


# --- identifying a segment from your own labelled practice -----------------


class IdentifyRequest(BaseModel):
    """What to do with a match.

    ``accept`` takes the inferred label as your own, ``reject`` clears it, and
    ``dismiss`` declines an *offered* match that was never written. Replacing a
    label with a different piece is not here: that is `PATCH /segments/{id}`, which
    records the overruled guess just the same.
    """

    action: Literal["accept", "reject", "dismiss"]


@router.post("/segments/{segment_id}/identification", response_model=list[SegmentSummary])
def resolve_identification(segment_id: int, body: IdentifyRequest) -> list[SegmentSummary]:
    return _handle(store.resolve_identification, segment_id, body.action)


@router.post("/autotag", response_model=AutotagReport)
def run_autotag() -> AutotagReport:
    """Look for matches among the segments that are still unlabelled.

    The backfill path, for practice that was logged before the matcher existed. It
    writes only the confident band, exactly like the pass that runs when a sitting
    is segmented, so running it can never invent a label the automatic path would
    not have written.
    """
    return _handle(store.autotag_unlabelled)


@router.get("/autotag/quality", response_model=IdentificationQuality)
def identification_quality() -> IdentificationQuality:
    """How well the matcher does on this library, by hiding one label at a time."""
    return _handle(store.identification_quality)


# --- analytics -------------------------------------------------------------


@router.get("/analytics/summary", response_model=AnalyticsSummary)
def analytics_summary(
    days: int = Query(default=30, ge=1, le=365),
    conn: sqlite3.Connection = Depends(get_conn),
) -> AnalyticsSummary:
    """The Log dashboard in one call.

    The workout counts are attached here rather than inside the practice store,
    so the practice domain never has to know that workouts exist; this layer is
    where the two domains are allowed to meet.
    """
    data = store.summary(conn, days)
    stats = workout_store.stats(conn)
    return data.model_copy(
        update={
            "workouts_completed": stats["workouts_completed"],
            "workouts_this_week": stats["workouts_this_week"],
        }
    )


@router.get("/pieces/{piece_id}", response_model=PiecePracticeDetail)
def piece_practice(
    piece_id: int, conn: sqlite3.Connection = Depends(get_conn)
) -> PiecePracticeDetail:
    """What one piece has actually cost in logged practice, and how fast it is now.

    The repertoire side shows this beside the journal, which is what makes
    "time per piece" one number instead of two rival ones.
    """
    return _handle(store.piece_practice, conn, piece_id)


@router.get("/analytics/tempo", response_model=TempoSeries)
def analytics_tempo(
    piece_id: int = Query(ge=1), conn: sqlite3.Connection = Depends(get_conn)
) -> TempoSeries:
    return _handle(store.tempo_series, conn, piece_id)


# --- one-time import -------------------------------------------------------


@router.post("/import-legacy", response_model=PracticeImportReport)
def import_legacy() -> PracticeImportReport:
    """Copy practice history out of the standalone logger's database.

    Separate from the repertoire import because the source is a different app's
    data with a different shape; the two are independently re-runnable, and the
    frontend's single Import button calls both.
    """
    try:
        return import_legacy_practice(Path(settings.legacy_db))
    except LegacyDatabaseMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
