"""Practice analytics: calendar, per-piece totals, neglected pieces, tempo, and streaks."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Sequence

from . import capture_status
from . import kinds
from .models import (
    AnalyticsSummary,
    CalendarDay,
    NeglectedPiece,
    PiecePractice,
    PiecePracticeDetail,
    PracticeKindSplit,
    SourceSplit,
    TempoPoint,
    TempoSeries,
)
from .store_core import NotFound, _find_sitting, list_sittings_conn

def _minutes(seconds: float | None) -> float:
    return round((seconds or 0.0) / 60.0, 1)


def _today():
    """The player's calendar day.

    Server-local, not UTC. This app runs on the piano machine — one host, one
    timezone — and `local_date` was written in the player's timezone, so comparing
    it against a UTC date would call an evening's practice "yesterday" for anyone
    west of Greenwich.
    """
    return datetime.now().date()


def calendar(conn: sqlite3.Connection, days: int) -> list[CalendarDay]:
    """One entry per day in the window, including the days nothing happened on.

    ``days`` bounds the *queries*, not only the list they produce. It used to be applied by
    `_fill_days` at the end alone, so a one-day calendar still grouped every note event in the
    database — 20 ms flat for any window, on a poll, which is a cost that grows with the log
    while the request does not (R1). The filter is the same one `sources` and `by_piece`
    already use, and `_fill_days` reads only the days inside the window, so every window's
    answer is unchanged.
    """
    since = (_today() - timedelta(days=days - 1)).isoformat()
    days_rows = conn.execute(
        """
        SELECT local_date AS date,
               COUNT(*) AS sittings,
               SUM(ended_ms - started_ms) / 60000.0 AS minutes
        FROM sittings
        WHERE local_date >= ?
        GROUP BY local_date
        ORDER BY local_date
        """,
        (since,),
    ).fetchall()
    note_rows = conn.execute(
        "SELECT s.local_date AS date, COUNT(*) AS notes"
        " FROM note_events e JOIN sittings s ON s.id = e.sitting_id"
        " WHERE s.local_date >= ?"
        " GROUP BY s.local_date",
        (since,),
    ).fetchall()
    notes_by_date = {row["date"]: int(row["notes"]) for row in note_rows}
    # What was written down, kept as its own series. The practice domain reads the
    # journal here for the same reason `by_piece` already does: "how long did I
    # practise" is a question about the whole log, and the journal is part of it.
    written_rows = conn.execute(
        """
        SELECT entry_date AS date,
               COALESCE(SUM(practice_minutes), 0) AS minutes,
               COUNT(*) AS entries
        FROM piece_journal
        WHERE practice_minutes IS NOT NULL AND entry_date >= ?
        GROUP BY entry_date
        """,
        (since,),
    ).fetchall()
    written_by_date = {
        row["date"]: (round(float(row["minutes"] or 0.0), 1), int(row["entries"]))
        for row in written_rows
    }
    by_date = {}
    for row in days_rows:
        date = row["date"]
        written, entries = written_by_date.get(date, (0.0, 0))
        by_date[date] = CalendarDay(
            date=date,
            minutes=round(float(row["minutes"] or 0.0), 1),
            notes=notes_by_date.get(date, 0),
            sittings=int(row["sittings"]),
            written_minutes=written,
            written_entries=entries,
        )
    # A day with prose but no notes still has to appear, or the entries vanish from
    # the calendar entirely.
    for date, (written, entries) in written_by_date.items():
        if date not in by_date:
            by_date[date] = CalendarDay(
                date=date, minutes=0.0, notes=0, sittings=0,
                written_minutes=written, written_entries=entries,
            )
    return _fill_days(by_date, days)


def _fill_days(by_date: dict[str, CalendarDay], days: int) -> list[CalendarDay]:
    """Every day in the window, including the empty ones.

    A heatmap drawn only from days that have rows renders a gap-free strip and
    silently loses the fact that nothing happened for a week.
    """
    today = _today()
    out: list[CalendarDay] = []
    for offset in range(days - 1, -1, -1):
        key = (today - timedelta(days=offset)).isoformat()
        out.append(by_date.get(key) or CalendarDay(date=key, minutes=0.0, notes=0, sittings=0))
    return out


def by_piece(conn: sqlite3.Connection, days: int) -> list[PiecePractice]:
    since = (_today() - timedelta(days=days - 1)).isoformat()
    rows = conn.execute(
        """
        SELECT p.id AS piece_id,
               p.title,
               c.name AS composer_name,
               p.opus,
               COUNT(g.id) AS segments,
               SUM(m.duration_s) AS seconds,
               SUM(m.note_count) AS notes,
               MAX(s.local_date) AS last_played,
               (SELECT COALESCE(SUM(j.practice_minutes), 0) FROM piece_journal j
                 WHERE j.piece_id = p.id) AS journal_minutes
        FROM segments g
        JOIN sittings s ON s.id = g.sitting_id
        JOIN pieces p ON p.id = g.piece_id
        LEFT JOIN composers c ON c.id = p.composer_id
        LEFT JOIN segment_metrics m ON m.segment_id = g.id
        WHERE g.piece_id IS NOT NULL AND s.local_date >= ?
        GROUP BY p.id
        ORDER BY seconds DESC, p.title COLLATE NOCASE
        """,
        (since,),
    ).fetchall()
    return [
        PiecePractice(
            piece_id=int(row["piece_id"]),
            title=row["title"],
            composer_name=row["composer_name"],
            opus=row["opus"],
            minutes=_minutes(row["seconds"]),
            notes=int(row["notes"] or 0),
            segments=int(row["segments"]),
            last_played=row["last_played"],
            journal_minutes=int(row["journal_minutes"] or 0),
        )
        for row in rows
    ]


def piece_practice(conn: sqlite3.Connection, piece_id: int, days: int = 3650) -> PiecePracticeDetail:
    """Logged practice for one piece, all time, plus its tempo trend."""
    rows = by_piece(conn, days)
    row = next((item for item in rows if item.piece_id == piece_id), None)
    if row is None:
        piece = conn.execute(
            "SELECT p.id, p.title, c.name AS composer_name, p.opus,"
            " (SELECT COALESCE(SUM(j.practice_minutes), 0) FROM piece_journal j"
            "   WHERE j.piece_id = p.id) AS journal_minutes"
            " FROM pieces p LEFT JOIN composers c ON c.id = p.composer_id"
            " WHERE p.id = ?",
            (piece_id,),
        ).fetchone()
        if piece is None:
            raise NotFound(f"no piece {piece_id}")
        row = PiecePractice(
            piece_id=int(piece["id"]),
            title=piece["title"],
            composer_name=piece["composer_name"],
            opus=piece["opus"],
            minutes=0.0,
            notes=0,
            segments=0,
            last_played=None,
            journal_minutes=int(piece["journal_minutes"] or 0),
        )
    return PiecePracticeDetail(**row.model_dump(), tempo=tempo_series(conn, piece_id))


def neglected(conn: sqlite3.Connection, limit: int = 8) -> list[NeglectedPiece]:
    """Active pieces, least recently played first.

    A piece with no logged segment at all sorts first: "never logged" is the
    strongest form of neglected, and dropping it for having no date would hide
    exactly the pieces the list exists to surface.
    """
    rows = conn.execute(
        """
        SELECT p.id AS piece_id,
               p.title,
               c.name AS composer_name,
               p.opus,
               MAX(s.local_date) AS last_played
        FROM pieces p
        LEFT JOIN composers c ON c.id = p.composer_id
        LEFT JOIN segments g ON g.piece_id = p.id
        LEFT JOIN sittings s ON s.id = g.sitting_id
        -- `active` only. `paused` is a deliberate decision by the player and `completed` is a
        -- piece that is done; reporting either as neglected is the list arguing with them.
        WHERE p.status = 'active'
        GROUP BY p.id
        ORDER BY (last_played IS NOT NULL), last_played ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    today = _today()
    out: list[NeglectedPiece] = []
    for row in rows:
        last = row["last_played"]
        days_since = None
        if last:
            days_since = (today - datetime.fromisoformat(last).date()).days
        out.append(
            NeglectedPiece(
                piece_id=int(row["piece_id"]),
                title=row["title"],
                composer_name=row["composer_name"],
                opus=row["opus"],
                days_since=days_since,
                last_played=last,
            )
        )
    return out


