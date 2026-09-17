"""HTTP routes for the repertoire domain.

Mounted by the main app, so the domain owns its endpoints without owning the
application object.
"""

from __future__ import annotations

import mimetypes
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from .. import db
from ..config import settings
from ..hostinfo import require_loopback
from ..practice import store as practice_store
from . import store
from .importer import LegacyDatabaseMissing, LegacySchemaUnexpected, import_legacy
from .media_pipeline import (
    SCORE_MEDIA_TYPES,
    MediaError,
    probe,
    store_recording,
    store_score,
)
from .models import (
    ComposerCreate,
    ComposerOut,
    ComposerUpdate,
    DeleteResult,
    ImportReport,
    ImportRequest,
    JournalCreate,
    JournalEntryOut,
    JournalUpdate,
    MediaOut,
    MediaUpdate,
    PieceCreate,
    PieceDetail,
    PieceSummary,
    PieceUpdate,
    RepertoireStatus,
)

router = APIRouter(prefix="/api/repertoire", tags=["repertoire"])


def _connection() -> sqlite3.Connection:
    """Own connection factory.

    Kept local rather than imported from the main app so this module does not
    reach into the application layer for a dependency.
    """
    from ..store import open_connection  # local import: avoids a cycle at import time

    return open_connection()


def get_conn():
    conn = _connection()
    try:
        yield conn
    finally:
        conn.close()


@router.get("/status", response_model=RepertoireStatus)
def status(conn: sqlite3.Connection = Depends(get_conn)) -> RepertoireStatus:
    counts = store.counts(conn)
    states = store.media_state_counts(conn)
    legacy = Path(settings.legacy_db)
    return RepertoireStatus(
        **counts,
        media_present=states["present"],
        media_pending=states["pending"],
        media_missing=states["missing"],
        legacy_db=str(legacy),
        legacy_found=legacy.exists(),
        media_dir=str(settings.media_dir),
    )


@router.get("/pieces", response_model=list[PieceSummary])
def pieces(
    conn: sqlite3.Connection = Depends(get_conn),
    status_filter: str | None = Query(default=None, alias="status"),
    composer_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
) -> list[PieceSummary]:
    rows = store.list_pieces(
        conn, status=status_filter, composer_id=composer_id, search=search
    )
    return [PieceSummary(**row) for row in rows]


