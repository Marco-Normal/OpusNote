"""Workout request and response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkoutStart(BaseModel):
    """Starting a workout.

    ``tz_offset_minutes`` is required rather than defaulted: the workout's
    ``local_date`` decides which day the streak counts it on, and a default of 0
    would file an 11 pm session under tomorrow for anyone west of Greenwich.
    """

    tz_offset_minutes: int = Field(ge=-840, le=840)
    target_skill: str | None = None
    bars: int | None = Field(default=None, ge=1, le=16)


class WorkoutOut(BaseModel):
    id: int
    started_ms: int
    started_at: str
    ended_ms: int | None = None
    ended_at: str | None = None
    local_date: str
    target_skill: str | None = None
    bars: int | None = None
    planned: int | None = None
    completed: bool
    running: bool
    sitting_id: int | None = None
    exercises_done: int
    minutes: float


class WorkoutHome(BaseModel):
    current: WorkoutOut | None = None
    recent: list[WorkoutOut]
    workouts_completed: int
    workouts_this_week: int
    last_workout_date: str | None = None
    window_days: int
