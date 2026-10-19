"""The rhythm read: weeks, days and technique over a window.

The rows are planted directly rather than recorded, for one reason: every assertion here is
about a *calendar* boundary, and a sitting produced through the clock-dependent ingest path
would drift across midnight (or a Monday) depending on when the suite runs. The measurements
themselves are the ingest path's business and are tested where they are produced.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from app.practice import store

MONDAY = 0

#: Enough margin that "today minus a week" is always inside the 90-day default.
WEEK = timedelta(days=7)


def _sitting(conn, day: date, minutes: float, *, hour: int = 18, minute: int = 0) -> int:
    start = datetime.combine(day, time(hour, minute))
    start_ms = int(start.timestamp() * 1000)
    end_ms = start_ms + int(minutes * 60_000)
    cursor = conn.execute(
        "INSERT INTO sittings (started_ms, ended_ms, started_at, ended_at, local_date, source)"
        " VALUES (?, ?, ?, ?, ?, 'web_midi')",
        (start_ms, end_ms, store.utc_text(start_ms), store.utc_text(end_ms), day.isoformat()),
    )
    conn.commit()
    return int(cursor.lastrowid)


def _measured_segment(conn, sitting_id: int, duration_s: float, **columns) -> None:
    segment_id = conn.execute(
        "INSERT INTO segments (sitting_id, start_ms, end_ms) VALUES (?, 0, ?)",
        (sitting_id, int(duration_s * 1000)),
    ).lastrowid
    names = ", ".join(["segment_id", "duration_s", *columns])
    marks = ", ".join(["?"] * (2 + len(columns)))
    conn.execute(
        f"INSERT INTO segment_metrics ({names}) VALUES ({marks})",
        (segment_id, duration_s, *columns.values()),
    )
    conn.commit()


def _this_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def test_a_day_keeps_its_first_sitting_separate_from_the_rest(conn) -> None:
    """The whole reason this read exists: a lost second session must be visible as such.

    Two sittings on Monday and one on Tuesday, so the week's ``first_minutes`` has to be the
    first of each *day* — 30 + 20 — and ``extra_minutes`` only Monday's second one.
    """
    monday = _this_monday()
    tuesday = monday + timedelta(days=1)
    _sitting(conn, monday, 30)
    _sitting(conn, monday, 10, hour=19)
    _sitting(conn, tuesday, 20)

    week = next(row for row in store.rhythm(conn).weeks if row.week_start == monday.isoformat())
    assert (week.sittings, week.practised_days) == (3, 2)
    assert (week.first_minutes, week.extra_minutes) == (50.0, 10.0)
    assert week.minutes == 60.0
    assert week.longest_minutes == 30.0


def test_a_week_with_no_practice_is_reported_rather_than_skipped(conn) -> None:
    """A gap is a fact about the habit. Skipping the empty week would draw the two
    neighbouring bars next to each other and turn a break into a slope."""
    monday = _this_monday()
    _sitting(conn, monday - WEEK, 15)
    _sitting(conn, monday, 20)

    weeks = store.rhythm(conn).weeks
    assert [row.week_start for row in weeks] == [
        (monday - WEEK).isoformat(),
        monday.isoformat(),
    ]
    assert weeks[0].minutes == 15.0


def test_a_sunday_belongs_to_the_week_that_started_six_days_before(conn) -> None:
    """Monday-first is a decision, not an accident: a Sunday-first bucket would put one
    weekend's practice on two sides of a boundary nobody crossed."""
    monday = _this_monday()
    _sitting(conn, monday + timedelta(days=6), 10)  # Sunday
    weeks = store.rhythm(conn).weeks
    assert [row.week_start for row in weeks] == [monday.isoformat()]
    assert weeks[0].minutes == 10.0


def test_sittings_outside_the_window_are_not_counted(conn) -> None:
    monday = _this_monday()
    _sitting(conn, monday, 20)
    _sitting(conn, monday - timedelta(days=200), 45)

    rhythm = store.rhythm(conn, days=90)
    assert rhythm.sittings == 1
    assert rhythm.minutes == 20.0
    assert rhythm.window_start == monday.isoformat()