@router.get("/pieces/{piece_id}", response_model=PieceDetail)
def piece(piece_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> PieceDetail:
    # Before the read, not after: this is the request the takes view makes, so it is the
    # moment a take recorded mid-session becomes findable under its passage.
    _catch_up_takes()
    row = store.get_piece(conn, piece_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no piece {piece_id}")
    return PieceDetail(**row)


@router.get("/composers", response_model=list[ComposerOut])
def composers(conn: sqlite3.Connection = Depends(get_conn)) -> list[ComposerOut]:
    return [ComposerOut(**row) for row in store.list_composers(conn)]


@router.get("/media/{media_id}/file")
def media_file(media_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> FileResponse:
    """Stream one recording.

    Served from our media directory when it has been copied, otherwise from the
    legacy library so recordings are playable immediately. The name comes from
    the database and is validated as a bare file name before use, so this cannot
    be walked out of either directory.
    """
    record = store.get_media(conn, media_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no recording {media_id}")

    path = store.resolve_media_path(str(record["file_name"]))
    if path is None:
        raise HTTPException(
            status_code=410,
            detail=(
                f"recording file {record['file_name']} is present in neither the media "
                "directory nor the legacy library"
            ),
        )

    media_type, _encoding = mimetypes.guess_type(str(path))
    return FileResponse(
        path,
        # A score's type comes from its stored format, because `mimetypes` does not
        # know `.musicxml` and calls `.xml` plain text — either of which makes a
        # browser download the file instead of rendering it. Recordings keep the
        # guess, which is right for the containers we produce ourselves.
        media_type=SCORE_MEDIA_TYPES.get(str(record["codec"] or ""), media_type)
        or "application/octet-stream",
        # Left inline on purpose: an <audio> element needs to stream it, not
        # download it. Starlette handles Range requests, so seeking works.
    )


@router.post("/import", response_model=ImportReport)
def run_import(body: ImportRequest) -> ImportReport:
    """Import the legacy library.

    The source path comes from configuration, never from the request, so this
    cannot be pointed at an arbitrary file on the machine. Safe to re-run: the
    metadata upserts on the original ids and copied files are skipped when
    already present.
    """
    try:
        with db.transaction(settings.db_path) as conn:
            report = import_legacy(
                conn,
                source_path=Path(settings.legacy_db),
                target_media_dir=Path(settings.media_dir),
                copy_media=body.copy_media,
            )
            states = store.media_state_counts(conn)
    except LegacyDatabaseMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LegacySchemaUnexpected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ImportReport(
        source_db=report.source_db,
        source_found=True,
        composers=report.composers,
        pieces=report.pieces,
        journal_entries=report.journal_entries,
        media_rows=report.media_rows,
        media_copied=report.media_copied,
        media_missing=report.media_missing,
        media_pending=states["pending"],
        skipped=report.skipped,
        notes=report.notes,
    )


# --------------------------------------------------------------------------
# Editing
#
# Every mutation runs inside `db.transaction`, so a request either lands whole or
# not at all. None of these delete a recording *file*: deleting a piece removes
# its catalogue rows and leaves the audio on disk.
# --------------------------------------------------------------------------


def _validate_composer(conn: sqlite3.Connection, composer_id: int | None) -> None:
    if composer_id is not None and not store.composer_exists(conn, composer_id):
        raise HTTPException(status_code=422, detail=f"no composer {composer_id}")


def _validate_sitting(conn: sqlite3.Connection, sitting_id: int | None) -> None:
    """Refuse a sitting that is not in the log, so a stale id is a 422.

    Without this the foreign key raises, and a mistyped or out-of-date id reaches
    the client as a 500 with nothing in it to act on.
    """
    if sitting_id is not None and not store.sitting_exists(conn, sitting_id):
        raise HTTPException(status_code=422, detail=f"no sitting {sitting_id}")


@router.post("/pieces", response_model=PieceDetail, status_code=201)
def create_piece(body: PieceCreate) -> PieceDetail:
    with db.transaction(settings.db_path) as conn:
        _validate_composer(conn, body.composer_id)
        piece_id = store.create_piece(conn, body.model_dump())
        row = store.get_piece(conn, piece_id)
    assert row is not None
    return PieceDetail(**row)


@router.patch("/pieces/{piece_id}", response_model=PieceDetail)
def update_piece(piece_id: int, body: PieceUpdate) -> PieceDetail:
    # `exclude_unset` is what makes this a PATCH: a field the client omitted is
    # left alone, while an explicit null clears it.
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="no fields to change")
    with db.transaction(settings.db_path) as conn:
        if "composer_id" in changes:
            _validate_composer(conn, changes["composer_id"])
        updated = store.update_piece(conn, piece_id, changes)
        if updated == 0:
            raise HTTPException(status_code=404, detail=f"no piece {piece_id}")
        row = store.get_piece(conn, piece_id)
    assert row is not None
    return PieceDetail(**row)


@router.delete("/pieces/{piece_id}", response_model=DeleteResult, dependencies=[Depends(require_loopback)])
def delete_piece(piece_id: int) -> DeleteResult:
    with db.transaction(settings.db_path) as conn:
        deleted, cascaded = store.delete_piece(conn, piece_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"no piece {piece_id}")
    return DeleteResult(deleted=True, cascaded=cascaded)


@router.post("/composers", response_model=ComposerOut, status_code=201)
def create_composer(body: ComposerCreate) -> ComposerOut:
    with db.transaction(settings.db_path) as conn:
        composer_id = store.create_composer(conn, body.model_dump())
        row = next(
            (item for item in store.list_composers(conn) if item["id"] == composer_id), None
        )
    assert row is not None
    return ComposerOut(**row)


@router.patch("/composers/{composer_id}", response_model=ComposerOut)
def update_composer(composer_id: int, body: ComposerUpdate) -> ComposerOut:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="no fields to change")
    with db.transaction(settings.db_path) as conn:
        if store.update_composer(conn, composer_id, changes) == 0:
            raise HTTPException(status_code=404, detail=f"no composer {composer_id}")
        row = next(
            (item for item in store.list_composers(conn) if item["id"] == composer_id), None
        )
    assert row is not None
    return ComposerOut(**row)


@router.delete("/composers/{composer_id}", response_model=DeleteResult, dependencies=[Depends(require_loopback)])
def delete_composer(composer_id: int) -> DeleteResult:
    with db.transaction(settings.db_path) as conn:
        deleted, cascaded = store.delete_composer(conn, composer_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"no composer {composer_id}")
    return DeleteResult(deleted=True, cascaded=cascaded)


@router.get("/journal", response_model=list[JournalEntryOut])
def journal_feed(
    limit: int = Query(default=50, ge=1, le=500),
    search: str | None = Query(default=None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> list[JournalEntryOut]:
    """The newest entries across the whole library.

    A piece's own page returns its journal inline; this is the other direction, so
    a note written months ago can be found without remembering the piece, and so
    the search box can answer a question about the prose rather than only about a
    title.
    """
    return [JournalEntryOut(**row) for row in store.list_journal_entries(conn, limit=limit, search=search)]


@router.post("/pieces/{piece_id}/journal", response_model=JournalEntryOut, status_code=201)
def create_journal_entry(piece_id: int, body: JournalCreate) -> JournalEntryOut:
    with db.transaction(settings.db_path) as conn:
        if not store.piece_exists(conn, piece_id):
            raise HTTPException(status_code=404, detail=f"no piece {piece_id}")
        _validate_sitting(conn, body.sitting_id)
        entry_id = store.create_journal_entry(conn, piece_id, body.model_dump())
        row = store.get_journal_entry(conn, entry_id)
    assert row is not None
    return JournalEntryOut(**row)


@router.patch("/journal/{entry_id}", response_model=JournalEntryOut)
def update_journal_entry(entry_id: int, body: JournalUpdate) -> JournalEntryOut:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="no fields to change")
    with db.transaction(settings.db_path) as conn:
        _validate_sitting(conn, changes.get("sitting_id"))
        if store.update_journal_entry(conn, entry_id, changes) == 0:
            raise HTTPException(status_code=404, detail=f"no journal entry {entry_id}")
        row = store.get_journal_entry(conn, entry_id)
    assert row is not None
    return JournalEntryOut(**row)


@router.delete("/journal/{entry_id}", response_model=DeleteResult, dependencies=[Depends(require_loopback)])
def delete_journal_entry(entry_id: int) -> DeleteResult:
    with db.transaction(settings.db_path) as conn:
        deleted = store.delete_journal_entry(conn, entry_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"no journal entry {entry_id}")
    return DeleteResult(deleted=True)


# --------------------------------------------------------------------------
# Recording import
# --------------------------------------------------------------------------


def _stage_upload(file: UploadFile, *, scratch: Path, what: str) -> Path:
    """Write one upload to a scratch path, enforcing the size cap while writing.

    Shared by recordings and scores so the cap cannot be enforced in one path and
    forgotten in the other.

    Two checks, and it is worth being exact about which one does the work. **Through the
    HTTP route only the first can fire**: FastAPI parses the whole multipart body before the
    route runs, so by the time this is reached the bytes have already been received and
    `file.size` is known and exact. The cap therefore protects the *media directory* — an
    oversized upload is refused before it is converted, hashed and stored — and not the disk,
    because by then the disk has already taken it. `test_the_endpoint_always_declares_a_size`
    pins that, so a future parser that stops declaring a size fails the suite rather than
    silently promoting the second check to the only one.

    The second check, on the bytes as they arrive, is a backstop for a path that streams
    rather than buffers. It is tested by calling this function directly, which is the only
    way to reach it.
    """
    limit_bytes = settings.max_upload_mb * 1024 * 1024
    if file.size is not None and file.size > limit_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"the {what} is larger than {settings.max_upload_mb} MB",
        )

    suffix = Path(file.filename or "").suffix
    staged = scratch / f"upload{suffix}"
    written = 0
    with staged.open("wb") as handle:
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)
            if written > limit_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"the {what} is larger than {settings.max_upload_mb} MB",
                )
            handle.write(chunk)
    if staged.stat().st_size == 0:
        raise HTTPException(status_code=422, detail="the uploaded file is empty")
    return staged


