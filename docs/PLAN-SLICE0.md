# Plan — Slice 0: grade the suite

**Parent spec:** [`TEST-STRATEGY.md`](./TEST-STRATEGY.md) § 4, Slice 0.
**Goal:** make the suite's own results trustworthy, and learn which of the existing 883
tests can actually fail. No new coverage is added here; this slice makes what exists
honest and measurable.

Architecture: no production code changes. Two surfaces move — `backend/tools/e2e_browser.py`
(the harness) and repository tooling (`./check.sh`, `requirements-dev.txt`, `pytest.ini`).
Tech stack: pytest 9.1.1, Playwright 1.62 with the system Chromium at `/usr/bin/chromium`,
Node's built-in test runner, `coverage` 7.16 (installed), plus `mutmut` and `hypothesis`.

**Baseline / authority refs.** `docs/TEST-STRATEGY.md` §1.1 (the nine lies), §4 Slice 0,
§7 (decisions T1-T9), §8 (the standing rule). `AGENT-LOG.md` (the `SRT_DB_PATH` mismatch
and the `database is locked` observation). `README.md` § Tests for the documented commands.

**Compatibility boundary.** `scenario_*` function names, the `ONLY` filter, and the
`check()` failure convention stay as they are: `AGENT-LOG.md` and the README both document
running a single scenario by name, and that must keep working. `check.sh` is additive.
`pytest.ini` gains flags that no existing test may fail under.

```text
TDD Route:
- Mode: auto
- Decision: strict
- Strict authority: project instruction — TEST-STRATEGY.md §8, "no assertion is trusted
  until it has been seen to fail", approved by the user
- Strict signals: the whole slice is test-infrastructure behaviour; every task either
  repairs an assertion or measures one
- Test posture: for assertion repairs, demonstrate the check failing before accepting it
- Verification: ./check.sh --fast, ./check.sh --full, and one named falsification per task
```

```text
Change Necessity:
- User-visible need: "when we modify something and it breaks another, the test will catch it"
- No-change option: insufficient — nine checks were proven unable to fail by reading them,
  and one migration path has never executed; no amount of process fixes that
- Why code change is necessary: the harness's assertions are the defect
- Minimum change boundary: backend/tools/e2e_browser.py, ./check.sh, requirements-dev.txt,
  pytest.ini, and one new tools/ script. No app/ code is touched.
- Decision: code-change
```

```text
Existence Check:
- Proposed new surface: ./check.sh
- Existing owner / reuse candidate: the README's Tests section documents three separate
  commands with env prefixes; nothing runs them together
- Why existing surface is insufficient: two tiers with a budget cannot be expressed in prose,
  and a budget nobody can measure is the failure mode §3 warns about
- Creation proof: TEST-STRATEGY.md §3 makes the two tiers a decision; this is its mechanism
- Entropy / retirement impact: one file; `pytest.ini` stays the pytest owner
- Decision: add-with-proof
```

---

## Task 1 — The entry point: `./check.sh` and pytest strictness

**Landed.** `./check.sh --fast` passes in **59 s** against the 180 s budget: 55 s backend,
1 s frontend, 2 s typecheck, 1 s build.

One deviation from the plan, taken because the first measurement justified it. With coverage
in the fast tier the run took **146 s** — inside the budget, but leaving only 34 s for
everything slices 1-7 add. Coverage is a report and never a gate, so it bought nothing on
every edit while costing ~70 s of headroom; it moved to `--full`, where reports are read.
The budget itself is unchanged, and the plan's own risk note anticipated exactly this.

`backend/tools/run_e2e.sh` came out of this task as well: `check.sh` needed a browser tier
that starts its own server, and the README's documented invocation has no wait for health
and no teardown. It defaults to port 8011 rather than the documented 8000 so a test cannot
silently drive somebody else's running server.

**Files:** create `/check.sh`; modify `backend/pytest.ini`, `backend/requirements-dev.txt`.
**Why:** every later task is verified through this command, and the 180-second budget is
unmeasurable without it.

**Steps.**

1. `backend/requirements-dev.txt` gains, under the existing list:

```
coverage>=7.16
hypothesis>=6.100
mutmut>=3.2
pytest-timeout>=2.3
```