def tempo_series(conn: sqlite3.Connection, piece_id: int) -> TempoSeries:
    """Median tempo per segment over time — the "is it getting faster?" line."""
    piece = conn.execute(
        "SELECT id, title FROM pieces WHERE id = ?", (piece_id,)
    ).fetchone()
    if piece is None:
        raise NotFound(f"no piece {piece_id}")
    rows = conn.execute(
        """
        SELECT s.local_date AS date, m.median_tempo, g.id AS segment_id
        FROM segments g
        JOIN sittings s ON s.id = g.sitting_id
        JOIN segment_metrics m ON m.segment_id = g.id
        WHERE g.piece_id = ? AND m.median_tempo IS NOT NULL
        ORDER BY s.local_date, g.start_ms
        """,
        (piece_id,),
    ).fetchall()
    return TempoSeries(
        piece_id=int(piece["id"]),
        title=piece["title"],
        points=[
            TempoPoint(
                date=row["date"],
                median_tempo=float(row["median_tempo"]),
                segment_id=int(row["segment_id"]),
            )
            for row in rows
        ],
    )


def sources(conn: sqlite3.Connection, days: int) -> list[SourceSplit]:
    since = (_today() - timedelta(days=days - 1)).isoformat()
    rows = conn.execute(
        """
        SELECT s.source,
               SUM(s.ended_ms - s.started_ms) / 60000.0 AS minutes,
               (SELECT COUNT(*) FROM note_events e JOIN sittings s2 ON s2.id = e.sitting_id
                 WHERE s2.source = s.source AND s2.local_date >= ?) AS notes
        FROM sittings s
        WHERE s.local_date >= ?
        GROUP BY s.source
        ORDER BY minutes DESC
        """,
        (since, since),
    ).fetchall()
    return [
        SourceSplit(
            source=row["source"],
            minutes=round(float(row["minutes"] or 0.0), 1),
            notes=int(row["notes"] or 0),
        )
        for row in rows
    ]


