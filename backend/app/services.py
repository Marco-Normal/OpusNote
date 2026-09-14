"""Application services: the seam between HTTP and the music/scoring/adaptive
cores.

Everything the API can do lives here as a plain function taking ``(conn, ...)``
so it can be exercised from tests without spinning up a server.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from .adaptive import elo as elo_mod
from .adaptive.selector import CALIBRATION_LADDER, ExercisePlan, calibration_plan, plan_exercise
from .config import Settings, settings as default_settings
from .db import ensure_user_skill_rows, get_or_create_user, transaction
from .music.expected import ExpectedNote, extract_expected, measure_meta
from .music.generator import GeneratedExercise, generate_exercise
from .scoring.engine import PlayedNote, accuracy_by_hand, score_performance
from .skills_data import DEFAULT_USER_LEVELS, SKILLS, SKILLS_BY_SLUG
from . import store


# --------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------


def init_workspace(config: Settings | None = None) -> int:
    """Create the schema, seed skills, and return the MVP user id."""
    cfg = config or default_settings
    with transaction(cfg.db_path) as conn:
        store.seed_skills(conn)
        user_id = get_or_create_user(conn, cfg.default_username)
        ensure_user_skill_rows(conn, user_id, store.get_skills(conn))
    return user_id


# --------------------------------------------------------------------------
# Exercise payloads
# --------------------------------------------------------------------------


def _plan_to_levels(plan: ExercisePlan) -> dict[str, int]:
    # Any dimension with no explicit level falls back to the taxonomy default.
    levels = dict(DEFAULT_USER_LEVELS)
    levels.update(plan.levels)
    return levels


def _generate(
    plan: ExercisePlan, bars: int, seed: int | None = None, key_name: str | None = None
) -> tuple[GeneratedExercise, list[ExpectedNote], list[dict[str, Any]]]:
    generated = generate_exercise(
        _plan_to_levels(plan), bars=bars, seed=seed, key_name=key_name
    )
    expected = extract_expected(generated.score, generated.tempo_bpm)
    measures = measure_meta(generated.score)
    return generated, expected, measures


def _exercise_payload(exercise: dict[str, Any], *, rationale: str | None = None) -> dict[str, Any]:
    return {
        "exercise_id": exercise["id"],
        "musicxml": exercise["musicxml_blob"],
        "tempo_bpm": exercise["tempo_bpm"],
        "bars": exercise["bars"],
        "key_name": exercise["key_name"],
        "meter": exercise["meter"],
        "levels": exercise.get("levels", {}),
        "difficulty_elo": exercise["difficulty_elo"],
        "target_skill": exercise.get("target_skill"),
        "source": exercise.get("source", "generated"),
        "expected_notes": [note.to_dict() for note in exercise.get("expected", [])],
        "measures": exercise.get("measures", []),
        "bass_pattern": exercise.get("bass_pattern"),
        "rationale": rationale,
    }


def _rationale_for(skill: str, level: int, *, config: Settings) -> str:
    if level is None:
        return f"Targeting {skill}"
    return (
        f"Targeting {skill} at level {level} "
        f"(aiming for {config.target_success_rate * 100:.0f}% success)"
    )


def create_exercise_from_plan(
    conn,
    *,
    plan: ExercisePlan,
    bars: int | None = None,
    source: str = "generated",
    config: Settings | None = None,
    reuse: bool = True,
    key_name: str | None = None,
) -> dict[str, Any]:
    cfg = config or default_settings
    bar_count = bars or cfg.exercise_bars

    if reuse and source == "generated":
        existing = store.find_reusable_exercise(
            conn,
            levels=plan.levels,
            target_skill=plan.target_skill,
            bars=bar_count,
            key_name=key_name,
        )
        if existing is not None:
            exercise = store.get_exercise(conn, int(existing["id"]))
            if exercise is not None:
                # Describe the exercise actually being served, not the plan that
                # went looking for one.
                served_skill = exercise.get("target_skill") or plan.target_skill
                return _exercise_payload(
                    exercise,
                    rationale=_rationale_for(
                        served_skill,
                        exercise.get("levels", {}).get(served_skill, 1),
                        config=cfg,
                    ),
                )

    generated, expected, measures = _generate(plan, bar_count, key_name=key_name)
    exercise_id = store.insert_exercise(
        conn,
        musicxml=generated.musicxml,
        difficulty_elo=plan.difficulty_elo,
        key_name=generated.key_name,
        meter=generated.meter_label,
        bars=bar_count,
        tempo_bpm=generated.tempo_bpm,
        seed=generated.seed,
        levels=plan.levels,
        expected=expected,
        measures=measures,
        target_skill=plan.target_skill,
        source=source,
        bass_pattern=generated.bass_pattern,
        pinned_key=key_name,
    )
    exercise = store.get_exercise(conn, exercise_id)
    assert exercise is not None
    return _exercise_payload(exercise, rationale=plan.rationale)


def next_exercise(
    conn,
    user_id: int,
    *,
    skill: str | None = None,
    bars: int | None = None,
    key_name: str | None = None,
    config: Settings | None = None,
) -> dict[str, Any]:
    cfg = config or default_settings
    ratings = store.get_ratings(conn, user_id)
    recent = store.recent_target_skills(conn, user_id, limit=3)
    plan = plan_exercise(
        ratings,
        target_skill=skill,
        recent_skills=recent,
        forced_key=key_name,
        config=cfg,
    )
    return create_exercise_from_plan(
        conn, plan=plan, bars=bars, config=cfg, key_name=key_name
    )


def calibration_exercise(conn, user_id: int, *, config: Settings | None = None) -> dict[str, Any]:
    cfg = config or default_settings
    step = store.calibration_progress(conn, user_id)
    ratings = store.get_ratings(conn, user_id)
    if step >= cfg.calibration_length:
        return {
            "complete": True,
            "step": step,
            "total": cfg.calibration_length,
            "next": next_exercise(conn, user_id, config=cfg),
        }
    plan = calibration_plan(step % len(CALIBRATION_LADDER), ratings=ratings, config=cfg)
    payload = create_exercise_from_plan(
        conn, plan=plan, bars=min(cfg.exercise_bars, 2), source="calibration", config=cfg, reuse=False
    )
    payload.update({"complete": False, "step": step + 1, "total": cfg.calibration_length})
    return payload


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def record_performance(
    conn,
    user_id: int,
    *,
    exercise_id: int,
    played: Sequence[Mapping[str, Any]],
    mode: str = "practice",
    latency_ms: float = 0.0,
    calibration: bool = False,
    config: Settings | None = None,
) -> dict[str, Any]:
    cfg = config or default_settings
    exercise = store.get_exercise(conn, exercise_id)
    if exercise is None:
        raise KeyError(f"unknown exercise {exercise_id}")

    expected: list[ExpectedNote] = exercise["expected"]
    tempo_bpm = float(exercise["tempo_bpm"] or 90.0)
    played_notes = [PlayedNote.from_dict(item) for item in played]

    result = score_performance(
        expected,
        played_notes,
        tempo_bpm=tempo_bpm,
        latency_ms=latency_ms,
        config=cfg,
    )

    levels: dict[str, int] = exercise["levels"]
    target_skill = exercise.get("target_skill")
    ratings = store.get_ratings(conn, user_id)
    updated = elo_mod.apply_performance(
        ratings,
        levels,
        result.score / 100.0,
        target_skill=target_skill,
        calibration=calibration,
        config=cfg,
    )

    by_hand = accuracy_by_hand(result.feedback)
    analysis = {
        "feedback": [item.to_dict() for item in result.feedback],
        "by_hand": by_hand,
        "levels": levels,
        "target_skill": target_skill,
        "weights": result.weights,
        "pass_threshold": cfg.pass_threshold,
    }

    performance_id = store.insert_performance(
        conn,
        user_id=user_id,
        exercise_id=exercise_id,
        result=result,
        mode=mode,
        tempo_bpm=tempo_bpm,
        latency_ms=latency_ms,
        played_notes=[dict(item) for item in played],
        analysis=analysis,
    )
    store.apply_rating_updates(conn, user_id, updated)
    # The change is recorded, not just applied: `user_skills` keeps only the current
    # value, so this row is the only way to see a curve later.
    store.record_rating_events(
        conn,
        user_id,
        before=ratings,
        after=updated,
        score=result.score,
        performance_id=performance_id,
    )

    passed = result.score >= cfg.pass_threshold
    skill_rows = {row["slug"]: row for row in store.get_skill_rows(conn, user_id)}
    focus_before = float(ratings.get(target_skill, cfg.default_rating)) if target_skill else None
    focus_after = float(updated.get(target_skill, focus_before)) if target_skill else None

    return {
        "performance_id": performance_id,
        "exercise_id": exercise_id,
        "mode": mode,
        "passed": passed,
        "score": result.score,
        "pitch_accuracy": result.pitch_accuracy,
        "rhythm_accuracy": result.rhythm_accuracy,
        "continuity_accuracy": result.continuity_accuracy,
        "counts": {
            "expected": result.expected_count,
            "played": result.played_count,
            "matched": result.matched,
            "wrong_pitch": result.wrong_pitch_count,
            "missed": result.missed_count,
            "extra": result.extra_count,
            "hesitations": result.hesitation_count,
        },
        "timing": {
            "mean_onset_error_beats": result.mean_onset_error_beats,
            "onset_error_std_beats": result.onset_error_std_beats,
        },
        "by_hand": by_hand,
        "feedback": [item.to_dict() for item in result.feedback],
        "target_skill": target_skill,
        "rating_change": (
            {
                "skill": target_skill,
                "before": round(focus_before, 1) if focus_before is not None else None,
                "after": round(focus_after, 1) if focus_after is not None else None,
                "delta": round((focus_after - focus_before), 1) if focus_before is not None and focus_after is not None else None,
            }
            if target_skill
            else None
        ),
        "skills": [
            {
                "slug": row["slug"],
                "name": row["name"],
                "rating": float(row["elo_rating"] or cfg.default_rating),
                "level": elo_mod.selection_level(
                    float(row["elo_rating"] or cfg.default_rating), cfg
                ),
                "attempts": int(row["attempts"] or 0),
                "target_level": levels.get(row["slug"]),
            }
            for row in skill_rows.values()
        ],
        "next_hint": _next_hint(conn, user_id, target_skill, passed, config=cfg),
    }


def _next_hint(conn, user_id: int, target_skill: str | None, passed: bool, *, config: Settings) -> str:
    if passed:
        return "Nice — the next exercise steps up."
    ratings = store.get_ratings(conn, user_id)
    weakest = min(SKILLS, key=lambda spec: ratings.get(spec.slug, config.default_rating))
    label = SKILLS_BY_SLUG[weakest.slug].name
    if target_skill and weakest.slug != target_skill:
        return f"Next up: easier material, with more work on {label.lower()}."
    return f"Next up: a similar exercise targeting {label.lower()}."


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------


def _local_day(timestamp: str) -> str:
    """The calendar day a stored timestamp belongs to, in this machine's timezone.

    Timestamps are stored UTC, so slicing the first ten characters gives a *UTC* day —
    which is the wrong day for every evening session east of Greenwich and every
    early-morning one west of it. At UTC-3, anything played after 21:00 local is
    already tomorrow in UTC, so the streak counted that day as missed and the tempo
    chart shifted a day. The app runs on the piano machine, so "this machine's
    timezone" is the player's timezone.
    """
    try:
        moment = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return str(timestamp)[:10]
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().date().isoformat()


def _streak_days(timestamps: Sequence[str]) -> int:
    days = sorted({_local_day(timestamp) for timestamp in timestamps if timestamp}, reverse=True)
    if not days:
        return 0
    streak = 0
    cursor = date.today()
    day_set = set(days)
    # Allow the streak to be alive if the last session was yesterday.
    if cursor.isoformat() not in day_set:
        today_ordinal = cursor.toordinal()
        if (today_ordinal - 1) not in {date.fromisoformat(day).toordinal() for day in days}:
            return 0
        cursor = date.fromordinal(today_ordinal - 1)
    while cursor.isoformat() in day_set:
        streak += 1
        cursor = date.fromordinal(cursor.toordinal() - 1)
    return streak


def _common_mistakes(rows: Sequence[Mapping[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    from .db import json_load
    from .store import midi_to_name

    missed: dict[str, int] = {}
    substitutions: dict[tuple[int, int], int] = {}
    for row in rows:
        analysis = json_load(row.get("analysis_json"), {})
        for item in analysis.get("feedback", []):
            if item.get("status") == "missed":
                name = midi_to_name(int(item["pitch"]))
                missed[name] = missed.get(name, 0) + 1
            elif item.get("status") == "wrong_pitch" and item.get("played_pitch") is not None:
                key = (int(item["pitch"]), int(item["played_pitch"]))
                substitutions[key] = substitutions.get(key, 0) + 1

    mistakes: list[dict[str, Any]] = []
    for name, count in sorted(missed.items(), key=lambda kv: -kv[1])[:limit]:
        mistakes.append({"kind": "missed_note", "label": f"{name} (missed)", "count": count})
    for (expected_pitch, played_pitch), count in sorted(substitutions.items(), key=lambda kv: -kv[1])[:limit]:
        mistakes.append(
            {
                "kind": "wrong_note",
                "label": f"{midi_to_name(expected_pitch)} played as {midi_to_name(played_pitch)}",
                "count": count,
            }
        )
    mistakes.sort(key=lambda item: -item["count"])
    return mistakes[:limit]


def build_stats(conn, user_id: int, *, config: Settings | None = None) -> dict[str, Any]:
    cfg = config or default_settings
    skill_rows = store.get_skill_rows(conn, user_id)
    recent = store.recent_performances(conn, user_id, limit=25)
    history_rows = store.performances_since(conn, user_id, days=180)

    radar = [
        {
            "slug": row["slug"],
            "name": row["name"],
            "rating": round(float(row["elo_rating"] or cfg.default_rating), 1),
            # The level of material this skill is *worked at*, not the level its
            # rating would imply: the selector deliberately aims about two levels
            # below the rating, and a radar drawn from the rating disagreed with the
            # exercise on screen. The rating is the ability number; this is the
            # material number, and both are shown.
            "level": elo_mod.selection_level(
                float(row["elo_rating"] or cfg.default_rating), cfg
            ),
            "attempts": int(row["attempts"] or 0),
            "last_practiced_at": row["last_practiced_at"],
        }
        for row in skill_rows
    ]

    history = [
        {
            "id": row["id"],
            "score": row["score"],
            "pitch_accuracy": row["pitch_accuracy"],
            "rhythm_accuracy": row["rhythm_accuracy"],
            "continuity_accuracy": row["continuity_accuracy"],
            "tempo_bpm": row["tempo_bpm"],
            "performed_at": row["performed_at"],
            "target_skill": row["target_skill"],
            "key_name": row["key_name"],
            "meter": row["meter"],
            "mode": row["mode"],
            "difficulty_elo": row["difficulty_elo"],
        }
        for row in reversed(recent)
    ]

    tempo_progress: list[dict[str, Any]] = []
    best_by_day: dict[str, float] = {}
    for row in history_rows:
        if (row["pitch_accuracy"] or 0) < 80:
            continue
        day = _local_day(row["performed_at"])
        best_by_day[day] = max(best_by_day.get(day, 0.0), float(row["tempo_bpm"] or 0))
    for day in sorted(best_by_day):
        tempo_progress.append({"date": day, "tempo_bpm": best_by_day[day]})

    scores = [float(row["score"] or 0) for row in history_rows]
    summary = {
        "performances": len(history_rows),
        "average_score": round(statistics.fmean(scores), 1) if scores else 0.0,
        "best_score": round(max(scores), 1) if scores else 0.0,
        "pass_rate": round(
            100.0 * sum(1 for score in scores if score >= cfg.pass_threshold) / len(scores), 1
        )
        if scores
        else 0.0,
        "streak_days": _streak_days([str(row["performed_at"]) for row in history_rows]),
        "calibration_complete": store.calibration_progress(conn, user_id) >= cfg.calibration_length,
        "calibration_step": min(store.calibration_progress(conn, user_id), cfg.calibration_length),
        "calibration_total": cfg.calibration_length,
    }

    return {
        "summary": summary,
        "radar": radar,
        "history": history,
        "tempo_progress": tempo_progress,
        "common_mistakes": _common_mistakes(history_rows),
        "skills": [
            {
                "slug": spec.slug,
                "name": spec.name,
                "description": spec.description,
                "levels": list(spec.levels),
            }
            for spec in SKILLS
        ],
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
    }


def reset_profile(conn, user_id: int, *, config: Settings | None = None) -> None:
    """Wipe ratings and history — used by tests and the Settings screen."""
    cfg = config or default_settings
    conn.execute("DELETE FROM performances WHERE user_id = ?", (user_id,))
    conn.execute("UPDATE user_skills SET elo_rating = ?, attempts = 0, last_practiced_at = NULL", (cfg.default_rating,))
