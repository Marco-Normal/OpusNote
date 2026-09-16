# Plan — Slice 1: persistence and migration

**Status: landed.** All ten tasks addressed; three deviations and five findings are recorded
below. `./check.sh --fast` passes in **62-65 s** across two runs against the 180 s ceiling; the
backend suite is **835 passing** (was 813).

The audit's top-ranked risk was the one code path that runs on the player's real database and
had never executed: `practice/schema.py`'s `ADDED_COLUMNS` loop and `repertoire/schema.py`'s.
There is now a frozen pre-Phase-18 database in the repository, an upgrade test that walks it to
the current shape, a schema version the app writes and refuses to go backwards past, a corrupt
JSON row that fails loudly, and an import that fails halfway leaving every table exactly as it
was. The slice's acceptance criterion holds: deleting any `ADDED_COLUMNS` entry, or reordering
`init_db`, fails the fast tier — each proved by a break script.

**Superseded by:** the remaining slices of [`TEST-STRATEGY.md`](./TEST-STRATEGY.md).

**Parent spec:** [`TEST-STRATEGY.md`](./TEST-STRATEGY.md) §1.2, §1.4, §4 Slice 1, §7 (T6, T9),
§8; [`PLAN-SLICES1-7.md`](./PLAN-SLICES1-7.md) § Slice 1 and its D1/D7 findings.

**Goal:** make the migration path, the persisted-JSON contract and interrupted work observable
in the tier that runs after every edit — without changing any route, column, table or wire
format, and without bumping `BACKUP_VERSION`.

**Files.**

- create `backend/tests/fixtures/pre_phase18_practice.sql` (frozen old-schema fixture, SQL)
- create `backend/tests/test_migration_upgrade.py`
- create `backend/tests/test_json_load.py`
- create `backend/tools/falsifications/` — thirteen break scripts (twelve named in the slice
  brief, plus one for the D1 reference)
- modify `backend/app/db.py` (`SCHEMA_VERSION`, `SchemaTooNew`, `CorruptJSON`, `json_load`)
- modify `backend/app/main.py` (one `@app.exception_handler(CorruptJSON)`)
- modify `backend/app/practice/schema.py` (the D1 `ADDED_COLUMNS` type string)
- modify `backend/tests/test_backup.py` (append: shape compatibility, import atomicity)
- modify `backend/tests/test_repertoire.py` (extend the migration test to all 7 entries)
- modify `docs/TEST-STRATEGY.md` (the two D7 corrections)
- append `AGENT-LOG.md`

```text
TDD Route:
- Mode: auto
- Decision: strict
- Strict authority: TEST-STRATEGY.md §8, "no assertion is trusted until it has been seen to
  fail", approved by the user
- Strict signals: migration, persistence, schema, contracts and a public behaviour change
- Test posture: RED first for the two behaviour changes (`CorruptJSON`, `user_version`); for
  tests added over already-correct behaviour, a break applied, the named check observed to
  fail, and the tree restored — 28 breaks, all falsified
- Verification: ./check.sh --fast (62 s); ./check.sh --full is the coordinator's
```

```text
Change Necessity:
- User-visible need: "when we modify something and it breaks another, the test will catch it"
- No-change option: insufficient — D1 is a real defect (an upgraded database lacks the
  `segments.workout_id` foreign key) and T9 is a decided behaviour change
- Why code change is necessary: a test cannot add a missing REFERENCES clause or make a
  corrupt row visible
- Minimum change boundary: db.py, main.py, practice/schema.py, tests, falsifications, docs
- Decision: code-change
```

---

## Task 1-2 — The frozen fixture, the upgrade test, and D1

**Landed.** `pre_phase18_practice.sql` is the four CREATE scripts minus exactly the
`ADDED_COLUMNS` columns: seven-column `segment_metrics`, the `NOT NULL ... ON DELETE CASCADE`
outcome reference, no `piece_journal.sitting_id`, no `performances.workout_id`, no
`legacy_id`/`loop_*` anywhere, and the partial `legacy_id` indexes absent with the column. One
row per table (18), including one outcome row and one seven-column metrics row.

