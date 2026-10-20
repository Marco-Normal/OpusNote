"""Request and response schemas for the practice domain.

Times on the wire are absolute epoch milliseconds. The client cannot know which
sitting it is in — that is the server's judgement — so events arrive absolute and
are stored relative to whichever sitting the server assigned.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field

from .capture_status import CaptureReport

#: What kind of practice produced these notes. A closed set, so a typo cannot
#: silently invent a third category that the analytics then have to display.
PracticeSource = Literal["web_midi", "sight_reading"]

#: How a segment was practised — the axis the log was missing. Deliberately **not**
#: including sight-reading: that is owned by `source`/`workout_id`, and a second owner
#: for one fact is how the two drift apart.
PracticeKind = Literal[
    "run_through",
    "slow",
    "section",
    "hands_separate",
    "memory",
    "warm_up",
    "other",
]

#: Where a stored kind came from. 'offered' is a proposal the player has not answered, so
#: it is displayed as a question and excluded from every aggregate — the same restraint
#: the autotag bands and `pedal_basis` follow.
PracticeKindBasis = Literal["offered", "manual", "accepted"]


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


class WireMark(BaseModel):
    """A place the player asked to come back to.

    A deliberate act rather than a measurement, which is why it travels as its own stream: nothing
    in the notes records that a person pressed a pedal to say "review this". It carries no value
    because there is nothing to carry — the fact is the instant.
    """

    epoch_ms: int = Field(description="Absolute event time, ms since the Unix epoch")
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

    ``marks`` is optional on the wire for the same reason: a client that predates
    it keeps working unchanged.
    """

    tz_offset_minutes: int = Field(
        ge=-840, le=840, description="Minutes east of UTC, e.g. -180 for UTC-3"
    )
    source: PracticeSource = "web_midi"
    events: list[WireNote] = Field(default_factory=list)
    pedals: list[WirePedal] = Field(default_factory=list)
    marks: list[WireMark] = Field(default_factory=list)


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
    #: Marks stored in this batch, and those dropped because no sitting was open. A flag pressed
    #: with no music around it is not practice, so it is dropped rather than allowed to open one.
    marks_accepted: int = 0
    marks_ignored: int = 0


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
    #: Touch, at MIDI controller resolution — comparable with itself over weeks, not a
    #: claim about loudness.
    median_velocity: float | None = None
    velocity_range: float | None = None
    #: Mean velocity below and above middle C. A *proxy* for the hands: the piano
    #: sends both hands on one channel, so a passive log has nothing better.
    mean_velocity_low: float | None = None
    mean_velocity_high: float | None = None
    #: Pedal, derived from the raw CC64 stream.
    pedal_changes: int | None = None
    pedal_down_ratio: float | None = None
    #: Share of the span the pedal spent part-way down. Disjoint from
    #: `pedal_down_ratio`, so the two together say how long it was doing anything.
    pedal_partial_ratio: float | None = None
    #: Attacks that brought new harmony over notes the pedal was already holding.
    pedal_blur: int | None = None
    #: Where the blurs were, in ms relative to the sitting, ascending. `pedal_blur` is its
    #: length: the count tells you whether to look, these tell you where.
    pedal_blur_ms: list[int] = Field(default_factory=list)
    #: Which harmony source produced `pedal_blur`. NULL means the sitting has no pedal
    #: rows at all — imported history — which is not the same as "the pedal was not
    #: used". Stored rather than re-derived so a score attached later cannot
    #: retroactively relabel an observed number.
    pedal_basis: str | None = None


class SegmentSummary(BaseModel):
    id: int
    sitting_id: int
    start_ms: int
    end_ms: int
    piece_id: int | None = None
    piece_title: str | None = None
    composer_name: str | None = None
    #: The catalogue number, so two pieces with one title can be told apart. Additive with a
    #: default, so every pre-existing reader of a segment still holds.
    piece_opus: str | None = None
    source: str | None = None
    workout_id: int | None = None
    confidence: float | None = None
    identified_by: str | None = None
    practice_kind: PracticeKind | None = None
    #: 'offered' is a proposal the player has not answered and counts in no aggregate.
    practice_kind_basis: PracticeKindBasis | None = None
    note_count: int
    metrics: SegmentMetricsOut | None = None
    #: What this segment might be, best first. Present only while it is undecided:
    #: an inferred label and a declined suggestion both mean the question is closed,
    #: and asking again on every reload is how a suggestion becomes a nuisance.
    candidates: list["SegmentCandidate"] = Field(default_factory=list)


