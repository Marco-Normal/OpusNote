"""Preparing a finished sitting in the background.

The runner owns *when* a sitting is prepared, never *what* preparing it means — that stays
`store.ensure_segments`, the same function the read calls when nothing is scheduled. So what
is worth testing here is the scheduling: that a finished sitting is picked up without a
request, that an unfinished one is not, that submitting twice queues once, and that a job
which fails leaves the sitting no worse off than before the feature existed.

Nothing here sleeps or waits on a thread. The suite runs with `SRT_BACKGROUND_JOBS=0`, and
every case drives `tick()`/`drain()` on the test's own thread, so an assertion cannot pass
because a worker happened to win a race.
"""

from __future__ import annotations

import dataclasses

import pytest

from app import db
from app.config import settings
from app.practice import jobs, store
from app.practice.models import EventBatch, WireNote

#: 2023-11-15, comfortably in the past, so a sitting created here is closed by the clock.
BASE_MS = 1_700_011_800_000
#: Ten minutes apart, far outside the five-minute sitting gap, so each drill is its own sitting.
STEP_MS = 10 * 60 * 1000


def make_sitting(index: int, *, notes: int = 8) -> int:
    """One sitting of `notes` notes, in its own sitting, and nothing else."""
    base = BASE_MS + index * STEP_MS
    events = [
        WireNote(
            epoch_ms=base + position * 250,
            pitch=60 + position,
            velocity=70,
            duration_ms=200,
            channel=0,
        )
        for position in range(notes)
    ]
    result = store.ingest(EventBatch(tz_offset_minutes=0, events=events))
    assert result.sitting_id is not None
    return result.sitting_id


def segment_count(sitting_id: int) -> int:
    conn = db.connect(settings.db_path)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM segments WHERE sitting_id = ?", (sitting_id,)
            ).fetchone()[0]
        )
    finally:
        conn.close()


@pytest.fixture
def runner():
    """A runner over this test's database, never started as a thread."""
    made = jobs.JobRunner(db_path=settings.db_path)
    yield made
    made.stop()


def test_submitting_the_same_sitting_twice_queues_one_job(fresh_db, runner) -> None:
    sitting_id = make_sitting(0)

    assert runner.submit(sitting_id) is True
    assert runner.submit(sitting_id) is False, "a second request is not a second job"
    assert runner.scheduled(sitting_id) is True
    assert runner.state().pending == 1

    runner.drain()
    assert runner.scheduled(sitting_id) is False, "and it stops being scheduled when it is done"


def test_a_finished_sitting_is_prepared_with_no_request_that_names_it(fresh_db, runner) -> None:
    """The point of the whole phase: the work happens without anybody opening the sitting."""
    sitting_id = make_sitting(0)
    assert segment_count(sitting_id) == 0

    queued = runner.tick()
    assert queued == 1, "a finished, unsegmented sitting is exactly what a sweep looks for"

    assert runner.state().pending == 1
    runner.drain()

    assert segment_count(sitting_id) > 0, "a tick plus a drain must leave it segmented"
    assert runner.state().finished == 1
    assert runner.state().last_finished_ms is not None


def test_a_tick_leaves_an_open_sitting_alone(fresh_db, runner) -> None:
    """A sitting still being played would get provisional boundaries, and they are permanent."""
    sitting_id = make_sitting(0)
    # The same sitting, seen from ten seconds after its last note: still open.
    now_ms = BASE_MS + 10_000

    assert runner.tick(now_ms=now_ms) == 0
    assert segment_count(sitting_id) == 0

    # And once the gap has run out, the very next tick finds it.
    later_ms = BASE_MS + (settings.sitting_gap_s + 5) * 1000
    assert runner.tick(now_ms=later_ms) == 1
    runner.drain()
    assert segment_count(sitting_id) > 0


