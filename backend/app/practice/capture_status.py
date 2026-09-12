"""Ephemeral capture state, reported by whichever client is logging.

Deliberately in memory rather than in the database: it describes *now* — is a client
capturing, is it behind, when did it last check in — and a stale row would be worse
than no row. The last *note* is not here either; that comes from the note events,
which are shared truth rather than something a client asserts.
"""

from __future__ import annotations

import time

from pydantic import BaseModel

#: A report older than this is treated as gone, not as "still capturing".
STALE_AFTER_MS = 60_000


class CaptureReport(BaseModel):
    origin: str
    enabled: bool
    pending: int
    at_ms: int


_report: CaptureReport | None = None


def record(
    *, origin: str, enabled: bool, pending: int, now_ms: int | None = None
) -> CaptureReport:
    global _report
    _report = CaptureReport(
        origin=origin[:120],
        enabled=bool(enabled),
        pending=max(0, int(pending)),
        at_ms=int(now_ms if now_ms is not None else time.time() * 1000),
    )
    return _report


def snapshot(now_ms: int | None = None) -> CaptureReport | None:
    if _report is None:
        return None
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    if now - _report.at_ms > STALE_AFTER_MS:
        return None
    return _report


def reset() -> None:
    """Forget the last report. Used by tests between cases."""
    global _report
    _report = None
