# Agent log

**This file is shared, append-only coordination between agents working in this
workspace.** Two projects live here and are being merged:

| Project | Path | Owner |
| --- | --- | --- |
| Sight-reading trainer | `backend/`, `frontend/`, `docs/` (repo root) | the sight-reading agent |
| Practice logger | `practice-logger/` | the practice-logger agent |
| Repertoire tracker (Rust/egui) | `piano-progress/` | neither — read-only library |

## Rules

1. **Append, never rewrite history.** Add a new entry at the bottom. If you
   disagree with an earlier entry, add a new one that says so; do not edit it.
2. **Announce before you touch the other project.** Any change outside your own
   directory gets an entry here *first*, describing what and why.
3. **Record shared-contract changes explicitly.** If you change a table, an
   endpoint, a column, or a shared file format, say so with the exact file and
   line, and say what the other side must do.
4. **Do not write another owner's tables.** `piano-progress` owns the library;
   `practice-logger` owns the practice tables. Cross-owner writes are the one
   thing that makes a shared SQLite file unsafe.

## Entry format

```
## <YYYY-MM-DD> — <agent> — <one-line summary>
Scope: <files or projects touched>
Did: <what changed>
Impact on the other side: <what they must know, or "none">
```

---

## 2026-09-12 — sight-reading agent — reconnaissance and integration proposal (no code changed)

Scope: read-only inspection of `practice-logger/` and `piano.db`; added
`docs/INTEGRATION-practice-logger.md`, this file, and one comment fix in
`.gitignore`.

Did:

- Read `practice-logger`'s DESIGN.md, README, `app/db.py`, `app/config.py`,
  `app/main.py`, `app/models.py`, `app/library.py`, `app/services.py` (ingest),
  `docs/PLAN-PHASE2.md`, git log, and its test layout.
- Inspected the live shared database (via a copy — see below) and recorded the
  table inventory and row counts.
- Wrote the integration design: `docs/INTEGRATION-practice-logger.md`.
- Corrected `.gitignore`: my earlier comment called `practice-logger` an
  independent repository, which is now known to be wrong — it is a planned merge.

Impact on the other side:

- **No behaviour changed and no code of yours was edited.** The only file added
  under `practice-logger/` is `docs/INTEGRATION-WITH-SIGHT-READING.md`.
- **One finding you should know about:** `practice_sessions.source` is already a
  live column with `DEFAULT 'web_midi'`, but `app/services.py:98` writes a
  hard-coded `'web_midi'` literal and nothing ever reads the column. The wire
  format (`app/models.py:16-21`) has no `source` field. Wiring it through is the
  whole of the first integration step and needs no schema change.
- Also noted: `EventBatch.client_id` is validated (`app/models.py:17`) and then
  never stored — `client_id` appears in no INSERT.
- **Sandbox constraint on my side:** I cannot open `piano.db` for writing
  (SQLite needs to create `-shm`/`-wal` beside it, and that path is outside my
  file sandbox). I can read and copy it. Any integration work I do must point
  `PL_PIANO_DB` at a workspace copy. Please do not assume I can touch the real
  file.

## 2026-09-12 — sight-reading agent — Slice E design pending the integration decision

Scope: `docs/ROADMAP.md` (Slice E), no code yet.

Did: nothing beyond the proposal above. Slice E (a deliberate, bounded practice
block in the trainer) is designed *around* the integration, because the two
"sessions" are different objects — see `docs/INTEGRATION-practice-logger.md` §2,
which proposes **sitting** (yours, emergent) vs **workout** (mine, declared).

Impact on the other side: none yet. Waiting on the decision in that document §5,
particularly I2 (reuse `POST /api/events`) and I5 (whether the trainer's tables
eventually move into `piano.db`).

## 2026-09-12 — sight-reading agent — DIRECTION CHANGE: one self-contained web app, Rust retired

Scope: `docs/ECOSYSTEM.md` (new), `docs/ROADMAP.md` §G, `docs/INTEGRATION-practice-logger.md`
(status note), and the brief in `practice-logger/docs/`.

Did (documentation only — **still no code changed in `practice-logger/`**):

- The user redirected the ecosystem. The target is now **one Python + Svelte web
  app** that owns its own database and media directory, absorbs the repertoire
  tracker as a module, and eventually retires the Rust `piano-progress` app.
- Wrote `docs/ECOSYSTEM.md`: target architecture, why the rewrite does *not* by
  itself fix multi-machine, the Rust retirement path, media as the expensive
  part, and a 7-phase migration plan.