def test_a_tick_leaves_a_sitting_that_already_has_segments_alone(fresh_db, runner) -> None:
    """Stored boundaries are never recomputed implicitly, so there is nothing to do here."""
    sitting_id = make_sitting(0)
    store.ensure_segments(sitting_id)
    before = segment_count(sitting_id)

    assert runner.tick() == 0
    runner.drain()
    assert segment_count(sitting_id) == before


def test_an_explicitly_closed_sitting_is_prepared_before_its_gap_runs_out(
    fresh_db, runner
) -> None:
    """A sitting the piano ended is finished *now*; waiting five minutes for it is the old bug."""
    sitting_id = make_sitting(0)
    store.close_open_sitting(now_ms=BASE_MS + 10_000)

    assert runner.tick(now_ms=BASE_MS + 10_000) == 1
    runner.drain()
    assert segment_count(sitting_id) > 0


def test_a_failing_job_is_reported_and_leaves_the_sitting_to_the_read(
    fresh_db, runner, monkeypatch
) -> None:
    """The fallback is the reason a broken worker is survivable, so it is asserted, not assumed."""
    sitting_id = make_sitting(0)

    def explode(*_args, **_kwargs):
        raise RuntimeError("no segments for you")

    monkeypatch.setattr(store, "ensure_segments", explode)

    runner.tick()
    runner.drain()

    state = runner.state()
    assert state.last_error is not None and "no segments for you" in state.last_error
    assert state.finished == 0
    assert runner.scheduled(sitting_id) is False, (
        "a sitting whose job failed must not stay 'preparing' for ever — the read has to "
        "be free to do the work itself"
    )


def test_one_failed_job_does_not_stop_the_next_one(fresh_db, runner, monkeypatch) -> None:
    first = make_sitting(0)
    second = make_sitting(1)
    real = store.ensure_segments

    def only_the_first_fails(sitting_id, **kwargs):
        if sitting_id == first:
            raise RuntimeError("this one is cursed")
        return real(sitting_id, **kwargs)

    monkeypatch.setattr(store, "ensure_segments", only_the_first_fails)

    runner.submit(first)
    runner.submit(second)
    runner.drain()

    assert segment_count(second) > 0, "the loop must keep going after a failure"
    assert runner.state().finished == 1
    assert runner.state().last_error is not None


def test_a_tick_is_bounded(fresh_db, runner) -> None:
    """One tick cannot queue the whole backlog, so a long backlog cannot monopolise writes."""
    for index in range(5):
        make_sitting(index)

    assert runner.tick(limit=2) == 2
    assert runner.state().pending == 2
    runner.drain()
    # The next tick takes the next slice, which is what makes a backlog drain in steps.
    assert runner.tick(limit=2) == 2


def test_awaiting_segments_returns_the_newest_first(fresh_db) -> None:
    oldest = make_sitting(0)
    middle = make_sitting(1)
    newest = make_sitting(2)

    assert store.awaiting_segments(limit=3) == [newest, middle, oldest]
    assert store.awaiting_segments(limit=2) == [newest, middle]


def test_awaiting_segments_ignores_an_open_sitting(fresh_db) -> None:
    sitting_id = make_sitting(0)
    now_ms = BASE_MS + 10_000  # ten seconds after the last note: still playing

    assert store.awaiting_segments(now_ms=now_ms) == []
    assert store.awaiting_segments(
        now_ms=BASE_MS + (settings.sitting_gap_s + 5) * 1000
    ) == [sitting_id]


def test_the_runner_does_not_start_when_the_setting_says_so(fresh_db, monkeypatch) -> None:
    """`SRT_BACKGROUND_JOBS=0` is the old behaviour, and the suite's own setting."""
    # `Settings` is frozen, so the module's settings object is what gets replaced rather than
    # a field on it — which is also the only way to be sure `jobs` re-reads the value.
    monkeypatch.setattr(jobs, "settings", dataclasses.replace(settings, background_jobs=False))
    make_sitting(0)

    jobs.reset()
    jobs.start()
    try:
        assert jobs.runner().state().running is False
        assert jobs.scheduled(1) is False
    finally:
        jobs.reset()
