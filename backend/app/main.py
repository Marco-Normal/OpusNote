"""FastAPI application.

The API is intentionally thin: it validates input, calls one service function,
and returns the result. That is the whole contract with the browser, so the
generator, scorer, and adaptive engine can all be replaced behind it.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlite3 import Connection

from . import backup, piano, services, store
from .backup import router as backup_router
from .config import settings
from .db import CorruptJSON, init_db
from .hostinfo import require_loopback, router as hostinfo_router
from .models import (
    ExerciseOut,
    HealthOut,
    MediaStates,
    PerformanceDetail,
    ProfileOut,
    RatingHistory,
    RatingPoint,
    ScoreRequest,
    SkillOut,
    SkillRatingSeries,
    SystemStatus,
)
from .adaptive.elo import MAX_LEVEL, MIN_LEVEL
from .practice.api import router as practice_router
from .repertoire.api import router as repertoire_router
from .skills_data import HAND_CHOICES, SKILLS, SKILLS_BY_SLUG, SKILL_SLUGS, level_for_key
from .workout import store as workout_store
from .workout.api import router as workout_router

USER_ID: int | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global USER_ID
    init_db(settings.db_path)
    USER_ID = services.init_workspace()
    yield


app = FastAPI(
    title="Opus Note API",
    version="0.1.0",
    description="Generates level-appropriate sight-reading exercises and scores MIDI performances.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(CorruptJSON)
def corrupt_json(request: Request, exc: CorruptJSON) -> JSONResponse:
    """A stored row is damaged; say what is damaged and fail loudly.

    Without this the exception is a bare Starlette traceback in the log and a generic 500
    on the wire, which hides the one thing the operator needs — *which* row is corrupt and
    what it contains. T9: visible at the piano, not "no expected notes" three weeks later.
    """
    return JSONResponse(status_code=500, content={"detail": str(exc)})


app.include_router(repertoire_router)
app.include_router(practice_router)
app.include_router(workout_router)
app.include_router(backup_router)
app.include_router(hostinfo_router)


def get_conn() -> Iterator[Connection]:
    conn = store.open_connection()
    try:
        yield conn
    finally:
        conn.close()


def current_user_id() -> int:
    global USER_ID
    if USER_ID is None:
        USER_ID = services.init_workspace()
    return USER_ID


@app.get("/api/health", response_model=HealthOut)
def health(conn: Connection = Depends(get_conn)) -> HealthOut:
    exercises = conn.execute("SELECT COUNT(*) AS n FROM exercises").fetchone()["n"]
    performances = conn.execute("SELECT COUNT(*) AS n FROM performances").fetchone()["n"]
    return HealthOut(
        status="ok",
        database=str(settings.db_path),
        exercises=int(exercises),
        performances=int(performances),
    )


@app.get("/api/profile", response_model=ProfileOut)
def profile(conn: Connection = Depends(get_conn)) -> ProfileOut:
    user_id = current_user_id()
    ratings = store.get_ratings(conn, user_id)
    user_row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    return ProfileOut(
        user_id=user_id,
        username=user_row["username"] if user_row else settings.default_username,
        default_rating=settings.default_rating,
        pass_threshold=settings.pass_threshold,
        exercise_bars=settings.exercise_bars,
        calibration_total=settings.calibration_length,
        calibration_step=min(store.calibration_progress(conn, user_id), settings.calibration_length),
        ratings=ratings,
        levels={slug: _level_for(ratings.get(slug, settings.default_rating)) for slug in SKILL_SLUGS},
    )


@app.post(
    "/api/profile/reset",
    response_model=ProfileOut,
    dependencies=[Depends(require_loopback)],
)
def reset_profile(conn: Connection = Depends(get_conn)) -> ProfileOut:
    user_id = current_user_id()
    services.reset_profile(conn, user_id)
    return profile(conn)


@app.get("/api/skills", response_model=list[SkillOut])
def skills(conn: Connection = Depends(get_conn)) -> list[SkillOut]:
    user_id = current_user_id()
    rows = {row["slug"]: row for row in store.get_skill_rows(conn, user_id)}
    out: list[SkillOut] = []
    for spec in SKILLS:
        row = rows.get(spec.slug, {})
        rating = float(row.get("elo_rating") or settings.default_rating)
        out.append(
            SkillOut(
                slug=spec.slug,
                name=spec.name,
                description=spec.description,
                levels=list(spec.levels),
                rating=rating,
                level=_level_for(rating),
                attempts=int(row.get("attempts") or 0),
                last_practiced_at=row.get("last_practiced_at"),
            )
        )
    return out


def _level_for(rating: float) -> int:
    """The level of material this rating is worked at.

    Not the level the rating "is": the selector aims below the rating on purpose, so
    that is the level the player actually sees in an exercise.
    """
    from .adaptive.elo import selection_level

    return selection_level(rating)


@app.get("/api/exercise/next", response_model=ExerciseOut)
def exercise_next(
    conn: Connection = Depends(get_conn),
    skill: str | None = Query(default=None, description="Force a skill dimension"),
    bars: int | None = Query(default=None, ge=1, le=16),
    key: str | None = Query(default=None, description="Pin the key, e.g. 'B' or 'c#'"),
    level: int | None = Query(
        default=None,
        ge=MIN_LEVEL,
        le=MAX_LEVEL,
        description="Pin the difficulty: every dimension at this level, and unrated",
    ),
    hands: str | None = Query(
        default=None,
        description="Pin what you read: 'RH', 'LH' or 'both', at any level",
    ),
) -> ExerciseOut:
    if skill is not None and skill not in SKILL_SLUGS:
        raise HTTPException(status_code=422, detail=f"unknown skill {skill!r}")
    if key is not None and level_for_key(key) is None:
        raise HTTPException(status_code=422, detail=f"unknown key {key!r}")
    if hands is not None and hands not in HAND_CHOICES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown hands {hands!r}; expected one of {', '.join(HAND_CHOICES)}",
        )
    payload = services.next_exercise(
        conn,
        current_user_id(),
        skill=skill,
        bars=bars,
        key_name=key,
        pin_level=level,
        forced_hand=hands,
    )
    return ExerciseOut(**payload)


@app.get("/api/exercise/{exercise_id}", response_model=ExerciseOut)
def exercise_by_id(exercise_id: int, conn: Connection = Depends(get_conn)) -> ExerciseOut:
    exercise = store.get_exercise(conn, exercise_id)
    if exercise is None:
        raise HTTPException(status_code=404, detail="exercise not found")
    return ExerciseOut(
        exercise_id=exercise["id"],
        musicxml=exercise["musicxml_blob"],
        tempo_bpm=exercise["tempo_bpm"],
        bars=exercise["bars"],
        key_name=exercise["key_name"],
        meter=exercise["meter"],
        levels=exercise.get("levels", {}),
        difficulty_elo=exercise["difficulty_elo"],
        target_skill=exercise.get("target_skill"),
        source=exercise.get("source", "generated"),
        expected_notes=[note.to_dict() for note in exercise["expected"]],
        measures=exercise.get("measures", []),
        bass_pattern=exercise.get("bass_pattern"),
    )


@app.get("/api/calibration/next", response_model=ExerciseOut)
def calibration_next(conn: Connection = Depends(get_conn)) -> ExerciseOut:
    payload = services.calibration_exercise(conn, current_user_id())
    if payload.get("complete"):
        return ExerciseOut(
            exercise_id=payload["next"]["exercise_id"],
            musicxml=payload["next"]["musicxml"],
            tempo_bpm=payload["next"]["tempo_bpm"],
            bars=payload["next"]["bars"],
            key_name=payload["next"]["key_name"],
            meter=payload["next"]["meter"],
            levels=payload["next"]["levels"],
            difficulty_elo=payload["next"]["difficulty_elo"],
            target_skill=payload["next"]["target_skill"],
            source=payload["next"]["source"],
            expected_notes=payload["next"]["expected_notes"],
            measures=payload["next"].get("measures", []),
            bass_pattern=payload["next"].get("bass_pattern"),
            rationale="Calibration complete — this is a normal adaptive exercise.",
            complete=True,
            step=payload["step"],
            total=payload["total"],
        )
    return ExerciseOut(**payload)


@app.post("/api/score")
def score(payload: ScoreRequest, conn: Connection = Depends(get_conn)) -> JSONResponse:
    try:
        result = services.record_performance(
            conn,
            current_user_id(),
            exercise_id=payload.exercise_id,
            played=[note.model_dump() for note in payload.notes],
            mode=payload.mode,
            latency_ms=payload.latency_ms,
            calibration=payload.calibration,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # Attribution happens here, after scoring, so a workout lookup can never cost
    # a performance: without a running workout this is a no-op and the attempt is
    # ordinary sight-reading, which is what it is.
    result["workout_id"] = workout_store.attach_performance(
        conn, int(result["performance_id"])
    )
    return JSONResponse(result)


@app.get("/api/practice-suggestions")
def practice_suggestions(conn: Connection = Depends(get_conn)) -> JSONResponse:
    """Repertoire the sight-reading side could build exercises around.

    Cross-domain, so it lives here rather than in either domain: the repertoire
    router has no business knowing about skill levels, and the adaptive engine has
    no business reading the library.
    """
    from .bridge import suggest_for_piece
    from .repertoire import store as repertoire_store

    active_only = [
        row
        for row in repertoire_store.list_pieces(conn)
        if row["status"] != "completed"
    ]
    suggestions = [
        suggest_for_piece(
            piece_id=row["id"],
            title=row["title"],
            composer_name=row["composer_name"],
            piece_key=row["key"],
            difficulty=row["difficulty"],
            status=row["status"],
        )
        for row in active_only
    ]
    return JSONResponse(
        [
            {
                "piece_id": item.piece_id,
                "title": item.title,
                "composer_name": item.composer_name,
                "piece_key": item.piece_key,
                "suggested_key": item.suggested_key,
                "difficulty": item.difficulty,
                "suggested_level": item.suggested_level,
                "notes": item.notes,
            }
            for item in suggestions
        ]
    )


@app.get("/api/status/system", response_model=SystemStatus)
def system_status(conn: Connection = Depends(get_conn)) -> SystemStatus:
    """The health of the installation, in one read.

    Cross-domain on purpose, so it lives in the composition root like
    `/api/practice-suggestions`: it reports a fact about each domain rather than
    belonging to one, and putting it in any of them would make that domain import the
    others.
    """
    from . import hostinfo
    from .practice import capture_status
    from .repertoire import store as repertoire_store

    db_path = settings.db_path
    wal = Path(str(db_path) + "-wal")
    # The directory comes from here rather than from the helper's own default, so the
    # route reports the same place it is configured to write to.
    latest = backup.latest_backup(settings.backup_dir)
    backups = (
        sorted(settings.backup_dir.glob("piano-ecosystem-*.json"))
        if settings.backup_dir.exists()
        else []
    )
    last_note = conn.execute("SELECT MAX(ended_ms) AS last_ms FROM sittings").fetchone()
    return SystemStatus(
        database_path=str(db_path),
        database_bytes=db_path.stat().st_size if db_path.exists() else 0,
        wal_bytes=wal.stat().st_size if wal.exists() else 0,
        media_dir=str(settings.media_dir),
        media=MediaStates(**repertoire_store.media_state_counts(conn)),
        backup_dir=str(settings.backup_dir),
        last_backup=latest.name if latest else None,
        last_backup_seconds=(
            round(time.time() - latest.stat().st_mtime, 1) if latest else None
        ),
        backup_count=len(backups),
        sequencer=hostinfo.sequencer_available(),
        alsa_clients=hostinfo.alsa_clients(),
        capture=capture_status.snapshot(),
        last_note_ms=(
            int(last_note["last_ms"]) if last_note and last_note["last_ms"] is not None else None
        ),
        latency_suggestion_ms=store.onset_bias_ms(conn, current_user_id()),
        latency_current_ms=0.0,
        captured_audio_bytes=repertoire_store.captured_bytes(conn),
    )


@app.get("/api/progress/ratings", response_model=RatingHistory)
def progress_ratings(
    conn: Connection = Depends(get_conn),
    days: int = Query(default=90, ge=1, le=3650),
) -> RatingHistory:
    """Every rating change in the window, grouped by skill.

    `user_skills` holds one number per skill, so a curve has to come from the recorded
    changes. Skills with no movement in the window are absent rather than present with
    an empty series, so the client can say "nothing changed" instead of drawing nine
    flat lines.
    """
    series = store.rating_series(conn, current_user_id(), days=days)
    skills = []
    biggest: tuple[str, float] | None = None
    for slug in SKILL_SLUGS:
        points = series.get(slug)
        if not points:
            continue
        spec = SKILLS_BY_SLUG[slug]
        skills.append(SkillRatingSeries(slug=slug, name=spec.name, points=points))
        total = round(sum(point["delta"] for point in points), 2)
        if biggest is None or total > biggest[1]:
            biggest = (spec.name, total)
    return RatingHistory(
        days=days,
        skills=skills,
        biggest_gain=biggest[0] if biggest else None,
        biggest_gain_delta=biggest[1] if biggest else 0.0,
    )


@app.get("/api/performances/{performance_id}", response_model=PerformanceDetail)
def performance_detail(
    performance_id: int, conn: Connection = Depends(get_conn)
) -> PerformanceDetail:
    """One past attempt: the score, the notes as written, the notes as played.

    Stored when the attempt happened, so this is a read rather than a reconstruction —
    and it is what lets a history row be opened and heard instead of only counted.
    """
    row = store.performance_detail(conn, performance_id, current_user_id())
    if row is None:
        raise HTTPException(status_code=404, detail="performance not found")
    return PerformanceDetail(
        performance_id=row["id"],
        exercise_id=row["exercise_id"],
        score=row["score"],
        pitch_accuracy=row["pitch_accuracy"],
        rhythm_accuracy=row["rhythm_accuracy"],
        continuity_accuracy=row["continuity_accuracy"],
        mode=row["mode"],
        tempo_bpm=row["tempo_bpm"],
        performed_at=row["performed_at"],
        key_name=row["key_name"],
        meter=row["meter"],
        difficulty_elo=row["difficulty_elo"],
        target_skill=row["target_skill"],
        levels=row["levels"],
        expected_notes=row["expected_notes"],
        played_notes=row["played_notes"],
        feedback=row["feedback"],
        by_hand=row["by_hand"],
    )


@app.get("/api/stats")
def stats(conn: Connection = Depends(get_conn)) -> JSONResponse:
    return JSONResponse(services.build_stats(conn, current_user_id()))


app.include_router(piano.router)
# Before `mount_frontend`, which is a catch-all at `/`: a mount registered after it
# is unreachable.
piano.mount_samples(app)


def mount_frontend() -> None:
    """Serve the built SPA when it exists (production-style single process)."""
    dist = settings.frontend_dist
    if dist.is_dir() and (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")


mount_frontend()
