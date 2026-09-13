"""Request and response schemas for the practice domain.

Times on the wire are absolute epoch milliseconds. The client cannot know which
sitting it is in — that is the server's judgement — so events arrive absolute and
are stored relative to whichever sitting the server assigned.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .capture_status import CaptureReport

#: What kind of practice produced these notes. A closed set, so a typo cannot
#: silently invent a third category that the analytics then have to display.
PracticeSource = Literal["web_midi", "sight_reading"]


class WireNote(BaseModel):
    epoch_ms: int = Field(description="Absolute event time, ms since the Unix epoch")
    pitch: int = Field(ge=0, le=127)
    velocity: int = Field(ge=0, le=127)
    duration_ms: int = Field(ge=0)
    channel: int | None = Field(default=None, ge=0, le=15)


class WirePedal(BaseModel):
    """One sustain-pedal move, as the piano sent it.

    The raw CC value rather than a boolean: it is what the device said, and a
    client that had already collapsed it to "down or up" could not send anything
    else without a change here.
    """

    epoch_ms: int = Field(description="Absolute event time, ms since the Unix epoch")
    value: int = Field(ge=0, le=127, description="CC64 value; 64 and above is down")
    channel: int | None = Field(default=None, ge=0, le=15)


class EventBatch(BaseModel):
    """A batch of played notes, and the pedal moves that went with them.

    ``client_id`` is deliberately absent. The ported logger validated one and
    then never stored it; now that one app owns capture there is exactly one
    client, so the field would be a value nothing reads.

    ``pedals`` is optional on the wire, so a client that predates it — or a
    keyboard with no pedal — keeps working unchanged. That is also why an empty
    ``events`` list is allowed when pedals are present: a client should not have
    to know which of the two the server would rather receive.
    """

    tz_offset_minutes: int = Field(
        ge=-840, le=840, description="Minutes east of UTC, e.g. -180 for UTC-3"
    )
    source: PracticeSource = "web_midi"
    events: list[WireNote] = Field(default_factory=list)
    pedals: list[WirePedal] = Field(default_factory=list)


class IngestResult(BaseModel):
    #: None when the batch held nothing a sitting could be found for — a pedal
    #: move with no music around it. That is a successful request, not an error:
    #: refusing it would leave a client retrying the same batch forever.
    sitting_id: int | None = None
    accepted: int
    duplicates: int
    started_at: str | None = None
    ended_at: str | None = None
    #: Pedal moves stored in this batch, and those dropped because no sitting was
    #: open at the time. A pedal pressed with no music around it is not practice,
    #: so it is dropped rather than allowed to open or extend a sitting.
    pedals_accepted: int = 0
    pedals_ignored: int = 0


class SittingSummary(BaseModel):
    id: int
    started_at: str
    ended_at: str
    local_date: str
    source: str
    note_count: int
    duration_s: float
    segment_count: int


class SegmentMetricsOut(BaseModel):
    duration_s: float | None = None
    note_count: int | None = None
    #: Note rate as BPM, measured over attacks — comparable with itself, not an
    #: absolute tempo. See `practice.metrics.median_tempo`.
    median_tempo: float | None = None
    mean_velocity: float | None = None
    velocity_stddev: float | None = None
    restarts: int | None = None


class SegmentSummary(BaseModel):
    id: int
    sitting_id: int
    start_ms: int
    end_ms: int
    piece_id: int | None = None
    piece_title: str | None = None
    composer_name: str | None = None
    source: str | None = None
    workout_id: int | None = None
    confidence: float | None = None
    identified_by: str | None = None
    note_count: int
    metrics: SegmentMetricsOut | None = None


class LoggedNote(BaseModel):
    """One note as it was played. Onsets are relative to the sitting's start."""

    onset_ms: int
    duration_ms: int
    pitch: int
    velocity: int
    channel: int | None = None


class LoggedPedal(BaseModel):
    """One pedal move as it was played. Onsets are relative to the sitting's start."""

    onset_ms: int
    value: int
    channel: int | None = None


