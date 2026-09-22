"""Exercise selection.

Given the user's current ratings, decide *which skill* to train and *how hard*
the next exercise should be. The output is a plain plan (target skill + a level
for every skill dimension), which the generator turns into notation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from ..config import Settings, settings as default_settings
from ..skills_data import HAND_CHOICES, HAND_LABELS, SKILL_SLUGS, level_for_key
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
    #: Set when the player pinned the hand and/or the level. Both are recorded on the
    #: exercise so a reused one is never served for a different request, and so scoring
    #: knows the attempt was deliberate practice rather than an assessment.
    forced_hand: str | None = None
    pinned_level: int | None = None


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
    forced_key: str | None = None,
    pin_level: int | None = None,
    forced_hand: str | None = None,
    config: Settings | None = None,
) -> ExercisePlan:
    """What the next exercise should be.

    ``pin_level`` and ``forced_hand`` are the player's own deliberate choices, and they
    behave differently from everything else here on purpose. Every other level is *derived*
    from a rating and then fenced in so one dimension cannot run away; a pin is not derived
    from anything, so it is neither capped nor fenced — the player asking for level 2 means
    level-2 material in every respect, not level-2 melody over level-5 rhythm.

    Pinning is also what makes the hand choosable at all. Handedness is decided by the
    *texture* level — 1 is the right hand alone, 2 the left, 3 and up are both — so before
    this the only way to practise reading the bass clef was to be rated at texture 2, and
    the only way out of it was to be rated higher. ``forced_hand`` separates the two: the
    material you read is a choice, the difficulty is a choice, and neither implies the other.
    """
    cfg = config or default_settings
    slug = target_skill or pick_target_skill(ratings, recent_skills=recent_skills, config=cfg)
    target_rating = float(ratings.get(slug, cfg.default_rating))
    # Aim below the rating so the learner succeeds roughly `target_success_rate`
    # of the time rather than half of it.
    target_level = elo.selection_level(target_rating, cfg)
    if max_level is not None:
        target_level = min(target_level, max_level)

    if forced_hand is not None and forced_hand not in HAND_CHOICES:
        raise ValueError(f"{forced_hand!r} is not a hand this taxonomy knows")
    if pin_level is not None and not MIN_LEVEL <= int(pin_level) <= MAX_LEVEL:
        raise ValueError(f"{pin_level!r} is not a level between {MIN_LEVEL} and {MAX_LEVEL}")

    if pin_level is not None:
        # Uniform by definition: the pin *is* the level, so the fence below has nothing to
        # fence. This is also why a pin can raise a level, which `max_level` never could.
        target_level = int(pin_level)
        levels = {other: target_level for other in SKILL_SLUGS}
    else:
        # Other dimensions follow the user's own rating, but never run far ahead of
        # the skill under test: an exercise is only as hard as its hardest surprise.
        #
        # The allowance is +3 rather than +1 because at +1 the guard swallowed real
        # capability. A player whose texture rating is high but whose accidentals are
        # weak was capped at texture 2 — left hand alone — so they could never be
        # given hands-together material at all, which is the opposite of the point.
        # Three levels still prevents one runaway dimension from dominating.
        ceiling = min(MAX_LEVEL, target_level + 3)
        floor = max(MIN_LEVEL, target_level - 3)
        levels = {}
        for other in SKILL_SLUGS:
            own = elo.selection_level(float(ratings.get(other, cfg.default_rating)), cfg)
            levels[other] = max(floor, min(ceiling, own))
    levels[slug] = target_level

    if forced_key is not None:
        # A pinned key is a hard constraint from the repertoire bridge, so it
        # overrides the level that the key-signature rating would have chosen.
        # The ceiling exists to stop one dimension running away; a deliberate
        # choice by the player is not that.
        #
        # It wins over `pin_level` for its own dimension, because a key the player named is
        # more specific than a level they named: asking for "level 3 in B major" cannot be
        # honoured as both, and the key is the one with an exact answer.
        key_level = level_for_key(forced_key)
        if key_level is None:
            raise ValueError(f"{forced_key!r} is not a key this taxonomy knows")
        levels["key_signature"] = key_level

    # Deliberately no further tuning of the focus level. Each skill is scored
    # against the Elo implied by *its own* level, so the level derived from the
    # rating is already exactly the right challenge. Nudging it to move the
    # exercise's blended mean would let an easy melodic dimension push the
    # focus skill up to a level the learner cannot actually read.
    key_note = f" in {forced_key}" if forced_key else ""
    hand_note = f", {HAND_LABELS[forced_hand]}" if forced_hand else ""
    if pin_level is not None:
        rationale = f"Practising level {pin_level}{hand_note} by choice{key_note}"
    else:
        rationale = (
            f"Targeting {slug} at level {target_level}{key_note}{hand_note} "
            f"(your rating {target_rating:.0f}, aiming for "
            f"{cfg.target_success_rate * 100:.0f}% success)"
        )
    return ExercisePlan(
        target_skill=slug,
        levels=levels,
        difficulty_elo=exercise_elo(levels, cfg),
        rationale=rationale,
        focus_notes=[f"{slug}: level {target_level}"],
        forced_hand=forced_hand,
        pinned_level=pin_level if pin_level is None else int(pin_level),
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