def test_adherence_is_measured_from_the_first_practised_day(conn) -> None:
    """A window wider than the record must not judge the player for the days before the
    log existed — that is how a brand-new log reports 10% adherence."""
    monday = _this_monday()
    _sitting(conn, monday, 20)
    rhythm = store.rhythm(conn, days=365)
    assert rhythm.practised_days == 1
    assert rhythm.elapsed_days == (date.today() - monday).days + 1


def test_four_or_more_sittings_share_one_bucket(conn) -> None:
    day = _this_monday()
    for hour in (9, 11, 13, 15, 17):
        _sitting(conn, day, 5, hour=hour)
    counts = {row.sessions: row.days for row in store.rhythm(conn).session_counts}
    assert counts[4] == 1
    assert counts[1] == 0
    assert store.rhythm(conn).sessions_per_practised_day == 5.0


def test_weekdays_start_on_monday(conn) -> None:
    monday = _this_monday()
    _sitting(conn, monday, 20)
    _sitting(conn, monday + timedelta(days=6), 10)  # Sunday
    days = {row.weekday: row for row in store.rhythm(conn).weekdays}
    assert sorted(days) == list(range(7))
    assert days[MONDAY].minutes == 20.0
    assert days[6].minutes == 10.0
    assert days[3].minutes == 0.0


def test_technique_averages_leave_out_segments_without_pedal_data(conn) -> None:
    """``pedal_basis IS NULL`` means "no pedal stream was ever recorded", which is not the
    same as "the pedal was up". Averaging those in would report a pedal habit the player
    may not have."""
    sitting = _sitting(conn, _this_monday(), 20)
    _measured_segment(
        conn,
        sitting,
        60.0,
        median_tempo=120.0,
        median_velocity=60.0,
        mean_velocity_low=50.0,
        mean_velocity_high=70.0,
        restarts=2,
        pedal_basis="observed",
        pedal_down_ratio=0.9,
        pedal_blur=3,
    )
    _measured_segment(conn, sitting, 60.0, median_tempo=80.0, restarts=0)

    technique = store.rhythm(conn).technique
    assert technique.segments == 2
    assert technique.measured_minutes == 2.0
    assert technique.mean_tempo == 100.0
    assert technique.pedal_segments == 1
    assert technique.pedal_down_ratio == 0.9
    assert technique.restarts_per_minute == 1.0  # 2 restarts over 2 measured minutes
    assert technique.blurs_per_minute == 3.0  # 3 blurs over the 1 min that carried pedal data


def test_an_empty_window_answers_with_nothing_rather_than_zero(conn) -> None:
    rhythm = store.rhythm(conn)
    assert (rhythm.sittings, rhythm.practised_days) == (0, 0)
    assert rhythm.window_start is None
    assert rhythm.median_session_minutes is None
    assert rhythm.technique.mean_tempo is None
    assert rhythm.weeks == []


def test_the_window_is_validated_at_the_edge(client) -> None:
    assert client.get("/api/practice/analytics/rhythm").status_code == 200
    assert client.get("/api/practice/analytics/rhythm?days=1").status_code == 200
    assert client.get("/api/practice/analytics/rhythm?days=0").status_code == 422
    assert client.get("/api/practice/analytics/rhythm?days=3651").status_code == 422


def test_the_endpoint_reports_the_same_numbers_the_store_does(client, conn) -> None:
    """The route is a projection, not a second implementation."""
    monday = _this_monday()
    _sitting(conn, monday, 30)
    _sitting(conn, monday, 12, hour=20)
    _sitting(conn, monday + timedelta(days=2), 25)

    body = client.get("/api/practice/analytics/rhythm?days=90").json()
    direct = store.rhythm(conn, days=90)
    assert body["sittings"] == direct.sittings == 3
    assert body["minutes"] == direct.minutes == 67.0
    assert body["weeks"][-1]["first_minutes"] == direct.weeks[-1].first_minutes == 55.0
    assert body["weeks"][-1]["extra_minutes"] == 12.0
    assert body["window_end"] == date.today().isoformat()