2. `backend/pytest.ini` becomes:

```ini
[pytest]
testpaths = backend/tests
norecursedirs = piano-progress practice-logger frontend node_modules .venv .cache
# A typo'd marker silently does nothing, which is how a "slow" tag stops being trusted.
addopts = --strict-markers --strict-config --timeout=120
markers =
    slow: takes more than a second; excluded from the fast tier
```

   The timeout is not decoration: a hung test inside a tier with a 180-second budget is
   indistinguishable from a slow suite, and the budget is what makes the tier worth running.

3. Create `/check.sh`:

```bash
#!/usr/bin/env bash
#
# The single entry point for verification. See docs/TEST-STRATEGY.md.
#
#   ./check.sh --fast    everything that must pass after every edit (< 180 s)
#   ./check.sh --full    the above plus the browser, mutation and scale tiers
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIER="${1:---fast}"

backend() { (cd "$ROOT/backend" && .venv/bin/python -m pytest "$@"); }
frontend() { (cd "$ROOT/frontend" && "$@"); }

start=$(date +%s)
echo "== backend tests =="
backend -q -m "not slow"

echo "== coverage (report only; never a gate) =="
(cd "$ROOT/backend" && .venv/bin/python -m coverage run --source=app -m pytest -q >/dev/null \
  && .venv/bin/python -m coverage report --skip-covered | tail -3)

echo "== frontend tests =="
frontend npm test

echo "== typecheck =="
frontend npm run check

echo "== build =="
frontend npm run build

if [ "$TIER" = "--full" ]; then
  echo "== browser scenarios =="
  "$ROOT/backend/tools/run_e2e.sh"
  echo "== mutation (report only) =="
  (cd "$ROOT/backend" && .venv/bin/python -m mutmut run || true)
  (cd "$ROOT/backend" && .venv/bin/python -m mutmut results | tail -20)
fi

echo "check.sh $TIER passed in $(( $(date +%s) - start ))s"
```

4. `chmod +x check.sh`.

**Verification.** `./check.sh --fast` exits 0 and prints a duration under 180 s. Record the
duration in the commit message — it is the baseline the budget is measured against.

**Risk.** The coverage line runs pytest a second time, roughly doubling the fast tier's
backend cost. If it pushes past 180 s, run coverage only in `--full`; do not raise the
budget.

---

## Task 2 — Per-scenario database isolation

**Landed.** All twelve scenarios pass in sequence *and* individually, and the `ONLY` filter
means something: `run_e2e.sh <name>` now verifies that scenario.

`reset_all()` is called from `main()`'s loop. Its table list is explicit and is checked
against `sqlite_master` on every run, so a table added in a later phase fails loudly rather
than carrying state between scenarios; `REFERENCE_TABLES` names the three seeded tables that
must survive, which is what keeps "deliberately kept" distinguishable from "forgotten".

**Three scenarios depended on the library `scenario_repertoire` created, not two.**
`lan_viewer` was the third, and the plan did not know about it — it only appeared once
isolation removed the state it had been quietly inheriting. All three now call
`seed_library()`. That is the clearest evidence for this slice's premise: the coupling was
invisible for as long as everything shared one database.

**The isolation work also reproduced the concurrency defect the audit predicted.** On the
first solo pass, `two_hands` failed with `sqlite3.OperationalError: database is locked`,
surfacing as a 500 on `POST /api/practice/events` — the same symptom seen once during Phase
19 on an accumulated log and unexplained since. Three immediate reruns passed, so it is a
race rather than a state: `store.ingest` reads to find a sitting and then writes, and a
concurrent writer invalidates the WAL snapshot, which fails as `SQLITE_BUSY_SNAPSHOT` — the
one busy condition `busy_timeout` does not retry.

**Not fixed here, deliberately.** It is a production change and this slice is scoped to the
harness; the drift rule in this plan's Execution Readiness View says to stop rather than
widen. It belongs to Slice 5, and it now has a reproduction instead of a memory.


**Files:** modify `backend/tools/e2e_browser.py` (`main`, the three `clear_*` helpers).
**Why:** this is the structural repair. Nine order dependencies, the `ONLY` filter being
meaningless, and a green filtered run proving nothing all come from one shared database
that is reset once per process.

