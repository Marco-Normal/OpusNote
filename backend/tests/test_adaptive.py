"""Adaptive engine tests: Elo maths and exercise selection."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.adaptive import elo
from app.adaptive.selector import calibration_plan, pick_target_skill, plan_exercise
from app.config import settings
from app.skills_data import SKILL_SLUGS


def test_expected_score_is_symmetric_and_bounded():
    assert elo.expected_score(1000, 1000) == pytest.approx(0.5)
    assert elo.expected_score(1400, 1000) > 0.9
    assert elo.expected_score(600, 1000) < 0.1
    assert elo.expected_score(1000, 1400) == pytest.approx(1 - elo.expected_score(1400, 1000))


def test_level_and_rating_round_trip():
    for level in range(1, 11):
        rating = elo.rating_for_level(level)
        assert elo.level_for_rating(rating) == level


def test_rating_level_is_clamped():
    assert elo.level_for_rating(-10_000) == 1
    assert elo.level_for_rating(10_000) == 10


def test_winning_raises_and_losing_lowers_the_rating():
    up = elo.update_rating(1000, 1000, 1.0)
    down = elo.update_rating(1000, 1000, 0.0)
    assert up > 1000 > down
    assert (up - 1000) == pytest.approx(1000 - down)


def test_beating_a_harder_exercise_moves_you_more():
    easy_gain = elo.update_rating(1000, 900, 1.0) - 1000
    hard_gain = elo.update_rating(1000, 1300, 1.0) - 1000
    assert hard_gain > easy_gain


def test_scoring_the_expected_result_barely_moves_the_rating():
    rating = 1000
    exercise = 1000
    expected = elo.expected_score(rating, exercise)
    assert elo.update_rating(rating, exercise, expected) == pytest.approx(rating)


def test_performance_updates_every_trained_skill():
    levels = {slug: 3 for slug in SKILL_SLUGS}
    ratings = {slug: 700.0 for slug in SKILL_SLUGS}
    updated = elo.apply_performance(ratings, levels, 1.0, target_skill="rhythm")
    assert set(updated) == set(SKILL_SLUGS)
    assert all(value > 700.0 for value in updated.values())
    # The focused skill moves at the full K, the others at half.
    assert (updated["rhythm"] - 700.0) > (updated["meter"] - 700.0)


def test_calibration_uses_a_larger_step():
    levels = {slug: 3 for slug in SKILL_SLUGS}
    ratings = {slug: 700.0 for slug in SKILL_SLUGS}
    normal = elo.apply_performance(ratings, levels, 1.0, target_skill="rhythm")
    calibration = elo.apply_performance(ratings, levels, 1.0, target_skill="rhythm", calibration=True)
    assert (calibration["rhythm"] - 700.0) > (normal["rhythm"] - 700.0)


def test_skill_is_scored_against_its_own_level():
    """A hard rhythm in an easy piece must not drag the key-signature rating down."""
    levels = {slug: 1 for slug in SKILL_SLUGS}
    levels["rhythm"] = 9
    ratings = {slug: 700.0 for slug in SKILL_SLUGS}
    ratings["rhythm"] = 1300.0
    updated = elo.apply_performance(ratings, levels, 1.0, target_skill="rhythm")
    # Scored perfectly against an exercise whose rhythm is hard for us: up.
    assert updated["rhythm"] > ratings["rhythm"]
    # The easy key signature must not be *dragged down* by the hard rhythm.
    assert updated["key_signature"] >= ratings["key_signature"]


def test_target_skill_prefers_the_weakest():
    ratings = {slug: 1000.0 for slug in SKILL_SLUGS}
    ratings["meter"] = 500.0
    assert pick_target_skill(ratings) == "meter"


def test_target_skill_avoids_repeating_recent_work():
    ratings = {slug: 1000.0 for slug in SKILL_SLUGS}
    ratings["meter"] = 500.0
    ratings["rhythm"] = 520.0  # close race; the recency nudge should decide it
    assert pick_target_skill(ratings, recent_skills=["meter"]) == "rhythm"


def test_success_rate_offset_is_below_the_rating():
    offset = elo.offset_for_success_rate(settings.target_success_rate)
    assert offset < 0
    assert elo.expected_score(1000, 1000 + offset) == pytest.approx(settings.target_success_rate, abs=1e-9)
    assert elo.selection_rating(1000) < 1000


def test_plan_aims_below_the_rating_for_a_70_to_85_percent_zone():
    ratings = {slug: 1000.0 for slug in SKILL_SLUGS}
    plan = plan_exercise(ratings, target_skill="rhythm")
    assert plan.target_skill == "rhythm"
    assert 1 <= plan.levels["rhythm"] <= 10
    # Observed success on an exercise at this difficulty should sit in the zone.
    observed = elo.expected_score(1000.0, plan.difficulty_elo)
    assert 0.70 <= observed <= 0.85


def test_plan_never_runs_other_dimensions_far_ahead():
    ratings = {slug: 700.0 for slug in SKILL_SLUGS}
    ratings["texture"] = 1900.0  # virtuoso texture, far above everything else
    ratings["rhythm"] = 640.0
    plan = plan_exercise(ratings, target_skill="rhythm")
    assert plan.levels["texture"] <= plan.levels["rhythm"] + 3


def test_a_strong_dimension_is_still_honoured():
    """Regression: a +1 allowance capped a strong texture rating at left hand
    alone, so hands-together material was unreachable."""
    ratings = {slug: 700.0 for slug in SKILL_SLUGS}
    ratings["texture"] = 1300.0  # comfortably two-handed
    plan = plan_exercise(ratings, target_skill="accidentals")
    assert plan.levels["texture"] >= 3, plan.levels


def _first_rating_for_level(level: int) -> int | None:
    """The lowest rating whose served level is ``level``, by asking the engine."""
    for rating in range(0, 4001):
        if elo.selection_level(float(rating)) == level:
            return rating
    return None


def test_no_level_swallows_a_wide_band_of_ratings():
    """Regression, from a real library: at the old anchor a learner rated 792 was
    served level 1 and had been for 25 attempts, because level 2 did not open until
    870. A level that covers 270 points of ability is a level that never changes."""
    opens = {level: _first_rating_for_level(level) for level in range(2, 11)}
    assert all(rating is not None for rating in opens.values()), opens

    gaps = [opens[level + 1] - opens[level] for level in range(2, 10)]
    assert set(gaps) == {100}, f"every level opens 100 points above the last ({gaps})"
    assert opens[2] <= 800, f"level 2 opens at {opens[2]}, which strands mid-range players"


def test_a_mid_rating_is_not_stuck_on_the_easiest_material():
    ratings = {slug: 792.0 for slug in SKILL_SLUGS}
    plan = plan_exercise(ratings, target_skill="rhythm")

    assert plan.levels["rhythm"] >= 2, plan.levels
    # And the material served is at the design's success target, not far below it.
    observed = elo.expected_score(792.0, plan.difficulty_elo)
    assert 0.70 <= observed <= 0.85, observed


def test_an_unrated_player_starts_on_the_easiest_material():
    """We know nothing about them yet, so they get the easiest thing there is —
    the calibration ladder is what finds out."""
    ratings = {slug: settings.default_rating for slug in SKILL_SLUGS}
    plan = plan_exercise(ratings, target_skill="rhythm")
    assert plan.levels["rhythm"] == 1, plan.levels


def test_the_documented_example_is_exact():
    """README: "a rating of 1000 gets exercises around Elo 780". Exact on purpose:
    a documented number that the engine only approximates is a number that drifts."""
    ratings = {slug: 1000.0 for slug in SKILL_SLUGS}
    plan = plan_exercise(ratings, target_skill="rhythm")
    assert plan.difficulty_elo == pytest.approx(780.0)


def test_plan_keeps_a_weak_user_on_easy_material():
    ratings = {slug: 620.0 for slug in SKILL_SLUGS}
    plan = plan_exercise(ratings, target_skill="intervals")
    assert plan.levels["intervals"] <= 2


def test_plan_keeps_a_strong_user_on_hard_material():
    ratings = {slug: 1600.0 for slug in SKILL_SLUGS}
    plan = plan_exercise(ratings, target_skill="intervals")
    assert plan.levels["intervals"] >= 9


def test_all_levels_stay_within_bounds():
    for rating in (400.0, 700.0, 1000.0, 1300.0, 1700.0):
        ratings = {slug: rating for slug in SKILL_SLUGS}
        plan = plan_exercise(ratings)
        assert set(plan.levels) == set(SKILL_SLUGS)
        assert all(1 <= level <= 10 for level in plan.levels.values())


def test_calibration_ladder_covers_distinct_skills():
    ratings = {slug: 700.0 for slug in SKILL_SLUGS}
    focuses = [calibration_plan(step, ratings=ratings).target_skill for step in range(8)]
    assert len(set(focuses)) == 8
    assert all(plan.levels[plan.target_skill] >= 1 for plan in (calibration_plan(s, ratings=ratings) for s in range(8)))


def test_adaptive_loop_converges_on_the_learners_true_ability():
    """A learner whose true ability is level 5 must end up in the 70-85% zone.

    The rating itself converges to an offset value — that is expected, because
    the selector deliberately aims below it. What must converge is the
    *difficulty of the exercises actually served*, which is the product goal.
    """
    from app.adaptive.selector import plan_exercise

    ratings = {slug: 700.0 for slug in SKILL_SLUGS}
    skill = "rhythm"
    served: list[tuple[int, float]] = []

    def simulated_score(exercise_level: int) -> float:
        """True ability = level 5, with a smooth falloff above it."""
        return max(0.0, min(1.0, 1.0 - 0.22 * max(0, exercise_level - 5)))

    for step in range(140):
        plan = plan_exercise(ratings, target_skill=skill)
        levels = dict(plan.levels)
        score_fraction = simulated_score(levels[skill])
        if step >= 120:  # ignore the settling period
            served.append((levels[skill], score_fraction))
        ratings.update(elo.apply_performance(ratings, levels, score_fraction, target_skill=skill))

    assert served, "no exercises were served"
    assert all(0.70 <= score <= 0.85 for _, score in served), served
    assert max(level for level, _ in served) >= 5


def test_served_difficulty_rises_as_the_learner_improves():
    ratings = {slug: 700.0 for slug in SKILL_SLUGS}
    start_level = plan_exercise(ratings, target_skill="rhythm").levels["rhythm"]
    ratings["rhythm"] = 1300.0
    end_level = plan_exercise(ratings, target_skill="rhythm").levels["rhythm"]
    assert end_level > start_level


# ---------------------------------------------------------------------------
# Deliberate practice: pinning the level and the hand
#
# The owner's decision (docs/ECOSYSTEM.md § Still open) is that handedness is a
# property of the *material*, not of the difficulty. A pin is a deliberate choice
# by the player, so unlike `max_level` it is not a ceiling the rating can sit
# under — it is the level, and it is the same for every dimension, because
# "practise level 2" means level-2 material in every respect rather than level-2
# melody over level-5 rhythm.
# ---------------------------------------------------------------------------


def test_a_pinned_level_sets_every_dimension():
    ratings = {slug: 1400.0 for slug in SKILL_SLUGS}
    plan = plan_exercise(ratings, pin_level=2)
    assert set(plan.levels.values()) == {2}, plan.levels


def test_a_pinned_level_raises_as_well_as_lowers():
    """A pin is not a cap: `max_level` could only ever pull a level down."""
    low = {slug: 700.0 for slug in SKILL_SLUGS}
    assert set(plan_exercise(low, pin_level=8).levels.values()) == {8}
    high = {slug: 1600.0 for slug in SKILL_SLUGS}
    assert set(plan_exercise(high, pin_level=1).levels.values()) == {1}


def test_a_pinned_level_is_refused_outside_the_ladder():
    ratings = {slug: 1000.0 for slug in SKILL_SLUGS}
    for bad in (0, -1, 11, 99):
        with pytest.raises(ValueError):
            plan_exercise(ratings, pin_level=bad)


def test_a_pinned_hand_reaches_the_plan_without_moving_the_levels():
    ratings = {slug: 900.0 for slug in SKILL_SLUGS}
    plain = plan_exercise(ratings)
    pinned = plan_exercise(ratings, forced_hand="LH")
    assert pinned.forced_hand == "LH"
    assert pinned.levels == plain.levels, "a hand is material, not difficulty"


def test_a_pinned_hand_is_refused_when_it_is_not_a_hand():
    ratings = {slug: 1000.0 for slug in SKILL_SLUGS}
    for bad in ("", "both_hands", "rh", "BOTH"):
        with pytest.raises(ValueError):
            plan_exercise(ratings, forced_hand=bad)


def test_both_hands_can_be_pinned_at_a_level_that_would_not_choose_them():
    """`both` is a real choice: levels 1 and 2 emit a single part left alone."""
    ratings = {slug: 1000.0 for slug in SKILL_SLUGS}
    plan = plan_exercise(ratings, pin_level=1, forced_hand="both")
    assert plan.levels["texture"] == 1
    assert plan.forced_hand == "both"


def test_no_pin_leaves_the_plan_exactly_as_the_rating_would_have_it():
    """Every existing caller passes neither pin, so this is the regression guard."""
    ratings = {slug: 1000.0 for slug in SKILL_SLUGS}
    plan = plan_exercise(ratings)
    assert plan.forced_hand is None
    assert plan.pinned_level is None
    assert plan.levels["texture"] == elo.selection_level(1000.0, settings)
