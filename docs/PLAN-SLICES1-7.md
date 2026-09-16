# Plan — Slices 1-7 of the test strategy (Slice 8 last)

**Status: executing.** Each slice lands as its own verified commit; `docs/TESTING.md`
(Slice 8) is written only after slices 1-7 are complete.

**Parent spec:** [`TEST-STRATEGY.md`](./TEST-STRATEGY.md) §4. §1 is the measured
diagnosis, §7 the decisions (T1-T9), §8 the standing rule. This document does not
restate them; it records execution order, ownership, the recon findings that changed
the plan, and the gate each slice owes.

**Goal.** Take the suite from *graded* (Slice 0: 97.1% mutation score, 305 named
survivors) to *growing in the right places*: the migration path that has never run,
the domain properties nobody stated, the contracts the README claims, the seams, the
non-functional bounds, the frontend, and the browser.

**Architecture.** No new subsystem. Slices 1-5 are backend; 6 is frontend; 7 is the
browser harness. Three slices carry production behaviour changes, each named below and
each decided by `TEST-STRATEGY.md` (T9) or by a defect the recon proved.

**Tech stack.** pytest 9.1.1, `hypothesis` 6.168 (installed for this plan),
`mutmut` 3.8, `coverage` 7.16, Playwright 1.62 + system Chromium, Node 26 built-in
test runner, `svelte-check` 4.

**Baseline / authority refs.** `docs/TEST-STRATEGY.md` §1.1-§1.4, §4, §7, §8;
`docs/PLAN-SLICE0.md`; `AGENT-LOG.md`; `backend/setup.cfg`; `pytest.ini`; `check.sh`.

**Compatibility boundary.** No route, response field, wire format, table or column is
removed. Existing tests may be strengthened but not deleted except where a check is
proved unable to fail. `scenario_*` names, `ONLY`, and `check()` keep working.
`check.sh --fast` stays under its 180 s ceiling (T8).

**TDD Route.**

```text
TDD Route:
- Mode: auto
- Decision: strict
- Strict authority: project instruction — TEST-STRATEGY.md §8, "no assertion is trusted
  until it has been seen to fail", approved by the user
- Strict signals: migration, persistence, schema, contracts, concurrency, public API,
  and test-infrastructure change in every slice
- Test posture: for a behaviour change, RED first (the failing test exists before the
  fix); for a test added over behaviour that is already correct, falsification — break
  the implementation, observe the named check fail, restore — is the equivalent of RED
  and is mandatory for every new or changed assertion
- Verification: ./check.sh --fast after every slice; ./check.sh --full after slices 1, 5
  and 7 and once at the end (user decision, 2026-09-16); per-assertion falsification log
```

**Change Necessity.**

```text
Change Necessity:
- User-visible need: "when we modify something and it breaks another, the test will catch it"
- No-change / non-code option: insufficient — the recon proved four defects that tests
  alone cannot fix (D1-D4 below), and three slices cannot be tested at all without a
  small production change
- Why code change is necessary: the defects are real behaviour, not missing assertions
- Minimum change boundary: db.py, practice/schema.py, generator.py, config.py,
  repertoire/importer.py, practice/store.py + practice/api.py, frontend/src/lib (3
  no-op refactors), frontend tsconfig + package.json, and 3 test-facing Svelte
  attributes; everything else is tests
- Decision: code-change
```

**Existence Check.** No new owner or subsystem is created. New test files own new test
kinds (`test_migration_upgrade.py`, `test_music_invariants.py`, `test_contracts.py`,
`test_seams.py`, `test_concurrency.py`, `test_config_env.py`, `test_scale.py`,
`test_faults.py`, `test_transactions.py`, three pure frontend modules, browser
scenarios). Each refactor is a move of existing logic to an owner file, not a new
responsibility. `@types/node` (Slice 6) is a types-only devDependency and is the one
addition beyond `TEST-STRATEGY.md` §5; recorded in Risks.

---

## Recon findings that changed the plan

Seven read-only slice briefs were produced before any edit (2026-09-16). Four defects
and three corrections came out of them; each is owned by exactly one slice.

