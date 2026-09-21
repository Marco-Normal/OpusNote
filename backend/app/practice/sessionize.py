"""Group note onsets into sittings, or into segments, by silence.

Ported unchanged from ``practice-logger/app/pipeline/sessionize.py``. Pure: no
database, no clock, no configuration import. ``sessionize()`` is defined by
feeding :class:`SessionBuilder`, so the live incremental path and the rebuild
path cannot drift apart — a test asserts they agree on the same stream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Note:
    """One played note."""

    epoch_ms: int
    pitch: int
    velocity: int
    duration_ms: int
    channel: int | None = None

    @property
    def end_ms(self) -> int:
        return self.epoch_ms + self.duration_ms


@dataclass(frozen=True)
class Window:
    start_ms: int
    end_ms: int


def continues(previous_end_ms: int | None, onset_ms: int, gap_ms: int) -> bool:
    """True when a note is close enough to keep the open group alive.

    Measured from the previous note's *release*, so a long held note is not
    mistaken for silence.
    """
    if previous_end_ms is None:
        return False
    return onset_ms - previous_end_ms <= gap_ms


class SessionBuilder:
    """Accumulates notes, in arrival order, into windows."""

    def __init__(self, gap_ms: int) -> None:
        self.gap_ms = gap_ms
        self._windows: list[Window] = []

    def add(self, note: Note) -> int:
        """Add one note; return the index of the window it belongs to."""
        if not self._windows or not continues(
            self._windows[-1].end_ms, note.epoch_ms, self.gap_ms
        ):
            self._windows.append(Window(note.epoch_ms, note.end_ms))
            return len(self._windows) - 1
        last = self._windows[-1]
        self._windows[-1] = Window(last.start_ms, max(last.end_ms, note.end_ms))
        return len(self._windows) - 1

    def windows(self) -> list[Window]:
        return list(self._windows)


def sessionize(notes: Iterable[Note], gap_ms: int) -> list[Window]:
    """Batch rule, defined as the incremental rule applied to sorted notes.

    One implementation, so the batch and incremental readings of the same stream cannot
    drift apart. It no longer cuts a stored sitting's segments: Phase 22a replaced that
    with the adaptive rule in ``segment.cut``, and sittings themselves are opened by the
    absolute-time query in ``store._find_sitting``. This is kept as the ported reference
    and is still what ``SessionBuilder`` is defined against.
    """
    builder = SessionBuilder(gap_ms)
    for note in sorted(notes, key=lambda item: (item.epoch_ms, item.pitch)):
        builder.add(note)
    return builder.windows()
