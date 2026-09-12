"""Elo ratings for the adaptive engine.

Two ideas carry the whole adaptation:

1. Every *exercise* has an Elo derived from its skill levels, and every *user*
   has an Elo per skill. That is enough to keep a learner in the 70-85% zone
   without any hand-tuned curriculum.
2. Each skill is scored against the Elo implied by *its own* level in the
   exercise, not the exercise's blended difficulty. Otherwise a hard rhythm in
   an otherwise easy piece would drag every unrelated skill rating down.
"""

from __future__ import annotations

import math
from typing import Mapping

from ..config import Settings, settings as default_settings
from ..skills_data import SKILL_SLUGS

MIN_LEVEL = 1
MAX_LEVEL = 10


def clamp_level(level: float) -> int:
    return max(MIN_LEVEL, min(MAX_LEVEL, int(round(level))))


def rating_for_level(level: float, config: Settings | None = None) -> float:
    cfg = config or default_settings
    return cfg.elo_base + cfg.elo_per_level * (float(level) - MIN_LEVEL)


def level_for_rating(rating: float, config: Settings | None = None) -> int:
    cfg = config or default_settings
    return clamp_level((float(rating) - cfg.elo_base) / cfg.elo_per_level + MIN_LEVEL)


def exercise_elo(levels: Mapping[str, int], config: Settings | None = None) -> float:
    """Blended difficulty of a whole exercise (mean of its per-skill Elos)."""
    cfg = config or default_settings
    if not levels:
        return cfg.default_rating
    return sum(rating_for_level(level, cfg) for level in levels.values()) / len(levels)


def skill_target_elo(levels: Mapping[str, int], slug: str, config: Settings | None = None) -> float:
    """Difficulty of a single skill dimension inside an exercise."""
    cfg = config or default_settings
    return rating_for_level(levels.get(slug, MIN_LEVEL), cfg)


def expected_score(user_rating: float, exercise_rating: float) -> float:
    """Standard Elo expectation, on the 400-point scale."""
    return 1.0 / (1.0 + 10.0 ** ((exercise_rating - user_rating) / 400.0))


def offset_for_success_rate(success_rate: float) -> float:
    """Elo offset that makes ``expected_score`` equal ``success_rate``.

    A learner's rating is the difficulty at which they score 50%. Practising
    there is demoralising, so we deliberately aim *below* the rating: the
    blueprint's 70-85% success zone sits roughly 130-260 points down.
    """
    rate = max(0.05, min(0.95, float(success_rate)))
    return 400.0 * math.log10(1.0 / rate - 1.0)


def selection_rating(user_rating: float, config: Settings | None = None) -> float:
    """The exercise difficulty that should produce the target success rate."""
    cfg = config or default_settings
    return float(user_rating) + offset_for_success_rate(cfg.target_success_rate)


def selection_level(user_rating: float, config: Settings | None = None) -> int:
    return level_for_rating(selection_rating(user_rating, config), config)


def update_rating(
    user_rating: float,
    exercise_rating: float,
    actual_score: float,
    *,
    k: float | None = None,
    config: Settings | None = None,
) -> float:
    """Move the user's rating toward the result. ``actual_score`` is 0..1."""
    cfg = config or default_settings
    factor = cfg.elo_k if k is None else k
    actual = max(0.0, min(1.0, float(actual_score)))
    return user_rating + factor * (actual - expected_score(user_rating, exercise_rating))


def apply_performance(
    ratings: Mapping[str, float],
    levels: Mapping[str, int],
    score_fraction: float,
    *,
    target_skill: str | None = None,
    calibration: bool = False,
    config: Settings | None = None,
) -> dict[str, float]:
    """Update every skill the exercise trains and return the new ratings.

    The targeted skill moves at the full K so sessions visibly adapt; the other
    skills move at half K because they were only indirectly exercised.
    """
    cfg = config or default_settings
    base_k = cfg.elo_k_calibration if calibration else cfg.elo_k
    updated: dict[str, float] = {}
    for slug in SKILL_SLUGS:
        if slug not in levels:
            continue
        current = float(ratings.get(slug, cfg.default_rating))
        k = base_k if (target_skill is None or slug == target_skill) else base_k / 2.0
        updated[slug] = update_rating(
            current,
            skill_target_elo(levels, slug, cfg),
            score_fraction,
            k=k,
            config=cfg,
        )
    return updated