class SegmentCandidate(BaseModel):
    """One piece's claim on a segment, with the arithmetic that produced it.

    The sub-scores travel with the total so a surprise can be understood rather
    than merely disbelieved: "0.83 because the notes match and the register does"
    is checkable by the person looking at it.
    """

    piece_id: int
    title: str
    composer_name: str | None = None
    #: The catalogue number. Two candidates can share a title — "Sonata" twice over — and a
    #: suggestion the player cannot identify is not a suggestion. Additive with a default.
    opus: str | None = None
    score: float
    pitch_class: float
    tempo: float
    #: Named with the suffix because a bare `register` shadows a BaseModel method.
    register_overlap: float
    #: The hand and interval terms (Phase 22e). Always reported, even while their weight
    #: is zero: the number beside a candidate is the arithmetic behind it, not a subset.
    hand: float = 0.0
    interval: float = 0.0
    #: Phase 22e terms, reported whether or not they carry weight: the numbers beside a
    #: candidate are the arithmetic behind its score, and leaving a term out would make the
    #: displayed parts stop adding up to the whole.
    hand: float = 0.0
    #: Interval-class agreement between consecutive attacks, which survives transposition.
    interval: float = 0.0
    support: int
    margin: float
    #: The band the *top* candidate fell in — 'auto', 'suggest' or 'none'. Rows
    #: below the first are 'listed': offered as alternatives, claiming nothing.
    band: str
    reason: str | None = None
    #: True when this is the piece the sitting is already about.
    from_context: bool = False


class AutotagReport(BaseModel):
    """What a pass of the matcher did."""

    considered: int = 0
    assigned: int = 0
    offered: int = 0
    unresolved: int = 0
    notes: list[str] = Field(default_factory=list)


class IdentificationQuality(BaseModel):
    """How the matcher does on this library, measured by hiding each label.

    Every rate is ``None`` when it has no denominator rather than 0.0: "no
    decisions yet" and "every decision wrong" are different facts, and a report
    that renders them the same way invites exactly the wrong conclusion.
    """

    #: Segments a person has labelled: the training set.
    labelled: int
    #: How many of them were actually tested, and how many were left out to keep
    #: the report quick (the work is quadratic in the number of labels).
    evaluated: int = 0
    skipped: int = 0
    correct_top: int = 0
    correct_top3: int = 0
    auto_attempted: int = 0
    auto_correct: int = 0
    offered_attempted: int = 0
    offered_correct: int = 0
    unresolved: int = 0
    #: Segments currently carrying a machine-written label, and what has become of
    #: the ones that were acted on since.
    inferred: int = 0
    confirmed: int = 0
    changed: int = 0
    rejected: int = 0
    dismissed: int = 0
    notes: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def accuracy(self) -> float | None:
        return self.correct_top / self.evaluated if self.evaluated else None

    @computed_field
    @property
    def top3_accuracy(self) -> float | None:
        return self.correct_top3 / self.evaluated if self.evaluated else None

    @computed_field
    @property
    def auto_coverage(self) -> float | None:
        return self.auto_attempted / self.evaluated if self.evaluated else None

    @computed_field
    @property
    def auto_precision(self) -> float | None:
        return self.auto_correct / self.auto_attempted if self.auto_attempted else None

    @computed_field
    @property
    def offered_coverage(self) -> float | None:
        return self.offered_attempted / self.evaluated if self.evaluated else None

    @computed_field
    @property
    def offered_precision(self) -> float | None:
        return self.offered_correct / self.offered_attempted if self.offered_attempted else None

    @computed_field
    @property
    def settled(self) -> int:
        """Machine labels that have since been confirmed, changed or rejected."""
        return self.confirmed + self.changed + self.rejected

    @computed_field
    @property
    def live_precision(self) -> float | None:
        """Of the inferred labels acted on, the share left alone."""
        return self.confirmed / self.settled if self.settled else None


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