- Marked `docs/INTEGRATION-practice-logger.md` as superseded in its destination
  while keeping its factual findings, and updated the brief in your docs.

Impact on the other side — **this changes your design of record, so please read it:**

- Your DESIGN.md §1 ownership split ("the load-bearing rule") exists to let two
  *processes* share one SQLite file. In a single app that becomes an internal
  package boundary, which is far cheaper to hold.
- Your app becomes `app/practice/` inside the merged app: sessionizer,
  segmentation, ingest and the whole test suite port across. **This is a port, not
  a rewrite.** Nothing you built is discarded.
- The double-capture hazard documented in the earlier brief **disappears
  structurally**, because there will be one capture path instead of two.
- The `source` column finding still stands and still matters — it is how
  sight-reading time will be separated from repertoire time in the analytics.
- Two constraints that shape the whole thing: Web MIDI needs a secure context, so
  the backend must run **on the piano machine** as `localhost`; and media
  (138 MB, 42 content-hashed recordings, ffmpeg) is the largest single cost and
  the gate on retiring Rust.

Open questions for you are in `docs/ECOSYSTEM.md` §8, of which **D1 — do you
practise at more than one instrument?** is the only one that can invalidate the
architecture.

## 2026-09-12 — sight-reading agent — nothing else pending on my side

Scope: none.

Did: nothing further. The sight-reading app is unchanged and its 418 tests pass;
`docs/ROADMAP.md` A–D are landed, E is designed, F is untouched.

Impact on the other side: none. I am waiting on the ECOSYSTEM.md §8 decisions
before starting Phase 1.

## 2026-09-12 — sight-reading agent — ECOSYSTEM decisions taken; Phase 1 landed

Scope: this repo only (`backend/app/repertoire/`, `backend/app/bridge.py`,
`config.py`, `db.py`, `main.py`, `tests/test_repertoire.py`, `tests/conftest.py`,
docs). **Nothing under `practice-logger/` was touched.**

Did:

- The user answered the ECOSYSTEM.md §8 questions: **D1 one instrument/one
  machine**, **D2 one app with three packages**, **D3 full media import and
  in-browser playback** (Phase 4).
- Landed Phase 1: our own data directory, a `repertoire/` package (schema,
  models, store, importer, HTTP routes), a `bridge.py` cross-domain seam, and 41
  new tests. The existing sight-reading modules were deliberately **not** moved —
  no churn for tidiness.
- Verified the importer against the **real** `piano-progress` database: 7
  composers, 17 pieces, 3 journal entries, 42 media rows, matching the source
  counts, with every piece key mapping to a sight-reading key.

Impact on the other side:

- **The runtime coupling your DESIGN.md §1 describes is now gone on my side.** I
  no longer read `piano.db` at runtime at all; I read it once at import and then
  own my tables in `~/.local/share/piano-ecosystem/piano.db`. Your database is
  opened read-only and the tests assert the file is byte-identical afterwards.
- **The rename is done**: `piano-progress.notes` (prose) becomes `piece_journal`
  in the new schema, because `note_events` will also live in that database.
- Phase 2 is a Repertoire UI against the read-only API that now exists. Phase 5
  is porting your app into `app/practice/` — unchanged from the plan.
- One naming casualty worth knowing: `SRT_*` is now the ecosystem's env prefix
  even for non-sight-reading settings. A rename to something neutral is cosmetic
  and deferred; I did not want to churn config in the same slice.

## 2026-09-12 — sight-reading agent — ecosystem Phase 2 landed (Repertoire UI)

Scope: this repo only (`frontend/src/components/RepertoireView.svelte`,
`lib/api.ts`, `lib/types.ts`, `App.svelte`, `backend/app/db.py`,
`backend/tools/e2e_browser.py`, docs). **Nothing under `practice-logger/` was
touched.**

Did:

- Built the Repertoire section: library grouped by composer or difficulty, search
  and filters, per-piece detail with journal and recording catalogue, the
  sight-reading fit for a piece, and an import flow for an empty library.
- Added e2e scenario 7 with a deterministic legacy fixture, and reset its own
  state so it is repeatable.
- Verified against the real library: 17 pieces, 7 composers, 42 recordings.

Impact on the other side — two findings worth carrying into your code:

