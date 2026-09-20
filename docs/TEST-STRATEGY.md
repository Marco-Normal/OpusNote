# Test strategy — the regression guardrail

Status: **planned.** Slice 0 is the foundation; slices 1-8 follow it in risk order.

This document owns one question: **how do we know a change did not break something
else?** That question was previously answered in four places at once — the README's
*Tests* section, `ROADMAP.md`'s standing rules and *Verification additions*, and the
acceptance bullets of nineteen phases — which is exactly how it became unanswerable.
Those places now point here.

It is a standing engineering policy, not a phase. Phases add features; this decides how
any of them is allowed to be called finished.

---

## 1. The diagnosis, measured

| Layer | State |
| --- | --- |
| Backend unit + integration | **811 tests** collected from 511 functions; 4,343 statements; **97% line coverage** (144 missed) |
| Frontend pure modules | **72 tests**, **98.2%** — across the **6 of 16 modules** that have tests at all |
| Browser end-to-end | 12 scenarios against a real server and a real Web MIDI path |
| Named regressions | **12**, across 6 files |
| Migration tests | **3** — and not the one that matters (§1.2) |
| Concurrency tests | **0** |
| Invariants (property-based) | none |
| Contracts (schema, status codes, boundaries) | by example only |
| Cross-domain seams | actually good — no zero-coverage seam found |
| Scale bounds, fault injection, accessibility, visual | none |
| Mutation score | **97.1%** — 10,652 mutants, 10,289 killed, **305 survived**, 53 uncovered, 5 timeouts |

Three facts make the rest of this document necessary.

**The uncovered 144 lines are not the problem.** They are unreachable defensive
branches: `raise NotFound` behind a route that validates first, `if not intervals: return
None` for a case the dedupe index makes impossible, music21 context fallbacks. Driving
them to 100% would be theatre. **This project does not have a coverage problem.**

**It has a resolution problem.** Phase 16 is the proof, in this project's own history: 25
attempts per skill, ratings near 800, and every exercise still level 1, because *"the tests
missed it because they only probed 620, 1000 and 1600 — never the middle, which is where
learners actually live."* Those lines were covered. The **domain** was not. An
example-based test confirms the cases you thought of; it cannot confirm the space between
them.

**And a grading problem.** No test here has ever been asked whether it *can* fail. During
Phase 19 the browser assertion for the pedal re-strike passed contentedly until the fix was
deleted from `play()`, at which point it reported `1 overlapping pairs` — it had been
correct by luck, not by construction. A test that cannot fail is worse than no test,
because it is bought with confidence.

### 1.1 The suite lies in nine specific places

Nine green ticks over nothing, all verified by reading the code.

**Assertions that provably cannot fail** — `backend/tools/e2e_browser.py`:

```python
check(len(page.evaluate("() => window.__fakeMidi.noteOns()")) >= 0, ...)          # :2512
check(report["considered"] >= 0 and "assigned" in report, ...)                    # :2787
check(quality["unresolved"] >= 0 and quality["offered_attempted"] >= 0, ...)      # :2693
check("A" in suggestion and "level 8" in suggestion, ...)                         # :1314
```

A length is never negative; `"A"` matches almost any string.

**Assertions that pass while the feature is broken:**

| Line | Says | Also true when |
| --- | --- | --- |
| `:2497` | "clicking the strip plays from there rather than from the beginning" | seeking plays **nothing** (`sought == 0`) |
| `:2482` | "nothing further is sent afterwards" | both counts are `0` |
| `:614` | "wrong pitches are coloured red" | one note is red and the rest are not |
| `:1923` | "no pedal figure is invented for it" | the selector was renamed |

**A test that claims to cover the check it short-circuits past.**
`test_server_hardening.py:175` is named `test_the_upload_cap_is_enforced_while_writing` and
sets `max_upload_mb=0`, so a 4 KB upload satisfies the **declared-size** check at
`repertoire/api.py:349` and never reaches the while-writing check at `:361` — the one the
docstring at `:344` says exists to defend against a lying `Content-Length`. The named
behaviour has never run.