class PracticePassageOut(BaseModel):
    """Adjacent attempts of a sitting that are the same musical material.

    Derived on read and never stored (22-D1): the label lives on the member segments (22-D2), so
    this is a view over them and there is nothing to migrate or keep in step. Named
    ``PracticePassage`` rather than ``Passage`` because the repertoire already owns that word for
    a player-marked bar range, which is a different thing the app cannot derive.

    ``session`` is the piece-session this passage belongs to — adjacent passages sharing a piece —
    as an index into the order the passages arrive in. It is sent rather than re-derived so the
    view is not a second owner of the grouping rule.
    """

    start_ms: int
    end_ms: int
    piece_id: int | None = None
    piece_title: str | None = None
    composer_name: str | None = None
    #: Additive with a default, like `piece_title`, so every pre-existing reader still holds.
    piece_opus: str | None = None
    attempt_ids: list[int] = Field(default_factory=list)
    attempts: int = 0
    session: int = 0


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
    #: Phase 24: `segments` is empty because the work is queued elsewhere, not because the
    #: sitting holds nothing. A read that finds the background already preparing this sitting
    #: answers immediately and says so rather than waiting for it; the client asks again in a
    #: moment. Additive with a default, so every pre-existing reader of a sitting still holds.
    preparing: bool = False
    #: Additive, with a default, so every pre-existing reader of a sitting still holds.
    passages: list[PracticePassageOut] = Field(default_factory=list)
    #: Where the player asked to come back to, in ms relative to the sitting, ascending. Additive
    #: with a default, so every pre-existing reader of a sitting still holds.
    review_marks_ms: list[int] = Field(default_factory=list)


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
    #: Time the piano heard, from the sittings that day.
    minutes: float
    notes: int
    sittings: int
    #: Time written down in the journal that day. Deliberately a separate series and
    #: never added to `minutes`: a session can be both played and written about, so
    #: summing them would count it twice. A day with prose and no notes reads as
    #: written-but-not-measured, which is a different fact from a day with neither.
    written_minutes: float = 0.0
    written_entries: int = 0


class PiecePractice(BaseModel):
    piece_id: int
    title: str
    composer_name: str | None = None
    #: The catalogue number. Two pieces can share a title, and a bar labelled "Sonata" twice
    #: attributes the time to nobody. Additive with a default.
    opus: str | None = None
    minutes: float
    notes: int
    segments: int
    last_played: str | None = None
    journal_minutes: int = 0


class NeglectedPiece(BaseModel):
    piece_id: int
    title: str
    composer_name: str | None = None
    #: Additive with a default, for the same reason as `PiecePractice.opus`.
    opus: str | None = None
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


class PracticeKindSplit(BaseModel):
    """Logged minutes per practice kind, with the uncharacterised as a bucket.

    ``kind`` is None for segments nobody has characterised. That is a real state and not
    a fault, and it must appear: a split that dropped it could not be reconciled against
    the segments it claims to summarise. An unanswered offer also lands here — see
    `store.kinds_breakdown`.
    """

    kind: str | None = None
    minutes: float
    notes: int
    segments: int


class PracticeKindRequest(BaseModel):
    """Answer the kind question for one segment.

    ``action`` is required rather than inferred from ``kind``, because choosing a kind by
    hand and accepting the app's offer are different facts about where the value came
    from — the same distinction ``pedal_basis`` exists to preserve.
    """

    action: Literal["set", "accept", "decline"]
    kind: PracticeKind | None = None


class AnalyticsSummary(BaseModel):
    days: int
    total_minutes: float
    total_notes: int
    today_minutes: float
    streak_days: int
    #: How many of the streak's days were tolerated rest days, 0 or 1 under the current rule.
    #: Reported so the UI can say the run includes a rest day rather than implying it was played.
    streak_grace_used: int = 0
    calendar: list[CalendarDay]
    by_piece: list[PiecePractice]
    neglected: list[NeglectedPiece]
    sources: list[SourceSplit]
    kinds: list[PracticeKindSplit] = Field(default_factory=list)
    recent: list[SittingSummary]
    #: Filled from the workout domain at the API layer, so this module stays
    #: ignorant of it: a practice summary counts practice, and workouts are
    #: counted by whoever owns them.
    workouts_completed: int = 0
    workouts_this_week: int = 0
    last_note_ms: int | None = None
    capture: CaptureReport | None = None


class RhythmWeek(BaseModel):
    """One Monday-to-Sunday week, and how its minutes were made up.

    ``first_minutes`` is each day's *first* sitting and ``extra_minutes`` every later one,
    summed over the week. The split is the whole point: a total that falls while the first
    sitting stays put is a lost second session, not a shorter habit, and the two want different
    answers from the player.
    """

    #: Monday of the week, ISO date.
    week_start: str
    minutes: float
    sittings: int
    #: Days with at least one sitting, so a run of short daily practice is distinguishable
    #: from one long evening.
    practised_days: int
    longest_minutes: float
    first_minutes: float
    extra_minutes: float


class SessionCountBucket(BaseModel):
    """How many days had exactly ``sessions`` sittings (``4`` means four or more)."""

    sessions: int
    days: int


class WeekdayMinutes(BaseModel):
    """Minutes on one weekday. ``weekday`` is 0 = Monday, matching the week buckets."""

    weekday: int
    minutes: float
    practised_days: int