1. **A latent SQLite threading bug, now fixed globally.** FastAPI resolves a sync
   dependency and runs a sync endpoint in *different* threadpool threads, so a
   connection created in a dependency is used from another thread and SQLite
   refuses it (`SQLite objects created in a thread can only be used in that same
   thread`). It only surfaced for routes mounted via `include_router`; top-level
   routes happened to be scheduled on one thread. The fix is
   `check_same_thread=False` on the single connection factory — safe because a
   connection is opened per request and never shared concurrently. **If your
   `app/db.py` connects without that flag you have the same latent bug**, and
   `TestClient` will not show it; only a real server will.
2. **`TestClient` does not schedule like uvicorn.** 459 unit tests passed while
   the API returned 500 for every repertoire route. The browser e2e caught it
   immediately. Worth knowing when weighing what your unit suite proves.

Nothing else. Phase 3 (repertoire editing) is next, then Phase 4 (media), then
Phase 5 is porting your app into `app/practice/`.

## 2026-09-12 — sight-reading agent — ecosystem Phase 4a: recordings actually play

Scope: this repo only (`backend/app/repertoire/{store,api,models}.py`,
`frontend/src/components/RepertoireView.svelte`, `lib/types.ts`,
`tests/conftest.py`, `tests/test_repertoire.py`, `tools/e2e_browser.py`, docs).
**Nothing under `practice-logger/` was touched.**

Did:

- Reported by the user: recordings in the Repertoire view all showed "file
  missing" instead of the file. Cause: the import defaulted to metadata only, so
  the files were never copied, and the UI conflated "not copied yet" with "lost".
- Three-state availability (`present` / `pending` / `missing`), copying on by
  default, a media streaming endpoint with Range support, and an in-browser
  player. 469 backend tests (10 new) and e2e assertions covering the stream.

Impact on the other side: none functional. Two notes worth having:

- Verified streaming serves **206 Partial Content** for a Range request, which is
  what makes seeking work in an `<audio>` element. If you ever serve media from
  your side, plain `FileResponse` gives that for free.
- Test-hygiene lesson that cost me two failing tests: the "fresh database"
  fixture wiped only the DB file, so media copied by an earlier test made a later
  test see `present` where it expected `pending`. Wiping *all* per-test state —
  files as well as rows — is the whole of the fix. If your conftest builds a
  scratch directory, check it clears everything the tests write.

Also: I left the user's own running server on port 8000 alone and ran the e2e on
a separate port. Worth knowing that the e2e reads `SRT_DB_PATH` from *its* env
while the server it talks to uses *its* own — if the two disagree, rating setup
silently applies to the wrong database and scenarios fail confusingly.

---

## 2026-09-12 — sight-reading agent — ecosystem Phases 3, 4b, 5, 6 and 7 landed; your code is now a package here

Scope: this repo, plus the status note appended to your
`practice-logger/docs/INTEGRATION-WITH-SIGHT-READING.md`. **No file under
`practice-logger/` was changed except that docs note**, and its database was only
ever opened read-only.

**Phase 5 is done: `practice-logger` is ported into `backend/app/practice/`.**
Your sessionizer, gap segmentation with frozen boundaries, absolute-time ingest
and idempotent dedupe moved across with their tests, and the ported suite is now
part of this repo's `tests/` (`test_practice_sessionize.py`,
`test_practice_store.py`, `test_practice_api.py`). Three deliberate changes, so
you can see exactly what was not a straight copy:

| Change | Reason |
| --- | --- |
| `practice_sessions` → `sittings` | The vocabulary agreed in the integration brief: a *sitting* is emergent, a *workout* is declared, a *segment* is one piece or one workout. Since the tables were empty, the rename was free |
| `segments.piece_id` FKs our own `pieces` | One app owns the library now, so `library.py` and "never write their tables" are gone — they existed only to let two processes share one file |
| `EventBatch.client_id` removed | You validated it and never stored it; with one capture client it was a value nothing read. Extra keys are still ignored, so an old client keeps working |

Also not ported, deliberately: self-similarity identification and
`identification_corrections`. Your Phase 3 never landed, so there was nothing to
correct and the table would have been dead weight. `segments.confidence` and
`segments.identified_by` survive, so a matcher can be added later without a
migration. Your Phase 4 *did* land here: `segment_metrics` is written, with the
attack-clustering tempo rule.

Two things you will want to know about, because they are corrections to designs
your docs called settled:

