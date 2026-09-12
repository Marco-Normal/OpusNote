"""Persistence queries.

One place where SQL lives, so :mod:`app.services` can stay about orchestration
and the API layer stays about HTTP.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

from .config import Settings, settings as default_settings
from .db import connect, json_dump, json_load, utcnow_iso
from .music.expected import ExpectedNote, expected_from_dicts
from .skills_data import SKILLS

_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def levels_key(levels: Mapping[str, int]) -> str:
    """A stable signature of a complete level profile.

    Reuse used to match on the *target* skill alone, which meant an exercise
    built for one profile could be served for a completely different one — a
    two-hand plan satisfied by a stored right-hand-alone exercise. The signature
    covers every dimension, so a reused exercise is the same exercise.
    """
    return ",".join(f"{slug}:{int(levels[slug])}" for slug in sorted(levels))


def midi_to_name(pitch: int) -> str:
    return f"{_NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------


def seed_skills(conn) -> None:
    for order, spec in enumerate(SKILLS):
        conn.execute(
            """
            INSERT INTO skills (slug, name, description, sort_order)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (slug) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                sort_order = excluded.sort_order
            """,
            (spec.slug, spec.name, spec.description, order),
        )


def get_skills(conn) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT id, slug, name, description, sort_order FROM skills ORDER BY sort_order").fetchall()
    return [dict(row) for row in rows]


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------


def get_ratings(conn, user_id: int) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT s.slug AS slug, us.elo_rating AS rating
        FROM user_skills us
        JOIN skills s ON s.id = us.skill_id
        WHERE us.user_id = ?
        """,
        (user_id,),
    ).fetchall()
    return {row["slug"]: float(row["rating"]) for row in rows}


