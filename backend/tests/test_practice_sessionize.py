"""Sessionization tests, ported from the standalone practice-logger.

The invariant that matters is ``batch and incremental agree``: replaying history
after an algorithm change must produce the same groups live capture did.
"""

from __future__ import annotations

from app.practice.sessionize import Note, SessionBuilder, continues, sessionize

GAP_MS = 300_000  # SRT_SITTING_GAP_S = 300


def note(epoch_ms: int, duration_ms: int = 300, pitch: int = 60) -> Note:
    return Note(epoch_ms=epoch_ms, pitch=pitch, velocity=70, duration_ms=duration_ms)


def test_silence_beyond_the_gap_starts_a_new_group() -> None:
    # The gap is measured from the previous note's *release*, so the second
    # phrase must start more than GAP_MS after 300 ms, not after the onset.
    onset = 300 + GAP_MS + 1
    windows = sessionize([note(0), note(onset)], GAP_MS)
    assert len(windows) == 2
    assert windows[0].start_ms == 0
    assert windows[1].start_ms == onset


def test_silence_within_the_gap_stays_one_group() -> None:
    windows = sessionize([note(0), note(1_000), note(2_000)], GAP_MS)
    assert len(windows) == 1
    assert windows[0].end_ms == 2_300


def test_a_held_note_is_not_silence() -> None:
    # The second onset is 200 s after the first, but the first is still held, so
    # the gap is measured from its release: 200_000 - 300_000 < 0.
    windows = sessionize([note(0, duration_ms=300_000), note(200_000)], GAP_MS)
    assert len(windows) == 1


def test_release_counts_as_the_end_of_the_group() -> None:
    windows = sessionize([note(0, duration_ms=1_000)], GAP_MS)
    assert windows[0].end_ms == 1_000


def test_unsorted_input_is_sorted_first() -> None:
    windows = sessionize([note(2_000), note(0), note(1_000)], GAP_MS)
    assert len(windows) == 1
    assert windows[0].start_ms == 0


def test_empty_input_yields_no_groups() -> None:
    assert sessionize([], GAP_MS) == []


def test_batch_and_incremental_paths_agree() -> None:
    notes = [note(0), note(1_000), note(GAP_MS + 2_000), note(GAP_MS + 3_000)]
    builder = SessionBuilder(GAP_MS)
    indices = [builder.add(item) for item in sorted(notes, key=lambda n: n.epoch_ms)]
    assert indices == [0, 0, 1, 1]
    assert builder.windows() == sessionize(notes, GAP_MS)


def test_continues_rejects_an_empty_history() -> None:
    assert continues(None, 0, GAP_MS) is False


def test_segmentation_is_sessionization_at_a_smaller_gap() -> None:
    # Two phrases 30 s apart: one sitting at the sitting gap, two segments at the
    # segment gap. Same notes, same function.
    notes = [note(0), note(500), note(30_000), note(30_500)]
    assert len(sessionize(notes, 300_000)) == 1
    assert len(sessionize(notes, 20_000)) == 2
