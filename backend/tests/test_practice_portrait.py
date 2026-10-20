"""The note-level portrait: register, touch, texture, travel, regularity.

The notes are planted directly and with exact onsets, because every number here is an
arithmetic consequence of them: a chord is three notes sharing an onset, a leap is the gap
between two attack centres, and an interval is the distance between two onsets. Recording
them through the ingest path would add a sitting boundary and a duration that none of the
assertions are about.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timezone

from app.practice import store
from app.practice.models import EventBatch, WireNote
from app.practice.portrait import portrait


def _sitting(conn, *, minutes: float = 10.0) -> int:
    start = datetime.combine(date.today(), time(20, 0), tzinfo=timezone.utc)
    start_ms = int(start.timestamp() * 1000)
    end_ms = start_ms + int(minutes * 60_000)
    cursor = conn.execute(
        "INSERT INTO sittings (started_ms, ended_ms, started_at, ended_at, local_date, source)"
        " VALUES (?, ?, ?, ?, ?, 'web_midi')",
        (
            start_ms,
            end_ms,
            store.utc_text(start_ms),
            store.utc_text(end_ms),
            date.today().isoformat(),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def _notes(conn, sitting_id: int, notes: list[tuple[int, int, int]]) -> None:
    for index, (offset_ms, pitch, velocity) in enumerate(notes):
        conn.execute(
            "INSERT INTO note_events"
            " (sitting_id, onset_ms, duration_ms, pitch, velocity, channel)"
            " VALUES (?, ?, 300, ?, ?, 0)",
            (sitting_id, 1_000 + offset_ms, pitch, velocity),
        )
    conn.commit()


def _six_notes(conn) -> int:
    """Three attacks: a triad, a rolled two-note chord, and a single note.

    Travel is between attack centres: 63.67 -> 74 -> 60, so 10.33 then 14 semitones.
    The two intervals are 100 ms and 150 ms, so mean 125 and CV 0.2.
    """
    sitting_id = _sitting(conn)
    _notes(
        conn,
        sitting_id,
        [
            (0, 60, 100),
            (0, 64, 100),
            (0, 67, 100),
            (100, 72, 80),
            (100, 76, 90),
            (250, 60, 100),
        ],
    )
    return sitting_id


def test_the_keyboard_profile_counts_the_keys_that_were_played(conn) -> None:
    _six_notes(conn)

    profile = portrait(conn, 90).keyboard
    assert profile.distinct_keys == 5
    assert (profile.lowest, profile.highest, profile.span_semitones) == (60, 76, 16)
    assert profile.mean_pitch == 66.5
    assert [(row.octave, row.notes) for row in profile.octaves] == [(4, 4), (5, 2)]
    classes = {row.pitch_class: row.notes for row in profile.pitch_classes}
    assert (classes[0], classes[4], classes[7]) == (3, 2, 1)


def test_an_attack_is_a_chord_and_a_roll_is_a_run(conn) -> None:
    """40 ms is the line between "together" and "one after another": the two notes a
    hundred milliseconds apart are a run, the three on the same onset are a chord."""
    _six_notes(conn)

    summary = portrait(conn, 90)
    assert summary.notes == 6
    assert summary.texture.attacks == 3
    assert summary.texture.notes_per_attack == 2.0
    assert summary.texture.chord_attacks == 1
    assert summary.texture.chord_share == round(1 / 3, 3)
    assert summary.texture.attacks_per_minute == 0.3


def test_travel_is_between_attack_centres_not_between_top_notes(conn) -> None:
    _six_notes(conn)

    travel = portrait(conn, 90).travel
    assert travel.semitones == round(10.3333 + 14, 1)
    assert travel.max_leap == 14.0
    assert travel.mean_leap == round((10.3333 + 14) / 2, 2)
    assert travel.metres == round(travel.semitones * 0.17 / 12, 1)


def test_regularity_is_measured_inside_phrases_only(conn) -> None:
    _six_notes(conn)

    timing = portrait(conn, 90).timing
    assert timing.intervals == 2
    assert timing.mean_interval_ms == 125.0
    assert timing.cv == 0.2


def test_touch_reports_the_palette_rather_than_one_average(conn) -> None:
    _six_notes(conn)

    touch = portrait(conn, 90).touch
    assert touch.notes == 6
    assert touch.mean_velocity == round(570 / 6, 2)
    assert (touch.min_velocity, touch.max_velocity) == (80, 100)
    assert touch.distinct_velocities == 3
    expected = -(4 / 6 * math.log2(4 / 6) + 2 * (1 / 6 * math.log2(1 / 6)))
    assert touch.entropy_bits == round(expected, 3)
    assert touch.dynamic_range_db == round(20 * math.log10(100 / 80), 2)


def test_an_empty_window_answers_with_nothing_rather_than_with_zero(conn) -> None:
    summary = portrait(conn, 90)
    assert summary.notes == 0
    assert summary.keyboard.mean_pitch is None
    assert summary.texture.attacks == 0
    assert summary.texture.notes_per_attack is None
    assert summary.timing.cv is None


def test_the_endpoint_serves_the_same_portrait_the_store_does(client) -> None:
    response = client.post(
        "/api/practice/events",
        json={
            "tz_offset_minutes": 0,
            "source": "web_midi",
            "events": [
                {
                    "epoch_ms": int(datetime.now().timestamp() * 1000) - 1_000,
                    "pitch": 60,
                    "velocity": 90,
                    "duration_ms": 250,
                    "channel": 0,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text

    body = client.get("/api/practice/analytics/portrait?days=90").json()
    assert body["notes"] == 1
    assert body["keyboard"]["mean_pitch"] == 60.0
    assert body["texture"]["attacks"] == 1


def test_the_offset_parameter_is_validated_at_the_edge(client) -> None:
    assert client.get("/api/practice/analytics/portrait?tz_offset_minutes=900").status_code == 422


def test_a_new_note_rebuilds_the_portrait_it_changed(conn) -> None:
    """The cache is keyed on the notes themselves, so the next read after a recording must
    not answer with the previous portrait — the whole point of a cache keyed on inputs is
    that the inputs move."""
    sitting_id = _six_notes(conn)
    assert portrait(conn, 90).notes == 6

    _notes(conn, sitting_id, [(400, 62, 100)])
    assert portrait(conn, 90).notes == 7


def test_a_new_sitting_rebuilds_the_portrait(conn) -> None:
    assert portrait(conn, 90).notes == 0

    _notes(conn, _sitting(conn), [(0, 60, 90)])
    assert portrait(conn, 90).notes == 1
