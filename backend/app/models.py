"""Request/response schemas for the HTTP boundary."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .practice.capture_status import CaptureReport


class PlayedNoteIn(BaseModel):
    """One MIDI note-on as observed by the browser."""

    pitch: int = Field(ge=0, le=127, description="MIDI note number")
    onset: float = Field(description="Seconds since the exercise started")
    duration: float = Field(default=0.0, ge=0.0, description="Seconds held, 0 if unknown")
    velocity: int = Field(default=64, ge=0, le=127)
    channel: int = Field(default=0, ge=0, le=15)


class RatingPoint(BaseModel):
    at: str
    before: float
    after: float
    delta: float
    score: float | None = None
    performance_id: int | None = None
    #: True when this skill was the attempt's target, rather than incidentally nudged.
    focus: bool = False


class SkillRatingSeries(BaseModel):
    slug: str
    name: str
    points: list[RatingPoint]


class RatingHistory(BaseModel):
    days: int
    skills: list[SkillRatingSeries]
    #: Skills that moved most in the window, for a summary line.
    biggest_gain: str | None = None
    biggest_gain_delta: float = 0.0


class MediaStates(BaseModel):
    present: int = 0
    pending: int = 0
    missing: int = 0


class SystemStatus(BaseModel):
    """Everything a person needs to answer "is this thing healthy?" in one screen."""

    database_path: str
    database_bytes: int
    #: WAL and their siblings are part of what a backup has to capture.
    wal_bytes: int = 0
    media_dir: str
    media: MediaStates
    backup_dir: str
    last_backup: str | None = None
    last_backup_seconds: float | None = None
    backup_count: int = 0
    sequencer: bool
    alsa_clients: list[str] = Field(default_factory=list)
    capture: CaptureReport | None = None
    last_note_ms: int | None = None
    #: Suggested latency in ms, or None when there is not enough evidence to suggest one.
    latency_suggestion_ms: float | None = None
    latency_current_ms: float = 0.0


class PerformanceDetail(BaseModel):
    """One past attempt, with everything needed to display and replay it."""

    performance_id: int
    exercise_id: int
    score: float | None = None
    pitch_accuracy: float | None = None
    rhythm_accuracy: float | None = None
    continuity_accuracy: float | None = None
    mode: str
    tempo_bpm: float | None = None
    performed_at: str | None = None
    key_name: str | None = None
    meter: str | None = None
    difficulty_elo: float | None = None
    target_skill: str | None = None
    levels: dict[str, int] = Field(default_factory=dict)
    expected_notes: list[dict] = Field(default_factory=list)
    played_notes: list[dict] = Field(default_factory=list)
    feedback: list[dict] = Field(default_factory=list)
    by_hand: dict = Field(default_factory=dict)


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