**Self-skipping green ticks, in both suites.** `scenario_repertoire` — the largest browser
scenario, 67 checks — prints `skipped` and `return`s when the server's legacy database is
not the fixture (`:1226`); `scenario_playback` does the same for the sampled piano
(`:2360`). Because `check()` is what raises, a silent `return` is a pass, and `main()`
prints *"All browser scenarios passed."* either way. In pytest the same shape appears at
`test_repertoire.py:773`, where **every media-conversion test vanishes** if `ffmpeg` is
absent — and the whole media failure surface is behind it.
(2026-09-20: the synthesiser arm of `scenario_playback` no longer sits inside that skip — it
is always available, so it now runs with or without the samples, and it is the arm that
asserts the master output is audible. The sampled-piano arm still skips.)

**A scenario that never checks its own errors and never closes its page.**
`scenario_repertoire` collects `console`/`pageerror`/HTTP failures at `:1235` and never
asserts them; it is the only scenario outside the `check(not errors, ...)` list.

**The loopback boundary is globally disabled.** `conftest.py:96-102` patches
`hostinfo.is_loopback` to `True` for every API test, so the guard protecting every
destructive route is exercised only in three re-patched tests — while
`hostinfo.require_loopback` has four importers and gates all of them.

### 1.2 The backend's silent gaps

Ranked by how quietly they would break.

**The practice `ADD COLUMN` migration has never executed.** `practice/schema.py:188-189` is
the loop applying all twelve practice `ADDED_COLUMNS` — `sittings.legacy_id`,
`sittings.closed_ms`, `segments.source`, `segments.workout_id`, and the eight
`segment_metrics` columns added in Phase 18. `db.py:176` runs `migrate_practice` *before*
`PRACTICE_SCHEMA` (`:177`), so on a fresh database the tables do not exist and the loop
`continue`s; and nothing in the suite fabricates an old-shape practice database. The one
code path that must work on **your** database is the one path with no test. Related: there
is **no `PRAGMA user_version`** anywhere, so the app cannot tell a current database from a
three-releases-old one, and there is **no downgrade path at all**.

**Articulation is swallowed whole.** `music/generator.py:225`, `:234` and `:243` are bare
`except Exception: pass` around slur, dynamic and hairpin insertion. All three handler
bodies are unreachable in the current suite, and **no test anywhere mentions slurs,
dynamics or hairpins**. A complete regression in expressive notation would be invisible.

**Corrupt JSON degrades silently.** `db.py:188 json_load`'s malformed branch (`:194`) never
runs, so a corrupt `exercises.expected_json` or `performances.analysis_json` becomes an
empty list rather than an error. A serialisation regression would present as "no expected
notes", not as a failure.

**Transaction rollback is unverified.** `db.py:155`'s `ROLLBACK` inside `except Exception`
has never executed, because no test makes a transaction fail. Separately, the upload path's
multi-statement work *is* wrapped — `repertoire/api.py:407-442` places the file and writes
the catalogue row inside `db.transaction`, and `media_pipeline.py:213-218` documents that
"the caller owns the transaction" — but the **file write is not transactional**, so a
rollback can leave a stray file on disk. Only the database half is atomic, which is the
real gap and not the one this paragraph first claimed.

**Nine functions are dead in both directions** — 0% covered *and* referenced by nothing in
`app/` or `tests/`: `selector.available_levels`, `db.row_to_dict`,
`events.even_durations`, `events.melody_events_to_pitches`, `expected.expected_to_dicts`,
`similarity.attack_count`, `similarity.top_piece`, `skills_data.keys_at_level`,
`store.performance_count` (`piano.fetch` is an intentional network seam). They rot outside
every test and every call graph.

**Two owners for one value, with divergent test depth** — the project's own recurring
defect class, found twice more: `services._streak_days` (`:363`, key branch unrun) versus
`practice/store.streak_days` (`:1137`, well tested), and `services._local_day` (`:344`)
versus `practice/store.local_date` (`:124`). The well-tested one is not the one
`/api/stats` uses.

**Roughly forty tuning knobs have never been set to a non-default value.** `settings` is
constructed once at import (`config.py:188`), and `conftest.py` redirects four paths and
nothing else. Every `SRT_ELO_*`, `SRT_AUTOTAG_*`, `SRT_WEIGHT_*` and scoring threshold runs
at its default in every test. `_env_int`/`_env_float` (`:34-41`) raise an uncaught
`ValueError` at import on a malformed value, and that is untested too.

