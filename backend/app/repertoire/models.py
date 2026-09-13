"""Request and response shapes for the repertoire domain."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PieceStatus = Literal["active", "completed", "paused"]

#: Upper bound for an A/B loop marker. Nothing here is longer than a couple of
#: hours, and a bound is what stops a nonsense value (a wrong unit, a stray
#: multiplication) from being stored as a place in the recording that does not
#: exist.
MAX_LOOP_SECONDS = 24 * 60 * 60.0


class ComposerOut(BaseModel):
    id: int
    name: str
    notes: str | None = None
    piece_count: int = 0


class JournalEntryOut(BaseModel):
    id: int
    piece_id: int
    entry_date: str
    content: str
    practice_minutes: int | None = None
    created_at: str | None = None


class MediaOut(BaseModel):
    id: int
    piece_id: int | None = None
    kind: str
    file_name: str
    original_name: str | None = None
    title: str | None = None
    duration_secs: float | None = None
    size_bytes: int | None = None
    codec: str | None = None
    taken_on: str | None = None
    #: The A/B practice loop, in seconds into the stored file. Either marker may
    #: be set alone — the player sets A, then B — so `None` means "not marked"
    #: rather than "the beginning" or "the end".
    loop_start_s: float | None = None
    loop_end_s: float | None = None
    #: present  — copied into our media directory
    #: pending  — not copied yet, but readable from the legacy library
    #: missing  — in neither place
    state: Literal["present", "pending", "missing"] = "missing"


class PieceSummary(BaseModel):
    id: int
    title: str
    composer_id: int | None = None
    composer_name: str | None = None
    opus: str | None = None
    difficulty: str | None = None
    key: str | None = None
    status: str
    started_on: str | None = None
    journal_entries: int = 0
    logged_minutes: int = 0
    recording_count: int = 0
    #: Attached scores (PDF or MusicXML), counted apart from recordings so
    #: "3 recordings" never turns out to include a PDF.
    score_count: int = 0


class PieceDetail(PieceSummary):
    description: str | None = None
    created_at: str | None = None
    journal: list[JournalEntryOut] = Field(default_factory=list)
    media: list[MediaOut] = Field(default_factory=list)


class ImportRequest(BaseModel):
    """Import from the legacy `piano-progress` database.

    The source path is *not* taken from the request: it comes from configuration,
    so this endpoint cannot be pointed at an arbitrary file on the machine.
    """

    copy_media: bool = Field(
        # Copying by default: a library whose recordings all read "missing" is
        # the wrong first impression, and the copy is what makes the app
        # self-contained rather than pointing back at the old app's directory.
        default=True,
        description="Copy recording files into the ecosystem media directory",
    )


class ImportReport(BaseModel):
    source_db: str
    source_found: bool
    composers: int = 0
    pieces: int = 0
    journal_entries: int = 0
    media_rows: int = 0
    media_copied: int = 0
    media_missing: int = 0
    #: Still readable from the legacy library but not copied into ours.
    media_pending: int = 0
    skipped: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class RepertoireStatus(BaseModel):
    pieces: int
    composers: int
    journal_entries: int
    media_rows: int
    #: Attached scores, which are media rows with `kind='score'`.
    scores: int = 0
    media_present: int
    media_pending: int
    media_missing: int
    #: Where the legacy database would be read from, and whether it is there.
    legacy_db: str
    legacy_found: bool
    media_dir: str


# --------------------------------------------------------------------------
# Editing
# --------------------------------------------------------------------------

#: Dates are stored as text and compared with SQL date functions, so the format
#: is part of the contract rather than a display choice.
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


class PieceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    composer_id: int | None = None
    opus: str | None = Field(default=None, max_length=120)
    difficulty: str | None = Field(default=None, max_length=60)
    key: str | None = Field(default=None, max_length=40)
    started_on: str | None = Field(default=None, pattern=DATE_PATTERN)
    status: PieceStatus = "active"
    description: str | None = None


class PieceUpdate(BaseModel):
    """PATCH body.

    Unset fields are left alone; an explicit `null` clears the column. That
    distinction is why this is not the same model as `PieceCreate`.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    composer_id: int | None = None
    opus: str | None = Field(default=None, max_length=120)
    difficulty: str | None = Field(default=None, max_length=60)
    key: str | None = Field(default=None, max_length=40)
    started_on: str | None = Field(default=None, pattern=DATE_PATTERN)
    status: PieceStatus | None = None
    description: str | None = None


class ComposerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    notes: str | None = None


class ComposerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    notes: str | None = None


class JournalCreate(BaseModel):
    entry_date: str = Field(pattern=DATE_PATTERN)
    content: str = Field(min_length=1)
    practice_minutes: int | None = Field(default=None, ge=0, le=24 * 60)


class JournalUpdate(BaseModel):
    entry_date: str | None = Field(default=None, pattern=DATE_PATTERN)
    content: str | None = Field(default=None, min_length=1)
    practice_minutes: int | None = Field(default=None, ge=0, le=24 * 60)


class DeleteResult(BaseModel):
    deleted: bool
    #: Rows removed alongside the one asked for. Recording *files* are never
    #: deleted — see the note in the API route.
    cascaded: dict[str, int] = Field(default_factory=dict)


class MediaUpdate(BaseModel):
    """Re-title a media row, move it to another piece, or set its A/B loop.

    Unset fields are left alone and an explicit `null` clears the column, which is
    how both loop markers are removed (send `{"loop_start_s": null, "loop_end_s":
    null}`). The pair is validated together against the row's current values in
    the route, because "start is before end" is a property of the two, not of
    either one.
    """

    title: str | None = Field(default=None, max_length=200)
    piece_id: int | None = None
    loop_start_s: float | None = Field(
        default=None, ge=0, le=MAX_LOOP_SECONDS, description="Seconds into the file"
    )
    loop_end_s: float | None = Field(
        default=None, ge=0, le=MAX_LOOP_SECONDS, description="Seconds into the file"
    )
