"""Preparing a finished sitting before anyone opens it.

Opening a sitting for the first time used to *be* the work: the read segmented it, measured
it, ran the matcher over it and offered practice kinds, all inside the request. On the
owner's library that is ~700 ms of a laptop's time on a 23,482-note sitting, paid while
somebody is looking at the screen, for work that depends on nothing but the fact that the
playing stopped.

So it happens here instead. The runner owns *when* and nothing else: a job is a sitting id,
and the work is exactly ``store.ensure_segments``, the same function the read still calls
when no job is scheduled. That is the whole safety argument — the background pass is an
optimisation over a path that still works, not a second owner of what segmentation means.

Why a thread in this process rather than FastAPI's ``BackgroundTasks``: a background task
only runs after a request that happened, so it cannot cover a sitting closed by the silence
gap, a backlog left by a restart, or a process that died mid-job — and it would hold a
threadpool request thread for the duration. This app is one process, one user and one piano
(the systemd unit starts a single uvicorn), so one daemon thread with a queue is the whole
machinery that is needed.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from . import store

log = logging.getLogger(__name__)

#: How many finished sittings one sweep may queue. Bounds a tick, not the backlog: the next
#: tick picks up the rest.
SWEEP_LIMIT = 4

#: How long `stop()` waits for a job in flight. The work is a single transaction, so it either
#: finishes or rolls back; this is a courtesy, not a correctness boundary.
STOP_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class RunnerState:
    """What the runner is doing, for a status route or a test. Never a source of truth."""

    running: bool
    pending: int
    working_on: int | None
    finished: int
    last_error: str | None
    last_finished_ms: int | None


class JobRunner:
    """One queue, one thread, and one meaning of "prepare this sitting"."""

    def __init__(self, *, db_path: Path | None = None, sweep_s: float | None = None) -> None:
        self._db_path = db_path
        self._sweep_s = float(sweep_s if sweep_s is not None else settings.job_sweep_s)
        self._queue: queue.Queue[int | None] = queue.Queue()
        self._lock = threading.Lock()
        #: Queued *or* running. Membership is what a read asks about, so it must not be
        #: possible to see "not scheduled" while a job for that sitting is on its way.
        self._known: set[int] = set()
        self._working: int | None = None
        self._finished = 0
        self._last_error: str | None = None
        self._last_finished_ms: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- what a caller asks --------------------------------------------------------------

    def submit(self, sitting_id: int) -> bool:
        """Queue one sitting. False when it is already queued or running."""
        with self._lock:
            if sitting_id in self._known:
                return False
            self._known.add(sitting_id)
        self._queue.put(int(sitting_id))
        return True

    def scheduled(self, sitting_id: int) -> bool:
        """Whether this sitting's preparation is queued or running *right now*.

        The read asks this to decide between answering "preparing" and doing the work
        itself. An id leaves this set when its job finishes **or fails**, so a worker that
        gave up can never leave a sitting permanently unanswered.
        """
        with self._lock:
            return sitting_id in self._known

    def state(self) -> RunnerState:
        with self._lock:
            return RunnerState(
                running=self._thread is not None,
                pending=self._queue.qsize(),
                working_on=self._working,
                finished=self._finished,
                last_error=self._last_error,
                last_finished_ms=self._last_finished_ms,
            )

    # --- the work ------------------------------------------------------------------------

    def work(self, sitting_id: int) -> None:
        """Prepare one sitting. The only place a job's meaning is defined."""
        with self._lock:
            self._working = sitting_id
        try:
            store.ensure_segments(sitting_id, db_path=self._db_path)
        except Exception as exc:  # noqa: BLE001 - a job must never kill the loop
            # Logged and remembered rather than raised: the read path still materialises
            # this sitting on demand, so a failure here costs the optimisation and nothing
            # else. Silence would be the only real defect.
            log.warning("preparing sitting %s failed: %s", sitting_id, exc)
            with self._lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
        else:
            with self._lock:
                self._finished += 1
                self._last_finished_ms = int(time.time() * 1000)
        finally:
            with self._lock:
                self._working = None
                self._known.discard(sitting_id)

    def tick(self, *, now_ms: int | None = None, limit: int = SWEEP_LIMIT) -> int:
        """Queue the finished sittings nobody has prepared yet. Returns how many were new."""
        rows = store.awaiting_segments(now_ms=now_ms, limit=limit, db_path=self._db_path)
        return sum(1 for sitting_id in rows if self.submit(sitting_id))

    def drain(self, *, limit: int | None = None) -> int:
        """Run queued jobs on this thread, now.

        The test seam, and what shutdown uses. Every assertion about the runner can be made
        without a thread and without a sleep, which is the only way to test one honestly.
        """
        done = 0
        while limit is None or done < limit:
            try:
                sitting_id = self._queue.get_nowait()
            except queue.Empty:
                break
            if sitting_id is None:
                continue
            self.work(sitting_id)
            done += 1
        return done

    # --- the thread ----------------------------------------------------------------------

    def start(self) -> None:
        """Start the thread and take the first look. Idempotent."""
        if self._thread is not None:
            return
        self._stop.clear()
        # The backlog first, before the thread exists: a database restored from a backup, or
        # one whose sittings were logged by a build without this feature, is prepared without
        # anybody having to open it.
        self.tick()
        self._thread = threading.Thread(target=self._loop, name="practice-jobs", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                sitting_id = self._queue.get(timeout=self._sweep_s)
            except queue.Empty:
                # Nothing to do, so it is the moment to look for a sitting that finished
                # without anything telling us: the silence gap ran out while the piano was
                # still connected, or the last process died mid-job.
                self.tick()
                continue
            if sitting_id is None:
                break
            self.work(sitting_id)

    def stop(self, *, timeout_s: float = STOP_TIMEOUT_S) -> None:
        """Ask the thread to finish and wait for it. Idempotent."""
        self._stop.set()
        self._queue.put(None)
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout_s)


#: The process's runner. Created on first use, because importing this module must not start a
#: thread — the suite imports the app, and a test that does not want a worker must not get one.
_runner: JobRunner | None = None


def runner() -> JobRunner:
    global _runner
    if _runner is None:
        _runner = JobRunner()
    return _runner


def scheduled(sitting_id: int) -> bool:
    """Whether the background is already preparing this sitting.

    False whenever background jobs are off, which is what makes "off" mean the old
    behaviour rather than "broken": the caller falls back to doing the work itself.
    """
    if not settings.background_jobs:
        return False
    if _runner is None:
        return False
    return _runner.scheduled(sitting_id)


def start() -> None:
    """Start preparing sittings in the background, unless the setting says not to."""
    if settings.background_jobs:
        runner().start()


def stop() -> None:
    if _runner is not None:
        _runner.stop()


def reset() -> None:
    """Forget the process's runner. Tests only, and it stops the thread if there is one."""
    global _runner
    if _runner is not None:
        _runner.stop()
    _runner = None
