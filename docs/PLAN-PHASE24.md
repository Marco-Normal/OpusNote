# Plan — Phase 24: the sitting is ready before you open it

**Parent spec:** [`ECOSYSTEM.md`](./ECOSYSTEM.md) § *Phase 24*, which adopts this document as the
how. The *why* is the measurements below: the owner asked for the segmentation to happen when a
sitting finishes rather than when it is first opened, and measuring that request found that about a
second of the wait was not scheduling at all — it was the matcher's cache being thrown away by
writes that cannot change it.

**Status: landed.**

**Goal.** A finished sitting is segmented, measured and classified *before* anyone opens it; a read
never waits on work that is already scheduled; and that work stops paying for a rebuild it does not
need. The click on a fresh sitting becomes the warm read it already is on every other sitting.

**Non-goals.** No change to the segmenter, the matcher, the scoring, or the shape of anything
stored. No second process, no message queue, no broker: one daemon thread inside the single uvicorn
process. The other paths that were measured and left alone: the `/autotag` button (219 ms warm), the
accuracy panel (112 ms warm), the dashboard (53 ms) and opening playback (234 ms) do not earn a job
state, and this phase does not give them one.

---

## 1. The measurements this plan rests on

Rebuilt from the local backup [docs/TEST-DATA.md](TEST-DATA.md) owns — 238,665 note events, 539,726
pedal events, 17 sittings, 49 labelled segments. Shapes, not promises; re-measure before quoting
one.

Opening a sitting that has never been segmented (the 23,482-note one):