### 1.3 The latent concurrency bug this exposed

`db.py:152` opens transactions with a plain deferred `BEGIN`. There are nine write
transactions through it in `practice/store.py` alone. In WAL, a deferred transaction that
reads and then upgrades to a write can fail with `SQLITE_BUSY_SNAPSHOT` — **which
`busy_timeout` does not retry**, precisely the two-writer case the comment at `db.py:141`
claims to protect. There is no concurrency test of any kind; the only locking-adjacent test
asserts PRAGMA *values*.

**Reproduced, 2026-09-16.** Running one browser scenario on its own — which per-scenario
isolation made possible for the first time — produced exactly this: `two_hands` failed with
`sqlite3.OperationalError: database is locked` surfacing as a 500 on
`POST /api/practice/events`. Three immediate reruns passed, so it is a race rather than a
state, and it is the same symptom seen once during Phase 19 on an accumulated log. The
mechanism is now confirmed rather than inferred: `store.ingest` reads to find a sitting and
then writes, and a concurrent writer invalidates the WAL snapshot. Slice 5 has a
reproduction to work from.

---

### 1.4 The mutation baseline, and what it says

`mutmut` 3.8 works with pytest 9 — the fallback was not needed — and its instrumented
trampoline design means the whole codebase is graded in one pass at roughly 21 mutants a
second rather than one test run per mutant. That makes it affordable as a `--full` report
instead of an overnight job.

**10,652 mutants: 10,289 killed, 305 survived, 53 uncovered, 5 timeouts.** The headline is
that the suite is genuinely good — 97% of deliberately-broken code is caught. The survivors
are the work queue, and they concentrate exactly where the gap analysis predicted:

| Module | Survivors | What it is |
| --- | --- | --- |
| `app.music` | **199** | the generator, the bass-pattern library, harmony |
| `app.config` | **30** | the settings plumbing |
| `app.skills_data` | **29** | the difficulty model's own data |
| `app.piano` | 23 | the one-time sample download and its static mount |
| `app.main` | 20 | the app factory and the frontend mount |
| everything else | 4 | |

Two of those rows are the audit restated as a number. `app.config`'s 30 survivors are the
"~40 `SRT_*` knobs never exercised at a non-default value" finding: the settings object is
built once at import and every test runs at its defaults, so a mutant that changes a default
changes nothing any test observes. `app.music`'s 199 are the resolution problem: the catalogue
sweeps are exhaustive over what ships and blind to anything else, so mutating a pattern's
internals often leaves every shipped case passing.

At function level the queue is sharpest at:

| Function | Survivors |
| --- | --- |
| `bass_patterns.x_free_line` | **62** |
| `bass_patterns.x_countermelody` | 30 |
| `skills_data.x_validate_taxonomy` | 23 |
| `piano.x_mount_samples` | 23 |
| `generator.x__inner_voice_events` | 22 |
| `main.x_mount_frontend` | 20 |
| `bass_patterns.x_canon` | 19 |

`x_free_line` is the free left hand that this project's own README calls *"the harder half:
it needs its own melodic generation… the difference between reading and guessing"*. The
hardest thing to generate is also the least defended, which is not a coincidence — it is
what a hard case looks like when the tests were written alongside it.

**This is a report, not a gate.** 305 survivors is a work queue, not a failure, and the score
becomes a no-regression gate only once slices 1-2 have worked through the worst of it.

---

## 2. The two principles

**Test the space, not the samples.** Where the code claims a property over a domain, the
test must be over the domain. The project already contains the pattern and uses it exactly
once: `sessionize`'s *"a test asserts they agree on the same stream"* — the batch rule and
the incremental rule must agree, as a property. The catalogue sweeps in `test_bass_patterns`
and `test_harmony` are the same instinct over a finite domain, and they are good; randomised
properties extend them past the shipped catalogue.