class HourMinutes(BaseModel):
    """Minutes that began in one hour of the player's day, ``0`` = midnight local.

    A sitting that crosses an hour boundary is split at it, so the hour buckets add up to the
    window's minutes. Bucketing on the stored UTC would put a 21:00 practice at midnight for a
    player three hours west, which is the reading this field exists to stop.
    """

    hour: int
    minutes: float
    #: Sittings whose *start* fell in this hour. A sitting counts once, even when it is split.
    sittings: int


class LagCorrelation(BaseModel):
    """Pearson correlation of the daily-minutes series with itself at ``lag`` days.

    Missing days are zeros, not gaps: a habit is a series of days including the ones left
    empty, and dropping them would ask whether long sittings follow long sittings.
    """

    lag: int
    r: float | None = None
    #: Overlapping pairs the correlation was computed from; fewer than three is not evidence.
    pairs: int = 0


class TechniqueSummary(BaseModel):
    """What the segment metrics say about *how* the time was spent.

    Every average is an average of per-segment values, so one long rambling section does not
    outweigh a short hard one. ``None`` where the window holds no measurement: a mean of nothing
    is not zero, and reporting 0 would read as "no restarts" rather than "not measured".
    """

    segments: int
    #: Minutes covered by segments that have metrics.
    measured_minutes: float
    #: Note-rate proxy over the window — see ``metrics.median_tempo``; not a metronome tempo.
    mean_tempo: float | None = None
    mean_velocity: float | None = None
    #: Velocity below/above middle C, the app's hand proxy.
    mean_velocity_low: float | None = None
    mean_velocity_high: float | None = None
    restarts_per_minute: float | None = None
    #: Segments that carried pedal data (``pedal_basis`` not null); the pedal averages use only
    #: these, so an imported sitting without a pedal stream cannot drag them to zero.
    pedal_segments: int = 0
    pedal_down_ratio: float | None = None
    blurs_per_minute: float | None = None


class RhythmSummary(BaseModel):
    """The shape of practice over time — the Progress tab that is not a rating.

    Deliberately a separate response from :class:`AnalyticsSummary`: the Log polls that one every
    twenty seconds, and a weekly breakdown of a year is not something to recompute on a poll.
    """

    days: int
    #: First practised day inside the window, or None when the window holds no practice. The
    #: window itself starts at ``today - days + 1``; the calendar can be wider than the record.
    window_start: str | None = None
    window_end: str
    practised_days: int
    #: Days from ``window_start`` to ``window_end`` inclusive — the denominator for adherence, so
    #: a first week is not judged against days before the log existed.
    elapsed_days: int
    sittings: int
    minutes: float
    median_session_minutes: float | None = None
    longest_session_minutes: float = 0.0
    sessions_per_practised_day: float | None = None
    weeks: list[RhythmWeek] = Field(default_factory=list)
    session_counts: list[SessionCountBucket] = Field(default_factory=list)
    weekdays: list[WeekdayMinutes] = Field(default_factory=list)
    #: Minutes by local hour of day, all 24 present, so an empty hour is a visible zero.
    hours: list[HourMinutes] = Field(default_factory=list)
    #: Serial correlation of daily minutes at 1, 7 and 14 days — is there a weekly rhythm?
    autocorrelations: list[LagCorrelation] = Field(default_factory=list)
    #: The offset used for sittings that do not carry their own (recorded before the column).
    tz_offset_minutes: int = 0
    technique: TechniqueSummary


class PitchClassNotes(BaseModel):
    """Notes played on one pitch class, ``0`` = C. Rehearsal of a piece in one key shows."""

    pitch_class: int
    notes: int


class OctaveNotes(BaseModel):
    """Notes played in one octave, scientific pitch: MIDI 60 is ``C4``."""

    octave: int
    notes: int


class RegisterProfile(BaseModel):
    """Which part of the keyboard the window actually used.

    ``mean_pitch`` is the centre of gravity of the notes, not the middle of the range: a
    hand that stays in the middle and one that visits both ends have the same range and
    different centres.
    """

    distinct_keys: int = 0
    lowest: int | None = None
    highest: int | None = None
    span_semitones: int | None = None
    mean_pitch: float | None = None
    octaves: list[OctaveNotes] = Field(default_factory=list)
    pitch_classes: list[PitchClassNotes] = Field(default_factory=list)


class HourTouch(BaseModel):
    """Mean velocity of the notes that began in one local hour."""

    hour: int
    notes: int
    mean_velocity: float | None = None


