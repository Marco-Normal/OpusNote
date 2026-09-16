"""`db.json_load` and every route that reads stored JSON.

T9 in `docs/TEST-STRATEGY.md`: a corrupt `exercises.expected_json` or
`performances.analysis_json` used to become an empty list, so damage presented as "this
exercise has no expected notes" three weeks after the row was written. The malformed
branch now raises `CorruptJSON`, the empty/`None` branch still returns the default, and
`main.py` maps the exception to a legible 500.

The call sites this covers, all of them:

* `store.py:199`  `onset_bias_ms`        -> `GET /api/status/system`
* `store.py:376`  `get_exercise` params -> `GET /api/exercise/{id}`
* `store.py:381`  `get_exercise` notes  -> `GET /api/exercise/{id}`
* `store.py:469`  `performance_detail`  -> `GET /api/performances/{id}`
* `store.py:470`  `performance_detail`  -> `GET /api/performances/{id}`
* `store.py:476`  `performance_detail`  -> `GET /api/performances/{id}`
* `store.py:477`  `performance_detail`  -> `GET /api/performances/{id}`
* `services.py:389` `_common_mistakes`   -> `GET /api/stats`
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db, main as main_module
from app.config import settings


def _perfect_performance(exercise: dict) -> list[dict]:
    return [
        {"pitch": note["pitch"], "onset": note["onset_s"], "duration": 0.4, "velocity": 80}
        for note in exercise["expected_notes"]
    ]


# --------------------------------------------------------------------------
# The function
# --------------------------------------------------------------------------


def test_valid_json_is_parsed() -> None:
    assert db.json_load('{"a": 1}', {}) == {"a": 1}
    assert db.json_load("[1, 2]", []) == [1, 2]


def test_empty_or_none_returns_the_default() -> None:
    """The positive control: "nothing stored" is not damage."""
    assert db.json_load(None, {"default": True}) == {"default": True}
    assert db.json_load("", []) == []
    assert db.json_load(0, "d") == "d"


def test_malformed_text_raises_and_names_the_damage() -> None:
    with pytest.raises(db.CorruptJSON) as caught:
        db.json_load('{"broken": ', [])
    message = str(caught.value)
    assert "corrupt" in message
    assert '{"broken": ' in message, "the message names the raw value"


def test_a_long_value_is_truncated_in_the_message() -> None:
    with pytest.raises(db.CorruptJSON) as caught:
        db.json_load("x" * 5000, None)
    message = str(caught.value)
    assert "..." in message
    assert len(message) < 400, "a 5 kB row must not become a 5 kB error message"


def test_a_non_text_value_counts_as_damage() -> None:
    """`json.loads` raises `TypeError` for a non-text value, which is still damage."""
    with pytest.raises(db.CorruptJSON):
        db.json_load(12345, [])


def test_corrupt_json_is_a_value_error() -> None:
    assert issubclass(db.CorruptJSON, ValueError)


# --------------------------------------------------------------------------
# The routes
# --------------------------------------------------------------------------


def test_every_route_that_reads_stored_json_still_works(client) -> None:
    exercise = client.get("/api/exercise/next").json()
    detail = client.get(f"/api/exercise/{exercise['exercise_id']}")
    assert detail.status_code == 200
    assert detail.json()["expected_notes"], "stored JSON was parsed, not defaulted"

    scored = client.post(
        "/api/score",
        json={
            "exercise_id": exercise["exercise_id"],
            "notes": _perfect_performance(exercise),
        },
    )
    assert scored.status_code == 200
    performance_id = scored.json()["performance_id"]

    attempt = client.get(f"/api/performances/{performance_id}")
    assert attempt.status_code == 200
    assert attempt.json()["played_notes"]
    assert attempt.json()["expected_notes"]

    assert client.get("/api/stats").status_code == 200
    assert client.get("/api/status/system").status_code == 200


def test_a_null_json_column_is_still_the_default(client) -> None:
    """The empty branch reaches the route as a normal, working exercise."""
    exercise = client.get("/api/exercise/next").json()
    conn = db.connect(settings.db_path)
    try:
        conn.execute(
            "UPDATE exercises SET expected_json = NULL, params_json = NULL WHERE id = ?",
            (exercise["exercise_id"],),
        )
    finally:
        conn.close()

    response = client.get(f"/api/exercise/{exercise['exercise_id']}")
    assert response.status_code == 200
    assert response.json()["expected_notes"] == []


def test_a_corrupt_row_is_a_legible_500(client) -> None:
    """Without the handler this is a bare Starlette traceback and a generic 500."""
    exercise = client.get("/api/exercise/next").json()
    conn = db.connect(settings.db_path)
    try:
        conn.execute(
            "UPDATE exercises SET expected_json = ? WHERE id = ?",
            ('{"oops"', exercise["exercise_id"]),
        )
    finally:
        conn.close()

    with TestClient(main_module.app, raise_server_exceptions=False) as raw:
        response = raw.get(f"/api/exercise/{exercise['exercise_id']}")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "corrupt" in detail
    assert '{"oops"' in detail, "the operator can see which row is damaged"