**Steps.**

1. Add a reset that covers every domain, next to the existing selective helpers:

```python
#: Every table holding practice or library data, verified against `sqlite_master`.
#:
#: The reference tables are deliberately absent. `users` and `skills` are seeded once by
#: `init_workspace` at startup, not per scenario, and `user_skills` links them — deleting any
#: of the three would break every scenario that followed rather than isolating it. A reset
#: removes data; it does not re-create the world.
DATA_TABLES = (
    "composers", "pieces", "piece_journal", "media",
    "sittings", "note_events", "pedal_events", "segments", "segment_metrics",
    "identification_outcomes", "workouts", "performances", "rating_events",
    "exercises", "exercise_skills",
)


def reset_all() -> None:
    """A known starting state for one scenario.

    The three `clear_*` helpers exist for narrower setups inside a scenario; this is the
    one `main()` calls between scenarios. Until it existed, the database was reset once per
    *process* and only for performances and rating values, so a scenario inherited whatever
    the previous one left behind. That is what made `ONLY=<name>` meaningless and what made
    `scenario_practice_log` depend on `scenario_repertoire` having run first.
    """
    import sqlite3
    with sqlite3.connect(os.environ["SRT_DB_PATH"]) as conn:
        for table in DATA_TABLES:
            conn.execute(f"DELETE FROM {table}")
        # Ratings are reset in place rather than deleted: the rows are the learner's skill
        # list, and a scenario that needs a fresh learner needs the numbers cleared, not the
        # skills removed.
        conn.execute("UPDATE user_skills SET elo_rating = 600, attempts = 0, last_practiced_at = NULL")
```

Note the table list is explicit on purpose. `backup.export_document` reads `sqlite_master`
precisely so a new table cannot be forgotten; this reset has the opposite need — a table
added in a later phase must force a decision rather than silently keep state across
scenarios. Task 9 asserts the list covers `sqlite_master` minus the three reference tables.

2. In `main()`, call `reset_all()` before each scenario rather than once before Chromium:

```python
for scenario in (...):
    if ONLY and ONLY not in scenario.__name__:
        continue
    reset_all()
    scenario(browser)
```

3. `scenario_repertoire`'s early return must no longer be silent — that is Task 5; isolate
the ordering change here so the two are separately reviewable.

**Verification.**
- `./check.sh --full` passes.
- Each of the twelve scenarios passes **alone**: `for s in perfect wrong_and_silence
  calibration_and_stats theming long_exercises two_hands repertoire practice_log
  midi_autodetect autotag playback lan_viewer; do python tools/e2e_browser.py
  http://127.0.0.1:8000 "$s"; done`. This is the acceptance criterion and it is expected to
  fail on the first run for `practice_log` and `autotag` — they currently rely on
  `repertoire` having created a library. Those two get a seeding step here, because a
  scenario that cannot run alone is a scenario that cannot verify a slice.

**Repair track.** Root cause: one process-wide reset that covered two tables out of
seventeen. Canonical owner: `main()`'s loop. Retirement: the old single `profile/reset`
call before Chromium is removed, not kept.

---

## Task 3 — Delete the assertions that cannot fail, and the test that stops short

**Landed.** Four `check()` calls and one pytest test rewritten so each can fail; two of them
were replaced by strict equalities over counted values rather than by another predicate.

**The upload-cap finding is the interesting one.** `test_the_upload_cap_is_enforced_while_writing`
set `max_upload_mb=0`, so a 4 KB body tripped the *declared-size* check and the while-writing
check never ran. Investigating why turned up the real answer: **it cannot run through the
endpoint at all.** FastAPI parses the whole multipart body before the route executes, so by
the time `_stage_upload` is reached the bytes have already been received and `file.size` is
known and exact. The cap protects the *media directory*, not the disk — and `_stage_upload`'s
own docstring claimed the opposite ("the point of the cap is to protect the disk"), so the
comment was corrected along with the test.

Three tests now, each with a different job: the declared-size refusal through the route, a
pinned assertion that the endpoint always hands over a real size (so a future parser that
stops declaring one fails the suite rather than silently promoting the second check), and a
direct call with an undeclared size that proves the while-writing check is not dead code and
stops the write *at* the limit rather than after it.