| # | Finding | Owner | Resolution |
| --- | --- | --- | --- |
| D1 | `practice/schema.py:162` adds `segments.workout_id` with no `REFERENCES`, while the CREATE at `:118` has `ON DELETE SET NULL`. On any upgraded database, deleting a workout leaves a dangling `segments.workout_id`; fresh databases are correct. Proved in memory: upgraded FK set lacks `workout_id`. | Slice 1 | Fix the `ADDED_COLUMNS` string; the fresh-vs-upgraded parity test is what catches it. Existing databases already have the column and are skipped by `migrate` — retro-fixing them needs a table rebuild, which is a separate decision (recorded, not taken). |
| D2 | The "diatonic" invariant fails on today's code: 589 non-diatonic notes in 357 exercises at accidentals level 1, which `skills_data.py:142-147` promises is diatonic-only. Sources: `_inner_voice_events`' `base_midi - 7` (`generator.py:265`) and the `+3/+4` chord third (`generator.py:376`). | Slice 2 | The invariant is the deliverable, so the generator is fixed in the smallest way that makes the property true, proven by the property failing first. If the fix is not small and safe, the property is scoped to the level range that does hold and the finding is recorded unresolved rather than silently scoped. |
| D3 | An unreadable legacy database (non-SQLite file, permission denied) is unmapped: `importer._open_source` catches only `OperationalError`, raises `DatabaseError` at `SELECT COUNT(*)`, and the route 500s. It also leaks the connection opened at `:55`. | Slice 5 | Named `LegacyDatabaseUnreadable`, mapped to 422 beside `LegacySchemaUnexpected`; connection closed on the failure path. |
| D4 | `SRT_SELECTION_WINDOW` (`config.py:91`) has no reader anywhere in `app/`. | Slice 5 | Recorded in the retirement inventory; **not deleted** (Appendix rule: deletion is a separate decision). Excluded from the env matrix, because a non-default test for it would exercise nothing. |
| D5 | `--full` never runs `slow`-marked tests: `check.sh:37` applies `-m "not slow"` in both tiers, and no test is marked `slow` today. Marking a property `slow` for the 180 s budget would make it run in neither tier. | Slice 2 | `--full` runs the slow tests; `SRT_TIER` distinguishes the tiers inside pytest. |
| D6 | `.hypothesis/` is not gitignored, which breaks `falsify.sh`'s clean-tree precondition after the first property run. | Slice 2 | Add to `.gitignore`. |
| D7 | Two `TEST-STRATEGY.md` claims are wrong about the code: §1.2's "`repertoire/store.py` … with no transaction wrapper at all" (the upload path *is* wrapped at `repertoire/api.py:407-442`; the real gap is that the file write is not transactional), and §3's "migration" step in `--full` (`check.sh` has none — migration tests are ordinary pytest and must not be marked `slow`). | Slice 1 | Correct the two sentences in `TEST-STRATEGY.md` as part of Slice 1's doc work. |

Two further decisions taken from the briefs:

- **Slice 6's Node constraint.** Node 26 is strip-only: parameter properties in
  `liveMatch.ts`, `score.ts` and `api.ts` make those modules unloadable by `node --test`,
  so removing them is a prerequisite, not a nicety. `@types/node` is authorised as a
  types-only devDependency; if it cannot be installed, the `svelte-check` half of the
  slice is deferred and the rest still lands.
- **Slice 3's PATCH deviation.** `PATCH /api/practice/segments/{id}` (`AssignRequest`)
  treats an omitted `piece_id` as a clear, unlike the four repertoire PATCH routes which
  honour `exclude_unset`. Slice 3 pins the **actual** semantics with an explicit comment
  naming the deviation; changing it is a behaviour change the strategy does not
  authorise, so it is recorded, not fixed. `MediaOut.kind` gains
  `Literal["audio","video","score"]` (output-only validation; no accepted input changes)
  so the closed set is real rather than aspirational.

---

## Ownership of shared files

One writer at a time; slices run in order, so no two slices edit a file concurrently.

