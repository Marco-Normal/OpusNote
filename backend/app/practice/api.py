"""HTTP routes for practice logging, mounted by the main app."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from ..config import settings
from ..store import open_connection
from ..workout import store as workout_store
from . import store
from .legacy import LegacyDatabaseMissing, import_legacy_practice
from .models import (
    AnalyticsSummary,
    AssignRequest,
    EventBatch,
    IngestResult,
    MergeRequest,
    PracticeImportReport,
    PracticeStatus,
    PiecePracticeDetail,
    ResegmentRequest,
    SegmentSummary,
    SittingDetail,
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
    if not batch.events:
        raise HTTPException(status_code=422, detail="events must not be empty")
    return _handle(store.ingest, batch)


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
    open_sitting = False
    if last_end is not None:
        open_sitting = int(last_end) + settings.sitting_gap_s * 1000 >= int(
            time.time() * 1000
        )
    return PracticeStatus(
        sittings=int(totals["sittings"] or 0),
        notes=int(notes or 0),
        first_date=totals["first_date"],
        last_date=totals["last_date"],
        open_sitting=open_sitting,
    )


# --- sittings --------------------------------------------------------------


@router.get("/sittings", response_model=list[SittingSummary])
def sittings(
    limit: int = Query(default=20, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_conn),
) -> list[SittingSummary]:
    return store.list_sittings_conn(conn, limit)


@router.get("/sittings/{sitting_id}", response_model=SittingDetail)
def sitting_detail(sitting_id: int) -> SittingDetail:
    return _handle(store.sitting_detail, sitting_id)


@router.post("/sittings/{sitting_id}/resegment", response_model=list[SegmentSummary])
def resegment(sitting_id: int, body: ResegmentRequest) -> list[SegmentSummary]:
    return _handle(store.resegment_sitting, sitting_id, confirm=body.confirm)


# --- segments --------------------------------------------------------------


@router.patch("/segments/{segment_id}", response_model=list[SegmentSummary])
def assign_segment(segment_id: int, body: AssignRequest) -> list[SegmentSummary]:
    return _handle(store.assign_piece, segment_id, body.piece_id)


@router.post("/segments/{segment_id}/split", response_model=list[SegmentSummary])
def split(segment_id: int, body: SplitRequest) -> list[SegmentSummary]:
    return _handle(store.split_segment, segment_id, body.at_ms)


@router.post("/segments/{segment_id}/merge", response_model=list[SegmentSummary])
def merge(segment_id: int, body: MergeRequest) -> list[SegmentSummary]:
    return _handle(store.merge_segments, segment_id, body.other_id)


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