**Grade the suite, do not merely grow it.** Mutation testing answers the actual question —
*mutate the source; any survivor is a line the suite executes but cannot see.* No quantity
of new tests substitutes for knowing whether the existing 883 can fail. A new assertion
that has not been seen to fail is not yet a test.

---

## 3. Execution model

**One command, two tiers.** `./check.sh` at the repository root — the single entry point,
because the thing being verified spans both processes the README already documents.

| Tier | Contains | Budget | When |
| --- | --- | --- | --- |
| `--fast` | backend unit + integration + invariants + contracts + seams; frontend tests; `svelte-check`; build | **< 180 s** | after every meaningful edit |
| `--full` | everything in `--fast`, plus browser e2e, mutation, scale and fault injection | no budget | before a slice is called done |

**There is no migration step in `check.sh`, in either tier.** Migration coverage is ordinary
pytest and belongs in `--fast`: it is fast, and the acceptance criterion for the slice that
adds it is that a schema regression fails the tier run after every edit. Marking a migration
test `slow` would be worse than useless — §1.2's missing `user_version` guard is exactly the
kind of thing that would then be exercised in neither tier.

**Why 180 and not 90.** The backend suite is already ~55 s and the frontend, typecheck and
build are seconds. At a 90-second ceiling that leaves roughly half a minute for everything
this document proposes to add — which is not enough for property testing (Slice 2) to run
more than a token number of examples, and `hypothesis` at ten examples is barely better than
the example-based tests it replaces. The extra ninety seconds buys the single biggest quality
jump in the plan, so it is worth paying. It stays a hard ceiling: if a future slice cannot fit,
the answer is to move something to `--full` by naming the risk, not to raise the number again.

The budget is a requirement, not an aspiration. A suite that takes five minutes is a suite
that stops being run, and then the guardrail is decorative.

**Coverage is a report, never a gate.** There is no threshold. A percentage target on a
codebase at 97% line coverage with a live plateau bug would only encourage testing getters.

**Mutation score is a report first, a gate later.** The first run will be humbling — this
suite has never been graded. Survivors become a work queue. The score becomes a
no-regression gate once the baseline is known and the worst offenders are dealt with.

---

## 4. The work

### Slice 0 — Grade the suite

Everything else is built on this. Adding tests to a suite that lies mostly adds more things
nobody has proven can fail.

**Ships.**

1. **Mutation testing** over `backend/app` (`mutmut`). Per-module mutation score; survivors
   listed with the test file that should have caught them. A report in `--full` for now.
2. **Harness repair** — every item in §1.1:
   - the four unfailable checks deleted or rewritten into something that can fail;
   - the four pass-while-broken checks rewritten with a positive control;
   - `test_the_upload_cap_is_enforced_while_writing` actually reaches the while-writing
     check, or is renamed to what it tests;
   - a self-skip becomes an explicit `SKIPPED` outcome that `main()` reports, and `main()`
     fails when a scenario was skipped unintentionally;
   - `ffmpeg`-dependent tests report as skipped rather than vanishing, and the count is
     asserted;
   - `scenario_repertoire` asserts its collected errors and closes its page;
   - **per-scenario isolation**: each scenario starts from a known database state, so order
     stops mattering and `ONLY` becomes meaningful;
   - the `SRT_DB_PATH` mismatch between helper and server becomes a hard error rather than
     silently targeting the wrong file (`AGENT-LOG.md` records this exact failure);
   - fixed sleeps replaced by condition waits wherever a condition exists.
3. **The falsification rule, mechanised.** For each repaired check, break the code it
   guards, watch the check fail, restore. A check that cannot be made to fail is deleted
   rather than kept.
4. **An inventory of the nine dead functions** and the duplicated owners, as a list to
   retire deliberately — not removed here, because deletion is a separate decision with its
   own evidence.
5. `pytest.ini` gains `--strict-markers` and a per-test timeout, so the two tiers are
   enforceable rather than conventional.

**Acceptance.**

- `check.sh --full` passes.
- Every scenario is individually runnable and passes alone (`ONLY=<name>`).
- Deliberately breaking `resolveOverlaps`, `sustained`, the loopback guard, and the journal
  `sitting_id` write each makes at least one **fast-tier** test fail. Named per case.