| Stage | Cost |
| --- | ---: |
| read the sitting's notes, `segment.cut`, insert, tag from workouts | ~260 ms |
| `_refresh_metrics` (the sitting's notes and its pedal stream) | 430 ms |
| `autotag_sitting` (the matcher) | ~1,100 ms |
| `_segment_rows` | 3 ms |
| **first click, total** | **1,755 ms** |
| the same sitting, already segmented | 90 ms |

Of the matcher's 1,100 ms, **~985 ms was rebuilding the matcher's reference set** — and that rebuild
is unnecessary. On identical fixtures, in one process, with the cache already warm:

| Invalidation rule | first click | reference-set rebuilds during it |
| --- | ---: | ---: |
| today | 1,755 ms | 1 |
| precise (task 1) | **770 ms** | **0** |

## 2. What is actually wrong

**2.1 The work happens on the read.** `store.sitting_detail` calls `store.ensure_segments`, which
does the whole pipeline — cut, insert, metrics, matcher, kind offers — inside the request. A read
that writes is deliberate and documented (`ensure_segments`' docstring), but it means the first
click on a finished sitting pays for everything the sitting needs, at the moment somebody is looking
at the screen.

**2.2 The cache is invalidated by writes that cannot change it.** Three triggers on `segments` bump
`reference_state.version`, and `cached_references` treats any move of that counter as "derive
everything again" — a pass over every labelled segment's notes, ~985 ms on the owner's library.

Two of the writes that bump it cannot change the answer:

* `ensure_segments` inserts its new segments **unlabelled**. `_labelled_rows` selects
  `piece_id IS NOT NULL AND (identified_by IS NULL OR identified_by <> 'similarity')`, so an
  unlabelled row entering the table changes nothing the cache is made of.
* `_tag_from_workouts` rewrites `identified_by` (`COALESCE(identified_by, 'workout')`) on every
  segment it overlaps — including segments with no piece on them at all — and `identified_by` is in
  the UPDATE trigger's column list.

So segmenting a sitting throws away the material it is about to read. This is `PERFORMANCE.md` R4
("cache derived material; let the database own the invalidation") with the ownership drawn one notch
too wide: the database owns it, but it is counting writes that are not invalidation.

## 3. Architecture

### 3.1 The runner (`backend/app/practice/jobs.py`, new)

One daemon thread over a `queue.Queue`. A job is a sitting id and nothing else; the work is
`store.ensure_segments(sitting_id)` in its own transaction, so segmentation, metrics,
classification and the kind offers keep the single owner they have today. The runner owns *when*,
never *what*.

```python
class JobRunner:
    def submit(self, sitting_id: int) -> bool: ...   # False when already queued/running
    def scheduled(self, sitting_id: int) -> bool: ... # is this one queued or running now?
    def tick(self, *, now_ms: int | None = None) -> int: ...  # synchronous, for tests
    def start(self) -> None: ...                     # the thread + the sweep
    def stop(self) -> None: ...
    def state(self) -> RunnerState: ...              # pending / running / last_finished / last_error
```

Queue membership is a set behind a lock, so `submit` is idempotent and `scheduled` is answerable
without touching the database. An id leaves the set when its job finishes **or fails** — a failed
job falls back to the lazy read, so nothing can be stuck behind a worker that gave up.

A job failure is caught, logged, and recorded in `state()`; it never kills the loop. The runner is
also the only thing that needed to be new: FastAPI's `BackgroundTasks` was the reuse candidate and
is insufficient, because it only runs after a request that happened — it cannot cover the
silence-gap close, a boot backlog, or a restart mid-job — and it would hold a threadpool thread for
the duration.

### 3.2 What it selects (`store.awaiting_segments`, new)

Finished sittings with no segments, newest first, limited:

```sql
SELECT s.id FROM sittings s
WHERE (s.closed_ms IS NOT NULL OR s.ended_ms + :gap_ms < :now_ms)
  AND NOT EXISTS (SELECT 1 FROM segments g WHERE g.sitting_id = s.id)
ORDER BY s.started_ms DESC LIMIT :limit
```

The `NOT EXISTS` is an index probe (`segments(sitting_id, start_ms)`); the scan is O(sittings), which
is one row per practice session — 17 today, ~365 a year. This is a *tick*, not a click, so it is the
one place an O(sittings) read is acceptable, and it says so in its docstring (`PERFORMANCE.md` R1).

### 3.3 When it runs

| Trigger | Covers |
| --- | --- |
| `POST /api/practice/sittings/close` submits that sitting | the piano-disconnect path the client already calls, which is the common case |
| a sweep every `JOB_SWEEP_S` (20 s) | the silence gap elapsing with the piano still connected, a backlog after a restart, and a sitting stranded by a crash mid-job |
| `lifespan` start | the first sweep happens immediately, so a database that has never had segments — or one restored from a backup — is prepared without anyone opening it |

`ensure_segments` already refuses to segment an open sitting whose gap has not run out, so a job that
fires too early is a no-op returning `[]`. That is not a stall: the sweep re-selects it while it
stays finished-and-unsegmented.

### 3.4 The read never waits for scheduled work

`SittingDetail` gains `preparing: bool` (default `false`), and `store.sitting_detail` gains
`materialise: bool = True`. `practice/api.py` passes `materialise=False` when
`jobs.runner().scheduled(sitting_id)` is true, so the response is the stored rows plus
`preparing: true`, in about a millisecond.

**The fallback is the point.** When no job is scheduled — the runner is off, the process just
started, the sitting is older than the last sweep, the job failed — the read materialises
synchronously exactly as today. The background is an optimisation over a path that still works, not
a new source of truth, and nothing can end up permanently unsegmented because a worker died.

### 3.5 The invalidation rule (task 1)

A segment is a **reference** when `piece_id IS NOT NULL AND COALESCE(identified_by,'') <> 'similarity'`.
The three triggers bump the version only when a reference is inserted, deleted, or when a reference's
identity or window (`piece_id`, `start_ms`, `end_ms`) changes — plus when a row enters or leaves the
set, which is what `piece_id` and `identified_by` moving means:

```sql
CREATE TRIGGER trg_segments_reference_insert AFTER INSERT ON segments
WHEN NEW.piece_id IS NOT NULL AND COALESCE(NEW.identified_by,'') <> 'similarity'
BEGIN UPDATE reference_state SET version = version + 1 WHERE id = 1; END;

CREATE TRIGGER trg_segments_reference_delete AFTER DELETE ON segments
WHEN OLD.piece_id IS NOT NULL AND COALESCE(OLD.identified_by,'') <> 'similarity'
BEGIN UPDATE reference_state SET version = version + 1 WHERE id = 1; END;

CREATE TRIGGER trg_segments_reference_update
AFTER UPDATE OF piece_id, identified_by, start_ms, end_ms ON segments
WHEN (OLD.piece_id IS NOT NULL AND COALESCE(OLD.identified_by,'') <> 'similarity')
  OR (NEW.piece_id IS NOT NULL AND COALESCE(NEW.identified_by,'') <> 'similarity')
BEGIN UPDATE reference_state SET version = version + 1 WHERE id = 1; END;
```

The direction of the error matters and is chosen deliberately: these guards can only *under*-bump on
a row that is not a reference, where the derived material is provably unchanged, and they bump
whenever a reference enters, leaves, or moves. Over-bumping is safe (a needless rebuild);
under-bumping is a stale matcher, which is why task 1's verification walks every write path that can
change the reference set and asserts which way the counter moves.

`schema.py` drops and recreates the three triggers (`DROP TRIGGER IF EXISTS` before each `CREATE`),
because `CREATE TRIGGER IF NOT EXISTS` would leave an existing database on the old rule forever.
`SCHEMA_VERSION` does **not** move: the stored shape is unchanged, an older build reading this
database sees the same tables and columns, and its own (wider) triggers are still correct, only
slower.

## 4. What stays compatible

* **No stored shape changes.** No table, no column, no migration, no `BACKUP_VERSION`, no
  `SCHEMA_VERSION`.
* **The lazy read stays.** `sitting_detail(materialise=True)` is today's behaviour and remains the
  default for every caller that is not the HTTP detail route.
* **`preparing` is additive with a default.** An older client ignores it; a newer client against an
  older server reads `undefined` and treats it as `false`, which is why the type is optional and the
  client reads it with `?? false` — the same rule `passages` already follows.
* **`repertoire/api.py`'s take catch-up is untouched.** It calls `ensure_segments` directly and
  keeps working; with the runner in place it usually finds the work already done.
* **Every existing route keeps its shape.** No route is added or removed.

## 5. TDD route

Host TDD mode is `off`, so this plan prescribes no RED/GREEN ceremony as an authority. The
repository's own standing rule outranks it and is what every task below follows:
[`TEST-STRATEGY.md`](TEST-STRATEGY.md) §8 — **no assertion is trusted until it has been seen to
fail**, which means a break script under `backend/tools/falsifications/` for every assertion this
phase adds. Task 1's assertion is written and run before the fix, because against today's triggers it
genuinely fails: that is the bug, stated as a test.

Count work, never seconds (`PERFORMANCE.md` R6): the new assertions count `references_from` calls,
`ensure_segments` calls and selected rows, not milliseconds.

---

## 6. Tasks

### Task 24.1 — precise invalidation (the ~1 s that is not scheduling)

**Files.** `backend/app/practice/schema.py`; `backend/tests/test_autotag.py` (which owns the
invalidation tests); `backend/tools/falsifications/over_invalidate_the_reference_cache.sh` (new).

**Change.** The three triggers above, and the `DROP TRIGGER IF EXISTS` that lets an existing database
adopt them.

**Verify.**
1. `store.references_from` is counted while `ensure_segments` runs on a fresh, unlabelled sitting:
   **0 calls**. Fails today.
2. Every real reference change still moves `reference_state.version`: label a segment, unlabel it,
   split a labelled segment, merge two labelled ones, delete a labelled one, accept an inference,
   and a segment becoming a reference by `identified_by` changing. Each moves it.
3. `_tag_from_workouts` rewriting `identified_by` on segments with no piece does **not** move it.
4. The existing invalidation tests in `tests/test_autotag.py` pass unchanged — they are the guard
   against under-bumping, and the reason the narrow rule is safe to ship.
5. Measured on the real fixture: first click **1,755 → 770 ms**, rebuilds **1 → 0**.

**Falsification.** `over_invalidate_the_reference_cache.sh` removes the `WHEN` guard from the insert
trigger (restoring today's rule); assertion 1 must fail and name itself.

**Repair track.** This is the bug fix; there is no old path retained.

### Task 24.2 — the runner, and what it selects

**Files.** `backend/app/practice/jobs.py` (new); `backend/app/practice/store.py`
(`awaiting_segments`); `backend/app/config.py` (`_env_bool`, `background_jobs`, `job_sweep_s`);
`backend/app/main.py` (start/stop in `lifespan`); `backend/tests/conftest.py` (the suite turns the
runner off and drives `tick()` by hand); `backend/tests/test_jobs.py` (new);
`backend/tools/falsifications/the_runner_segments_an_open_sitting.sh` (new).

**Change.** The `JobRunner` of §3.1, the selection query of §3.2, and one setting pair:
`SRT_BACKGROUND_JOBS` (default on) and `SRT_JOB_SWEEP_S` (default 20). No new dependency; `queue` and
`threading` are stdlib.

**Verify.**
1. `submit` twice for one sitting queues one job; `scheduled` is true until the job finishes.
2. `tick()` on a finished, unsegmented sitting segments it: segments exist and `scheduled` is false
   afterwards. Counting, not timing: the sitting is segmented by one `tick()` with **no HTTP request
   in between**.
3. `tick()` leaves an open sitting alone, and leaves a sitting that already has segments alone.
4. A job that raises does not kill the loop: the next `tick()` still runs, the failure is in
   `state().last_error`, and `scheduled` for that sitting is false (so the read falls back).
5. `awaiting_segments` returns finished-and-unsegmented only, newest first, honouring `limit`.
6. With `SRT_BACKGROUND_JOBS=0` the runner does not start and `scheduled` is always false.
7. The suite's existing behaviour is unchanged: `./check.sh --fast` green with the runner off.

**Falsification.** `the_runner_segments_an_open_sitting.sh` drops the "finished" half of
`awaiting_segments`' predicate; assertion 3 must fail.

### Task 24.3 — the triggers

**Files.** `backend/app/practice/jobs.py` (the sweep); `backend/app/practice/api.py` (submit on
close); `backend/tests/test_jobs.py`, `backend/tests/test_practice_api.py`.

**Change.** `POST /sittings/close` submits the sitting it just closed. `start()` runs one sweep
immediately and then one every `job_sweep_s`.

**Verify.**
1. Closing a sitting through the route submits it, and a subsequent `tick()` segments it — asserted
   through the API, not by calling the runner's internals.
2. A sitting whose silence gap has elapsed without a close (the clock case) is found by the sweep and
   segmented, with no request naming it.
3. `POST /sittings/close` that closes nothing (`reason="nothing open"`) submits nothing.

**Falsification.** `the_close_route_forgets_to_prepare.sh` removes the queue call from the close
route; assertion 1 must fail. (This plan first named `the_sweep_forgets_the_clock_case.sh`, which
would have duplicated task 24.2's break on the same predicate; the honest falsifier for this task is
the code it adds — the trigger — and the sweep's clock case is already pinned by
`the_runner_segments_an_open_sitting.sh`. Recorded rather than quietly renamed.)

### Task 24.4 — the read reports `preparing` instead of waiting

**Files.** `backend/app/practice/models.py` (`SittingDetail.preparing: bool = False`);
`backend/app/practice/store.py` (`materialise` parameter); `backend/app/practice/api.py`; the
frontend `src/lib/types.ts` (`preparing?: boolean`) and `src/components/PracticeLogView.svelte`;
`backend/tools/e2e_browser.py` (`scenario_practice_log`);
`backend/tools/falsifications/the_read_waits_for_a_scheduled_job.sh` (new).

**Change.** The detail route consults the runner; the view shows *Preparing…* in place of the
timeline and re-reads on a short bounded retry (about 700 ms, ten tries) until `preparing` clears,
cleaning the timer up when the selection changes or the view is destroyed. The 20 s poll keeps
working underneath; the retry exists so a click one second after switching the piano off fills in
immediately rather than after the poll.

**Verify.**
1. With a job queued, `GET /api/practice/sittings/{id}` answers `preparing: true` with no segments,
   and **`store.ensure_segments` is not called** for it (counted with a spy) — the read does not do
   the work it just declined to wait for.
2. After one `tick()`, the same request answers `preparing: false` with the segments, and the total
   is two requests rather than a block plus a retry.
3. With the runner off, the request materialises synchronously and answers `preparing: false` —
   today's behaviour, unchanged (regression guard).
4. Browser: switching the piano off closes the sitting, and the log shows it ready without a manual
   refresh; a sitting whose work is scheduled shows *Preparing…* and then its timeline.
5. `svelte-check` clean, frontend unit tests green (the retry's bound is pure enough to test).

**Falsification.** `the_read_waits_for_a_scheduled_job.sh` makes the route ignore `scheduled()`;
assertion 1 must fail.

### Task 24.5 — the restore re-seed, the documents, and the full gate

**Files.** `backend/app/backup.py`; `backend/tests/test_backup.py`; `docs/ECOSYSTEM.md`,
`docs/ENGINEERING.md`, `docs/FEATURES.md`, `docs/PERFORMANCE.md`, `AGENT-LOG.md`.

**Change.** After a `replace` import, re-insert the `reference_state` singleton (five lines): a
restore empties every table, including the one row the cache's version lives in, and until the next
restart every matcher read pays ~985 ms for a cache it cannot use. `init_db` already repairs this on
a restart — verified — but a restore does not restart anything.

**Docs, in the same commits** (`ECOSYSTEM.md`'s trigger table is the authority):

| Change | Document |
| --- | --- |
| the phase lands | `ECOSYSTEM.md` status line, phase-table row and § *Phase 24* heading, and this plan's own `Status:` |
| `SittingDetail` gains a field | `ENGINEERING.md` §2, `FEATURES.md` for what the player sees |
| two new settings | `ENGINEERING.md` §8, naming `SRT_BACKGROUND_JOBS` and `SRT_JOB_SWEEP_S` and what reads them |
| a cost model changes | `PERFORMANCE.md`: a case study for the invalidation bug, a row in §3's map for `awaiting_segments` and the runner, and a refinement of R4 |
| the work lands | `AGENT-LOG.md`, with the measurements |

**Verify.** `./check.sh --fast` green after every task; `./check.sh --full` green before hand-off;
`./check.sh --falsify` for each new break script, each seen to fail *and* name its assertion; the
tree clean.

---

## 7. Risks

| Risk | Response |
| --- | --- |
| **Under-invalidation** — a narrowed trigger misses a real reference change and the matcher silently uses stale material | The one real hazard, and why task 1's verification enumerates every write path that can change the reference set in both directions, and why the existing invalidation tests are a required pass rather than a regression check |
| The worker holds the write lock for ~770 ms per sitting, so a concurrent edit could wait | Bounded and single-user; one transaction per sitting; `busy_timeout` already waits 5 s. Documented rather than engineered around — shrinking it means computing outside the transaction, which is a larger change than this phase |
| A background thread in the test process makes the suite flaky | The runner is off in `conftest` and tests call `tick()` synchronously; no test sleeps and none asserts a duration |
| A job segments a sitting while the player is still playing it | `ensure_segments` already refuses an open sitting, and the sweep re-selects it; assertion 24.2.3 pins it |
| The runner is a second owner of "when a sitting becomes segments" | It has no opinions: it calls the same `ensure_segments`, and the read path that used to call it still can |

## 8. Retirement track

Nothing is retired: the read path's lazy materialisation is deliberately retained as the fallback
(§3.4), and `reference_state` keeps its ownership of invalidation — this phase narrows what it
counts, it does not replace it. The one thing removed is the wider trigger rule, replaced in place.

## 9. Execution record

What the implementation changed from what this plan said, and why.

* **Task 24.3's falsification was renamed** from `the_sweep_forgets_the_clock_case.sh` to
  `the_close_route_forgets_to_prepare.sh`: the old name would have duplicated task 24.2's break on
  the same predicate, while the code 24.3 adds is the close trigger. The sweep's clock case is
  pinned by 24.2's script, which fails two assertions when the predicate is widened.
* **The invalidation test's evidence changed.** It first asserted `identified_by = 'workout'` as
  proof the tagging pass ran; `autotag_sitting` legitimately overwrites that column when a segment
  matches a reference confidently, so the durable evidence is `workout_id`. The overwrite itself is
  a separate observation, recorded in `ECOSYSTEM.md` rather than changed here.
* **Two conditions were added that the plan did not have**, both found by writing the tests:
  `awaiting_segments` gained `EXISTS (note_events)` and `preparing` gained `note_count > 0`, because
  a sitting with no notes can never produce a segment and would otherwise be selected on every tick
  for ever and reported as preparing for ever.
* **The browser checks wait for the outcome.** Two existing assertions read a sitting's segments
  immediately after it closed (`scenario_takes`, `scenario_practice_log`), which becomes a race with
  the worker once the work is asynchronous — the read legitimately answers `preparing` with no
  segments. Both now poll through one shared `settled_detail()` helper until the sitting is closed
  and not preparing, which is the outcome the phase is for. A fixed sleep would have hidden it on a
  fast machine.

**One acceptance gap, stated rather than papered over.** The `Preparing this sitting…` display and
its bounded retry are **not asserted end to end**. The e2e server runs with the worker on, and on the
fixture it finishes the preparation faster than a browser can observe it, so no browser assertion can
see the state without racing. What *is* asserted is the server behaviour it depends on — that a
scheduled sitting answers `preparing` with no work done, and that the same request is complete after
one `tick()` (`tests/test_jobs.py`) — plus the fact that the branch is in the built bundle. Closing
the gap honestly means a way to hold the worker still in a scenario, which would be a test hook in
production code; it is recorded instead.

**One pre-existing browser-tier failure, found and deliberately not fixed here.** `./check.sh --full`
stops in scenario 5 on `16 bars fits at 1280x600 once focus mode is on`. It is **not** caused by this
phase: it reproduces identically at `366dfb7`, the commit this phase starts from — score top 290 +
height 356 = bottom 645 against a 600 px viewport, `tooLong=False`. `PracticeView.heightBudget()`
subtracts a constant for the chrome *above* the score (150 px in focus mode) and nothing for what is
below it, so with focus on the fit believes it has 450 px where the layout has 310: it renders a
score that overflows the window and does not refuse it, which is exactly what the assertion exists to
catch. Fixing it means making that budget honest against the real layout instead of a constant, in
the component that also owns the "never scroll during a performance" invariant and the OSMD
re-render trap, so it is named for its own slice rather than guessed at here. The failing check's
message now carries the numbers, so the next attempt starts from a measurement rather than from this
paragraph.

## 10. Execution route

```text
Execution Route:
- Decision: inline
- Evidence: five tasks, ordered — 24.1 is independent, but 24.2 and 24.3 share jobs.py and 24.4
  depends on 24.2's `scheduled()`. One repository, one working tree, each task leaves it green.
- Fallback: 24.1 could be delegated alone; it is small enough that the handoff would cost more.
- User confirmation required: no
```

<!-- historical-record -->
This plan is a record of work that has landed, not a specification. Current behaviour is in docs/FEATURES.md; current status is the status line in ECOSYSTEM.md. See docs/archive/README.md.