| File | Slices that touch it | Rule |
| --- | --- | --- |
| `backend/tests/conftest.py` | 2 (hypothesis profile), 3 (`lan` fixture), 5 (nothing new) | Slice 2 appends the profile block; Slice 3 appends the `lan` fixture after the `client` fixture. Neither restructures `client`. |
| `backend/tests/test_backup.py` | 1 (shape compatibility, atomicity), 2 (round-trip property), 4 (`tomorrow` table test) | Appends only, by the slice that owns the relevant invariant. |
| `check.sh` | 2 (`SRT_TIER`, slow tests in `--full`) | Slice 2 only. |
| `.gitignore` | 2 (`.hypothesis/`) | Slice 2 only. |
| `db.py` | 1 (`json_load`, `user_version`), 5 (`BEGIN IMMEDIATE`) | Slice 1 first, Slice 5 second. |
| `frontend/src/lib/*` | 6 (refactors + tests), 7 (reads `eventTimeMs`/Metronome behaviour) | Slice 6 lands the extractions before Slice 7's timing assertions, and keeps the Metronome public API and `eventTimeMs`'s 5000 ms window byte-identical. |
| `repertoire/api.py`, `practice/api.py` | 3 (contract assertions), 5 (error mapping, clock seams) | Slice 3 is test-only there; Slice 5 owns the production edits. |
| `docs/TEST-STRATEGY.md` | 1 (D7 corrections), 2 (mutation work-queue progress), 8 (the guide) | Small targeted edits, named per slice. |
| `AGENT-LOG.md` | every slice | One dated entry per slice, appended. |

**Slice 0's precedent for falsification.** `backend/tools/falsify.sh` refuses a dirty
tree and reverts with `git checkout -- .`, so each slice is committed **before** its
break scripts run, and the break scripts are committed afterwards. A check that passes
with its break applied is deleted, not kept.

---

## Execution Readiness View

```text
- Intent Lock: complete TEST-STRATEGY.md slices 1-7, then slice 8
- Scope Fence: backend/app/{db.py,practice/,repertoire/,music/generator.py,config.py,services.py},
  backend/tests/**, backend/tools/{falsify.sh,falsifications/,e2e_browser.py},
  frontend/src/lib/**, frontend/src/components/{ResultsPanel,PracticeView}.svelte,
  frontend/{tsconfig.json,package.json}, frontend/src/app.css, check.sh, .gitignore,
  docs/**, AGENT-LOG.md
- Baseline Lock: TEST-STRATEGY.md §1-§8 and PLAN-SLICE0.md, approved by the user
- Approved Behavior: slices 1-7 as written in §4; slices 6-7 may add 3 test-facing
  Svelte attributes; ROUTE/SHAPE/COLUMN REMOVALS ARE OUT OF SCOPE
- Owner / Contract Constraints: scenario_* names, ONLY, check(), falsify.sh semantics,
  the four documented PATCH routes, BACKUP_VERSION = 1
- Compatibility Boundary: check.sh --fast < 180 s; no wire-format change; no table drop
- Retirement Boundary: nothing is deleted in slices 1-7. D4 and the dead
  delete_media still_referenced branch join the Appendix inventory instead.
- Task Batches: 1 migration; 2 invariants; 3 contracts; 4 seams; 5 non-functional;
  6 frontend; 7 browser; 8 the guide
- Test Obligations: every new assertion falsified by name; check.sh --fast green per
  slice; check.sh --full green for 1, 5, 7 and at the end
- Review Gates: per slice — implementer, independent spec-compliance review,
  independent code-quality review, coordinator-run tier, then commit
- Drift / Rewind Rules: a slice that needs a production change outside its named
  boundary stops and returns here; a property that is red against correct-by-spec code
  becomes D2-style finding plus decision, never a silently weakened assertion
- Evidence Required: per-slice falsification log, tier output, AGENT-LOG entry,
  mutation survivor movement for the modules a slice targets
- Advisory Boundary: method-pack execution guidance only; not completion authority
```