`test_migration_upgrade.py` asserts the *pre* shape first, so a later "fix the fixture" edit
fails rather than quietly deleting the coverage; then upgrades it in place and asserts every
table's row count unchanged, the outcome row surviving with the same `segment_id` and score,
`segment_metrics.duration_s` intact and `pedal_changes` NULL on the old row, `user_version`
moving 0 → `SCHEMA_VERSION`, `migrate(...) == []` for both domains, and a second `init_db` a
no-op. The `upgraded ⊇ fresh` comparison is over **sets** (ALTER appends; `sittings` and
`segments` legitimately end up in a different order).

**D1 fixed.** `("segments", "workout_id", "INTEGER")` becomes
`("segments", "workout_id", "INTEGER REFERENCES workouts(id) ON DELETE SET NULL")`. SQLite
accepts the reference on `ADD COLUMN` because the default is NULL, exactly as
`repertoire/schema.py:112` already does for `piece_journal.sitting_id`.

**Deviation 1 — the parity test needed foreign keys.** The recon said "the fresh-vs-upgraded
parity test is what catches it". Comparing column names does **not** catch D1: the column is
present either way; only the reference is missing. The parity comparison therefore includes
`PRAGMA foreign_key_list`, and a focused
`test_the_upgraded_segments_workout_reference_is_kept` proves the reference works (deleting the
workout clears the column rather than dangling).

**Deviation 2 — a frozen index literal was necessary.** `upgraded ⊇ fresh` compares indexes
too, but when `idx_sittings_legacy` is deleted from the CREATE script it is absent from *both*
sides, so the comparison agrees and notices nothing. `EXPECTED_INDEXES` is a second frozen
literal, asserted against the fresh database; it is what makes the mandated
`drop_sittings_legacy_index.sh` break fail.

**Tautology trap avoided.** Both frozen literals are written down, never derived from
`ADDED_COLUMNS`. The twelve entries across the three domains are each covered: deleting a
practice entry fails the parity comparison, deleting a repertoire entry fails both the parity
comparison and the extended `test_repertoire.py` migration test, and deleting the workout entry
fails the frozen `EXPECTED_COLUMNS` for `performances` because that column exists **only** in
`workout/schema.py`'s `ADDED_COLUMNS` — `db.py`'s `performances` CREATE has no such column.

**Recorded, not taken: retro-fixing an already-upgraded database.** A database that already has
`segments.workout_id` created by the old type string is skipped by `migrate` (the column
exists), so it keeps the missing reference. Repairing it needs a table rebuild, which is a
separate decision with its own risk; nothing in this slice attempts it. Fresh databases and
databases upgraded from here on are correct.

**Files:** the fixture and `test_migration_upgrade.py`; `practice/schema.py`.
**Verification:** `pytest tests/test_migration_upgrade.py -q` → 11 passed.

## Task 3 — Every repertoire `ADDED_COLUMNS` entry exercised

**Landed.** `test_migration_adds_legacy_id_to_an_existing_database` (which already rebuilt an
old-shape library and re-ran `init_db`) now asserts a frozen map covering all seven entries:
`composers.legacy_id`, `pieces.legacy_id`, `piece_journal.{legacy_id,sitting_id}` and
`media.{legacy_id,loop_start_s,loop_end_s}`. The assertion is a literal, not a walk over
`ADDED_COLUMNS` — a deleted entry leaves the loop, so an iteration could not fail.

**Verification:** `pytest tests/test_repertoire.py -q -k migration` → 2 passed;
`drop_repertoire_added_column.sh` names the missing `media.loop_end_s`.

## Task 4 — `PRAGMA user_version`