**Falsified, end to end, three of the five.**

| Rewritten check | Break applied | Result |
| --- | --- | --- |
| while-writing cap | removed the `written > limit_bytes` raise | `DID NOT RAISE HTTPException` |
| suggestion key | forced `suggested_key = "C"` in `bridge.py` | `key and level mapped ('…\nC\nstarting level 8\nPractise in C')` |
| pedal-not-recorded equality | rendered a `data-pedal-changes` pill *alongside* the marker, so the positive control still passed | `and no pedal figure is invented for a sitting with no pedal rows` |

The first attempt at the pedal one failed the *adjacent* positive control rather than the
rewritten check, which proved nothing about the rewrite; the break was tightened until only
the rewritten equality could catch it. That is the difference the standing rule is for.

**Not separately falsified:** the pitch-quality count relationships and the backfill
accounting. Both are strict comparisons — `correct_top <= evaluated <= labelled` with
`correct_top > 0`, and `assigned + offered + unresolved == considered` — so any deviation in
the asserted quantities fails them, and both passed against the real values. Recorded here as
argued rather than proven, because the difference matters.


**Files:** modify `backend/tools/e2e_browser.py` (`:1314`, `:1923`, `:2693`, `:2787`, `:2512`);
modify `backend/tests/test_server_hardening.py:175`.

**Why:** they read as coverage and can never catch anything. One of them is in pytest, not
the browser, and is the same defect wearing a test's name.

**Steps.**

First, the pytest one. `test_the_upload_cap_is_enforced_while_writing` sets
`max_upload_mb=0`, so a 4 KB upload satisfies the **declared-size** check at
`repertoire/api.py:349` and returns there — the while-writing check at `:361`, which the
docstring says exists to defend against a lying `Content-Length`, has never run. Send a
body whose declared size is absent or under the cap while the bytes exceed it, so the
second check is the one that fires; assert the message names the size cap and that the
first check was *not* the one reached (by asserting the declared-size branch's distinct
message is absent). If the while-writing check cannot be made to fire through the endpoint,
that is a finding: the test is renamed to what it actually covers and the gap is recorded
rather than left implied.

Then the four browser assertions:

| Line | Replace with |
| --- | --- |
| `:2512` | after the « 30 s jump, assert `len(noteOns()) > 0` **and** that the earliest onset is later than the pre-jump playhead — the jump must *produce* notes, not merely not crash |
| `:2787` | assert `report["assigned"] + report["offered"] + report["unresolved"] == report["considered"]` — the backfill must account for every segment |
| `:2693` | assert `quality["correct_top"] <= quality["evaluated"]` **and** `quality["correct_top"] > 0`, which the current `>= 0` does not |
| `:1314` | assert the suggestion names the *exact* key (`"A"` was matching anything): compare against the value the API returns for that piece's suggested key |

**Verification.** For each, run the case, then break the feature it guards and confirm the
check fails. Name the break in the commit message. A check whose break cannot be constructed
is deleted instead.

---

## Task 4 — Fix the four that pass while the feature is broken

**Landed, with one of the four rejected.** Two rewrites stand and one was reverted after it
failed against working code:

- **The seek check** — `len(sought) < total_notes` accepted seeking that played *nothing*.
  Now `0 < len(sought) < total_notes`: the seek has to produce notes and fewer than all of
  them.
- **The score-colour check** — `live_counts.get(wrong, 0) > 0` accepted one red notehead as
  proof that wrong notes are red. It now polls until the notation agrees with the strip
  below it and requires `red >= flagged > 0`, so the two displays have to tell the same
  story. Polling replaced a fixed wait as a side effect.
- **The after-Stop check — rejected as an audit false positive.** The audit called
  `still == after_stop` vacuously true when both are zero. It is not vacuous: both being zero
  *is* the pass condition, because any note-on after Stop is the bug. Requiring a non-zero
  count was tried, and the scenario failed against working code with `(0 -> 0)` — exactly
  right behaviour and exactly the wrong assertion. The audit's own note for a neighbouring
  check ("mitigated because `len(played) > 0` precedes them") applies here too: `84 in
  started` above proves playback was producing notes before the forget. The check now says
  `still == after_stop == 0` and its comment records why.