```text
Execution Route:
- Decision: subagent-driven, sequential across slices
- Evidence: the seven slices share one working tree, one check.sh, one SQLite test
  database and one git history. subagent-driven-development forbids parallel
  implementers on a shared workspace, and dispatching-parallel-agents excludes shared
  state. Recon (read-only) was fanned out 7-wide because it writes nothing; execution
  is serialised because it does.
- Fallback: inline if a slice's implementer is blocked twice on the same condition
- User confirmation required: no — route, gate depth and cadence were confirmed
  2026-09-16: slice 8 last; --fast per slice with --full for 1, 5, 7 and at the end;
  unattended with one commit per slice.
```

---

## Slice 1 — Persistence and migration

**Gate:** `./check.sh --fast` then `./check.sh --full`. **Owner:** backend persistence.

**Ships.** Frozen pre-Phase-18 SQL fixture + upgrade test; `ADDED_COLUMNS` executed for
practice and repertoire; the `init_db` ordering contract asserted; `PRAGMA user_version`;
backup shape-compatibility; interrupted work (rollback + WAL); corrupt JSON raises.

**Tasks.**

1. `backend/tests/fixtures/pre_phase18_practice.sql` + `backend/tests/test_migration_upgrade.py`:
   the fixture is the CREATE scripts minus exactly the `ADDED_COLUMNS` columns, with the
   old-shape `identification_outcomes` (`segment_id NOT NULL … ON DELETE CASCADE`) and
   old-shape `performances` (no `workout_id`), one row per table. The test asserts the
   fixture's *pre* shape (so a later "fix the fixture" edit fails), runs `db.init_db`,
   then asserts no rows lost and the outcome row survived with its `segment_id`.
2. **D1 fix** — `("segments", "workout_id", "INTEGER REFERENCES workouts(id) ON DELETE SET NULL")`
   — plus a frozen `EXPECTED_COLUMNS` per table asserted against a **fresh empty**
   database. This is the only assertion that can catch a deleted `ADDED_COLUMNS` entry,
   because a comparison derived from the tuple itself is tautological. Assert upgraded ⊇
   fresh for columns and indexes, **sets not order** (ALTER appends).
3. `PRAGMA user_version` — `SCHEMA_VERSION` constant, written last in `init_db` (SQLite
   rejects a bound parameter there), and a refusal when the database is newer than the
   code (the missing downgrade guard). Test: fresh reports current; the fixture reports 0
   before and current after.
4. **Behaviour change (T9).** `db.json_load`'s malformed branch raises `CorruptJSON`
   (a `ValueError`) naming the damage, truncated; the empty/`None` branch still returns
   the default; `TypeError` still means damage. One `@app.exception_handler(CorruptJSON)`
   returns a documented 500 rather than a bare Starlette traceback. Tests for both the
   corrupt and the empty case. Callers affected: `get_exercise`, `performance_detail`,
   `onset_bias_ms`, `_common_mistakes` (all enumerated in the recon brief).
5. Backup compatibility: a hand-written v1 document in the *old shape* imports, keeps
   `duration_s`, leaves `pedal_changes` NULL, and counts. `BACKUP_VERSION` is **not**
   bumped; the guarantee is one-directional (fewer columns fine, unknown refused).