def kinds_breakdown(conn: sqlite3.Connection, days: int) -> list[PracticeKindSplit]:
    """Logged minutes per practice kind, untagged included.

    Two rules live in this query and both are asserted:

    * the kind is taken through a CASE, so a row whose basis is ``offered`` resolves to
      NULL and lands in the untagged bucket rather than its own. An unanswered question
      must not be counted as a label, and it must not vanish either — a split that
      dropped it could not be reconciled against the segments it summarises;
    * minutes are segment minutes, not sitting minutes, because the axis is per segment.
      The Log dashboard's ``total_minutes`` stays sitting-based and is a different number.
    """
    since = (_today() - timedelta(days=days - 1)).isoformat()
    rows = conn.execute(
        """
        WITH per_segment AS (
            SELECT CASE
                       WHEN g.practice_kind_basis IN ('manual', 'accepted')
                       THEN g.practice_kind
                       ELSE NULL
                   END AS kind,
                   (g.end_ms - g.start_ms) / 60000.0 AS minutes,
                   (SELECT COUNT(*) FROM note_events e
                     WHERE e.sitting_id = g.sitting_id
                       AND e.onset_ms >= g.start_ms
                       AND e.onset_ms <= g.end_ms) AS notes
            FROM segments g
            JOIN sittings s ON s.id = g.sitting_id
            WHERE s.local_date >= ?1
        )
        SELECT kind, SUM(minutes) AS minutes, SUM(notes) AS notes, COUNT(*) AS segments
        FROM per_segment
        GROUP BY kind
        ORDER BY minutes DESC
        """,
        (since,),
    ).fetchall()
    return [
        PracticeKindSplit(
            kind=row["kind"],
            minutes=round(float(row["minutes"] or 0.0), 1),
            notes=int(row["notes"] or 0),
            segments=int(row["segments"] or 0),
        )
        for row in rows
    ]