- The mutation report exists and its survivor count is recorded as the baseline.
- `grep` finds no `>= 0` assertion and no scenario that can `return` without reporting.

**Risk:** mutation testing on a 4,300-statement codebase is slow. Mitigation: per-module,
cached, `--full` only.

---

### Slice 1 — Persistence and migration

**Promoted to first among the deep slices**, because the audit's top-ranked risk is the one
path that runs on your real database and has never executed.

**Ships.**

- A **frozen old-schema fixture** in the repository — SQL, not a binary — reproducing a
  pre-Phase-18 practice database: seven-column `segment_metrics`, the `NOT NULL` outcome
  reference, no `sitting_id`. Every `--full` run upgrades it to current and asserts **no rows
  lost, every column the code reads exists, every index exists**.
- The **`ADDED_COLUMNS` loop is executed by a test** for both the practice and repertoire
  domains, and the `db.py:162` ordering contract ("a migration must run before the script
  that indexes the column it adds") is asserted rather than left as a comment.
- **`PRAGMA user_version`**, so the schema has a version and a stale database is detectable,
  with a test that a current database reports the current version.
- **Backup compatibility**: a document written by an older version imports into the current
  one.
- **Interrupted work**: a crash mid-import leaves the database usable; the WAL is handled as
  `DEPLOYMENT.md` describes.
- **Corrupt JSON raises.** `db.json_load`'s malformed branch currently returns a default, so a
  corrupt `exercises.expected_json` or `performances.analysis_json` surfaces as "no expected
  notes" instead of as damage. It becomes a loud error, with tests for both the corrupt case
  and the empty case. **This is a behaviour change, not only a test**: a single corrupt row
  will now fail the request that reads it rather than degrading quietly, which is the point —
  but it also means the failure is visible at the piano rather than three weeks later.

**Acceptance.** Deleting any `ADDED_COLUMNS` entry, or reordering `init_db`, fails the fast
tier.

---

### Slice 2 — Invariants

The biggest quality jump per unit of effort, because `hypothesis` writes the cases nobody
thought of.

| Invariant | Where it is claimed | Current state |
| --- | --- | --- |
| Every generated bar fills its meter exactly | `generator.py`, `bass_patterns.py` | swept over the shipped catalogue only |
| Every figure stays in register and diatonic | same | same |
| Generation is deterministic for a seed | three test files | a small fixed seed list |
| **Every articulation asked for is emitted** | `generator.py:225-244` | **nothing asserts slurs, dynamics or hairpins at all** |
| Selection level is monotone in rating | `selector.py` | three sample points |
| Batch rule ≡ incremental rule | `sessionize.py` | **done — this is the model** |
| `sustained()` never shortens; `resolveOverlaps()` never overlaps | `playback.ts` | example-based |
| Scores bounded by their parts | `scoring/engine.py` | example-based |
| Export → import → export is stable | `backup.py` | one round trip |
| Re-import, re-segment, re-tag are idempotent | several | one scenario each |

The articulation row is new from the audit and is the highest-value single addition: three
bare `except Exception: pass` currently make an entire notation feature unobservable.

**Acceptance.**

- Each property test is shown to fail against a deliberately-broken implementation, with the
  break named in its docstring.
- `hypothesis` uses a fixed seed in `--full` and a random one interactively; a failure prints
  its minimal example.
- The Phase 16 plateau is pinned as a property over the whole rating range, so re-anchoring
  `elo_base` must break it.

---

### Slice 3 — Contracts

The README states as a standing rule that **the API is the contract**. Nothing enforces it.

**Ships.**

- A frozen **response-schema snapshot** per route: field names and types. Adding a field
  passes; removing or renaming one fails.
- A **status-code matrix** per route, including `403` for **every** irreversible route — the
  Phase 9 boundary, currently invisible because `conftest` forces loopback on for the whole
  suite.
- **PATCH semantics** as a contract: unset leaves alone, explicit `null` clears.
- **Closed-set rejection**: `PracticeSource` refuses a third value; `kind` refuses an unknown
  media type; a backup document with an unknown field or table is refused, and the refusal is
  asserted to come from the documented layer rather than from Pydantic incidentally.
- An **OpenAPI document snapshot**, so a route or model that changes shape without a test
  changing shows up in the diff.
- A **`PRAGMA foreign_keys = ON`** assertion that an orphan insert is actually rejected, and
  that each `ON DELETE` mode is what the schema says it is.

**Acceptance.** Removing a field from any response model, or adding a route without a
declared status-code expectation, fails `--fast`.

---

### Slice 4 — Seams

The audit found **no zero-coverage seam**, and that is worth saying: the cross-domain work in
this project has been done carefully. What remains is the deletion semantics, tested only
incidentally.

**Ships.** One test per reference in the schema, asserting both the happy path and what
happens when the parent is deleted:

| Seam | Invariant | State |
| --- | --- | --- |
| piece → segments | deleting a piece orphans segments; never deletes practice history | incidental |
| sitting → journal | deleting a sitting nulls `sitting_id`; the prose survives | new in Phase 18 |
| workout → performances | deleting a workout nulls `workout_id`; attempts survive | incidental |
| composer → pieces | deleting a composer leaves pieces unattributed | tested |
| media → disk | a row's file is removed only if nothing else references it | tested |
| bridge | every piece key and difficulty maps to a legal key and level | tested |
| practice ↔ repertoire | a segment's minutes and the piece's measured minutes agree | tested |
| backup ↔ schema | every table in `sqlite_master` is exported, including one added tomorrow | tested |

The last row matters most: the backup reads its table list from `sqlite_master` precisely so
a new table cannot be silently omitted. That design deserves a test that fails if someone
replaces it with a hand-written list.

**Acceptance.** A new foreign key added without a test fails the slice's own inventory check.

---

### Slice 5 — Non-functional

**Ships.**

- **Concurrency, with the deferred-`BEGIN` question settled.** Reproduce the two-writer lock
  from §1.3, decide between `BEGIN IMMEDIATE` and a retry, and make the result a test with a
  budget rather than a flake. Assert a connection is never shared across threads, per the
  `check_same_thread=False` comment.
- **Environment plumbing.** Every numeric `SRT_*` knob gets at least one test at a
  non-default value — through the environment, not by patching a consumer's global, so the
  actual plumbing is exercised. A malformed value is asserted to fail loudly rather than
  raise an uncaught `ValueError` at import.
- **Scale canaries.** `identification_quality` (documented quadratic), `_notes_for_segments`
  (documented N+1), `export_document` and `list_pieces` get a bound at a realistic history
  size, so a complexity regression is a failing test rather than a slow afternoon.
- **Fault injection.** Missing media file, absent ffmpeg, corrupt JSON, truncated upload,
  unreadable legacy DB, and the `immutable=1` fallback at `importer.py:58` — each must
  produce the documented error rather than a 500.
- **Transaction rollback**: a failing transaction leaves the database unchanged.
- **Clock control.** Much of the practice domain already accepts `now_ms`; the rest gets a
  seam so the five-minute silence gap and the 1.5-second close window are testable without
  waiting.

---

### Slice 6 — Frontend depth

**Ships.**

- Tests for the pure modules that have none: `liveMatch.ts` (a deterministic class with no
  dependencies — the clearest gap), the `score.ts` colour helpers, the `types.ts` formatters,
  `ApiError`, and the two exported functions of `playback.ts` that no test references
  (`firstOnset`, `fromTime`).
- **Extraction for testability** where the interesting logic is private and therefore
  unreachable: `metronome.buildSchedule`, `pianoPlayer.sendMidi`/`pumpQueue`,
  `midi.handleMessage`. These are pure decisions trapped behind Tone, `performance.now` and
  the DOM; moving them out is a refactor justified by the fact that they are what breaks.
- `svelte-check` currently **excludes `src/**/*.test.ts`**, so the tests are not type-checked.
  Fixed, which also surfaces the `allowImportingTsExtensions` question Phase 19 deferred.

---

### Slice 7 — Browser reach

Only where the harness can genuinely observe it.

**Ships.**

- **Keyboard navigation and focus order** — there is not one `page.keyboard` call today.
- **Accessibility assertions**: ARIA roles and names on the controls the recon flagged as
  missing `aria-live`, and `prefers-reduced-motion` for the beat pulse (a stated ROADMAP
  item).
- **Failure injection** via `page.route`: API down, 500, malformed payload. The only existing
  precedent stubs `/api/host`.
- **Timing**: patch `performance.now` in the fake MIDI so late, duplicate and out-of-order
  note-ons can be injected — currently every message carries the real clock, which makes
  onset accuracy untestable.

**Explicitly not:** audio output (unobservable, and the harness says so), and pixel-perfect
visual baselines (see non-goals).

---

### Slice 8 — `docs/TESTING.md`

The guide, written once the above is settled. Its shape:

- **The decision procedure.** "What did I change?" → which tier of test is owed. A scoring
  change owes an invariant. A route change owes a contract test. A schema change owes a
  migration fixture and a seam test.
- **Recipes**, one per test kind, as short worked examples taken from this repository.
- **The falsification rule** as step one of every recipe, not as a closing note.
- **The fixture inventory**: what `conftest.py`, the `sessionize` agreement harness, the fake
  MIDI device and the browser harness already give you, so nobody rebuilds them.
- **Anti-patterns this project has actually hit**, each with the real example: the assertion
  that cannot fail (`>= 0`), the check that passes on an empty collection, the test that
  passes when the feature plays nothing, the test whose name promises a check it
  short-circuits past, the skip that reports green, the fixed sleep where a condition
  existed, and the probe that did not reproduce how the harness launches (Phase 19, where a
  standalone `chromium.launch()` was read as a property of the suite).

---

## 5. Tool decisions

| Tool | For | Justification |
| --- | --- | --- |
| `hypothesis` | property tests | Generates the cases nobody thought of; the direct fix for the resolution problem |
| `coverage` | reporting | Already installed for the diagnosis; reports only, never a gate |
| `mutmut` | grading | The only tool that answers "would this test fail if the code were wrong" |
| Node's `--experimental-test-coverage` | frontend reporting | Built in; verified working during the diagnosis, no dependency |
| nothing new | browser | Playwright is already there and already drives the real path |

All Python additions are **dev-only** (`requirements-dev.txt`). The project has refused
avoidable dependencies everywhere else — no JS test runner, no `.mxl` unzip, no
`@tonejs/piano` — and this is the smallest set that buys machinery we would otherwise
hand-write badly.

---

## 6. Non-goals, stated so the plan cannot drift

- **A coverage threshold.** 97% line coverage coexisting with a live plateau bug is the
  argument against it.
- **Pixel-diff visual regression.** Twenty-two screenshots exist and none is diffed. A
  baseline on an OSMD-rendered score fails on font rendering and teaches people to ignore
  red — worse than no baseline. Contrast and layout *are* asserted, numerically.
- **Load testing.** One user, one piano, one machine. Concurrency and scale get bounds, not
  benchmarks.
- **Rewriting the existing 883 tests.** They are good, and the audit says so explicitly:
  `scoring/engine.py` at 99.3%, the backup round-trip, legacy import idempotence, the
  bass-pattern sweeps, the 12 named regressions, and the cross-domain seams. They are being
  *graded*; the survivors of that grading get attention.
- **A CI service.** There is none today and this does not add one. The gate is
  `check.sh --full` plus the standing rule below.
- **Removing the dead code in this plan.** Nine functions are dead in both directions. They
  are inventoried in Slice 0 and retired deliberately, with their own evidence, rather than
  swept up here.

---

## 7. Decisions taken

| ID | Question | Decision | Consequence |
| --- | --- | --- | --- |
| T1 | Add dev dependencies? | **A small justified set**: `hypothesis`, `coverage`, `mutmut` | Hand-writing property generation and mutation tooling would be worse in every way; all three are `requirements-dev.txt` only |
| T2 | Coverage as a gate? | **No — report only** | A threshold on a codebase at 97% with a live plateau bug rewards testing getters |
| T3 | Mutation score as a gate? | **Report first, gate once the baseline is known** | 883 tests have never been graded; the first score is a discovery, not a verdict |
| T4 | Fix the harness before adding tests? | **Yes — Slice 0 first** | Anything built on a suite that reports green over a skipped scenario inherits the lie |
| T5 | Visual regression baselines? | **No** | Font rendering makes an OSMD diff noise, and noise teaches people to ignore red |
| T6 | Migrations before invariants? | **Yes — Slice 1** | The one code path that runs on the real database had never executed when this was written |
| T7 | Is this an ADR? | **No** | `ECOSYSTEM.md` § *Phase 9* records that this project's decision record is its own documents and tables; an ADR directory would be a second authority for the same facts |
| T8 | `--fast` budget? | **180 s**, a hard ceiling | 90 s leaves ~30 s for everything this plan adds, which is not enough for property testing to be worth having; the next raise needs a named risk moved to `--full`, not a bigger number |
| T9 | Corrupt JSON in `db.json_load`? | **Raise, never degrade silently** | A corrupt row must be visible at the piano, not present as "no expected notes" three weeks later |

---

## 8. The standing rule

> **A slice is not done until `check.sh --full` passes, and no assertion is trusted until
> it has been seen to fail.**

The second half is the part that matters. It is the Phase 19 lesson written down: the pedal
re-strike assertion was correct by luck until the fix was removed and the failure observed.
Every check added from here is falsified before it is kept.

---

## 9. What this replaces

- `README.md` § *Tests* — keeps the commands, points here for what they must cover.
- `ROADMAP.md` § *Standing rules* 2 and 3 and § *Verification additions* — superseded by
  slices 0-7; the rules stay as history with a pointer.
- Each phase's acceptance bullets in `docs/ECOSYSTEM.md` — unchanged, but a phase now also
  owes whatever this document says its change surface implies.
---

## Appendix — dead code and duplicated owners

Inventoried in Slice 0 and **deliberately not removed**. Deletion is a decision with its own
evidence, and sweeping it into a test-strategy slice would be exactly the "while here" work
this document argues against. Each entry names what would justify keeping it.

### Dead in both directions — 0% covered *and* referenced by nothing

Verified by grep: no non-definition reference anywhere in `app/` or `tests/`.

| Function | Note |
| --- | --- |
| `adaptive/selector.py:147` `available_levels` | superseded by the level table it derives from |
| `db.py:184` `row_to_dict` | a one-line adapter nothing calls |
| `music/events.py:102` `even_durations` | an exact-`Fraction` bar divider, never entered |
| `music/events.py:136` `melody_events_to_pitches` | never entered |
| `music/expected.py:205` `expected_to_dicts` | an orphaned serialiser; callers use `note.to_dict()` inline in three modules |
| `practice/similarity.py:196` `attack_count` | superseded by `metrics.attacks` |
| `practice/similarity.py:399` `top_piece` | superseded by the ranked candidate list |
| `skills_data.py:226` `keys_at_level` | never entered |
| `store.py:482` `performance_count` | never entered |

`piano.py:120 fetch` is **not** on this list: it is the deliberate network seam that
`load_piano` wraps, and its `OSError`/`URLError` handlers are unreachable in tests only because
every test monkeypatches around the network. That is a coverage gap, not dead code, and
Slice 5 owns it.

### Two owners for one value

The project's own recurring defect class — a rule written twice, with the two copies drifting
apart in how well they are tested.

| Value | Owners | Divergence |
| --- | --- | --- |
| consecutive practice days | `services.py:363 _streak_days` | the "today unplayed, yesterday played" branch has never run — and this is the one `/api/stats` uses |
| | `practice/store.py:1137 streak_days` | well tested, via `/api/practice/analytics/summary` |
| the player's calendar day | `services.py:344 _local_day` | malformed-timestamp fallback never run |
| | `practice/store.py:124 local_date` | tested |
| the upload cap | `repertoire/api.py:349` | fires through the route; tested in Slice 0 |
| | `repertoire/api.py:361` | unreachable through the route; tested directly in Slice 0 with the finding recorded |
| serialisation | `music/expected.py:205 expected_to_dicts` | dead |
| | inline `[n.to_dict() for n in …]` | three call sites, none of which round-trip |

The first two rows are the same shape: the copy that is *used* is the copy that is *untested*.
Retiring one of each pair is the fix, and Slice 5's environment work touches the same files.