That the strengthened version failed against correct code is the useful part: it is the
standing rule catching a bad repair rather than a bad test.

**Files:** modify `backend/tools/e2e_browser.py` (`:614`, `:1923` already covered, `:2482`,
`:2497`).

**Steps.**

- `:2497` — `len(sought) < total_notes` passes when `sought == 0`. Assert
  `0 < len(sought) < total_notes`: the seek must play *something*, and less than the whole.
- `:2482` — `still == after_stop` passes when both are zero. Assert
  `after_stop > 0` first, then equality.
- `:614` — `live_counts.get(wrong, 0) > 0` is "one red path". Compute the set of wrong
  pitches from the payload and assert **every** one is present in `live_counts`.
- `:1923` — `'[data-pedal-changes]'.length == 0` is also satisfied by a renamed selector.
  Assert the `[data-pedal-unrecorded]` marker is present (the positive control already
  exists at `:1919`) and that the segment list is non-empty.

**Verification.** Each rewritten check is falsified: break the feature, watch it fail,
restore. `:614`'s break is a CSS change on `.wrong_pitch`; `:2497`'s is making the seek
handler a no-op.

---

## Task 5 — Skips report as skips

**Landed, and it found a graceful path that had never run.**

`skip()` records a scenario that ran nothing; `main()` prints them and returns 1 unless
`SRT_E2E_ALLOW_SKIPS=1`. Verified by pointing the client at a legacy fixture the server was
not using: the scenario reports `SKIPPED`, `main()` prints *"but these ran no assertions"*,
and the process exits **1** where it used to print *"All browser scenarios passed."* and
exit 0.

On the pytest side, `conftest.py` records setup-time skips and prints them under a
"*N tests did not run*" separator, so a quiet `-q` run cannot hide them. Verified by running
the repertoire suite with `ffmpeg` removed from `PATH`: `87 passed, 12 skipped`, with all
twelve reasons listed.

**And that verification exposed a branch that had never executed.**
`tone_wav` checked `result.returncode` for a `pytest.skip` — but `subprocess.run` raises
`FileNotFoundError` when the binary is missing, *before* the returncode is ever inspected. So
the intended "skip the media suite when ffmpeg is absent" behaviour did not exist: a machine
without ffmpeg got twelve errors, and the graceful branch was unreachable code. It now catches
the missing binary and skips with a reason. This is the same shape as the upload-cap finding
in Task 3 — a documented fallback that the happy path never reaches, which only a deliberate
failure injection makes visible.

**Also here:** `pytest.ini` now excludes `mutants/`, mutmut's working copy of the tree.
Without it pytest collects a second `conftest.py` under the same module name and aborts
collection — so a mutation run would break the very suite it had just graded.

**Files:** modify `backend/tools/e2e_browser.py` (`main`, `scenario_repertoire`,
`scenario_playback`); modify `backend/tests/test_repertoire.py` (the `ffmpeg` fixture).

**Why.** A silent `return` is a pass, so the largest scenario can vanish and `main()` still
prints "All browser scenarios passed." The same shape hides every media test behind a
missing `ffmpeg`.

**Steps.**

1. A module-level `SKIPPED: list[str] = []` and a `skip(scenario, reason)` helper that
   records and prints.
2. Both skip sites call it instead of `return`/`print`.
3. `main()` prints the skip list and returns non-zero when any scenario was skipped, unless
   `SRT_E2E_ALLOW_SKIPS=1` is set for the known environment cases (no ffmpeg, samples not
   installed). The default is loud; the escape hatch is explicit.
4. In `conftest.py`, the `ffmpeg`-or-skip path becomes a `pytest.skip` with a reason that
   names the file, and a session-level count of skipped media tests is printed at the end so
   "0 media tests ran" is visible rather than inferred.

**Verification.** With `ffmpeg` present, no skips. Rename the fixture's `ffmpeg` lookup to a
missing binary: the run fails loudly rather than passing.

---

## Task 6 — `scenario_repertoire` checks its own errors and closes its page

**Landed.** One line each, added where the other eleven scenarios already had them. It was
the largest scenario and the only one collecting console, page and network errors without
ever asserting them — a `console.error` or a failed request anywhere in 67 checks went
unreported.