class VelocitySpan(BaseModel):
    """Mean velocity in one quarter of the window, oldest first.

    Equal *time* slices, not equal sitting counts, so a lull does not get a quarter of its
    own and a busy week cannot outvote a quiet month.
    """

    span: int
    notes: int
    mean_velocity: float | None = None


class TouchProfile(BaseModel):
    """How hard and how variously the window was played.

    Entropy is over the velocity histogram in bits: 0 means one dynamic repeated for
    everything, ``log2(127)`` ≈ 7 means an even spread over the whole MIDI range. It is a
    property of MIDI touch, not of acoustic loudness — the dynamic range figures are a
    velocity proxy, and comparing them across instruments or rooms is meaningless.
    """

    notes: int = 0
    mean_velocity: float | None = None
    min_velocity: int | None = None
    max_velocity: int | None = None
    distinct_velocities: int = 0
    entropy_bits: float | None = None
    #: ``20 * log10(max / min)`` over MIDI velocity — a proxy, never a sound-pressure level.
    dynamic_range_db: float | None = None
    by_hour: list[HourTouch] = Field(default_factory=list)


class TextureProfile(BaseModel):
    """How many notes sound together.

    An *attack* is a group of notes whose onsets are within 40 ms of each other, so a
    rolled chord counts as one attack rather than as a run. ``notes_per_attack`` above 1
    is polyphony; a window of single-line practice sits near 1.
    """

    attacks: int = 0
    notes_per_attack: float | None = None
    #: Attacks sounding three or more notes at once.
    chord_attacks: int = 0
    chord_share: float | None = None
    attacks_per_minute: float | None = None


class TravelProfile(BaseModel):
    """How far the hands moved, in semitones and in a deliberately silly unit.

    The distance is between consecutive attacks' mean pitches, so a chord costs the jump
    to its centre rather than the jump to its top note. ``metres`` uses the 17 cm per
    octave a standard piano key span implies; it is a conversion for intuition, not a
    measurement of hand travel.
    """

    semitones: float = 0.0
    metres: float = 0.0
    mean_leap: float | None = None
    max_leap: float | None = None


class TimingProfile(BaseModel):
    """Interval regularity inside phrases (gaps of 2 s or less).

    ``cv`` is the coefficient of variation of inter-attack intervals: 0 is metronomic, and
    above ~1 the intervals vary more than their own mean. Gaps longer than 2 s are phrase
    boundaries and are excluded — a pause is not an uneven rhythm.
    """

    intervals: int = 0
    mean_interval_ms: float | None = None
    cv: float | None = None


class PracticePortrait(BaseModel):
    """The note-level portrait of a window: register, touch, texture, travel, regularity.

    Deliberately a separate response from :class:`RhythmSummary`, which never reads
    ``note_events``: this one is a pass over every note in the window (roughly a second on
    the owner's million-note library) and is fetched only when the portrait is asked for,
    not when the Progress tab opens.
    """

    days: int
    window_start: str | None = None
    window_end: str
    minutes: float = 0.0
    notes: int = 0
    tz_offset_minutes: int = 0
    keyboard: RegisterProfile = Field(default_factory=RegisterProfile)
    touch: TouchProfile = Field(default_factory=TouchProfile)
    texture: TextureProfile = Field(default_factory=TextureProfile)
    travel: TravelProfile = Field(default_factory=TravelProfile)
    timing: TimingProfile = Field(default_factory=TimingProfile)
    velocity_spans: list[VelocitySpan] = Field(default_factory=list)


class SittingCloseResult(BaseModel):
    """What closing an open sitting did."""

    closed: bool
    sitting_id: int | None = None
    #: Always present, and always one of three things: 'closed', 'still playing' or
    #: 'nothing open'. The last two are different facts — the piano went quiet long
    #: ago, versus notes arrived moments ago and the sitting is being left alone — and
    #: the client needs to tell them apart to react sensibly to a device event.
    reason: Literal["closed", "still playing", "nothing open"] = "nothing open"


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
    #: Silence the *take-cutter* treats as a boundary, in seconds. Reported so the client can cut
    #: recorded audio on the same rule rather than keeping a second copy of it: audio cut
    #: somewhere else would disagree with the notes about where a passage ended.
    #:
    #: Phase 22a took this number out of the *log*'s segmentation — a stored sitting is cut by
    #: the adaptive gap in ``segment.cut``, which is not one number — so this is now the
    #: take-cutter's rule and nothing else. A take is still linked to a segment by the instant
    #: it started (``repertoire.store.segment_at``), not by sharing a boundary.
    segment_gap_s: int = 0


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
