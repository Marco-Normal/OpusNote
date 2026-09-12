"""HTTP routes for the repertoire domain.

Mounted by the main app, so the domain owns its endpoints without owning the
application object.
"""

from __future__ import annotations

import mimetypes
import shutil
import sqlite3
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from .. import db
from ..config import settings
from . import store
from .importer import LegacyDatabaseMissing, LegacySchemaUnexpected, import_legacy
from .media_pipeline import MediaError, probe, store_recording
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
        media_type=media_type or "application/octet-stream",
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


@router.delete("/pieces/{piece_id}", response_model=DeleteResult)
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


@router.delete("/composers/{composer_id}", response_model=DeleteResult)
def delete_composer(composer_id: int) -> DeleteResult:
    with db.transaction(settings.db_path) as conn:
        deleted, cascaded = store.delete_composer(conn, composer_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"no composer {composer_id}")
    return DeleteResult(deleted=True, cascaded=cascaded)


@router.post("/pieces/{piece_id}/journal", response_model=JournalEntryOut, status_code=201)
def create_journal_entry(piece_id: int, body: JournalCreate) -> JournalEntryOut:
    with db.transaction(settings.db_path) as conn:
        if not store.piece_exists(conn, piece_id):
            raise HTTPException(status_code=404, detail=f"no piece {piece_id}")
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
        if store.update_journal_entry(conn, entry_id, changes) == 0:
            raise HTTPException(status_code=404, detail=f"no journal entry {entry_id}")
        row = store.get_journal_entry(conn, entry_id)
    assert row is not None
    return JournalEntryOut(**row)


@router.delete("/journal/{entry_id}", response_model=DeleteResult)
def delete_journal_entry(entry_id: int) -> DeleteResult:
    with db.transaction(settings.db_path) as conn:
        deleted = store.delete_journal_entry(conn, entry_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"no journal entry {entry_id}")
    return DeleteResult(deleted=True)


# --------------------------------------------------------------------------
# Recording import
# --------------------------------------------------------------------------


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

    suffix = Path(file.filename or "").suffix
    media_dir = Path(settings.media_dir)
    with tempfile.TemporaryDirectory() as scratch:
        staged = Path(scratch) / f"upload{suffix}"
        with staged.open("wb") as handle:
            shutil.copyfileobj(file.file, handle, length=1024 * 1024)
        if staged.stat().st_size == 0:
            raise HTTPException(status_code=422, detail="the uploaded file is empty")
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


@router.patch("/media/{media_id}", response_model=MediaOut)
def update_recording(media_id: int, body: MediaUpdate) -> MediaOut:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="no fields to change")
    with db.transaction(settings.db_path) as conn:
        if "piece_id" in changes and changes["piece_id"] is not None:
            if not store.piece_exists(conn, int(changes["piece_id"])):
                raise HTTPException(status_code=422, detail=f"no piece {changes['piece_id']}")
        if store.update_media(conn, media_id, changes) == 0:
            raise HTTPException(status_code=404, detail=f"no recording {media_id}")
        row = store.get_media(conn, media_id)
    assert row is not None
    return MediaOut(**row)


@router.delete("/media/{media_id}", response_model=DeleteResult)
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