@dataclass(frozen=True)
class Streak:
    """A run of days at the piano, with at most one rest day forgiven per rolling week."""

    days: int
    grace_used: int


#: How many calendar days a forgiven rest day stays forgiven for. One rest day per week is the
#: rule a pianist can actually keep; two inside a week is a break.
GRACE_WINDOW_DAYS = 7


#: How far back to look. A streak longer than ten years is not a thing this app needs to prove.
STREAK_LOOKBACK_DAYS = 3_660


def streak(conn: sqlite3.Connection) -> Streak:
    """The run of days ending today or yesterday, forgiving one rest day per rolling week.

    Three rules, each of which exists because the obvious version got it wrong:

    * **Today not yet played does not break it.** The day is not over, and a streak that resets
      every midnight until you play is a nag, not a measurement.
    * **One missed day in seven is forgiven**, and the run continues from the day before it. A
      second miss within the same seven days ends the run, which is why the check is against the
      previous forgiven day rather than a count.
    * **A run never opens on a rest day.** Otherwise coming back after a fortnight would report a
      one-day streak, which is worse than reporting nothing.

    ``days`` is the length of the run in calendar days, so it includes a forgiven rest day; the
    caller reports ``grace_used`` beside it so the number is never read as days played.
    """
    rows = [
        row["local_date"]
        for row in conn.execute("SELECT DISTINCT local_date FROM sittings")
    ]
    dates = {datetime.fromisoformat(value).date() for value in rows}
    today = _today()

    cursor = today if today in dates else today - timedelta(days=1)
    if cursor not in dates:
        return Streak(days=0, grace_used=0)

    days = 0
    grace_used = 0
    last_forgiven: date | None = None
    while (today - cursor).days <= STREAK_LOOKBACK_DAYS:
        if cursor in dates:
            days += 1
        else:
            # A rest day is only forgiven when it is joining two stretches of practice. A
            # gap at the *end* of a run is simply the end of the run — without this check
            # every streak would be one longer than the days it is made of, which is
            # exactly what `test_an_unbroken_week_is_unchanged_by_the_grace_rule` pins.
            ahead = range(1, GRACE_WINDOW_DAYS + 1)
            if not any((cursor - timedelta(days=step)) in dates for step in ahead):
                break
            if last_forgiven is not None and (last_forgiven - cursor).days < GRACE_WINDOW_DAYS:
                break
            last_forgiven = cursor
            grace_used += 1
            days += 1
        cursor -= timedelta(days=1)
    return Streak(days=days, grace_used=grace_used)


def summary(conn: sqlite3.Connection, days: int = 30, recent: int = 10) -> AnalyticsSummary:
    """Everything the Log dashboard draws, in one call.

    ``total_minutes`` and ``total_notes`` are all-time on purpose: the dashboard's
    headline numbers answer "how much have I practised", and a 30-day total would
    shrink on its own with no practice having been lost.
    """
    calendar_days = calendar(conn, days)
    today = _today().isoformat()
    totals = conn.execute(
        "SELECT COALESCE(SUM(ended_ms - started_ms), 0) / 60000.0 AS minutes,"
        " MAX(ended_ms) AS last_ms,"
        " (SELECT COUNT(*) FROM note_events) AS notes FROM sittings"
    ).fetchone()
    run = streak(conn)
    return AnalyticsSummary(
        days=days,
        total_minutes=round(float(totals["minutes"] or 0.0), 1),
        total_notes=int(totals["notes"] or 0),
        today_minutes=next(
            (day.minutes for day in calendar_days if day.date == today), 0.0
        ),
        streak_days=run.days,
        streak_grace_used=run.grace_used,
        calendar=calendar_days,
        by_piece=by_piece(conn, days),
        neglected=neglected(conn),
        sources=sources(conn, days),
        kinds=kinds_breakdown(conn, days),
        recent=list_sittings_conn(conn, recent),
        last_note_ms=(
            int(totals["last_ms"]) if totals["last_ms"] is not None else None
        ),
        capture=capture_status.snapshot(),
    )