@router.post("/pieces/{piece_id}/media", response_model=MediaOut, status_code=201)
def upload_recording(
    piece_id: int,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
) -> MediaOut:
    """Import one recording: probe, convert, hash, store, catalogue.

    Synchronous on purpose. A conversion takes seconds and this is a
    single-player local app; a job queue would add moving parts and a status
    endpoint to poll, for no benefit at this scale.
    """
    with db.transaction(settings.db_path) as conn:
        if not store.piece_exists(conn, piece_id):
            raise HTTPException(status_code=404, detail=f"no piece {piece_id}")

    media_dir = Path(settings.media_dir)
    with tempfile.TemporaryDirectory() as scratch:
        staged = _stage_upload(file, scratch=Path(scratch), what="recording")
        try:
            staged_info = probe(staged)
        except MediaError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        with db.transaction(settings.db_path) as conn:
            # Refused outright rather than behind a `force` flag. Adding a second
            # catalogue row for the same recording is not something the library
            # should be able to do: the file name is content-addressed and
            # unique, so "forced" duplicates would either collide or quietly
            # double the storage this design exists to avoid.
            similar = store.find_similar_recording(
                conn, duration_secs=staged_info.duration_secs
            )
            if similar is not None:
                label = similar["title"] or similar["original_name"] or similar["file_name"]
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"a recording of the same length is already in the library "
                        f"(id {similar['id']}, {label})"
                    ),
                )
            try:
                stored = store_recording(
                    staged, media_dir=media_dir, original_name=file.filename
                )
            except MediaError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

            media_id = store.create_media(
                conn,
                piece_id=piece_id,
                kind=stored.kind,
                file_name=stored.file_name,
                original_name=file.filename,
                title=title,
                duration_secs=stored.duration_secs,
                size_bytes=stored.size_bytes,
                codec=stored.codec,
            )
            row = store.get_media(conn, media_id)

    assert row is not None
    return MediaOut(**row)


