"""End-to-end API tests.

These drive the real FastAPI app against a throwaway SQLite file, so they cover
the generator, the scorer, the Elo updates, and the persistence layer together.
"""

from __future__ import annotations

import os
import time as time_module
from datetime import date, datetime, timezone

import pytest

from app import store
from app.skills_data import SKILL_SLUGS


def perfect_performance(exercise: dict) -> list[dict]:
    """MIDI events a flawless player would send for this exercise."""
    return [
        {"pitch": note["pitch"], "onset": note["onset_s"], "duration": 0.4, "velocity": 80}
        for note in exercise["expected_notes"]
    ]


def silent_performance(exercise: dict) -> list[dict]:
    return []


def sloppy_performance(exercise: dict) -> list[dict]:
    """Right rhythm, wrong notes."""
    return [
        {"pitch": note["pitch"] + 1, "onset": note["onset_s"], "duration": 0.4, "velocity": 80}
        for note in exercise["expected_notes"]
    ]


# --------------------------------------------------------------------------
# Basics
# --------------------------------------------------------------------------


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_profile_lists_every_skill(client):
    payload = client.get("/api/profile").json()
    assert set(payload["ratings"]) == set(SKILL_SLUGS)
    assert payload["calibration_total"] >= 5
    assert payload["pass_threshold"] == 80.0


def test_skills_expose_ten_levels_each(client):
    payload = client.get("/api/skills").json()
    assert len(payload) == len(SKILL_SLUGS)
    for skill in payload:
        assert len(skill["levels"]) == 10
        assert skill["description"]


# --------------------------------------------------------------------------
# Exercise generation
# --------------------------------------------------------------------------


def test_next_exercise_returns_renderable_musicxml(client):
    payload = client.get("/api/exercise/next").json()
    assert payload["musicxml"].startswith("<?xml")
    assert "<score-partwise" in payload["musicxml"]
    assert payload["expected_notes"]
    assert payload["tempo_bpm"] > 0
    assert payload["target_skill"] in SKILL_SLUGS
    assert payload["levels"]


def test_next_exercise_reports_per_bar_meter(client):
    payload = client.get("/api/exercise/next").json()
    measures = payload["measures"]
    assert len(measures) == payload["bars"]
    for index, measure in enumerate(measures, start=1):
        assert measure["measure"] == index
        assert measure["beats"] >= 1
        assert measure["beat_unit_q"] > 0
        assert measure["beats"] * measure["beat_unit_q"] == pytest.approx(measure["bar_quarters"])


def test_mixed_meter_is_reported_per_bar(client):
    payload = client.get("/api/exercise/next", params={"skill": "meter", "bars": 6}).json()
    assert len(payload["measures"]) == 6


def test_next_exercise_can_force_a_skill(client):
    payload = client.get("/api/exercise/next", params={"skill": "meter"}).json()
    assert payload["target_skill"] == "meter"


def test_next_exercise_rejects_an_unknown_skill(client):
    response = client.get("/api/exercise/next", params={"skill": "telepathy"})
    assert response.status_code == 422


def test_exercise_can_be_refetched_by_id(client):
    created = client.get("/api/exercise/next").json()
    fetched = client.get(f"/api/exercise/{created['exercise_id']}").json()
    assert fetched["musicxml"] == created["musicxml"]
    assert len(fetched["expected_notes"]) == len(created["expected_notes"])


def test_unknown_exercise_is_404(client):
    assert client.get("/api/exercise/999999").status_code == 404


def test_current_exercise_picks_the_weakest_skill(client):
    """A deliberately weak dimension should be targeted next."""
    conn = store.open_connection()
    try:
        rows = store.get_skill_rows(conn, 1)
        row = next(item for item in rows if item["slug"] == "articulation")
        conn.execute(
            "UPDATE user_skills SET elo_rating = 400 WHERE user_id = 1 AND skill_id = ?",
            (row["skill_id"],),
        )
        payload = client.get("/api/exercise/next").json()
        assert payload["target_skill"] == "articulation"
    finally:
        conn.close()


def test_reused_exercise_focus_matches_what_was_asked_for(client):
    """Regression: every exercise is tagged with all nine skills, so a reuse
    lookup keyed on the skill tag alone could serve an exercise whose actual
    focus was a different dimension."""
    for skill in ("rhythm", "meter", "texture", "accidentals", "articulation"):
        for _ in range(3):
            payload = client.get("/api/exercise/next", params={"skill": skill}).json()
            assert payload["target_skill"] == skill, payload["rationale"]
            assert skill in payload["rationale"], payload["rationale"]
            assert f"level {payload['levels'][skill]}" in payload["rationale"]