**Landed.** `db.SCHEMA_VERSION = 1` beside `SCHEMA`; `init_db` reads the database's version
first and raises the new `db.SchemaTooNew` when it is greater than the code's (the missing
downgrade guard — a newer schema may have reshaped a column this build would misread), then
writes `PRAGMA user_version = {SCHEMA_VERSION}` **last**, as an f-string because SQLite rejects
a bound parameter in a PRAGMA. Tests: a fresh database reports 1; the frozen fixture reports 0
before and 1 after; a database stamped 2 is refused.

**Finding — the refusal surfaces at startup.** `init_db` is called from the FastAPI lifespan,
so a database from a newer build now makes the server refuse to start instead of reading a
shape it does not know. That is the intent, but it is a startup-visible behaviour change and is
recorded here for the operator-facing docs.

**Verification:** `pytest tests/test_migration_upgrade.py -q -k "version or newer"` →
`drop_user_version_write.sh` fails with `assert 0 == 1`.

## Task 5 — Corrupt JSON raises (T9)

**Landed.** `db.json_load`'s malformed branch raises `db.CorruptJSON(ValueError)`, naming the
raw value truncated to 120 characters; the empty/`None` branch still returns the default
(positive control); `TypeError` (a non-text value) is still damage. `main.py` gains one
`@app.exception_handler(CorruptJSON)` returning a documented 500 whose `detail` names the
damage, so the failure is legible instead of a bare Starlette traceback.

`test_json_load.py` covers the function's three branches and then drives **every** call site's
route on valid data: `/api/exercise/{id}` (`store.get_exercise`, both JSON columns),
`/api/performances/{id}` (`store.performance_detail`, four), `/api/stats`
(`services._common_mistakes`) and `/api/status/system` (`store.onset_bias_ms`). The 500 is
asserted through `TestClient(..., raise_server_exceptions=False)`.

**Finding — the blast radius is the decision.** A single corrupt row now fails the request that
reads it. That is what T9 chose ("visible at the piano, not three weeks later"), but it means
an imported or hand-edited row with bad JSON is a hard error, not a quiet default. No migration
repairs existing corrupt rows; the handler names the row's value so the operator can.

**Verification:** `pytest tests/test_json_load.py -q` → 9 passed.

## Task 6 — Backup shape compatibility