6. Interrupted work: an import that fails mid-insert leaves every table unchanged (the
   first execution of `db.transaction`'s `ROLLBACK`); a `BEGIN`+insert+`close()` without
   COMMIT leaves no row and a readable database; `journal_mode == 'wal'` and
   `wal_checkpoint(TRUNCATE)` succeeds (`DEPLOYMENT.md:158-181`).
7. **D7** corrections to `TEST-STRATEGY.md` §1.2 and §3; `docs/PLAN-SLICE1.md`;
   `AGENT-LOG.md` entry; falsification scripts.

**Acceptance.** Deleting any `ADDED_COLUMNS` entry, or reordering `init_db`, fails
`--fast`. Falsification: delete an entry; move `migrate_practice` after `PRACTICE_SCHEMA`;
move `migrate_workouts` above `SCHEMA`; restore `return default` in `json_load`; drop the
outcome-rebuild `INSERT … SELECT`; delete `idx_sittings_legacy`; delete the
`user_version` write; `journal_mode = DELETE`; unwrap the backup transaction.

---

## Slice 2 — Invariants

**Gate:** `./check.sh --fast`. **Owner:** backend music/scoring/practice + frontend
playback properties.

**Ships.** `hypothesis` properties over the claimed domains, with the articulation
finding fixed at its owner, and the tier plumbing that makes a fixed seed possible.

**Tasks.**

1. Tier plumbing — **D5/D6**: register `srt-fast` (`deadline=None`, `max_examples≈30`)
   and `srt-full` (`derandomize=True`, `deadline=None`, `max_examples≈100`,
   `database=None`) in `conftest.py` and `load_profile` from `SRT_TIER`; `check.sh`
   exports `SRT_TIER` and `--full` **runs the slow tests**; `.gitignore` gains
   `backend/.hypothesis/`. `deadline=None` is mandatory — music21 export trips the
   200 ms default.
2. **D2** — `tests/test_music_invariants.py`: catalogue meter/register/diatonic over
   random meter × key × chord × span × seed; generator bar-fill and inner-voice
   sum-to-bar; the diatonic property at accidentals level 1 **fails first**, then the
   minimal fix in `_inner_voice_events` and the chord third makes it pass with the rest
   of the suite still green. If the fix is not small and safe, scope the property and
   record the finding unresolved.
3. Articulation — assert slur / dynamic / hairpin presence from the score graph exactly
   when the level's params request them, and replace the three `except Exception: pass`
   (`generator.py:225,234,243`) with a re-raise so a swallowed insertion is a hard error
   rather than a silently absent mark. Melody part only: the bass is capped at level 3.
4. Determinism over random level dicts; selector monotonicity and the whole-range ladder
   property (pins Phase 16 so re-anchoring `elo_base` must break it); `sessionize`
   batch ≡ incremental over random streams; scores bounded by their parts; backup
   round-trip stability and idempotence.
5. Frontend `playback.property.test.ts` with a tiny seeded LCG (`SRT_SEED`, fixed under
   `SRT_TIER=full`): `sustained` never shortens, `resolveOverlaps` never overlaps and is
   idempotent.

**Acceptance.** Each property is shown to fail against a deliberately-broken
implementation, with the break named in its docstring; `--full` uses a fixed seed and a
failure prints its minimal example; `--fast` stays under 180 s (backend ≈54 s today;
the recon estimates ≈5-10 s for the property set at 30 examples — measure, do not
assume). Mutation targets: `x_free_line` 62, `x_countermelody` 30,
`x__inner_voice_events` 22, `x_canon` 19, `app.config` 30.

---

## Slice 3 — Contracts

**Gate:** `./check.sh --fast`. **Owner:** API surface.

**Ships.** Route inventory, response-schema snapshot, OpenAPI snapshot, status-code
matrix with 403 for all seven irreversible routes, PATCH contract, closed-set
rejection with provenance, `PRAGMA foreign_keys` orphan rejection.

**Tasks.**

1. `lan` fixture appended after `client` in `conftest.py`: re-patches
   `hostinfo.is_loopback` to False and restores it in `finally`. `client` is untouched.
2. Route inventory in `backend/tests/test_contracts.py`: the exact `(method, path)` set,
   so adding a route without declaring its status codes fails `--fast`.
3. Status matrix + the three missing 403s (`DELETE /composers/{id}`,
   `DELETE /journal/{entry_id}`, `DELETE /media/{media_id}`), plus the conditional
   guards (`resegment?confirm=true`, `backup/import?mode=replace`) — arbitrary ids work
   because route-level dependencies are solved before path params.
4. Response-schema snapshot (`backend/tests/contracts/response_schema.json`): built from
   `response_model.model_fields`, compared as a **subset** — every snapshot field must
   exist with an equal type, extra live fields ignored, a removed or renamed field fails,
   a type change fails. Deliberate regeneration via `SRT_UPDATE_CONTRACTS=1`, which
   prints a diff.
5. OpenAPI snapshot compared with **exact equality** (intentionally stricter than the
   response snapshot: §4 wants any shape change to force a visible regeneration). Built
   from `app.openapi()` directly — no network, milliseconds.
6. PATCH contract over the five routes: unset leaves alone, explicit null clears, `{}`
   rejected — with the `AssignRequest` deviation pinned and named (see decisions above).
7. Closed-set rejection: `PracticeSource` (Pydantic), media `kind` as a real
   `Literal["audio","video","score"]` plus a produced-value inventory, upload refusals
   from `score_format`/`probe`, and the backup document refusal asserted to come from
   `_validate`/`_insert` (a `str` detail, not a Pydantic list).
8. `PRAGMA foreign_keys == 1` and a real orphan insert rejected with `IntegrityError`.
   The FK inventory and mode table are **Slice 4's** `_live_fks`/`FK_COVERAGE`; Slice 3
   imports them rather than declaring a second mode table (which is why Slice 4 runs
   first for this pair).
9. Falsification scripts: remove a response field; add a route; drop a loopback guard;
   replace `exclude_unset` with `model_dump`; widen `PracticeSource`; rename an OpenAPI
   field; remove `PRAGMA foreign_keys = ON`.

**Acceptance.** Removing a field from any response model, or adding a route without a
declared status-code expectation, fails `--fast`.

---

## Slice 4 — Seams

**Gate:** `./check.sh --fast`. **Owner:** referential integrity and cascade semantics.

**Ships.** One test per FK: happy path plus what happens when the parent is deleted;
the FK inventory check; the backup table-list derivation test.

**Tasks.**

1. `backend/tests/test_seams.py` with local helpers. Raw `DELETE`s (there is no
   application delete route for a sitting or a workout) with `foreign_keys` ON.
2. Delete semantics per seam: piece → segments (`SET NULL`, history and measured minutes
   survive, piece minutes drop to 0); piece → journal/media (CASCADE, **exact file set
   unchanged**); sitting → journal (`SET NULL`, prose survives) and sitting → everything
   else (CASCADE); workout → performances (`SET NULL`, attempts survive) and workout →
   segments; composer → pieces; user/skill/exercise/performance/segment cascades and
   `rating_events.performance_id → SET NULL`.
3. `bridge.DIFFICULTY_LEVELS` sweep: every label maps to a legal level in
   `skills_data.LEVELS`, and every label round-trips.
4. Cross-domain minutes: a piece's measured minutes equal the sum of its own segments'
   `duration_s`, computed from `/api/practice/sittings/…`.
5. **Backup ↔ schema**: create a table at runtime and require it in the export. A
   hand-written list can never contain it, which is the honest form of "the list comes
   from `sqlite_master`" (the existing test derives its expectation from the function
   under test and cannot fail).