# --------------------------------------------------------------------------
# Captured takes
# --------------------------------------------------------------------------


def _catch_up_takes() -> int:
    """Attach captured takes whose segments have appeared since they were uploaded.

    A recorder cuts audio eight seconds after the player stops, and the practice domain only
    segments a sitting once it has closed — five minutes of silence, or the piano going away.
    So a take is almost always catalogued before the segment it belongs to exists, and the
    delayed half is this: run on every take upload and on the piece read the takes view makes.

    Two steps, and the order is the whole point. `ensure_segments` is the practice domain's own
    read-through materialisation, so it is the practice domain that writes `segments` and it
    refuses a sitting that is still open, which is exactly right — a provisional boundary would
    be permanent. The sweep that follows writes only `media`, which is this domain's table.
    Neither domain reaches into the other's writes.
    """
    with db.transaction(settings.db_path) as conn:
        waiting = store.unlinked_take_sittings(conn)
    for sitting_id in waiting:
        practice_store.ensure_segments(sitting_id)
    # `immediate`: the sweep reads `media` and then writes the rows it read, which a deferred
    # transaction cannot do safely — a connection committing in between turns the write into
    # "database is locked" instead of waiting, and this runs on a plain piece read.
    with db.transaction(settings.db_path, immediate=True) as conn:
        return store.link_unlinked_takes(conn)