**Files:** modify `backend/tools/e2e_browser.py` (end of `scenario_repertoire`).

**Steps.** Add the `check(not errors, ...)` the other eleven scenarios have, and
`page.close()`. This is the only scenario missing both — and it is the largest.

**Verification.** Insert a deliberate `console.error` via `page.evaluate` and confirm the
scenario now fails.

---

## Task 7 — A database mismatch is a hard error

**Landed and falsified.** The guard compares the server's reported database path with this
process's and refuses to run, naming both. Verified by pointing `SRT_DB_PATH` at a file the
server was not using: exit 1, both paths quoted.

Worth noting where it *cannot* fire: `run_e2e.sh` exports the environment it uses, so the two
can only diverge on the README's manual invocation — which is exactly the path that produced
the failure `AGENT-LOG.md` records, so the guard is aimed at the right place.

**Files:** modify `backend/tools/e2e_browser.py` (the `clear_*` / `reset_all` helpers).

**Why.** The helpers read `os.environ["SRT_DB_PATH"]` while the server uses its own; when
they disagree, rating setup silently applies to the wrong database. `AGENT-LOG.md` records
this exact failure being met.

**Steps.** At the top of `main()`, after `api("/api/health")`, compare the server's reported
database path with `os.environ.get("SRT_DB_PATH")` and exit non-zero with the two paths
quoted when they differ.

**Verification.** Run with `SRT_DB_PATH` pointing at a second file; the run aborts with both
paths named. Then run normally.

---

## Task 8 — Condition waits instead of fixed sleeps

**Files:** modify `backend/tools/e2e_browser.py` (the 56 `wait_for_timeout` sites).

**Scope, deliberately partial.** Replace only where a condition exists that can be waited
on; leave a sleep where it is genuinely a settle time and say so in a comment.

**Steps.** The three that matter most:

- `:2121` — sleeps 22,000 ms after instrumenting `window.__logPolls`. Replace with
  `page.wait_for_function("() => window.__logPolls > 0", timeout=30_000)`. This removes
  ~20 s from every full run.
- `:2419`, `:2465`, `:2471`, `:2483`, `:2495`, `:2524`, `:2574` — playback reads after
  fixed waits. Wait on the outgoing-MIDI count instead: `wait_for_function` over
  `window.__fakeMidi.noteOns().length`.
- `:898`, `:902`, `:931`, `:934`, `:940`, `:943` — layout settles after a 200 ms debounce.
  Wait on `svgCount === 1 && height === <previous>`, or on a `data-layout-settled`
  attribute added to the container by the renderer.

**Verification.** The full suite passes; its wall-clock duration drops by at least 20 s.
Record before and after.

**Risk.** `wait_for_function` times out rather than hanging, but an over-eager condition can
make a scenario flaky in the other direction. If a replacement proves flaky, revert that one
site to a sleep with a comment saying why — an honest sleep beats a flaky wait.

---

## Task 9 — A scripted falsification helper