6. Inventory check: `FK_COVERAGE` maps every live `(child, column)` to
   `(parent, on_delete, covering test nodeid)`, read from `PRAGMA foreign_key_list` over
   the tables in `sqlite_master`; a new FK with no covering test fails `--fast`, and a
   map entry whose covering test is not collected fails too.
7. Falsification scripts: `SET NULL → CASCADE` for each seam; unlink removed in
   `delete_media`; `virtuoso → 11`; truncate in `_minutes`; replace the `table_names`
   query with a literal list.

**Acceptance.** A new foreign key added without a test fails the slice's own inventory
check. (The dead `still_referenced` branch in `repertoire/store.py` is recorded for the
Appendix, not tested — it cannot be reached given `media.file_name UNIQUE`.)

---

## Slice 5 — Non-functional

**Gate:** `./check.sh --fast` then `./check.sh --full`. **Owner:** concurrency, config,
scale, faults, clock.

**Ships.** The deferred-`BEGIN` question settled; environment plumbing; scale canaries;
fault injection; transaction rollback; clock seams; the duplicated owners pinned (not
retired).

**Tasks.**

1. **`BEGIN IMMEDIATE`** at `db.py:152`. A deterministic two-writer reproduction (two
   threads, two connections, events rather than sleeps) is written first and must fail
   against deferred `BEGIN` with `SQLITE_BUSY_SNAPSHOT` before the fix. A retry is
   rejected on structure: `with db.transaction()` cannot re-execute the caller's body, so
   a retry would touch all 36 call sites; every caller is a write path. Also assert a
   connection is never used from two threads.
