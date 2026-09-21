"""Where a stretch of playing turns over."""

from __future__ import annotations

from app.practice.segment import Config, cut
from app.practice.sessionize import Note


def play(*onsets_ms: int, duration_ms: int = 100) -> list[Note]:
    return [Note(onset, 60 + index, 70, duration_ms, 0) for index, onset in enumerate(onsets_ms)]


def steady(count: int, every_ms: int, *, start_ms: int = 0, duration_ms: int = 100) -> list[Note]:
    return play(*[start_ms + index * every_ms for index in range(count)], duration_ms=duration_ms)


#: The gap rule observed on its own. At the default minimum size, a lone note after a pause
#: is absorbed into its neighbour and the pause becomes invisible — the merge rule would be
#: doing the counting, not the gap rule, and the assertion would pass for the wrong reason.
GAPS_ONLY = Config(min_notes=1)

#: The silence used by the adaptive test, measured from the previous note's release.
PAUSE_MS = 2_400


def after_a_pause(every_ms: int) -> list[Note]:
    """A steady passage, a silence of exactly ``PAUSE_MS``, then one more note."""
    run = steady(40, every_ms)
    return run + [Note(run[-1].end_ms + PAUSE_MS, 60, 70, 100, 0)]


def test_a_pause_longer_than_the_floor_cuts() -> None:
    notes = steady(20, 200) + [Note(20 * 200 + 5_000, 60, 70, 100, 0)]
    assert len(cut(notes, config=GAPS_ONLY)) == 2


def test_a_pause_shorter_than_the_floor_does_not() -> None:
    notes = steady(20, 200) + [Note(20 * 200 + 900, 60, 70, 100, 0)]
    assert len(cut(notes, config=GAPS_ONLY)) == 1


def test_a_slow_passage_tolerates_a_pause_a_fast_one_would_not() -> None:
    """The whole point of the adaptive term: one silence is a breath at 60 bpm and a stop at 240.

    The pause is identical in both cases and only the passage's own pulse differs, so a
    pass here cannot come from the floor alone: the slow passage is kept together by the
    multiplier (2.5 x 1 s = 2.5 s), and the fast one is cut by the 2 s floor.
    """
    slow = after_a_pause(1_000)
    fast = after_a_pause(150)
    assert len(cut(slow, config=GAPS_ONLY)) == 1, "2.4 s inside a 1 s pulse is not a break"
    assert len(cut(fast, config=GAPS_ONLY)) == 2, "2.4 s inside a 150 ms pulse is"


def test_an_undersized_group_is_absorbed_into_its_neighbour() -> None:
    """A one-note stray is a segment today, and should not be."""
    notes = steady(40, 200) + [Note(40 * 200 + 5_000, 60, 70, 100, 0)]
    notes += [Note(40 * 200 + 5_000 + 10_000, 60, 70, 100, 0)]
    windows = cut(notes, config=Config())
    assert len(windows) == 1, "the one-note group between the two pauses is absorbed"


def test_a_long_group_is_split_at_its_largest_internal_gap() -> None:
    """Three legato runs separated by pauses too short to be boundaries on their own.

    The pauses are 500 ms against a 100 ms pulse, so the adaptive rule keeps all three in
    one group; only the maximum size forces a split, and it has to land on the pauses.
    """
    notes = steady(30, 100)
    notes += [Note(3_500 + index * 100, 60, 70, 100, 0) for index in range(30)]
    notes += [Note(7_000 + index * 100, 60, 70, 100, 0) for index in range(30)]
    windows = cut(notes, config=Config(max_ms=4_000))
    assert len(windows) == 3
    assert [window.end_ms - window.start_ms for window in windows] == [3_000, 3_000, 3_000], (
        "each run comes back whole: the split lands on the pauses, it does not truncate a phrase"
    )
    assert all(window.end_ms - window.start_ms <= 4_000 for window in windows)


def test_a_gap_free_run_is_never_truncated_to_fit() -> None:
    """Rule 4 beats rule 3: with no pause to split on, splitting would cut a phrase in half."""
    notes = steady(120, 100)
    windows = cut(notes, config=Config(max_ms=4_000))
    assert len(windows) == 1
    assert windows[0].end_ms - windows[0].start_ms == 12_000


def test_nothing_at_all_cuts_to_nothing() -> None:
    assert cut([], config=Config()) == []


def test_one_note_is_one_window() -> None:
    single = play(1_000)
    assert len(cut(single, config=Config())) == 1