def get_skill_rows(conn, user_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT s.id AS skill_id, s.slug AS slug, s.name AS name, s.description AS description,
               us.elo_rating AS elo_rating, us.attempts AS attempts,
               us.last_practiced_at AS last_practiced_at
        FROM skills s
        LEFT JOIN user_skills us ON us.skill_id = s.id AND us.user_id = ?
        ORDER BY s.sort_order
        """,
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def apply_rating_updates(conn, user_id: int, updated: Mapping[str, float], now: str | None = None) -> None:
    timestamp = now or utcnow_iso()
    for slug, rating in updated.items():
        conn.execute(
            """
            UPDATE user_skills
            SET elo_rating = ?, attempts = attempts + 1, last_practiced_at = ?
            WHERE user_id = ? AND skill_id = (SELECT id FROM skills WHERE slug = ?)
            """,
            (float(rating), timestamp, user_id, slug),
        )


def recent_target_skills(conn, user_id: int, limit: int = 3) -> list[str]:
    rows = conn.execute(
        """
        SELECT json_extract(e.params_json, '$.target_skill') AS slug
        FROM performances p
        JOIN exercises e ON e.id = p.exercise_id
        WHERE p.user_id = ?
        ORDER BY p.performed_at DESC, p.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    seen: list[str] = []
    for row in rows:
        slug = row["slug"]
        if slug and slug not in seen:
            seen.append(slug)
    return seen


# --------------------------------------------------------------------------
# Exercises
# --------------------------------------------------------------------------


def insert_exercise(
    conn,
    *,
    musicxml: str,
    difficulty_elo: float,
    key_name: str,
    meter: str,
    bars: int,
    tempo_bpm: float,
    seed: int,
    levels: Mapping[str, int],
    expected: Sequence[ExpectedNote],
    measures: Sequence[Mapping[str, Any]],
    target_skill: str,
    source: str = "generated",
    bass_pattern: str | None = None,
    pinned_key: str | None = None,
) -> int:
    # `key_name` above is the key the exercise is *in*; `pinned_key` records that
    # the player asked for that key specifically. Only the latter is part of the
    # exercise's identity for reuse, or an exercise that happened to land in B
    # would satisfy a request to practise in B.
    cursor = conn.execute(
        """
        INSERT INTO exercises
            (musicxml_blob, difficulty_elo, key_name, meter, bars, tempo_bpm,
             generator_seed, source, params_json, expected_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            musicxml,
            float(difficulty_elo),
            key_name,
            meter,
            int(bars),
            float(tempo_bpm),
            int(seed),
            source,
            json_dump(
                {
                    "levels": dict(levels),
                    "target_skill": target_skill,
                    "measures": [dict(item) for item in measures],
                    "bass_pattern": bass_pattern,
                    "levels_key": levels_key(levels),
                    "pinned_key": pinned_key,
                }
            ),
            json_dump([note.to_dict() for note in expected]),
        ),
    )
    exercise_id = int(cursor.lastrowid)
    for slug, level in levels.items():
        conn.execute(
            """
            INSERT INTO exercise_skills (exercise_id, skill_id, level)
            VALUES (?, (SELECT id FROM skills WHERE slug = ?), ?)
            """,
            (exercise_id, slug, int(level)),
        )
    return exercise_id


def find_reusable_exercise(
    conn,
    *,
    levels: Mapping[str, int],
    target_skill: str,
    bars: int,
    key_name: str | None = None,
    source: str = "generated",
    library_cap: int = 32,
) -> dict[str, Any] | None:
    """Pick a stored exercise for this exact profile and focus, if one should be reused.

    Both halves of the match are needed and neither is sufficient. Matching on
    the target skill alone served exercises built for a different level profile;
    matching on the profile alone served exercises focused on a different skill,
    because two skills can share an identical profile.

    Reuse policy, in order:

    1. An exercise nobody has played yet — no reason to write a new one.
    2. Otherwise, *nothing*, until the profile has ``library_cap`` exercises.

    Step 2 is what makes this a sight-reading trainer rather than a memory test:
    replaying the same eight exercises forever defeats the point. Generating
    fresh material is cheap; the cap only exists so the table cannot grow without
    bound.
    3. Past the cap, rotate the least recently played.
    """
    key = levels_key(levels)
    where = """
        FROM exercises e
        WHERE e.source = ?
          AND e.bars = ?
          AND json_extract(e.params_json, '$.levels_key') = ?
          AND json_extract(e.params_json, '$.target_skill') = ?
          AND IFNULL(json_extract(e.params_json, '$.pinned_key'), '') = ?
    """
    params = (source, int(bars), key, target_skill, key_name or "")

    untried = conn.execute(
        f"""
        SELECT e.*
        {where}
          AND NOT EXISTS (SELECT 1 FROM performances p WHERE p.exercise_id = e.id)
        ORDER BY RANDOM()
        LIMIT 1
        """,
        params,
    ).fetchone()
    if untried is not None:
        return dict(untried)

    total = conn.execute(f"SELECT COUNT(*) AS n {where}", params).fetchone()["n"]
    if total < library_cap:
        return None

    stale = conn.execute(
        f"""
        SELECT e.*, MAX(p.performed_at) AS last_used
        {where}
        LEFT JOIN performances p ON p.exercise_id = e.id
        GROUP BY e.id
        ORDER BY last_used ASC
        LIMIT 1
        """,
        params,
    ).fetchone()
    return dict(stale) if stale else None


def get_exercise(conn, exercise_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM exercises WHERE id = ?", (exercise_id,)).fetchone()
    if row is None:
        return None
    exercise = dict(row)
    params = json_load(exercise.get("params_json"), {})
    exercise["levels"] = params.get("levels", {})
    exercise["target_skill"] = params.get("target_skill")
    exercise["measures"] = params.get("measures", [])
    exercise["bass_pattern"] = params.get("bass_pattern")
    exercise["expected"] = expected_from_dicts(json_load(exercise.get("expected_json"), []))
    return exercise


# --------------------------------------------------------------------------
# Performances
# --------------------------------------------------------------------------


def insert_performance(
    conn,
    *,
    user_id: int,
    exercise_id: int,
    result,
    mode: str,
    tempo_bpm: float,
    latency_ms: float,
    played_notes: Sequence[dict[str, Any]],
    analysis: Mapping[str, Any],
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO performances
            (user_id, exercise_id, score, pitch_accuracy, rhythm_accuracy,
             continuity_accuracy, mode, tempo_bpm, latency_ms, played_notes_json,
             analysis_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            exercise_id,
            result.score,
            result.pitch_accuracy,
            result.rhythm_accuracy,
            result.continuity_accuracy,
            mode,
            float(tempo_bpm),
            float(latency_ms),
            json_dump(list(played_notes)),
            json_dump(dict(analysis)),
        ),
    )
    return int(cursor.lastrowid)


def recent_performances(conn, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT p.id, p.exercise_id, p.score, p.pitch_accuracy, p.rhythm_accuracy,
               p.continuity_accuracy, p.mode, p.tempo_bpm, p.performed_at,
               e.key_name, e.meter, e.difficulty_elo,
               json_extract(e.params_json, '$.target_skill') AS target_skill
        FROM performances p
        JOIN exercises e ON e.id = p.exercise_id
        WHERE p.user_id = ?
        ORDER BY p.performed_at DESC, p.id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def performance_count(conn, user_id: int) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM performances WHERE user_id = ?", (user_id,)).fetchone()
    return int(row["n"]) if row else 0


def performances_since(conn, user_id: int, days: int = 120) -> list[dict[str, Any]]:
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat(sep=" ")
    rows = conn.execute(
        """
        SELECT p.id, p.score, p.pitch_accuracy, p.rhythm_accuracy,
               p.continuity_accuracy, p.tempo_bpm, p.performed_at, p.analysis_json,
               json_extract(e.params_json, '$.target_skill') AS target_skill
        FROM performances p
        JOIN exercises e ON e.id = p.exercise_id
        WHERE p.user_id = ? AND p.performed_at >= ?
        ORDER BY p.performed_at ASC, p.id ASC
        """,
        (user_id, cutoff),
    ).fetchall()
    return [dict(row) for row in rows]


def calibration_progress(conn, user_id: int) -> int:
    """How many calibration exercises have been completed so far."""
    row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM performances p
        JOIN exercises e ON e.id = p.exercise_id
        WHERE p.user_id = ? AND e.source = 'calibration'
        """,
        (user_id,),
    ).fetchone()
    return int(row["n"]) if row else 0


def open_connection(config: Settings | None = None):
    return connect((config or default_settings).db_path)
