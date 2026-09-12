"""Request/response schemas for the HTTP boundary."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PlayedNoteIn(BaseModel):
    """One MIDI note-on as observed by the browser."""

    pitch: int = Field(ge=0, le=127, description="MIDI note number")
    onset: float = Field(description="Seconds since the exercise started")
    duration: float = Field(default=0.0, ge=0.0, description="Seconds held, 0 if unknown")
    velocity: int = Field(default=64, ge=0, le=127)
    channel: int = Field(default=0, ge=0, le=15)


class ScoreRequest(BaseModel):
    exercise_id: int
    notes: list[PlayedNoteIn] = Field(default_factory=list)
    mode: Literal["practice", "performance"] = "practice"
    latency_ms: float = Field(default=0.0, description="Measured round-trip latency to subtract")
    calibration: bool = False


class ExpectedNoteOut(BaseModel):
    index: int
    event_id: int
    pitch: int
    onset_q: float
    duration_q: float
    onset_s: float
    hand: str
    measure: int
    beat: float


class ExerciseOut(BaseModel):
    exercise_id: int
    musicxml: str
    tempo_bpm: float
    bars: int
    key_name: str | None
    meter: str | None
    levels: dict[str, int]
    difficulty_elo: float
    target_skill: str | None
    source: str
    expected_notes: list[dict[str, Any]]
    measures: list[dict[str, Any]] = Field(default_factory=list)
    #: Left-hand figure used, when the exercise has two hands.
    bass_pattern: str | None = None
    bass_pattern_description: str | None = None
    rationale: str | None = None
    complete: bool | None = None
    step: int | None = None
    total: int | None = None
    next: dict[str, Any] | None = None


class SkillOut(BaseModel):
    slug: str
    name: str
    description: str | None = None
    levels: list[str] | None = None
    rating: float | None = None
    level: int | None = None
    attempts: int | None = None
    last_practiced_at: str | None = None


class ProfileOut(BaseModel):
    user_id: int
    username: str
    default_rating: float
    pass_threshold: float
    exercise_bars: int
    calibration_total: int
    calibration_step: int
    ratings: dict[str, float]
    levels: dict[str, int]


class HealthOut(BaseModel):
    status: str
    database: str
    exercises: int
    performances: int