@router.post("/takes", response_model=MediaOut, status_code=201)
def upload_take(
    file: UploadFile = File(...),
    # Bounded, so a nonsense epoch is a 422 rather than an OverflowError from sqlite3. The
    # ceiling is 2100-01-01 in ms: past it, the value is a bug and not a clock.
    started_ms: int = Form(..., ge=0, le=4_102_444_800_000),
    title: str | None = Form(default=None),
) -> MediaOut:
    """Catalogue one captured take and attach it to the playing it came from.

    The client cannot name a segment: it cut the audio on the server's silence rule, before the
    server had made any segments at all. So it sends the absolute epoch the chunk started at —
    the same reasoning the note wire format uses — and this resolves the sitting, then the
    segment inside it, then the piece the segment is labelled with.

    A take uploaded while its sitting is still open gets the sitting and no segment; the piece
    read in the takes view attaches it once the sitting has closed.
    """
    _catch_up_takes()
    with db.transaction(settings.db_path) as conn:
        sitting_id = store.sitting_at(conn, started_ms)
        if sitting_id is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "no sitting covers that time, so this take cannot be placed; "
                    "the capture heartbeat and the sitting gap decide where a playing begins"
                ),
            )

    media_dir = Path(settings.media_dir)
    with tempfile.TemporaryDirectory() as scratch:
        staged = _stage_upload(file, scratch=Path(scratch), what="take")
        try:
            stored = store_recording(staged, media_dir=media_dir, original_name=file.filename)
        except MediaError as exc:
            # The same 422 the recording upload gives: an unnamed blob and a file that is not
            # audio are the caller's problem, not a server fault. `store_recording` probes as
            # part of its own work, so this is the only probe on the path.
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # `immediate`: this reads the row it is about to insert (the duplicate check), and two
        # identical uploads racing on a deferred transaction would both pass it — the loser
        # getting a 500 instead of the 409 this route documents.
        with db.transaction(settings.db_path, immediate=True) as conn:
            # Resolved here rather than before the transcode: a `resegment` running while
            # ffmpeg works would otherwise leave this pointing at a segment that no longer
            # exists, and the insert would fail as a bare foreign-key error.
            found = store.segment_at(conn, sitting_id, started_ms)
            # Content-addressed storage means an identical take is one file, so the
            # second row would collide on the unique name. Asking first says where it
            # already lives instead of surfacing a bare integrity error.
            existing = store.find_media_by_file_name(conn, stored.file_name)
            if existing is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "that take is byte-for-byte identical to one already in the library "
                        f"(id {existing['id']})"
                    ),
                )
            take_id = store.create_media(
                conn,
                piece_id=found[1] if found is not None else None,
                kind=stored.kind,
                file_name=stored.file_name,
                original_name=file.filename,
                title=title or "Take",
                duration_secs=stored.duration_secs,
                size_bytes=stored.size_bytes,
                codec=stored.codec,
                taken_on=datetime.now(timezone.utc).date().isoformat(),
                source="captured",
                sitting_id=sitting_id,
                segment_id=found[0] if found is not None else None,
                captured_start_ms=started_ms,
            )
            row = store.get_media(conn, take_id)

    assert row is not None
    return MediaOut(**row)


# --------------------------------------------------------------------------
# Scores
# --------------------------------------------------------------------------


@router.post("/pieces/{piece_id}/scores", response_model=MediaOut, status_code=201)
def upload_score(
    piece_id: int,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
) -> MediaOut:
    """Attach a score: validate it, hash it, store it, catalogue it.

    No ffmpeg anywhere in this path. A score is not probed (its bytes are the
    only honest description of it) and not re-encoded (the browser draws a PDF
    and OSMD reads MusicXML), so the file is stored exactly as uploaded — which
    also means what you read in the app is the edition you chose.
    """
    with db.transaction(settings.db_path) as conn:
        if not store.piece_exists(conn, piece_id):
            raise HTTPException(status_code=404, detail=f"no piece {piece_id}")

    media_dir = Path(settings.media_dir)
    with tempfile.TemporaryDirectory() as scratch:
        staged = _stage_upload(file, scratch=Path(scratch), what="score")
        try:
            stored = store_score(staged, media_dir=media_dir, original_name=file.filename)
        except MediaError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        with db.transaction(settings.db_path) as conn:
            # The stored name is the content hash, so the same document uploaded
            # twice is one file and the second row would collide. Refused with the
            # place it already lives: a score attached to the wrong piece can be
            # moved, and knowing where it is beats a bare integrity error.
            existing = store.find_media_by_file_name(conn, stored.file_name)
            if existing is not None:
                where = existing["piece_title"] or f"piece {existing['piece_id']}"
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"this exact score is already attached to {where} "
                        f"(id {existing['id']})"
                    ),
                )
            media_id = store.create_media(
                conn,
                piece_id=piece_id,
                kind=stored.kind,
                file_name=stored.file_name,
                original_name=file.filename,
                title=title,
                duration_secs=None,
                size_bytes=stored.size_bytes,
                codec=stored.codec,
            )
            row = store.get_media(conn, media_id)

    assert row is not None
    return MediaOut(**row)


