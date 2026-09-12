"""HTTP routes for workouts, mounted by the main app."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..skills_data import SKILL_SLUGS
from ..store import open_connection
from . import store
from .models import WorkoutHome, WorkoutOut, WorkoutStart

router = APIRouter(prefix="/api/workout", tags=["workout"])


def get_conn():
    conn = open_connection()
    try:
        yield conn
    finally:
        conn.close()


@router.get("/current", response_model=WorkoutOut | None)
def current() -> WorkoutOut | None:
    return store.current()


@router.get("", response_model=WorkoutHome)
def home(conn: sqlite3.Connection = Depends(get_conn)) -> WorkoutHome:
    """Everything the workout banner needs, in one call."""
    return WorkoutHome(
        current=store.current(),
        recent=store.recent(),
        **store.stats(conn),
    )


@router.post("/start", response_model=WorkoutOut)
def start(body: WorkoutStart) -> WorkoutOut:
    if body.target_skill is not None and body.target_skill not in SKILL_SLUGS:
        raise HTTPException(status_code=422, detail=f"unknown skill {body.target_skill!r}")
    return store.start(
        tz_offset_minutes=body.tz_offset_minutes,
        target_skill=body.target_skill,
        bars=body.bars,
    )


@router.post("/{workout_id}/finish", response_model=WorkoutOut)
def finish(workout_id: int) -> WorkoutOut:
    try:
        return store.finish(workout_id)
    except store.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