class SittingNotes(BaseModel):
    """Every note of a sitting, for playback, and the pedalling under it.

    Separate from the detail view because it is the only heavy payload in the practice
    domain: a four-minute sitting is a few thousand notes, and the detail is re-read
    after every edit to a segment, which has no use for them.

    The pedals travel with the notes rather than in a payload of their own: a
    recording that reproduces the notes but not the pedal is not what was played,
    and splitting them would make it possible to fetch one without the other.
    """

    sitting_id: int
    started_ms: int
    notes: list[LoggedNote]
    pedals: list[LoggedPedal] = Field(default_factory=list)


class SittingDetail(BaseModel):
    id: int
    started_at: str
    ended_at: str
    local_date: str
    source: str
    note_count: int
    duration_s: float
    closed: bool
    segments: list[SegmentSummary]


class AssignRequest(BaseModel):
    piece_id: int | None = None


class SplitRequest(BaseModel):
    """``at_ms`` is relative to the sitting start, like ``segments.start_ms``."""

    at_ms: int = Field(gt=0)


class MergeRequest(BaseModel):
    other_id: int


class ResegmentRequest(BaseModel):
    confirm: bool = False


class CalendarDay(BaseModel):
    date: str
    minutes: float
    notes: int
    sittings: int


class PiecePractice(BaseModel):
    piece_id: int
    title: str
    composer_name: str | None = None
    minutes: float
    notes: int
    segments: int
    last_played: str | None = None
    journal_minutes: int = 0


class NeglectedPiece(BaseModel):
    piece_id: int
    title: str
    composer_name: str | None = None
    days_since: int | None = None
    last_played: str | None = None


class TempoPoint(BaseModel):
    date: str
    median_tempo: float
    segment_id: int


class TempoSeries(BaseModel):
    piece_id: int
    title: str
    points: list[TempoPoint]


class PiecePracticeDetail(PiecePractice):
    """One piece's logged practice, all time, with its tempo trend.

    All time rather than windowed: a piece is worked on for months, and "you have
    logged 4 hours on this" is the useful number, not "40 minutes in the last 30
    days".
    """

    tempo: TempoSeries


class SourceSplit(BaseModel):
    source: str
    minutes: float
    notes: int


class AnalyticsSummary(BaseModel):
    days: int
    total_minutes: float
    total_notes: int
    today_minutes: float
    streak_days: int
    calendar: list[CalendarDay]
    by_piece: list[PiecePractice]
    neglected: list[NeglectedPiece]
    sources: list[SourceSplit]
    recent: list[SittingSummary]
    #: Filled from the workout domain at the API layer, so this module stays
    #: ignorant of it: a practice summary counts practice, and workouts are
    #: counted by whoever owns them.
    workouts_completed: int = 0
    workouts_this_week: int = 0
    last_note_ms: int | None = None
    capture: CaptureReport | None = None


class PracticeStatus(BaseModel):
    """What the Log section needs before anything has been recorded."""

    sittings: int
    notes: int
    first_date: str | None = None
    last_date: str | None = None
    #: True when the most recent sitting is still open, i.e. notes are arriving.
    #: Shown so "is capture working?" is answerable without playing a note.
    open_sitting: bool = False
    #: Epoch ms of the end of the last note the server stored, or None. Read from
    #: the database, so it is a fact rather than a client's claim.
    last_note_ms: int | None = None
    #: The last capture heartbeat, or None when nothing has reported recently.
    capture: CaptureReport | None = None


class CaptureReportIn(BaseModel):
    """What a capturing client tells the server about itself.

    The timestamp is the server's, not the client's, so it lives on `CaptureReport`
    rather than here.
    """

    origin: str = Field(max_length=120)
    enabled: bool
    pending: int = Field(default=0, ge=0)


class PracticeImportReport(BaseModel):
    """What a practice-history import found and copied.

    Practice tables are optional in the legacy database — it may never have been
    used — so a missing one is reported, not raised.
    """

    source_db: str
    available: bool
    sittings: int = 0
    note_events: int = 0
    segments: int = 0
    note: str | None = None