**Landed.** `test_a_v1_document_in_the_old_shape_still_imports` hand-writes a v1 document with a
seven-column `segment_metrics` row, no `pedal_*`, no `piece_journal.sitting_id`, no `legacy_id`,
and no loop points, then imports it through the route. It lands (`total == 6`), `duration_s`
survives, `pedal_changes` and `median_velocity` are NULL, and the journal row keeps its content
with `sitting_id` NULL. `BACKUP_VERSION` is **not** bumped: the guarantee is one-directional —
fewer columns is fine (`backup.py:115`'s intersection), unknown tables and columns are refused
(`:91-96`, `:109-114`), and that refusal is already covered by existing tests.

**Boundary note.** The break script that replaces `backup.table_names`'s `sqlite_master` query
with a literal list uses a *stale* hand list (the MVP's six tables), because a complete literal
list would still pass every Slice 1 test: the existing
`test_an_export_covers_every_table` derives its expectation from the function under test, and
the assertion that a table created at runtime appears in the export is **Slice 4's** task. The
break is caught by the existing subset assertion and the round-trip wipe.

**Verification:** `pytest tests/test_backup.py -q` → 20 passed.

## Task 7 — Interrupted work

**Landed.**

1. **Import atomicity.** `test_an_import_that_fails_mid_insert_changes_nothing` conflicts with
   a NOT NULL during a `replace`-mode import — after every table has been emptied — and asserts
   every table's row count is identical afterwards, with the new `composers` row (written
   before the failure) gone. This executes `db.py`'s `ROLLBACK` for the first time in the
   suite; the error is not caught, because an import that half-happened must surface.
2. **A crash between BEGIN and COMMIT.** A raw `BEGIN`, an insert, and `close()` with no
   COMMIT; the reopened database has no row and passes `PRAGMA integrity_check`. This one
   guards SQLite's rollback-on-close rather than any line of ours, so its falsification is
   test-local (commit before close) and is reported as such.
3. **WAL.** `PRAGMA journal_mode == 'wal'` after `init_db`, and `PRAGMA wal_checkpoint(TRUNCATE)`
   returns `busy == 0` — the two halves `DEPLOYMENT.md:158-181` depends on.

**Verification:** `pytest tests/test_backup.py tests/test_migration_upgrade.py -q -k "fails_mid_insert or without_a_commit or wal"`; `unwrap_backup_transaction.sh` and
`journal_mode_delete.sh` both fail the named check.

## Task 8 — D7 corrections in `TEST-STRATEGY.md`

**Landed.** §1.2's "`repertoire/store.py` … with no transaction wrapper at all" is corrected:
the upload path *is* wrapped (`repertoire/api.py:407-442`, and `media_pipeline.py:213-218`
documents "the caller owns the transaction"); the real gap is that the **file write** is not
transactional, so a rollback can leave a stray file. §3's `--full` row drops "migration", and a
new paragraph states plainly that `check.sh` has no migration step and that migration tests are
ordinary pytest which must not be marked `slow` — marking them would put them in neither tier,
which is exactly how §1.2's missing `user_version` guard survived.

## Task 9 — This document and the log

**Landed.** This file, plus a dated `AGENT-LOG.md` entry in the existing style.

## Task 10 — Falsification scripts

**Landed, thirteen scripts**, each asserting its target text exists before editing, so a moved
line fails the break instead of certifying it:

`drop_practice_added_column.sh`, `drop_repertoire_added_column.sh`,
`drop_workout_added_column.sh`, `drop_segments_workout_reference.sh` (the D1 reference, added
beyond the brief), `migrate_practice_after_schema.sh`, `migrate_workouts_before_schema.sh`,
`drop_outcome_rebuild_insert.sh`, `drop_sittings_legacy_index.sh`, `drop_user_version_write.sh`,
`journal_mode_delete.sh`, `json_load_returns_default.sh`, `unwrap_backup_transaction.sh`,
`literal_backup_table_list.sh`.

`falsify.sh` was **not** run: it refuses a dirty tree and reverts with `git checkout -- .`,
which would discard this slice's uncommitted work. Each break was instead applied from a
snapshot, the focused check observed to fail, the file restored by copy, and the check observed
green again — 31 breaks, 0 not falsified, 0 restore failures. The coordinator runs the scripts
through `falsify.sh` after the commit.

---

## Verification

| Command | Result |
| --- | --- |
| `cd backend && .venv/bin/python -m pytest tests/test_migration_upgrade.py tests/test_json_load.py tests/test_backup.py -q` | 40 passed in 4.07 s |
| `cd backend && .venv/bin/python -m pytest -q -m "not slow"` | 835 passed (57.7-59.8 s across runs; baseline 813) |
| `./check.sh --fast` | passed in **63 s** (three runs: 62 / 65 / 63 s; ceiling 180): backend 58.3 s, frontend 1 s, typecheck 2 s, build <1 s |

**Finding — `check.sh`'s per-step timing is shifted by one, and the first step is never
printed.** `step()` compares `step_start` against the script's `start`, so a second step that
begins in the same second as the first is mistaken for the first and prints nothing; every
later elapsed line is the *previous* step's duration. The backend step's time is therefore never
shown (58-60 s of a 62-65 s run). Pre-existing, and `check.sh` belongs to Slice 2
(`PLAN-SLICES1-7.md`, Ownership of shared files); recorded, not fixed here.

## Falsification

Every new or changed assertion was broken and observed to fail; the full per-case log is in the
AGENT-LOG entry. Representative evidence:

| Assertion | Break | Observed failure |
| --- | --- | --- |
| upgraded ⊇ fresh columns (practice) | delete `segment_metrics.pedal_blur` entry | `upgrading left segment_metrics without ['pedal_blur']` |
| upgraded ⊇ fresh columns (repertoire) | delete `media.loop_end_s` entry | `upgrading left media without ['loop_end_s']` |
| frozen `EXPECTED_COLUMNS` | delete the `performances.workout_id` entry | `performances columns drifted` |
| upgraded FK parity / D1 | restore `"INTEGER"` without REFERENCES | `upgrading left segments without foreign key(s) [('workout_id', 'workouts', 'id', 'SET NULL')]` |
| `init_db` ordering | `migrate_practice` after `PRACTICE_SCHEMA` | `sqlite3.OperationalError: no such column: legacy_id` |
| `init_db` ordering | `migrate_workouts` above `SCHEMA` | `performances columns drifted` |
| no rows lost | drop the outcome-rebuild `INSERT … SELECT` | `the upgrade kept every table's rows` |
| frozen `EXPECTED_INDEXES` | delete `idx_sittings_legacy` | `sittings indexes drifted` |
| `user_version` | delete the write | `assert 0 == 1` |
| WAL | `journal_mode = DELETE` | `assert 'delete' == 'wal'` |
| malformed raises | restore `return default` | `DID NOT RAISE CorruptJSON` |
| import atomicity | unwrap the route's `db.transaction` | `the failed import rolled back every delete and insert` |
| backup table list | replace the `sqlite_master` query with a literal | subset assertion fails |
| fixture stays old | add `user_version`/`workout_id`/nullable outcome | the pre-shape assertions fail |
| `migrate(...) == []` | make either migrate loop non-idempotent | `duplicate column name: legacy_id` |

## Execution Readiness View

```text
- Intent Lock: make the migration path, persisted JSON and interrupted work observable in --fast
- Scope Fence: backend/app/{db.py,main.py,practice/schema.py}, backend/tests/**,
  backend/tools/falsifications/**, docs/TEST-STRATEGY.md, docs/PLAN-SLICE1.md, AGENT-LOG.md
- Baseline Lock: TEST-STRATEGY.md §1.2/§4 Slice 1/§7 T6,T9/§8 and PLAN-SLICES1-7.md, approved
- Approved Behavior: T9 (corrupt JSON raises, one 500 handler); the D1 defect fix; a schema
  version and a downgrade refusal. No route, column, table or wire format removed;
  BACKUP_VERSION unchanged
- Owner / Contract Constraints: falsify.sh semantics, BACKUP_VERSION = 1, the four documented
  PATCH routes, scenario_* names
- Compatibility Boundary: no route or response field changes; older-shape backup documents
  still import; migration tests stay in --fast and are never marked slow
- Retirement Boundary: nothing deleted; the retro-fix of already-upgraded databases is recorded,
  not taken
- Task Batches: 1-2 fixture + upgrade + D1; 3 repertoire entries; 4 user_version; 5 corrupt JSON;
  6 backup shape; 7 interrupted work; 8-9 docs; 10 falsifications
- Test Obligations: every new assertion seen to fail (28 breaks); --fast green
- Review Gates: implementer, coordinator-run --fast/--full, then commit
- Drift / Rewind Rules: a production change outside the named file boundary stops the slice
- Evidence Required: this plan, the AGENT-LOG entry, the break scripts, tier output
- Advisory Boundary: method-pack execution guidance only; not completion authority
```

## Risks

1. **Retro-fix not taken.** Databases upgraded before this commit keep an un-referenced
   `segments.workout_id`. A rebuild is a separate decision.
2. **A corrupt row is now a 500.** Intended, but an existing library with one bad JSON value
   would surface it on the request that reads it. The message names the value.
3. **The harness stays in `--fast`.** The new tests add ~4 s; the tier is at 62 s of 180 s.