2. Config errors: `_env_int`/`_env_float` raise a named `ConfigError` naming the variable
   and the raw value instead of a bare `ValueError` at import.
3. Env matrix: one subprocess sets every numeric `SRT_*` knob to a non-default and
   asserts the singleton (the class-body defaults are frozen, so `Settings()` cannot
   re-read the environment and `dataclasses.replace` only tests a consumer's global);
   one knob proven to change behaviour; one malformed value proven to fail loudly.
   `SRT_SELECTION_WINDOW` is excluded (D4).
4. Scale canaries: `identification_quality` (exact `compare` call count at 450 labelled
   segments; wall-clock bound behind `@pytest.mark.slow`), `_notes_for_segments`
   (SELECT count = one per sitting), `export_document` (one SELECT per table),
   `list_pieces` (one statement). Counters in `--fast`, timings in `slow`.
5. Fault injection: missing media file → 410; absent ffmpeg → 422 (falsifies the
   `# pragma: no cover` branch); truncated/empty upload → 422; **D3** unreadable legacy
   DB → 422 not 500, with the leaked connection closed; the `immutable=1` fallback URI.
   Corrupt JSON is **Slice 1's**; not re-owned here.
6. Transaction rollback: a failing transaction leaves the database unchanged. The
   recon's finding is recorded — `ROLLBACK` alone is likely unfalsifiable because
   `close()` also rolls back, so the break that must fail the test is `ROLLBACK → COMMIT`
   or dropping the re-raise, and the docstring names it.
7. Clock seams: `today` on `store._today` threaded through its five readers, and
   `now_ms` on the two routes that hide it. The five-minute gap and the 1.5 s close
   window already accept `now_ms` — no clock abstraction, no freezegun.
8. Duplicated owners: pin the *documented divergence* between `services._streak_days`
   and `practice/store.streak_days`, and between `services._local_day` and
   `local_date`. **No retirement** — the Appendix says deletion is its own decision.

---

## Slice 6 — Frontend depth

**Gate:** `./check.sh --fast`. **Owner:** frontend pure modules.

**Ships.** Tests for the untested pure modules; three extractions for testability;
`svelte-check` over the tests.

**Tasks.**

1. Remove parameter properties from `liveMatch.ts:22-26`, `score.ts:157`,
   `api.ts:53-58` (Node 26 is strip-only; today those modules cannot load at all).
   Behaviour identical; the probe is that `node -e "import('./src/lib/liveMatch.ts')"`
   resolves.
2. `liveMatch.test.ts` — window boundaries, claimed-never-rematched, wrong_pitch, extra,
   progress, `isComplete`, `finalSnapshot` fills unclaimed as missed.
3. `score.test.ts` colour helpers + `types.test.ts` formatters (`midiToName` octave
   edges, `formatDuration`/`formatSize`/`formatMinutes` boundaries).
4. `api.test.ts` (`ApiError` fields and `name`) + `playback.test.ts` additions
   (`firstOnset`, `fromTime`).
5. Extraction A: `metronomePlan.ts` (`buildSchedule`, zero imports) + tests; `metronome.ts`
   re-exports `MetronomePlan` and keeps its public API byte-identical.
6. Extraction B: `midiSchedule.ts` (`midiEventsFor`, `dueCount`, `import type` only) +
   tests; `pianoPlayer.ts` rewired with identical side effects.
7. Extraction C: `midiMessage.ts` (`decodeMidi`, `eventTimeMs`, zero value imports — the
   caller keeps the `>= PEDAL_DOWN` threshold) + tests; `midi.ts` rewired.
8. `tsconfig.json` stops excluding tests, gains `noEmit` + `allowImportingTsExtensions`;
   `@types/node` added as a devDependency. If TS2307 persists with explicit `types`,
   append `"node"` and watch for DOM/Node `setTimeout` collisions. If the dependency
   cannot be installed, defer this task alone and record it.

**Falsification.** Per file, mutate the source, watch the named test fail, restore —
the exact breaks (window arithmetic, colour constants, `padStart`, `toFixed`,
`Math.round`, velocity clamps, CC64 detection, the 5000 ms window, `dueCount` `<=`)
are listed in the recon brief. tsconfig proof: a deliberate type error in a test file
must make `npm run check` red (today it is silent).

---

## Slice 7 — Browser reach

**Gate:** `./check.sh --fast` then `./check.sh --full`. **Owner:** the browser harness.

**Ships.** Keyboard navigation and focus order; accessibility assertions; failure
injection via `page.route`; timing injection in the fake MIDI.

**Tasks.**

1. Fake-MIDI timing hook: `send(bytes, portId, atMs)` threads an explicit `timeStamp`,
   and `PLAY_TIMED` lets the stamp differ from the emission instant. Existing arities
   keep working; `run_e2e.sh perfect` must still pass unchanged.
2. New `scenario_midi_timing`: late notes shift the measured timing bias while pitch
   stays correct, a real-clock control reads ≈0, and out-of-order notes persist by
   timestamp, not send order. (A same-port duplicate is flagged as an open design
   question, not asserted.)
3. Keyboard and focus order: Tab-walk the shell, assert the Practice tab is first and
   `aria-current`, Enter activates the Log tab, the Focus toggle flips
   `documentElement.dataset.focus`, and `[data-strip]` ArrowRight moves
   `aria-valuenow` by 5.
4. Reduced motion: `page.emulate_media(reduced_motion="reduce")` collapses the beat
   pulse's transition, with a `no-preference` control. No production change —
   `app.css:345-350` already implements it; the slice certifies it.
5. Accessibility production change: `ResultsPanel`'s root becomes
   `role="status" aria-live="polite"` (the ROADMAP item), asserted after a scored run.
   The error banner and the metronome region get their roles only if the assertions can
   observe them; both are named in the recon.
6. New `scenario_failure_injection`: `/api/health` aborted → the offline banner and
   Retry recovery; a 500 on `/api/exercise/next` with `allow_statuses={500}`; a
   malformed 200 body that must be caught with `check(not errors)`.
7. Every new scenario passes alone under `ONLY`, and `reset_all`'s coverage assertion
   still holds.

---

## Slice 8 — `docs/TESTING.md`

Written last. The decision procedure ("what did I change → which tier of test is
owed"), one worked recipe per test kind taken from this repository, the falsification
rule as step one of every recipe, the fixture inventory, and the anti-patterns this
project has actually hit — each with the real example from `TEST-STRATEGY.md` §1.1 and
from the slices above (including the new findings D1-D7).

---

## Risks

1. **`--fast` budget.** Backend ≈54 s plus property tests, contracts, seams and
   non-functional tests must stay under 180 s with the frontend, typecheck and build.
   Mitigation: counters not timings in `--fast`; timings behind the `slow` marker; and
   D5 makes `--full` actually run them. Measure per step; move to `--full` by naming the
   risk, never by raising 180 (T8).
2. **`@types/node`.** One devDependency beyond §5. Types-only, no runtime. Fallback:
   defer the `svelte-check`-over-tests task.
3. **D2's blast radius.** Fixing the generator's diatonic violation changes generated
   music, which the browser scenarios score. If it breaks `scenario_perfect`'s
   `score >= 95` or existing accidental-count tests, scope the property and record the
   finding rather than forcing the fix.
4. **Extraction C** (`midi.handleMessage`) has no unit test today; only the browser e2e
   guards it. It lands before Slice 7 and is verified by `--full` there.
5. **Concurrency test flakiness.** The two-writer reproduction is event-ordered, not
   time-ordered; if it proves flaky it is a bug in the test, not a reason to weaken it.
6. **Mutation score is a report.** The survivors are the work queue; no gate is added in
   these slices (T3).
7. **Doc corrections.** D7 changes two sentences of the governing document; both are
   corrections toward what the code does, recorded here and in `AGENT-LOG.md`.

## Retirement boundary

Nothing is deleted in slices 1-7. `SRT_SELECTION_WINDOW` (D4), the unreachable
`delete_media` `still_referenced` branch, and the nine dead functions from the Appendix
join the retirement inventory with their evidence. Deleting any of them is a separate
decision.