- **`median_tempo` is a note rate, not a tempo.** Measured over attack onsets it is
  right about "faster than last week" and wrong as an absolute number: a passage of
  sixteenths reports four times its nominal tempo, because with no score there is no
  way to know where the beat falls. Documented in the metrics module and shown that
  way in the UI rather than dressed up.
- **Your history is importable, and the import is idempotent.** `POST
  /api/practice/import-legacy` reads `practice_sessions`, `note_events` and
  `segments` out of the old database, matches sittings on a new `legacy_id` column,
  and remaps `piece_id` through the repertoire importer's `legacy_id`. Re-running it
  adds nothing. Your five tables were empty, so on the real library it reports
  "already imported" — but the path is tested with a fixture, so it will not
  silently drop data if you did log something.

**Phase 6** added `app/workout/` (workouts are declared; finishing one links the
sitting by overlap and tags its segments `sight_reading`) and the cross-domain
numbers — measured minutes beside journal minutes per piece, and one Log dashboard.
**Phase 7** added `/api/backup/export` + `/api/backup/import` (one JSON document,
every table, merge or replace) and `docs/DEPLOYMENT.md`, which records the WAL
caveat your DESIGN.md asked for an ADR about: copying `piano.db` without `-wal` is
a silently truncated backup.

Capture moved into this frontend and is app-level, so the double-capture hazard you
flagged is gone structurally — there is exactly one capture path — with the one
remaining operational rule that two *tabs* are still two clients.

Verification: 631 backend tests, `svelte-check` clean, and eight browser e2e
scenarios including a backup round trip. The e2e caught two real bugs worth
recording: a duplicate `{#each}` key that aborted the whole Log view (padding cells
in the calendar shared a key), and a stale-detail bug where an edit reached the API
but not the screen.

---

## 2026-09-12 — sight-reading agent — ecosystem Phase 8 landed (automatic MIDI device selection)

Scope: this repo only (`frontend/src/lib/{midiDevice,midi,state.svelte}.ts`,
`frontend/src/components/{DeviceBar,PracticeView}.svelte`,
`backend/tools/e2e_browser.py`, README, ECOSYSTEM, the Phase 8/9 plan).
**Nothing under `practice-logger/` was touched.**

Did: the app now opens **every** MIDI input instead of choosing one by position, and
picks the port that actually carries notes. On Linux that is the difference between
working and not: ALSA always exposes a virtual `Midi Through Port-0`, a real Web MIDI
input that never sends a byte, and `devices[0]` is a coin toss against it.

Contract notes the other side may care about, if anything ever consumes this layer:

- `MidiInput.select(id)` and `AppState.selectDevice(id)` are **gone**; the
  replacements are `pin(id | null)` and `pinDevice(id | null)`, and `activeId` is a
  read-only answer rather than something a caller sets.
- `MidiInput` gained `onPorts(handler)` (a `PortSnapshot[]` of every port, with
  `lastNoteMs`/`notes`/`inUse`/`pinned`) and `hasPin`. `onNote`/`onNoteRelease`/
  `onSustain`/`onNoteOnMonitor`/`onNoteOffMonitor` are unchanged, so `capture.ts` and
  `PracticeView` needed no edit.
- Cross-port echo suppression lives in `NoteGate` and applies to *both* consumers, so
  a doubled note can neither add an "extra note" to a score nor duplicate a log row.
- The e2e harness's fake device now has **two** inputs. `window.__fakeMidi.send(bytes)`
  still means "the piano sent this" (it targets the live port), which is why the
  earlier eight scenarios run unchanged; `sendToAll`, `plug`/`plugLater`/`unplugAll`
  and `total` are new.
- `data-exercise-badge` was added to the exercise skill pill: `.pill.accent` stopped
  being unique once the device bar reported the live port in the same style.

Verified: 9 unit tests (`npm test`), `svelte-check` clean, frontend built, all **nine**
browser e2e scenarios pass, 631 backend tests unaffected.

Worth knowing if you ever port this: the e2e caught three things a unit test could
not, and each is recorded in `docs/PLAN-PHASE8-9.md` as a deviation rather than
silently fixed — the pre-first-note tie-break announcing the dead port as "in use", a
pin restored from storage being labelled "Auto" while it was being honoured, and my
own harness toggling the port list closed before clicking a row inside it.

**Phase 9 is next**: `app/hostinfo.py` (`/api/host`), loopback-only destructive
routes, `busy_timeout` and an upload cap, a capture heartbeat, and `deploy/` for the
planted notebook. The plan is `docs/PLAN-PHASE8-9.md`.
