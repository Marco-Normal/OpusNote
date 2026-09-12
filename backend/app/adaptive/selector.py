"""Exercise selection.

Given the user's current ratings, decide *which skill* to train and *how hard*
the next exercise should be. The output is a plain plan (target skill + a level
for every skill dimension), which the generator turns into notation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from ..config import Settings, settings as default_settings
from ..skills_data import SKILL_SLUGS
from . import elo
from .elo import MAX_LEVEL, MIN_LEVEL, exercise_elo, level_for_rating, rating_for_level


@dataclass
class ExercisePlan:
    target_skill: str
    levels: dict[str, int]
    difficulty_elo: float
    rationale: str
    calibration: bool = False
    focus_notes: list[str] = field(default_factory=list)


def pick_target_skill(
    ratings: Mapping[str, float],
    *,
    recent_skills: Sequence[str] = (),
    config: Settings | None = None,
) -> str:
    """Lowest-rated skill wins, with a nudge away from what was just practised."""
    cfg = config or default_settings
    recent = set(recent_skills)

    def score(slug: str) -> tuple[float, str]:
        # A recently practised skill is treated as if it were slightly stronger,
        # which keeps a session from drilling the same dimension five times.
        penalty = 0.0
        if slug in recent:
            penalty = cfg.elo_per_level * 0.5
        return (float(ratings.get(slug, cfg.default_rating)) + penalty, slug)

    return min(SKILL_SLUGS, key=score)


def plan_exercise(
    ratings: Mapping[str, float],
    *,
    target_skill: str | None = None,
    recent_skills: Sequence[str] = (),
    max_level: int | None = None,
    config: Settings | None = None,
) -> ExercisePlan:
    cfg = config or default_settings
    slug = target_skill or pick_target_skill(ratings, recent_skills=recent_skills, config=cfg)
    target_rating = float(ratings.get(slug, cfg.default_rating))
    # Aim below the rating so the learner succeeds roughly `target_success_rate`
    # of the time rather than half of it.
    target_level = elo.selection_level(target_rating, cfg)
    if max_level is not None:
        target_level = min(target_level, max_level)

    # Other dimensions follow the user's own rating, but never run far ahead of
    # the skill under test: an exercise is only as hard as its hardest surprise.
    ceiling = min(MAX_LEVEL, target_level + 1)
    floor = max(MIN_LEVEL, target_level - 3)
    levels: dict[str, int] = {}
    for other in SKILL_SLUGS:
        own = elo.selection_level(float(ratings.get(other, cfg.default_rating)), cfg)
        levels[other] = max(floor, min(ceiling, own))
    levels[slug] = target_level

    # Deliberately no further tuning of the focus level. Each skill is scored
    # against the Elo implied by *its own* level, so the level derived from the
    # rating is already exactly the right challenge. Nudging it to move the
    # exercise's blended mean would let an easy melodic dimension push the
    # focus skill up to a level the learner cannot actually read.
    rationale = (
        f"Targeting {slug} at level {target_level} "
        f"(your rating {target_rating:.0f}, aiming for "
        f"{cfg.target_success_rate * 100:.0f}% success)"
    )
    return ExercisePlan(
        target_skill=slug,
        levels=levels,
        difficulty_elo=exercise_elo(levels, cfg),
        rationale=rationale,
        focus_notes=[f"{slug}: level {target_level}"],
    )


#: Calibration ladder: one short exercise per dimension, walking up in level so
#: the Elo updates can find a starting point fast.
CALIBRATION_LADDER: tuple[tuple[str, int], ...] = (
    ("rhythm", 1),
    ("key_signature", 2),
    ("intervals", 2),
    ("hand_position", 2),
    ("texture", 2),
    ("meter", 3),
    ("accidentals", 3),
    ("articulation", 3),
)


def calibration_plan(step: int, *, ratings: Mapping[str, float], config: Settings | None = None) -> ExercisePlan:
    """Plan the ``step``-th calibration exercise (0-based)."""
    cfg = config or default_settings
    focus, level = CALIBRATION_LADDER[step % len(CALIBRATION_LADDER)]
    levels: dict[str, int] = {}
    for slug in SKILL_SLUGS:
        own = elo.selection_level(float(ratings.get(slug, cfg.default_rating)), cfg)
        levels[slug] = max(MIN_LEVEL, min(level, own + 1))
    levels[focus] = level
    return ExercisePlan(
        target_skill=focus,
        levels=levels,
        difficulty_elo=exercise_elo(levels, cfg),
        rationale=f"Calibration {step + 1}/{len(CALIBRATION_LADDER)}: {focus} at level {level}",
        calibration=True,
        focus_notes=[f"{focus}: level {level}"],
    )


def available_levels(config: Settings | None = None) -> list[int]:
    cfg = config or default_settings
    return [level for level in range(MIN_LEVEL, MAX_LEVEL + 1) if rating_for_level(level, cfg) >= 0]