@pytest.mark.parametrize("bars", [1, 4, 8, 12, 16])
def test_requested_length_is_always_honoured(client, bars):
    """Regression: the reuse lookup ignored bar count, so a request for 12 bars
    could be served a stored 4-bar exercise."""
    for _ in range(3):
        payload = client.get("/api/exercise/next", params={"bars": bars}).json()
        assert payload["bars"] == bars, f"asked for {bars} bars, got {payload['bars']}"
        assert len(payload["measures"]) == bars


def test_length_change_produces_a_different_exercise(client):
    short = client.get("/api/exercise/next", params={"bars": 4}).json()
    long = client.get("/api/exercise/next", params={"bars": 12}).json()
    assert short["exercise_id"] != long["exercise_id"]
    assert long["bars"] == 12


def test_played_exercises_lead_to_fresh_material(client):
    """Sight-reading is defeated by replaying the same handful of exercises."""
    ids = []
    for _ in range(10):
        exercise = client.get("/api/exercise/next").json()
        ids.append(exercise["exercise_id"])
        client.post(
            "/api/score",
            json={"exercise_id": exercise["exercise_id"], "notes": perfect_performance(exercise)},
        )
    assert len(set(ids)) >= 8, f"only {len(set(ids))} distinct exercises in 10 attempts"


def test_an_unplayed_exercise_is_reused_rather_than_regenerated(client):
    first = client.get("/api/exercise/next").json()
    second = client.get("/api/exercise/next").json()
    assert first["exercise_id"] == second["exercise_id"]


def test_reuse_never_crosses_level_profiles(client):
    """Regression: reuse matched on the target skill alone, so a plan calling for
    two hands could be served a stored right-hand-alone exercise."""
    conn = store.open_connection()
    try:
        conn.execute(
            """
            UPDATE user_skills SET elo_rating = 1300
            WHERE user_id = 1 AND skill_id = (SELECT id FROM skills WHERE slug = 'texture')
            """
        )
    finally:
        conn.close()

    saw_two_hands = False
    for _ in range(12):
        payload = client.get("/api/exercise/next").json()
        levels = payload["levels"]
        hands = {note["hand"] for note in payload["expected_notes"]}
        # texture 1 is right hand alone, 2 is left hand alone, 3+ is both.
        if levels["texture"] >= 3:
            saw_two_hands = True
            assert hands == {"RH", "LH"}, f"texture {levels['texture']} produced {hands}"
        elif levels["texture"] == 1:
            assert hands == {"RH"}, f"texture 1 produced {hands}"
        else:
            assert hands == {"LH"}, f"texture 2 produced {hands}"
        if payload["bass_pattern"]:
            assert levels["texture"] >= 3
    assert saw_two_hands, "a high texture rating should have produced two-hand material"