**Files:** create `backend/tools/falsify.sh`; modify `backend/tools/e2e_browser.py` (one
assertion in Task 2's verification).

**Why.** §8's rule is a policy until it is mechanical. This makes "prove the check can fail"
a command rather than a habit.

**Steps.** `falsify.sh` takes a patch file and a check command:

```bash
#!/usr/bin/env bash
# Apply a deliberate break, run the check that should catch it, and require that it fails.
#   ./falsify.sh break.patch "./check.sh --fast"
set -euo pipefail
PATCH="$1"; CHECK="$2"
git apply "$PATCH"
if eval "$CHECK"; then
  git apply -R "$PATCH"
  echo "FALSIFICATION FAILED: the check passed with the break applied"; exit 1
fi
git apply -R "$PATCH"
echo "falsified: the check caught the break"
```

Store the break patches under `backend/tools/falsifications/` — one per guard the strategy
names, starting with the four in Slice 0's acceptance list.

2. In `reset_all`, assert the table list covers `sqlite_master`:

```python
        missing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )} - set(TABLES)
        assert not missing, f"reset_all does not cover {sorted(missing)}"
```

so a table added in a future phase forces a decision rather than silently keeping state.

**Verification.** `./falsify.sh backend/tools/falsifications/loopback.patch "./check.sh --fast"`
reports success; removing the `git apply` makes it report failure.

---

## Task 10 — Mutation baseline

**Landed, and the fallback was not needed.** `mutmut` 3.8 works with pytest 9 and grades the
whole codebase in one pass at roughly 21 mutants a second, so it is a `--full` report rather
than an overnight job. Configured in `backend/setup.cfg`.

**Baseline: 10,652 mutants — 10,289 killed, 305 survived, 53 uncovered, 5 timeouts. 97.1%.**
The headline is that the suite is genuinely good. The survivors are the work queue and
concentrate exactly where the audit predicted: `app.music` 199, `app.config` 30,
`app.skills_data` 29, `app.piano` 23, `app.main` 20. The full distribution and what it means
are in `TEST-STRATEGY.md` §1.4; the sharpest single entry is `bass_patterns.x_free_line` with
62, which is the free left hand the README itself calls the harder half.

**Files:** modify `backend/setup.cfg` or `pytest.ini` (mutmut config); no app changes.

**Steps.** Configure `mutmut` over `backend/app`, run it, and record the score per module in
`docs/TEST-STRATEGY.md` §1 as the baseline. Survivors become the work queue for slices 1-5.

**Verification.** `mutmut run` completes and `mutmut results` lists survivors.

**Risk.** `mutmut` against pytest 9 may not work; it has lagged pytest releases before. If it
does not, the fallback is a ~120-line AST rewriter in `backend/tools/mutate.py` that applies
one operator at a time and runs the owning test file. Try the library first, fall back
without ceremony, and record which was used.

---

## Task 11 — Inventory the dead code and duplicated owners

**Files:** create `docs/TEST-STRATEGY.md` § Appendix (or a section in `AGENT-LOG.md`).

**Steps.** Record the nine dead functions and the four duplicated owners from the audit, with
their `file:line`, so retirement is a deliberate decision with evidence. **Nothing is
deleted in this slice.**

**Verification.** The list is present and each entry names its evidence.

---

## Execution Readiness View

```text
- Intent Lock: make the suite's results trustworthy and measure which tests can fail
- Scope Fence: backend/tools/e2e_browser.py, ./check.sh, backend/tools/falsify.sh,
  requirements-dev.txt, pytest.ini, tests/conftest.py. No app/ source changes.
- Baseline Lock: TEST-STRATEGY.md §1.1 and §4 Slice 0, approved
- Approved Behavior: no user-visible behaviour changes; test infrastructure only
- Owner / Contract Constraints: scenario_* names, ONLY, and check() stay as documented
- Compatibility Boundary: every documented e2e invocation keeps working
- Retirement Boundary: the process-wide profile reset is removed; selective clear_* stay
  for in-scenario setup
- Task Batches: 1-2 tooling+isolation; 3-8 the nine lies; 9-10 the machinery; 11 inventory
- Test Obligations: each repaired check falsified by name; all twelve scenarios run alone
- Review Gates: check.sh --fast green after each task; check.sh --full before the slice closes
- Drift / Rewind Rules: if a task needs app/ code to pass, stop — the slice is scoped to the
  harness and a production change means the diagnosis was wrong
- Evidence Required: fast-tier duration, per-scenario solo runs, the falsification log, the
  mutation baseline
- Advisory Boundary: method-pack execution guidance only; not completion authority
```

```text
Execution Route:
- Decision: inline
- Evidence: tasks 2-8 all edit one file, e2e_browser.py — parallel subagents would conflict
  on every task boundary; tasks 1, 9, 10 are small and sequential
- Fallback: none needed
- User confirmation required: no
```

## Risks

1. **The fast tier may not fit 180 s** once coverage and Slice 2's property tests land.
   Mitigation: move coverage to `--full` (Task 1's noted fallback); the budget is a ceiling.
2. **`mutmut` may not support pytest 9** — fallback scripted in Task 10.
3. **Per-scenario isolation may surface real failures** in scenarios that were passing on
   inherited state. That is the point, but it means Task 2 may take longer than it looks.
4. **`wait_for_function` replacements can flake** in the other direction; revert an
   individual site rather than weakening the wait.