#: A loop this short is a mis-click, not a passage: the browser's own seek
#: granularity is coarser than this, so it would not loop the same audio twice.
MIN_LOOP_S = 0.2

#: How far past the stored duration an end marker may sit. ffprobe's duration is
#: a container estimate, and an Ogg/Opus stream's declared length can be a
#: fraction of a second short.
LOOP_DURATION_SLACK_S = 0.5


def _check_loop(conn: sqlite3.Connection, media_id: int, changes: dict) -> None:
    """Validate an A/B loop against the row's *resulting* state.

    A loop is a property of two numbers, and a PATCH may carry either one alone —
    the player sets A and then B — so the check has to merge the request with what
    is already stored rather than look at the payload on its own.
    """
    record = store.get_media(conn, media_id)
    if record is None:
        return  # the update itself reports the 404

    if record["kind"] == "score":
        raise HTTPException(status_code=422, detail="a score has no recording to loop")

    start = changes.get("loop_start_s", record["loop_start_s"])
    end = changes.get("loop_end_s", record["loop_end_s"])
    start = float(start) if start is not None else None
    end = float(end) if end is not None else None

    if start is not None and end is not None:
        if end - start < MIN_LOOP_S:
            raise HTTPException(
                status_code=422,
                detail=f"a loop must be at least {MIN_LOOP_S:g}s long (got {end - start:g}s)",
            )
        duration = record["duration_secs"]
        if duration is not None and end > float(duration) + LOOP_DURATION_SLACK_S:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"the recording is {float(duration):.1f}s long, so a loop cannot end "
                    f"at {end:.1f}s"
                ),
            )


@router.patch("/media/{media_id}", response_model=MediaOut)
def update_recording(media_id: int, body: MediaUpdate) -> MediaOut:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="no fields to change")
    with db.transaction(settings.db_path) as conn:
        if "piece_id" in changes and changes["piece_id"] is not None:
            if not store.piece_exists(conn, int(changes["piece_id"])):
                raise HTTPException(status_code=422, detail=f"no piece {changes['piece_id']}")
        if "loop_start_s" in changes or "loop_end_s" in changes:
            _check_loop(conn, media_id, changes)
        if store.update_media(conn, media_id, changes) == 0:
            raise HTTPException(status_code=404, detail=f"no recording {media_id}")
        row = store.get_media(conn, media_id)
    assert row is not None
    return MediaOut(**row)


@router.delete("/media/{media_id}", response_model=DeleteResult, dependencies=[Depends(require_loopback)])
def delete_recording(media_id: int) -> DeleteResult:
    """Remove a recording from the library.

    The file is removed only from *our* copy, and only when no other row
    references it — the same content-hashed file can legitimately be attached to
    more than one piece. A file that only exists in the legacy library is never
    touched: that directory belongs to the app we are replacing.
    """
    with db.transaction(settings.db_path) as conn:
        deleted, file_name, still_referenced = store.delete_media(conn, media_id)

    if deleted == 0 or file_name is None:
        raise HTTPException(status_code=404, detail=f"no recording {media_id}")

    removed_file = 0
    if not still_referenced:
        own = Path(settings.media_dir) / file_name
        if own.exists():
            own.unlink()
            removed_file = 1

    return DeleteResult(deleted=True, cascaded={"files_removed": removed_file})
