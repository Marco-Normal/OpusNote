"""FastAPI application.

The API is intentionally thin: it validates input, calls one service function,
and returns the result. That is the whole contract with the browser, so the
generator, scorer, and adaptive engine can all be replaced behind it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlite3 import Connection

from . import services, store
from .config import settings
from .db import init_db
from .models import ExerciseOut, HealthOut, ProfileOut, ScoreRequest, SkillOut
from .skills_data import SKILLS, SKILL_SLUGS

USER_ID: int | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global USER_ID
    init_db(settings.db_path)
    USER_ID = services.init_workspace()
    yield


app = FastAPI(
    title="Sight-Reading Trainer API",
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


@app.post("/api/profile/reset", response_model=ProfileOut)
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
    from .adaptive.elo import level_for_rating

    return level_for_rating(rating)


@app.get("/api/exercise/next", response_model=ExerciseOut)
def exercise_next(
    conn: Connection = Depends(get_conn),
    skill: str | None = Query(default=None, description="Force a skill dimension"),
    bars: int | None = Query(default=None, ge=1, le=16),
) -> ExerciseOut:
    if skill is not None and skill not in SKILL_SLUGS:
        raise HTTPException(status_code=422, detail=f"unknown skill {skill!r}")
    payload = services.next_exercise(conn, current_user_id(), skill=skill, bars=bars)
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
    return JSONResponse(result)


@app.get("/api/stats")
def stats(conn: Connection = Depends(get_conn)) -> JSONResponse:
    return JSONResponse(services.build_stats(conn, current_user_id()))


def mount_frontend() -> None:
    """Serve the built SPA when it exists (production-style single process)."""
    dist = settings.frontend_dist
    if dist.is_dir() and (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")


mount_frontend()