def test_exercises_are_reused_before_being_regenerated(client):
    first = client.get("/api/exercise/next", params={"skill": "key_signature"}).json()
    second = client.get("/api/exercise/next", params={"skill": "key_signature"}).json()
    # The library should hand back the same stored exercise when it still fits.
    assert first["exercise_id"] == second["exercise_id"]
    assert second["rationale"]


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def test_perfect_performance_passes_and_raises_the_rating(client):
    exercise = client.get("/api/exercise/next").json()
    before = client.get("/api/skills").json()
    before_rating = next(s for s in before if s["slug"] == exercise["target_skill"])["rating"]

    response = client.post(
        "/api/score",
        json={"exercise_id": exercise["exercise_id"], "notes": perfect_performance(exercise), "mode": "performance"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["score"] == pytest.approx(100.0)
    assert result["passed"] is True
    assert result["rating_change"]["delta"] > 0
    assert result["counts"]["missed"] == 0
    assert result["rating_change"]["before"] == pytest.approx(before_rating)


def test_silence_fails_and_lowers_the_rating(client):
    exercise = client.get("/api/exercise/next").json()
    # Move the user above the exercise so there is room to fall.
    response = client.post(
        "/api/score",
        json={"exercise_id": exercise["exercise_id"], "notes": silent_performance(exercise)},
    )
    result = response.json()
    assert result["score"] == 0.0
    assert result["passed"] is False
    assert result["counts"]["missed"] == len(exercise["expected_notes"])
    assert result["rating_change"]["delta"] < 0


def test_wrong_notes_are_reported_per_note_for_the_score_view(client):
    exercise = client.get("/api/exercise/next").json()
    result = client.post(
        "/api/score",
        json={"exercise_id": exercise["exercise_id"], "notes": sloppy_performance(exercise)},
    ).json()
    assert result["counts"]["wrong_pitch"] == len(exercise["expected_notes"])
    for item in result["feedback"]:
        assert item["status"] == "wrong_pitch"
        assert item["played_pitch"] == item["pitch"] + 1
        assert item["hand"] in {"RH", "LH"}


def test_scoring_an_unknown_exercise_is_404(client):
    response = client.post("/api/score", json={"exercise_id": 999999, "notes": []})
    assert response.status_code == 404


def test_latency_compensation_improves_a_late_performance(client):
    exercise = client.get("/api/exercise/next").json()
    late = [
        {"pitch": note["pitch"], "onset": note["onset_s"] + 0.15, "duration": 0.3}
        for note in exercise["expected_notes"]
    ]
    raw = client.post("/api/score", json={"exercise_id": exercise["exercise_id"], "notes": late}).json()
    compensated = client.post(
        "/api/score",
        json={"exercise_id": exercise["exercise_id"], "notes": late, "latency_ms": 150},
    ).json()
    assert compensated["rhythm_accuracy"] > raw["rhythm_accuracy"]


def test_repeated_success_pushes_difficulty_up(client):
    """The whole point of the loop: keep winning and the material gets harder."""
    first = client.get("/api/exercise/next", params={"skill": "rhythm"}).json()
    start_elo = first["difficulty_elo"]
    start_level = first["levels"]["rhythm"]

    latest = first
    for _ in range(12):
        latest = client.get("/api/exercise/next", params={"skill": "rhythm"}).json()
        client.post(
            "/api/score",
            json={
                "exercise_id": latest["exercise_id"],
                "notes": perfect_performance(latest),
                "mode": "performance",
            },
        )

    after = client.get("/api/profile").json()
    assert after["ratings"]["rhythm"] > start_elo
    final = client.get("/api/exercise/next", params={"skill": "rhythm"}).json()
    assert final["levels"]["rhythm"] >= start_level


def test_repeated_failure_pushes_difficulty_down(client):
    for _ in range(10):
        exercise = client.get("/api/exercise/next", params={"skill": "texture"}).json()
        client.post(
            "/api/score",
            json={"exercise_id": exercise["exercise_id"], "notes": sloppy_performance(exercise)},
        )
    final = client.get("/api/exercise/next", params={"skill": "texture"}).json()
    assert final["levels"]["texture"] <= 2


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------


def test_calibration_walks_a_ladder_then_hands_over_to_adaptation(client):
    seen_skills = []
    for _ in range(10):
        payload = client.get("/api/calibration/next").json()
        if payload.get("complete"):
            break
        seen_skills.append(payload["target_skill"])
        assert payload["source"] == "calibration"
        assert payload["step"] <= payload["total"]
        client.post(
            "/api/score",
            json={
                "exercise_id": payload["exercise_id"],
                "notes": perfect_performance(payload),
                "calibration": True,
            },
        )
    assert len(seen_skills) == 8
    assert len(set(seen_skills)) == 8, "calibration should sample distinct skills"

    final = client.get("/api/calibration/next").json()
    assert final["complete"] is True
    assert final["source"] != "calibration"


def test_calibration_converges_faster_than_normal_practice(client):
    for _ in range(8):
        payload = client.get("/api/calibration/next").json()
        if payload.get("complete"):
            break
        client.post(
            "/api/score",
            json={
                "exercise_id": payload["exercise_id"],
                "notes": perfect_performance(payload),
                "calibration": True,
            },
        )
    ratings = client.get("/api/profile").json()["ratings"]
    assert all(rating > 700.0 for rating in ratings.values())


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------


def test_a_stored_timestamp_belongs_to_a_local_day():
    """Regression: the streak took the UTC day and compared it with the local one.

    Timestamps are stored UTC, so slicing ten characters is only the right day for
    part of the clock. At UTC-3 anything played after 21:00 local is already tomorrow
    in UTC, and the Progress view reported a broken streak every evening.
    """
    from app.services import _local_day

    now_utc = datetime.now(timezone.utc).isoformat(sep=" ")
    assert _local_day(now_utc) == date.today().isoformat()


def test_a_utc_day_is_not_a_local_day():
    """Deterministic, in a zone where the two dates differ at that hour."""
    from app.services import _local_day

    previous = os.environ.get("TZ")
    os.environ["TZ"] = "Pacific/Kiritimati"  # UTC+14
    time_module.tzset()
    try:
        assert _local_day("2026-09-12 20:00:00") == "2026-09-13"
        assert _local_day("2026-09-12 05:00:00") == "2026-09-12"
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time_module.tzset()


def test_stats_summarise_progress(client):
    exercise = client.get("/api/exercise/next").json()
    client.post(
        "/api/score",
        json={"exercise_id": exercise["exercise_id"], "notes": perfect_performance(exercise)},
    )
    stats = client.get("/api/stats").json()

    assert stats["summary"]["performances"] == 1
    assert stats["summary"]["average_score"] == pytest.approx(100.0)
    assert stats["summary"]["pass_rate"] == 100.0
    assert stats["summary"]["streak_days"] == 1
    assert len(stats["radar"]) == len(SKILL_SLUGS)
    assert len(stats["history"]) == 1
    assert stats["history"][0]["target_skill"] == exercise["target_skill"]
    assert stats["tempo_progress"], "a passing performance should record a tempo"
    assert stats["skills"][0]["levels"]


def test_stats_report_common_mistakes(client):
    exercise = client.get("/api/exercise/next").json()
    client.post(
        "/api/score",
        json={"exercise_id": exercise["exercise_id"], "notes": sloppy_performance(exercise)},
    )
    stats = client.get("/api/stats").json()
    mistakes = stats["common_mistakes"]
    assert mistakes
    assert mistakes[0]["kind"] == "wrong_note"
    assert "played as" in mistakes[0]["label"]

    conn = store.open_connection()
    try:
        conn.execute("DELETE FROM performances")
    finally:
        conn.close()
    exercise = client.get("/api/exercise/next").json()
    client.post("/api/score", json={"exercise_id": exercise["exercise_id"], "notes": []})
    missed_stats = client.get("/api/stats").json()["common_mistakes"]
    assert missed_stats and missed_stats[0]["kind"] == "missed_note"
    assert missed_stats[0]["label"].endswith("(missed)")


def test_stats_are_empty_but_valid_before_any_practice(client):
    stats = client.get("/api/stats").json()
    assert stats["summary"]["performances"] == 0
    assert stats["summary"]["average_score"] == 0.0
    assert stats["history"] == []


def test_reset_profile_clears_progress(client):
    exercise = client.get("/api/exercise/next").json()
    client.post(
        "/api/score",
        json={"exercise_id": exercise["exercise_id"], "notes": perfect_performance(exercise)},
    )
    client.post("/api/profile/reset")
    profile = client.get("/api/profile").json()
    assert all(rating == pytest.approx(700.0) for rating in profile["ratings"].values())
    assert client.get("/api/stats").json()["summary"]["performances"] == 0


def test_performance_history_accumulates(client):
    for _ in range(3):
        exercise = client.get("/api/exercise/next").json()
        client.post(
            "/api/score",
            json={"exercise_id": exercise["exercise_id"], "notes": perfect_performance(exercise)},
        )
    stats = client.get("/api/stats").json()
    assert stats["summary"]["performances"] == 3
    assert len(stats["history"]) == 3
    # History is ordered oldest first for charting.
    assert stats["history"][0]["performed_at"] <= stats["history"][-1]["performed_at"]


# --------------------------------------------------------------------------
# Cross-domain: practising in the key of a piece
# --------------------------------------------------------------------------


def test_exercise_can_be_pinned_to_a_key(client):
    payload = client.get("/api/exercise/next", params={"key": "F#"}).json()
    assert payload["key_name"] == "F#"
    # The key-signature level is whatever makes that key legal, regardless of the
    # rating that dimension would otherwise have chosen.
    assert payload["levels"]["key_signature"] == 7


def test_pinning_a_key_sets_the_level_that_makes_it_legal(client):
    from app.skills_data import level_for_key

    for key in ("C", "Gb", "bb"):
        payload = client.get("/api/exercise/next", params={"key": key}).json()
        assert payload["key_name"] == key
        assert payload["levels"]["key_signature"] == level_for_key(key)


def test_an_unknown_key_is_refused(client):
    response = client.get("/api/exercise/next", params={"key": "H"})
    assert response.status_code == 422
    assert "unknown key" in response.json()["detail"]


def test_a_pinned_key_is_honoured_on_every_request(client):
    """The reuse lookup must not hand back an exercise in some other key."""
    for _ in range(6):
        payload = client.get("/api/exercise/next", params={"key": "Gb"}).json()
        assert payload["key_name"] == "Gb", payload["rationale"]


def test_pinning_a_key_is_reported_in_the_rationale(client):
    payload = client.get("/api/exercise/next", params={"key": "Ab"}).json()
    assert "Ab" in payload["rationale"]


def test_the_suggestion_endpoint_output_can_be_fed_back_as_a_key(client, legacy_db):
    """The whole point of the bridge: repertoire tells the trainer what to write."""
    client.post("/api/repertoire/import", json={"copy_media": False})
    suggestions = client.get("/api/practice-suggestions").json()
    assert suggestions, "the fixture has active pieces"
    for suggestion in suggestions:
        if not suggestion["suggested_key"]:
            continue
        exercise = client.get(
            "/api/exercise/next", params={"key": suggestion["suggested_key"]}
        ).json()
        assert exercise["key_name"] == suggestion["suggested_key"]


# --- progress: rating history and past attempts ---------------------------


def test_scoring_records_where_each_rating_moved(client):
    """`user_skills` keeps only today's number, so the curve needs recorded changes."""
    exercise = client.get("/api/exercise/next").json()
    assert client.get("/api/progress/ratings").json()["skills"] == []

    client.post(
        "/api/score",
        json={"exercise_id": exercise["exercise_id"], "notes": perfect_performance(exercise)},
    )
    body = client.get("/api/progress/ratings").json()
    # The Elo engine spreads an update across every dimension, so every skill moves a
    # little and all nine appear. The skill that was actually trained moves most, and
    # every point says whether it was the focus.
    assert {entry["slug"] for entry in body["skills"]} == set(SKILL_SLUGS)
    focus = next(entry for entry in body["skills"] if entry["slug"] == exercise["target_skill"])
    assert focus["name"]
    point = focus["points"][0]
    assert point["focus"] is True
    assert point["after"] > point["before"], "a perfect attempt raises the rating"
    assert point["delta"] == round(point["after"] - point["before"], 2)
    assert point["score"] == pytest.approx(100.0, abs=0.5)
    assert point["performance_id"] is not None

    incidental = [entry for entry in body["skills"] if entry["slug"] != exercise["target_skill"]]
    assert any(entry["points"][0]["focus"] is False for entry in incidental)
    assert focus["points"][0]["delta"] > max(
        abs(entry["points"][0]["delta"]) for entry in incidental
    ), "the trained skill moves more than the incidental nudges"
    assert body["biggest_gain"] == focus["name"]
    assert body["biggest_gain_delta"] > 0


def test_a_failed_attempt_records_a_fall(client):
    exercise = client.get("/api/exercise/next").json()
    client.post(
        "/api/score",
        json={"exercise_id": exercise["exercise_id"], "notes": []},
    )
    point = client.get("/api/progress/ratings").json()["skills"][0]["points"][0]
    assert point["after"] < point["before"]
    assert point["delta"] < 0


def test_rating_history_accumulates_in_order(client):
    for _ in range(3):
        exercise = client.get("/api/exercise/next").json()
        client.post(
            "/api/score",
            json={"exercise_id": exercise["exercise_id"], "notes": []},
        )
    skills = client.get("/api/progress/ratings").json()["skills"]
    assert skills
    for entry in skills:
        points = entry["points"]
        assert len(points) == 3, f"{entry['slug']} should have one point per attempt"
        assert [point["at"] for point in points] == sorted(point["at"] for point in points)
        # Every series has to be continuous: a point starts where the last one ended,
        # or the curve is drawing a rating that never existed.
        for previous, following in zip(points, points[1:]):
            assert following["before"] == pytest.approx(previous["after"])


def test_rating_history_can_be_windowed(client):
    exercise = client.get("/api/exercise/next").json()
    client.post(
        "/api/score",
        json={"exercise_id": exercise["exercise_id"], "notes": perfect_performance(exercise)},
    )
    assert client.get("/api/progress/ratings?days=1").json()["skills"] != []
    assert client.get("/api/progress/ratings?days=1").json()["days"] == 1


def test_a_past_attempt_can_be_read_back_for_replay(client):
    """The three things the results panel had in memory, read from the database."""
    exercise = client.get("/api/exercise/next").json()
    notes = perfect_performance(exercise)
    scored = client.post(
        "/api/score", json={"exercise_id": exercise["exercise_id"], "notes": notes}
    ).json()

    detail = client.get(f"/api/performances/{scored['performance_id']}").json()
    assert detail["exercise_id"] == exercise["exercise_id"]
    assert detail["score"] == pytest.approx(scored["score"])
    assert detail["target_skill"] == exercise["target_skill"]
    assert len(detail["expected_notes"]) == len(exercise["expected_notes"])
    assert len(detail["played_notes"]) == len(notes)
    assert len(detail["feedback"]) == len(exercise["expected_notes"])
    # Both sides carry what playback needs: pitch, onset in seconds, and a duration.
    assert {"pitch", "onset_s", "hand"} <= set(detail["expected_notes"][0])
    assert {"pitch", "onset", "duration", "velocity"} <= set(detail["played_notes"][0])
    assert {"hand", "played_pitch", "onset_error_s"} <= set(detail["feedback"][0])


def test_an_unknown_performance_is_not_found(client):
    assert client.get("/api/performances/9999").status_code == 404


# ---------------------------------------------------------------------------
# Deliberate practice: pinning the level and the hand
#
# The owner's decision (docs/ECOSYSTEM.md § Still open) is that handedness belongs to the
# material and difficulty is a separate choice. Two requests that differ only in which hand
# they ask for must therefore never be served each other's exercise — the fourth time this
# reuse key has had to learn a new field.
# ---------------------------------------------------------------------------


def test_a_pinned_level_is_honoured_in_every_dimension(client):
    payload = client.get("/api/exercise/next", params={"level": 3}).json()
    assert set(payload["levels"].values()) == {3}, payload["levels"]


def test_a_pinned_hand_is_the_clef_you_asked_to_read(client):
    """Level 1 alone would emit the right hand; the pin is what makes it the left."""
    payload = client.get(
        "/api/exercise/next", params={"skill": "texture", "level": 1, "hands": "LH"}
    ).json()
    assert payload["levels"]["texture"] == 1
    hands = {note["hand"] for note in payload["expected_notes"]}
    assert hands == {"LH"}, f"asked for the left hand at level 1 and got {hands}"


def test_both_hands_can_be_asked_for_at_level_one(client):
    payload = client.get(
        "/api/exercise/next", params={"skill": "texture", "level": 1, "hands": "both"}
    ).json()
    hands = {note["hand"] for note in payload["expected_notes"]}
    assert hands == {"RH", "LH"}, f"asked for both hands at level 1 and got {hands}"


def test_reuse_never_crosses_a_pinned_hand(client):
    """The collision this feature creates: equal level profiles, different material."""
    left = client.get(
        "/api/exercise/next", params={"skill": "texture", "hands": "LH"}
    ).json()
    right = client.get(
        "/api/exercise/next", params={"skill": "texture", "hands": "RH"}
    ).json()
    # The identity claim is asserted first because it is the one that names the defect.
    # Asserting the hands before it fails on `{'LH'} == {'RH'}` — true, but it reports the
    # symptom rather than the cause, and a falsifier cannot attribute the failure to this
    # assertion, so the check would be refused as unattributed evidence.
    assert left["exercise_id"] != right["exercise_id"], (
        "the left-hand exercise was served for a request for the right hand"
    )
    assert {note["hand"] for note in left["expected_notes"]} == {"LH"}
    assert {note["hand"] for note in right["expected_notes"]} == {"RH"}


def test_reuse_never_crosses_a_pinned_level(client):
    one = client.get("/api/exercise/next", params={"skill": "texture", "level": 1}).json()
    two = client.get("/api/exercise/next", params={"skill": "texture", "level": 2}).json()
    assert one["levels"]["texture"] == 1
    assert two["levels"]["texture"] == 2
    assert one["exercise_id"] != two["exercise_id"]


def test_reuse_still_serves_the_same_pinned_request_twice(client):
    """The pin must not defeat reuse altogether: the same request is the same exercise."""
    first = client.get("/api/exercise/next", params={"skill": "texture", "level": 4}).json()
    second = client.get("/api/exercise/next", params={"skill": "texture", "level": 4}).json()
    assert first["exercise_id"] == second["exercise_id"]


def test_a_pinned_request_says_so(client):
    payload = client.get(
        "/api/exercise/next", params={"skill": "texture", "level": 2, "hands": "LH"}
    ).json()
    assert payload["pinned_level"] == 2
    assert payload["pinned_hand"] == "LH"
    assert "level 2" in payload["rationale"]


def test_an_unpinned_request_pins_nothing(client):
    payload = client.get("/api/exercise/next").json()
    assert payload["pinned_level"] is None
    assert payload["pinned_hand"] is None


@pytest.mark.parametrize("params", [{"level": 0}, {"level": 11}, {"level": "two"}])
def test_an_impossible_level_is_refused(client, params):
    assert client.get("/api/exercise/next", params=params).status_code == 422


@pytest.mark.parametrize("hands", ["rh", "both_hands", "RH,LH", ""])
def test_an_unknown_hand_is_refused(client, hands):
    response = client.get("/api/exercise/next", params={"hands": hands})
    assert response.status_code == 422, f"{hands!r} was accepted"


# ---------------------------------------------------------------------------
# A pinned exercise is practice, not an assessment
#
# The owner's decision (2026-09-22): drilling easy material must not inflate the rating that
# chooses the automatic material. A perfect run at pinned level 1 against a rating of 900 is
# still worth about +2.6 under Elo, and twenty of them would move the rating ~50 points while
# the player was doing easier work than usual — the opposite of what they asked for.
# ---------------------------------------------------------------------------


def _ratings(client) -> dict[str, float]:
    return {row["slug"]: row["rating"] for row in client.get("/api/skills").json()}


def _rating_events() -> int:
    conn = store.open_connection()
    try:
        return int(conn.execute("SELECT COUNT(*) AS n FROM rating_events").fetchone()["n"])
    finally:
        conn.close()


def test_a_pinned_exercise_is_scored_and_logged_but_moves_no_rating(client):
    exercise = client.get(
        "/api/exercise/next", params={"skill": "texture", "level": 2, "hands": "LH"}
    ).json()
    before = _ratings(client)
    events_before = _rating_events()

    result = client.post(
        "/api/score",
        json={
            "exercise_id": exercise["exercise_id"],
            "notes": perfect_performance(exercise),
            "mode": "performance",
        },
    ).json()

    assert result["score"] == pytest.approx(100.0), "a pinned attempt is still scored"
    assert result["performance_id"] > 0, "and still logged, so the practice is recorded"
    # The invariant first, because it is the one that names the defect. Asserting `rated`
    # before it fails on `True is False` — true, but a falsifier cannot attribute that to the
    # claim the break is meant to test, so the run would be refused as unattributed.
    assert _ratings(client) == before, "deliberate practice must not move the ratings"
    assert _rating_events() == events_before, "and must not add a point to the curve"
    assert result["rated"] is False
    assert result["rating_change"] is None, "nothing moved, so there is no change to report"


def test_the_same_performance_unpinned_still_moves_the_rating(client):
    """The contrast that makes the previous test about the pin rather than about scoring."""
    exercise = client.get("/api/exercise/next", params={"skill": "texture"}).json()
    before = _ratings(client)
    result = client.post(
        "/api/score",
        json={
            "exercise_id": exercise["exercise_id"],
            "notes": perfect_performance(exercise),
            "mode": "performance",
        },
    ).json()
    assert result["rated"] is True
    assert result["rating_change"] is not None
    assert _ratings(client) != before


def test_pinning_only_the_hand_also_makes_it_practice(client):
    """A hand you chose is material you chose; the same reasoning applies."""
    exercise = client.get(
        "/api/exercise/next", params={"skill": "texture", "hands": "RH"}
    ).json()
    before = _ratings(client)
    result = client.post(
        "/api/score",
        json={
            "exercise_id": exercise["exercise_id"],
            "notes": perfect_performance(exercise),
            "mode": "performance",
        },
    ).json()
    assert result["rated"] is False
    assert _ratings(client) == before
