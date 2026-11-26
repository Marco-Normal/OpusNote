"""Practice rhythm analytics: weekly/daily distributions, hours, and lag correlations."""

from __future__ import annotations

import collections
import sqlite3
import statistics
from datetime import date, datetime, timedelta

from ..config import settings
from . import kinds
from .analytics import _fill_days, _minutes, _today
from .models import (
    HourMinutes,
    LagCorrelation,
    RhythmSummary,
    RhythmWeek,
    SessionCountBucket,
    TechniqueSummary,
    WeekdayMinutes,
)

def _round(value, digits: int = 1):
    return None if value is None else round(float(value), digits)


def _utc_offset_minutes_now() -> int:
    """The host's present UTC offset — the fallback for sittings that carry none.

    Only a fallback: a sitting recorded from this build stores the offset it was logged
    with, which is the only one that can describe a DST change that has since happened.
    """
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds() // 60) if offset is not None else 0


def _hour_chunks(start_ms: int, end_ms: int, offset_minutes: int):
    """Split a sitting into ``(local hour, minutes)`` chunks at the hour boundaries.

    A 21:40 two-hour sitting is 20 minutes on one day's 21:00 and 100 on the next day's
    00:00; assigning the whole thing to the start hour would move an hour of playing into
    a bucket it never touched.
    """
    step = 3_600_000
    shift = offset_minutes * 60_000
    cursor = start_ms + shift
    end = max(end_ms, start_ms) + shift
    if end <= cursor:
        yield (cursor // step) % 24, 0.0
        return
    while cursor < end:
        boundary = (cursor // step + 1) * step
        chunk_end = min(end, boundary)
        yield (cursor // step) % 24, (chunk_end - cursor) / 60_000.0
        cursor = chunk_end


def _correlation_at_lag(series: list[float], lag: int) -> tuple[float | None, int]:
    """Pearson r of ``series`` with itself ``lag`` days apart, and the pair count."""
    pairs = len(series) - lag
    if pairs < 3:
        return None, max(pairs, 0)
    left = series[:pairs]
    right = series[lag:]
    mean_left = sum(left) / pairs
    mean_right = sum(right) / pairs
    cov = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    var_left = sum((a - mean_left) ** 2 for a in left)
    var_right = sum((b - mean_right) ** 2 for b in right)
    denominator = (var_left * var_right) ** 0.5
    if denominator == 0:
        return None, pairs
    return cov / denominator, pairs


def rhythm(
    conn: sqlite3.Connection,
    days: int = 90,
    tz_offset_minutes: int | None = None,
) -> RhythmSummary:
    """Practice volume over time: weeks, daily distribution, weekdays, technique.

    Deliberately its own read rather than a section of :func:`summary`. The Log polls that one
    every twenty seconds, so anything added there is paid on a poll; this is paid once, when the
    tab is opened, and ``days`` bounds every query below to the window the player asked for.

    Nothing here touches ``note_events``. The weekly split needs one fact per sitting (when it
    started, how long it lasted), which is a scan of ``sittings`` for the window; the technique
    averages are one join from ``segment_metrics`` through ``segments``. Both grow with the
    window, never with the note count.

    The week bucket is Monday-first because that is what "this week" means in the rest of the
    UI (the streak and the dashboard's seven-day figure), and a Sunday-first bucket would put
    one weekend's practice on two sides of a boundary it does not cross.

    ``tz_offset_minutes`` is the caller's offset, used only for sittings that do not carry
    their own — everything recorded since the column existed uses the offset it was logged
    with, because the player's clock at 21:00 is a fact about that evening, not about now.
    """
    assumed_offset = (
        tz_offset_minutes if tz_offset_minutes is not None else _utc_offset_minutes_now()
    )
    today = _today()
    since = (today - timedelta(days=days - 1)).isoformat()
    # A per-day rank, so "was this the day's first sitting" is a property of the row rather than
    # a second query the caller has to join back. `started_ms` then `id` is the order the player
    # experienced, and it stays deterministic when an imported sitting shares a millisecond.
    week_rows = conn.execute(
        """
        WITH sitting AS (
            SELECT local_date,
                   (ended_ms - started_ms) / 60000.0 AS minutes,
                   ROW_NUMBER() OVER (PARTITION BY local_date ORDER BY started_ms, id) AS position
            FROM sittings
            WHERE local_date >= ?
        )
        SELECT date(local_date, 'weekday 0', '-6 days') AS week_start,
               SUM(minutes) AS minutes,
               COUNT(*) AS sittings,
               COUNT(DISTINCT local_date) AS practised_days,
               MAX(minutes) AS longest_minutes,
               SUM(CASE WHEN position = 1 THEN minutes ELSE 0 END) AS first_minutes,
               SUM(CASE WHEN position > 1 THEN minutes ELSE 0 END) AS extra_minutes
        FROM sitting
        GROUP BY week_start
        ORDER BY week_start
        """,
        (since,),
    ).fetchall()
    # Weeks with nothing in them are part of the shape — a gap is the interesting fact, and
    # dropping it would join two distant weeks into one downward slope.
    weeks: list[RhythmWeek] = []
    if week_rows:
        by_week = {row["week_start"]: row for row in week_rows}
        cursor = date.fromisoformat(week_rows[0]["week_start"])
        last = date.fromisoformat(week_rows[-1]["week_start"])
        while cursor <= last:
            row = by_week.get(cursor.isoformat())
            weeks.append(
                RhythmWeek(
                    week_start=cursor.isoformat(),
                    minutes=_round(row["minutes"]) if row else 0.0,
                    sittings=int(row["sittings"]) if row else 0,
                    practised_days=int(row["practised_days"]) if row else 0,
                    longest_minutes=_round(row["longest_minutes"]) if row else 0.0,
                    first_minutes=_round(row["first_minutes"]) if row else 0.0,
                    extra_minutes=_round(row["extra_minutes"]) if row else 0.0,
                )
            )
            cursor += timedelta(days=7)

    sittings = conn.execute(
        "SELECT local_date, (ended_ms - started_ms) / 60000.0 AS minutes"
        " FROM sittings WHERE local_date >= ?",
        (since,),
    ).fetchall()
    durations = [float(row["minutes"]) for row in sittings]
    per_day = collections.Counter(row["local_date"] for row in sittings)
    per_count = collections.Counter(per_day.values())
    session_counts = [
        SessionCountBucket(sessions=label, days=per_count.get(label, 0))
        for label in (1, 2, 3)
    ]
    session_counts.append(
        SessionCountBucket(
            sessions=4, days=sum(count for n, count in per_count.items() if n >= 4)
        )
    )

    # strftime('%w') is Sunday = 0; the rest of this module counts from Monday.
    weekday_rows = conn.execute(
        """
        SELECT CAST(strftime('%w', local_date) AS INTEGER) AS sunday_first,
               SUM(ended_ms - started_ms) / 60000.0 AS minutes,
               COUNT(DISTINCT local_date) AS practised_days
        FROM sittings
        WHERE local_date >= ?
        GROUP BY sunday_first
        """,
        (since,),
    ).fetchall()
    by_weekday = {
        (int(row["sunday_first"]) + 6) % 7: row for row in weekday_rows
    }
    weekdays = [
        WeekdayMinutes(
            weekday=index,
            minutes=_round(by_weekday[index]["minutes"]) if index in by_weekday else 0.0,
            practised_days=(
                int(by_weekday[index]["practised_days"]) if index in by_weekday else 0
            ),
        )
        for index in range(7)
    ]

    tech = conn.execute(
        """
        SELECT COUNT(*) AS segments,
               COALESCE(SUM(m.duration_s), 0) AS seconds,
               AVG(m.median_tempo) AS mean_tempo,
               AVG(m.median_velocity) AS mean_velocity,
               AVG(m.mean_velocity_low) AS mean_velocity_low,
               AVG(m.mean_velocity_high) AS mean_velocity_high,
               COALESCE(SUM(m.restarts), 0) AS restarts,
               SUM(CASE WHEN m.pedal_basis IS NOT NULL THEN 1 ELSE 0 END) AS pedal_segments,
               AVG(CASE WHEN m.pedal_basis IS NOT NULL THEN m.pedal_down_ratio END)
                   AS pedal_down_ratio,
               COALESCE(SUM(CASE WHEN m.pedal_basis IS NOT NULL THEN m.pedal_blur ELSE 0 END), 0)
                   AS blurs,
               COALESCE(SUM(CASE WHEN m.pedal_basis IS NOT NULL THEN m.duration_s ELSE 0 END), 0)
                   AS pedal_seconds
        FROM segment_metrics m
        JOIN segments g ON g.id = m.segment_id
        JOIN sittings s ON s.id = g.sitting_id
        WHERE s.local_date >= ?
        """,
        (since,),
    ).fetchone()
    measured_minutes = float(tech["seconds"] or 0.0) / 60.0
    pedal_minutes = float(tech["pedal_seconds"] or 0.0) / 60.0
    technique = TechniqueSummary(
        segments=int(tech["segments"] or 0),
        measured_minutes=_minutes(tech["seconds"]),
        mean_tempo=_round(tech["mean_tempo"], 1),
        mean_velocity=_round(tech["mean_velocity"], 1),
        mean_velocity_low=_round(tech["mean_velocity_low"], 1),
        mean_velocity_high=_round(tech["mean_velocity_high"], 1),
        restarts_per_minute=(
            _round(float(tech["restarts"]) / measured_minutes, 2)
            if measured_minutes > 0
            else None
        ),
        pedal_segments=int(tech["pedal_segments"] or 0),
        pedal_down_ratio=_round(tech["pedal_down_ratio"], 3),
        blurs_per_minute=(
            _round(float(tech["blurs"]) / pedal_minutes, 2) if pedal_minutes > 0 else None
        ),
    )

    hour_rows = conn.execute(
        "SELECT started_ms, ended_ms, tz_offset_minutes FROM sittings WHERE local_date >= ?",
        (since,),
    ).fetchall()
    hour_minutes = [0.0] * 24
    hour_sittings = [0] * 24
    for row in hour_rows:
        offset = (
            int(row["tz_offset_minutes"])
            if row["tz_offset_minutes"] is not None
            else assumed_offset
        )
        start_hour = (int(row["started_ms"]) + offset * 60_000) // 3_600_000 % 24
        hour_sittings[start_hour] += 1
        for hour, minutes in _hour_chunks(
            int(row["started_ms"]), int(row["ended_ms"]), offset
        ):
            hour_minutes[hour] += minutes
    hours = [
        HourMinutes(
            hour=index, minutes=_round(hour_minutes[index]), sittings=hour_sittings[index]
        )
        for index in range(24)
    ]

    # Daily minutes over the window, zeros included, for the serial correlation. Built from
    # `per_day` (a Counter of practised days) so an empty day is an explicit 0.
    by_day: dict[str, float] = collections.defaultdict(float)
    for row in sittings:
        by_day[str(row["local_date"])] += float(row["minutes"])
    daily: list[float] = []
    cursor = today - timedelta(days=days - 1)
    while cursor <= today:
        daily.append(by_day.get(cursor.isoformat(), 0.0))
        cursor += timedelta(days=1)
    autocorrelations = []
    for lag in (1, 7, 14):
        r, pairs = _correlation_at_lag(daily, lag)
        autocorrelations.append(
            LagCorrelation(lag=lag, r=_round(r, 3), pairs=pairs)
        )

    window_start = min(per_day) if per_day else None
    elapsed_days = days
    if window_start is not None:
        elapsed_days = min(days, (today - date.fromisoformat(window_start)).days + 1)
    total_minutes = sum(durations)
    return RhythmSummary(
        days=days,
        window_start=window_start,
        window_end=today.isoformat(),
        practised_days=len(per_day),
        elapsed_days=elapsed_days,
        sittings=len(durations),
        minutes=_round(total_minutes),
        median_session_minutes=_round(statistics.median(durations) if durations else None),
        longest_session_minutes=_round(max(durations)) if durations else 0.0,
        sessions_per_practised_day=(
            _round(len(durations) / len(per_day), 2) if per_day else None
        ),
        weeks=weeks,
        session_counts=session_counts,
        weekdays=weekdays,
        hours=hours,
        autocorrelations=autocorrelations,
        tz_offset_minutes=assumed_offset,
        technique=technique,
    )

