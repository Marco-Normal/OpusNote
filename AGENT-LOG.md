# Agent log

**This file is shared, append-only coordination between agents working in this
workspace.** The two projects it was created to merge are now one: the practice logger's code lives
in `backend/app/practice/` and its history is importable, and the repertoire tracker's library was
imported by the one-time `piano-progress` importer. Neither `practice-logger/` nor
`piano-progress/` is a directory in this repository any more; the entries below are the record of
how that happened.

## Rules

1. **Append, never rewrite history.** Add a new entry at the bottom. If you
   disagree with an earlier entry, add a new one that says so; do not edit it.
2. **Announce before you touch another owner's area.** Any change outside your own
   directory gets an entry here *first*, describing what and why.
3. **Record shared-contract changes explicitly.** If you change a table, an
   endpoint, a column, or a shared file format, say so with the exact file and
   line, and say what the other side must do.
4. **Move the docs with the code.** A change is not done until the documents it invalidates
   are updated, in the same commit that lands it. The trigger table — which file, for which
   kind of change — is
   [`docs/ECOSYSTEM.md`](docs/ECOSYSTEM.md) § *The standing rule for documentation*.

The rule this list used to carry about table ownership is discharged by the merge, and must not be
read as current: `backend/app/` is the only writer of `piano.db` now.

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

---

## 2026-09-12 — sight-reading agent — ecosystem Phase 9 landed (the notebook as a LAN server)

Scope: this repo only (`backend/app/hostinfo.py`, `backend/app/practice/capture_status.py`,
route wiring in `main.py`/`repertoire/api.py`/`backup.py`/`practice/api.py`,
`backend/app/{db,config}.py`, `frontend/src/**`, `deploy/**`, `docs/**`, the e2e).
**Nothing under `practice-logger/` was touched.**

Did: the app can now be the thing running on a notebook planted at the piano, read
from a main computer over the LAN, with the irreversible actions refused away from
the piano machine.

Contract notes for the other side:

- **New routes.** `GET /api/host` (client address, `loopback`, `sequencer`, ALSA
  `clients`), and `POST /api/practice/capture-status` (a 15 s heartbeat).
  `GET /api/practice/status` and `/api/practice/analytics/summary` gained
  `last_note_ms` and `capture` — **additive**, no existing field changed.
- **New refusals.** Four repertoire DELETEs, `POST /api/profile/reset`,
  `POST /api/backup/import` with `mode="replace"`, and
  `POST /api/practice/sittings/{id}/resegment` with `confirm=true` return **403**
  unless the socket peer is loopback. If you add a destructive route, it needs
  `dependencies=[Depends(require_loopback)]` or a `require_loopback(request)` call —
  and if you ever put a reverse proxy in front, the check must move to a trusted
  header, because `request.client.host` becomes the proxy's address.
- **Two writers on one file.** `PRAGMA busy_timeout = 5000`, and uploads are capped
  by `SRT_MAX_UPLOAD_MB` (512) *while writing*, not against the declared size.
- The `TestClient` fixture now declares the suite local, because TestClient's client
  address is the literal "testclient" and the loopback check would otherwise 403
  every delete in the suite. Both directions are tested in
  `tests/test_server_hardening.py`.

One diagnosis worth carrying forward, because it was wrong in the design docs first:
**`Midi Through Port-0` is a real ALSA sequencer client that never carries a note**,
and it is the "0" in the reported device list. Procfs confirms it:
`Client 14 : "Midi Through" Port 0 : "Midi Through Port-0"`. Phase 8 attaches to every
port and de-duplicates echoes rather than trying to pick the right one; Phase 9's
`/api/host` reports the sequencer and the visible clients, so "the piano is not
plugged in" and "the kernel module is missing" can be told apart.

Verified: 646 backend tests, 9 unit tests, `svelte-check` clean, frontend built, all
**ten** browser e2e scenarios pass, `bash -n`/JSON/`systemd-analyze` on the deploy
files.

---

## 2026-09-12 — sight-reading agent — the installer worked on Mint only after three fixes

Triggered by a real install on the user's Linux Mint notebook, which stopped at the
kiosk step with `Failed to connect to bus: No medium found`. Nothing was corrupted —
the server unit was already installed and enabled — but the kiosk never got set up,
and the cause was my installer, in three separate ways:

1. **`sudo -u user systemctl --user` has no bus.** Sudo drops `XDG_RUNTIME_DIR` and
   `DBUS_SESSION_BUS_ADDRESS`, and a machine may have no user session at all. The
   kiosk is now an **XDG autostart** entry (`~/.config/autostart/piano-kiosk.desktop`
   → `~/.local/bin/piano-kiosk.sh`), which needs no bus and is honoured by Cinnamon,
   MATE and XFCE. `deploy/piano-kiosk.service` is **deleted** rather than kept as a
   second mechanism that would race with the first.
2. **Mint ships no chromium package** (Mint dropped it when Ubuntu's became a snap
   stub), so the unit would have failed at boot even with the bus fixed. The wrapper
   now resolves Chromium, Chrome, Brave, Vivaldi, Edge or flatpak Chromium at runtime,
   so installing a browser later starts working — and the profile directory follows
   the browser (a flatpak gets `~/.var/app/...`).
3. **The policy directory is package-specific.** Chromium's own default is
   `/etc/chromium/policies`, but Debian and Ubuntu packages read
   `/etc/chromium-browser/policies`, and Chrome reads `/etc/opt/chrome/policies`. The
   installer picks by detected browser; a flatpak browser cannot read `/etc` at all,
   so it attempts an override and then says the MIDI prompt may need one click (the
   kiosk profile remembers it).

New in the repo: `deploy/browser.sh`, `deploy/kiosk-run.sh`,
`deploy/piano-kiosk.desktop`, `deploy/browser.test.sh` (ten cases, plain bash — it
stubs a PATH so a machine with a real browser cannot make a case pass by accident),
and `deploy/install.sh --check`, which reports the resolved paths and detected browser
without root and without writing anything.

For anyone whose install stopped at the kiosk step: remove the stray, disabled unit
(`rm ~/.config/systemd/user/piano-kiosk.service`), pull, re-run
`sudo ./deploy/install.sh`, and log out and back in. Automatic login is required —
the kiosk needs a graphical session — and the kiosk log is
`~/.local/state/piano-kiosk.log`.

## 2026-09-12 — sight-reading agent — the installer no longer guesses the LAN URL

`install.sh` printed `http://$(hostname).local:$PORT` unconditionally, which is only
true when avahi is running *and* the client resolves mDNS. It now enumerates the
global IPv4 addresses (skipping `docker*`, `br-*`, `virbr*`, `veth*`, `tun*`, `tap*`,
`zt*`, `tailscale*`, `wg*`, because a machine running containers otherwise lists six
unreachable addresses and hides the real one), reports the `.local` name only when
`avahi-daemon` is active, and says so when it is not. `--check` prints both, so the
"what URL do I type" question is answered before anything is installed.

`docs/DEPLOYMENT.md` gains a *Reaching it from another machine* section: IP versus
`.local` versus a router DNS name versus a `hosts` entry, the advice to give the
notebook a DHCP reservation so the IP stops moving, and the two traps — MIDI only
works on the notebook over `http://localhost:8000` (an IP is not a secure context, so
Chrome refuses MIDI and the app correctly reports itself as remote), and Mint ships
`ufw` installed but inactive, so port 8000 may need opening.

## 2026-09-12 — sight-reading agent — the empty library had no way to add a piece

Reported by the user on the notebook: no way to add repertoire. They were right, and it
was a first-run dead end rather than a missing menu. The **New piece** button and the
piece editor both lived inside the *non-empty* branch of the Repertoire view, so with
an empty library — which is what a fresh machine has, and the notebook is one — the
only control offered was *Import from piano-progress*, useless on a machine that never
ran that app. The library was therefore unaddable from the UI until something else put
a row in it.

Fixed by lifting the editor out of the branch so it renders in both states and adding
**New piece** to the empty panel ("Or start from scratch:"), next to the import. The
e2e now covers the first run explicitly: empty library → create a piece *and its
composer inline* → listed → delete → empty again, before the import flow it already
tested. Nothing about the Rust app is involved at runtime; the importer reads its
database once, and only on the machine that has it.

## 2026-09-12 — sight-reading agent — the streak was reading UTC days as local days

Found by accident, while re-running the suite after the empty-library fix: two tests
failed that had passed an hour earlier. The clock had crossed midnight UTC while local
time was 22:39 (UTC-3), which is the whole bug.

`performances.performed_at` is stored UTC, and `_streak_days` took the first ten
characters of that string as "the day" while comparing against `date.today()` — the
*local* day. At UTC-3, anything played after 21:00 local is already tomorrow in UTC, so
the Progress view reported a broken streak every evening (and the tempo-progress chart
grouped those sessions under the wrong date). Fixed with `_local_day(timestamp)`, which
parses the stored value as UTC and converts it to this machine's timezone — legitimate
because the app runs on the piano machine, so the server's zone *is* the player's.

Two regression tests, one of which does not depend on the time of day: a fixed zone
(`Pacific/Kiritimati`, UTC+14) where a 20:00 UTC timestamp must land on the next local
day. The practice-side streak test was also sending `tz_offset_minutes=0` while the
analytics compare against the server's local today; it now sends this machine's offset,
which is what a browser in the same room sends.

## 2026-09-12 — sight-reading agent — playback: the logged notes can finally be heard

Asked by the user why the log records every note but cannot play any of it. Nothing
did, and the notes were not even reachable: `Tone.js` was used only by the count-in
click, and the practice API exposed counts and metrics, never note events. The original
logger's pipeline had no playback stage — its "media" phase meant *audio recordings* —
so this was an omission in the port, not a hidden feature.

Two players landed:

- **Attempt playback** (results panel, `lib/playback.ts` + `lib/pianoPlayer.ts`, no
  backend change): play your performance, the exercise as notated, or either hand.
  Written durations come from quarter notes at the exercise's tempo; each played note's
  hand is recovered by reconstructing `played.onset = expected.onset_s +
  onset_error_s` from the scorer's own feedback, so no scoring logic is duplicated on
  the client.
- **Log playback** (`GET /api/practice/sittings/{id}/notes`): read on demand, because
  it is the only payload in the practice domain that grows with how long you played —
  the sitting detail is re-read after every segment edit and needs none of it.
  Synthesised through the same player, with a playhead over the segment strip and a
  per-segment play button.

Contract note for the other side: **one new additive route**, no changed fields.
`SittingNotes` = `{sitting_id, started_ms, notes: [{onset_ms, duration_ms, pitch,
velocity, channel}]}`.

Honest limits, recorded in the UI as well as here: it is a synthesiser, not the piano
(no samples ship); and the passive log cannot separate hands, because the piano sends
both on one MIDI channel and only the channel is stored. A scored attempt can, because
the exercise labels each note's hand.

Verified: 652 backend tests, 21 frontend unit tests, `svelte-check` clean, frontend
built, all ten browser scenarios — including assertions that the player reports which
source is sounding, that Stop clears the playhead, and that the notes route is fetched
only when playback is asked for.

## 2026-09-12 — sight-reading agent — Phase 11 landed (progress you can see), and Phases 12-14 planned

After a brainstorm the user picked four directions and an order: progress (11), ops
polish (12), library depth (13), musical content (14). They explicitly *declined*
section practice and per-hand practice for now; both are recorded as still-open rather
than quietly dropped.

Phase 11 landed:

- **`rating_events`**, written for every skill whose rating moves, one row per attempt.
  `user_skills` kept only the current number, so there was no curve. The Elo engine
  moves all nine dimensions on every attempt, so each point carries a **focus** flag —
  without it, eight incidental nudges drown the series that matters.
- **`GET /api/progress/ratings?days=`** (grouped by skill, with the biggest gain) and
  **`GET /api/performances/{id}`** (the stored played notes, analysis and exercise, in
  the shapes the results panel already used). Both additive; no existing field changed.
- **`HearIt.svelte`** now owns the player UI, used by a fresh result and by a past
  attempt, so the two cannot drift.
- Week in review in the Log tab, and clickable history rows in Progress.

Contract note for the other side: the only new stored artefact is `rating_events`, and
the two new routes are read-only. `PerformanceDetail.expected_notes` uses `onset_s` and
`duration_q` (the notation's own units) while `played_notes` uses `onset`/`duration` in
seconds — the same asymmetry the score endpoint has, deliberately.

## 2026-09-12 — sight-reading agent — Phase 12 landed (ops polish)

- **Nightly rotating backup.** `python -m app.backup [--out DIR] [--keep N]` writes one
  dated JSON export and prunes the rest; `deploy/piano-backup.{service,timer}` runs it at
  03:10 with `Persistent=true`, and the installer writes a first backup immediately so
  the job is never merely assumed to work. New settings: `SRT_BACKUP_DIR`,
  `SRT_BACKUP_KEEP`.
- **`GET /api/status/system`** — database size and WAL, media states, backups kept and
  the newest one's age, sequencer presence, ALSA clients, capture heartbeat, and a
  latency suggestion. One read, cross-domain, so it lives in the composition root next
  to `/api/practice-suggestions` rather than making any domain import the others.
- **`store.onset_bias_ms`** — median timing bias over the last twelve attempts, needing
  three before it answers. It *suggests*; the device bar offers "Use N ms" and never
  applies it, because changing what the scorer subtracts would make past scores
  incomparable with future ones.

Small production change worth noting: the status route passes its backup directory to
`backup.latest_backup(dir)` explicitly instead of letting the helper resolve settings
itself. Two places reading the same configuration independently is how a panel ends up
reporting a directory nothing writes to.

## 2026-09-12 — sight-reading agent — Phase 13 split, clef reading decided

Two scope decisions taken, recorded in `docs/ECOSYSTEM.md` §10 so they are not
re-derived later:

- **Phase 13 is two slices.** Scores (PDF + MusicXML through the existing media
  pipeline, `kind='score'`, no ffmpeg in that path), a client-side waveform with a
  database-stored A/B loop, and sustain-pedal capture land first; **self-similarity
  auto-tagging** follows as its own slice, so its accuracy can be judged on its own.
- **Clef reading is a modifier on existing dimensions, not a tenth skill.** Clef variety
  goes into `hand_position` (and `intervals` for cross-staff reading), which keeps the
  radar chart, the calibration ladder and the default levels as they are. The accepted
  cost: clef reading cannot be tracked as a skill in its own right.

## 2026-09-13 — sight-reading agent — Phase 13a, part 1: scores (PDF and MusicXML)

Scope: `backend/app/repertoire/`, `backend/tests/test_scores.py`,
`frontend/src/components/{RepertoireView,ScoreViewer}.svelte`,
`frontend/src/lib/{api,types}.ts`, `backend/tools/e2e_browser.py`. No table
changed: a score is a `media` row with `kind='score'`.

Did:

- **`media_pipeline.store_score`** — a score takes the same content-hashed,
  content-addressed storage as a recording but no ffmpeg pass at all. It is not
  probed (its own bytes are the honest description) and not re-encoded, so the
  file you attach is the file you read. `.pdf` must begin with `%PDF-`; MusicXML
  must parse and have a `score-partwise`/`score-timewise` root. `.mxl` is refused
  with a message saying to unzip it, rather than an unzip dependency.
- **`POST /api/repertoire/pieces/{id}/scores`** and a
  `api.repertoire.uploadScore` client call. The stored name is the content hash,
  so re-attaching the same document is a 409 that names where it already lives
  instead of a unique-constraint error.
- **Scores are not recordings.** `recording_count` and the
  present/pending/missing media counts now exclude `kind='score'` (a score is
  never "not copied yet"), and `score_count`/`status.scores` were added so the
  counts stay separable. The serve route picks the MIME type from the stored
  format, because `mimetypes` does not know `.musicxml` and calls `.xml` text —
  either of which makes a browser download the score.
- **UI**: a Scores section in the piece panel (PDF in an `<iframe>` using the
  browser's own viewer; MusicXML engraved in place by the existing OSMD
  `ScoreRenderer` with no expected-note timeline), a size/codec pill per score,
  and an attach form.
- 16 new backend tests; the repertoire browser scenario now attaches both a
  MusicXML and a PDF score, checks the engraving, the content type, and the
  duplicate refusal. The e2e also gained an optional scenario-name filter
  argument so a single scenario can be re-run while fixing it.

Impact on the other side: none — `practice-logger/` and `piano-progress/` are
untouched, and no shared table changed. `media.kind` gains one more value
(`'score'`), which only this app writes.

## 2026-09-13 — sight-reading agent — Phase 13a, part 2: waveform and an A/B loop

Scope: `backend/app/repertoire/{schema,store,models,api}.py`,
`backend/tests/test_repertoire.py`, `frontend/src/lib/waveform.ts` (+ tests),
`frontend/src/components/{Waveform,RecordingPlayer}.svelte`,
`frontend/src/components/RepertoireView.svelte`, `backend/tools/e2e_browser.py`.

Did:

- **The loop is in the database.** `media.loop_start_s` / `media.loop_end_s`
  (additive migration, so an existing library upgrades in place) and two more
  fields on `PATCH /api/repertoire/media/{id}`. Either marker may be set alone —
  the player marks A and then B — so the route validates the *merged* pair, not
  the body: the second marker is checked against the stored first one. A score is
  refused a loop outright; a marker past the recording's end is refused with the
  duration in the message.
- **`lib/waveform.ts`** — peaks, marker placement and the loop decision as pure
  functions with 24 unit tests. `peaksFrom` pools channels (a note in one channel
  must not be averaged into near-silence) and allocates columns by ratio, so the
  final sample is always pictured.
- **`Waveform.svelte`** draws two stacked canvases (the picture changes rarely,
  the playhead sixty times a second), dims the audio *outside* the loop, and
  reports a click as a seek. **`RecordingPlayer.svelte`** owns the media element,
  decodes with an `OfflineAudioContext` (no output device, no user gesture) and
  refuses to decode beyond 64 MB rather than push a practice machine into swap.
- 12 new backend tests; the browser scenario decodes a real recording, asserts
  the tone is drawn at its real height, sets A and B by clicking the picture,
  reads the markers back from the API, and clears them.

Two things the e2e caught that are worth keeping:

- **The picture moved under the cursor.** Revealing "Clear" after the first marker
  reflowed the toolbar and pushed the waveform down, so the next click landed on
  a button. Both buttons are now always in the layout and merely disabled, and the
  scenario measures the box before and after to keep it that way.
- **The fixture tone was −18 dB**, which made "the waveform drew something" a test
  that a flat line would also pass. `make_tone_wav` now normalises it.

Impact on the other side: none. `practice-logger/` and `piano-progress/` are
untouched; `media` gained two nullable columns that only this app writes.

## 2026-09-13 — sight-reading agent — Phase 13a, part 3: the sustain pedal

Scope: `backend/app/practice/{schema,models,store,api}.py`,
`backend/tests/{test_practice_store,test_practice_api,test_backup}.py`,
`frontend/src/lib/{midi,capture,playback,types,api}.ts` (+ tests),
`frontend/src/components/{SegmentTimeline,CaptureBar}.svelte`,
`backend/tools/e2e_browser.py`, and the user-facing docs.

Did:

- **CC64 is no longer dropped.** `note_events` gains a sibling: a `pedal_events`
  table holding the raw value stream (onset, value, channel) with the same
  `INSERT OR IGNORE` idempotence a retried batch needs. `EventBatch.pedals` is
  optional on the wire, so an older client — or a keyboard with no pedal — is
  unaffected.
- **A pedal never opens or extends a sitting.** A move is attached to the sitting
  that contains it and otherwise dropped and counted (`pedals_ignored`). A foot
  resting on the pedal is not practice, and letting it extend a window would hold
  a sitting open for as long as it rested there.
- **A pedal-only batch is accepted**, with `sitting_id: null` when nothing matched.
  The client keeps a failed batch queued and resends it, so refusing these would
  block every note behind them until the player happened to play again.
- **Playback holds the notes.** `sustained()` turns the value stream into intervals
  and extends each note whose release falls inside one; a pedal pressed after a
  release does not resurrect the note, and a pedal-up that never arrives ends at a
  short tail rather than at infinity. Applied to the whole sitting before any
  segment range is taken, so a note pedalled over a segment boundary still rings
  where the next segment starts.
- 11 new backend tests (plus a pedal row in the backup round trip) and 9 frontend
  unit tests; the browser scenario presses CC64 through the simulated device and
  reads both halves of the press back from the API, timed against the notes.

Impact on the other side: none. `practice-logger/` and `piano-progress/` are
untouched. The shared database gains one table (`pedal_events`) that only this app
writes, and the JSON backup picks it up automatically because the table list is read
from `sqlite_master`.

## 2026-09-13 — sight-reading agent — Phase 13b: recognising what you played

Scope: `backend/app/practice/similarity.py` (new), `{schema,models,store,api}.py`,
`backend/app/config.py`, `backend/tests/{test_similarity,test_autotag,test_backup}.py`,
`backend/tools/measure_autotag.py` (new),
`frontend/src/components/{SegmentTimeline,PracticeLogView}.svelte`,
`frontend/src/lib/{api,types}.ts`, `backend/tools/e2e_browser.py`, and the docs.

Did:

- **The matcher, built from `practice-logger/docs/DESIGN.md` §5.** A pitch-class
  profile, tempo proximity and register overlap per segment; k-nearest over your own
  labelled segments; bands. Fingerprints are derived from `note_events` on every use and
  never stored, and an inferred label is never training data, so a wrong guess cannot
  become evidence for itself.
- **The write policy the user chose.** Only the confident band is written
  (`identified_by='similarity'`, marked *guessed* in the timeline with "It's right" and
  "Not this"); between the two thresholds a match is *offered* with its ranked
  alternatives and the arithmetic behind each one, and written only if accepted.
  Declining records a dismissal so it is not asked again, and is deliberately not
  counted as the matcher being wrong.
- **A high score is not enough.** A match is written only when it also leads the
  runner-up by a margin, because two pieces that sound alike both score high. Plus a
  sitting-context tie-break: a near-tie goes to the piece the sitting is already about,
  which is measured to be worth 84.7% → 91.7% top-1.
- **One owner for a decision.** Accept/reject/correct all write through `_settle_label`,
  including the piece dropdown, so every overruled guess is recorded. `change` was built
  as an API action and then removed when it turned out to duplicate `PATCH /segments/{id}`
  exactly.
- **Accuracy, measured two ways.** Leave-one-out over your own labels (hiding each in
  turn) reports coverage and precision per band with their counts, `null` rather than 0%
  where there is no denominator; `identification_outcomes` gives the live figure — the
  share of written guesses left alone — so the measurement can be checked against real
  use. The Log tab has a panel for both.
- **The weights are measured, not inherited.** `tools/measure_autotag.py` generates
  drill-shaped practice from the app's own generator (sections, half speed, one hand,
  staccato, repeated passages, wrong and dropped notes) and scores weight schemes
  leave-one-out: the design's 0.60/0.25/0.15 got 79.2%, the shipped 0.75/0.10/0.15 gets
  84.7%. Tempo is the weakest term, exactly as a player who drills slowly would expect.
  Per-kind breakdown: repeats 16/16, at tempo 18/19, staccato 12/13, **right hand only
  9/13, left hand only 6/11** — the honest cost of drilling one hand, and the reason the
  context prior and the "offered rather than written" band exist.
- 54 new backend tests (28 on the pure matcher, 26 integration); the browser suite gained
  an eleventh scenario that walks the whole story, including the cold-start mistake the
  margin rule cannot prevent (a new piece resembling one already tagged is guessed at,
  corrected, and the library then stops answering and starts asking).

Two harness findings worth keeping:

- The e2e's `clear_practice` relied on `identification_outcomes` cascading from
  `segments`, but that raw connection does not set `PRAGMA foreign_keys = ON`. The table
  is now listed explicitly, so the accuracy counters do not depend on how many times the
  suite has been run.
- Two `expect_response` waits matched URLs by substring, and a sitting id is a prefix of
  a longer one — `sittings/5` matched a response for `sittings/57`. Both are `endswith`
  now.

Impact on the other side: none. `practice-logger/` and `piano-progress/` are untouched.
One new table (`identification_outcomes`) that only this app writes, picked up
automatically by the JSON backup; and the `segments.candidates` field is additive on the
wire, so an older client ignores it.

## 2026-09-13 — sight-reading agent — Phase 15: playback you can navigate, and a real piano

Scope: `frontend/src/lib/{pianoPlayer,midi,playback,clock,pianoRoll}.ts`,
`frontend/src/components/{SegmentTimeline,HearIt,DeviceBar,PianoRoll}.svelte`,
`frontend/src/lib/{state.svelte,api,types}.ts`, `frontend/src/lib/{clock,pianoRoll}.test.ts`,
`backend/app/piano.py` (new), `backend/app/{config,main}.py`,
`backend/tests/test_piano.py` (new), `backend/tests/conftest.py`,
`backend/tools/e2e_browser.py`, and the docs.

Did (all four from the user's report, plus the question):

- **Two things played at once, and Stop did not stop.** Every component built its own
  `PianoPlayer`; there is now one shared instance. `releaseAll()` only releases voices
  sounding *now*, while `triggerAttackRelease` had already scheduled notes seconds ahead
  — playback is a `Tone.Part` that is cancelled, and MIDI output goes out in a rolling
  window so at most 400 ms is in flight. Verified against the simulated piano: note-off
  for the sounding note, an all-notes-off sweep on all 16 channels, a second sweep after
  the window drains.
- **Play through the piano itself.** `midi.ts` now tracks outputs; the sink chooses one
  by matching the *input's* device fingerprint, so "the piano you play is the piano you
  hear" needs no configuration. Three instruments in the device bar.
- **A real sampled piano, downloaded once.** `@tonejs/piano` was rejected after
  inspection: 15 kB, no samples, fetches from a CDN at play time. `app/piano.py` fetches
  the 30 Salamander files itself (2.0 MB measured, minor thirds, A0–C8), atomically and
  idempotently, served from this host at `/piano/…`. The first probe of the sharp names
  was wrong — `D#4.mp3` is a 404 HTML page, `Ds4.mp3` is the sample — so the set was
  measured, not assumed. Licence attribution travels in the status payload and is shown
  where the download is offered.
- **Seeking into a long sitting.** The strip is a transport: click to play from there,
  arrow keys, ±30 s jumps, a position readout. `fromTime()` rebases notes for a start
  offset and keeps a note still sounding, shortened, rather than dropping it.
- **Falling notes**, with the geometry in a pure module — which caught a sign error that
  a `max(sliver, …)` had been hiding, so every rectangle was a hairline.
- **The field nobody could identify** (*Split at*) is labelled and shows a clock; it is
  the position at which *Split here* cuts the segment.

Two bugs found by writing the checks:

- The sitting's notes were cached per *component*, so choosing a second sitting played
  the first one's notes. Now keyed on the sitting id.
- The store's remembered instrument was never pushed into the player, so "through the
  piano" sent nothing until the select was touched.

Harness: the strip's playhead is now shown while playing even at zero (a sitting whose
first note is at 0:00 was hiding it), and the rating-curve check waits for its panel
instead of racing it.

Impact on the other side: none. `practice-logger/` and `piano-progress/` untouched; the
new files are the 30 samples under `<data dir>/piano/`, which the JSON backup does not
include — they are re-downloadable in two seconds, and `docs/DEPLOYMENT.md` says so.

## 2026-09-14 — sight-reading agent — Phase 16: the exercise ladder actually climbs

Reported from the owner's real library: 25 attempts per skill, a rating near 800, and
every generated exercise still level 1 and "very trivial". Diagnosed from a backup of
the live database rather than from reading the code, which settled it in one look: 306 of
324 `exercise_skills` rows were level 1, every `exercises.difficulty_elo` was 600, and
the last attempts scored 96–98 with pitch accuracy 100%.

Did:

- **Re-anchored `SRT_ELO_BASE`, 600 → 480.** The selector aims `offset = -220` Elo below
  the rating (a 78% success target) and a level is 100 Elo, so the practice offset costs
  2.2 levels. At 600, level 2 did not open until a rating of 870 — 270 points of ability
  collapsed into one level of material, and a learner rated 792 was served 600-Elo
  material for as long as they stayed under it. 480 is the only value that satisfies
  three constraints: the documented example (rating 1000 → Elo 780) becomes exact
  (780 = 480 + 3 x 100), an unrated learner still starts on level 1, and it is the
  smallest such value so every level opens 100 points above the last.
- **One meaning for "level".** Two display paths computed a level from the rating with an
  inline copy of the formula and disagreed with what was served: the Progress radar said
  ~4 while the exercise on screen said level 2. Both now use the selector's level — the
  material you are worked at — and the caption says so.
- New tests pin the three constraints, the even spacing of the levels, the unrated
  default, and the exact case from the backup (792 must not select level 1). Verified by
  reverting the anchor: three of them fail at 600 and pass at 480.
- Verified against the live data: the same nine ratings now select level 2 across the
  board with difficulty 580, which is the design's own target for a 790 rating.

Not changed, and offered to the owner instead: the *rate* of progression. K = 32 with a
220-point offset means about 7 points an attempt and roughly one level per 10–13
attempts. `SRT_ELO_K` and `SRT_TARGET_SUCCESS_RATE` are the knobs, and they are a
preference rather than a bug.

Impact on the other side: none. Existing ratings need no migration — the re-anchor
raises the material a given rating selects, which is the fix, and historical
`exercises.difficulty_elo` values keep the scale they were scored on.

## 2026-09-14 — sight-reading agent — Phase 17: a sitting ends when the piano does

Three reports from using it at the instrument.

Did:

- **The dashboard now updates itself.** A sitting exists only once it has been quiet for
  the sitting gap, and nothing told an open page about it, so the newest one needed a
  reload. The Log view polls every 20 s while it is on screen, and the poll cannot move
  the selection — it refreshes the tiles, the list and the open sitting's detail and
  leaves the choice exactly as it was.
- **Switching the piano off closes the sitting.** `sittings.closed_ms` (additive
  migration), `POST /api/practice/sittings/close`, and the client reports a MIDI
  disconnect. The server judges it: a closed sitting takes no further notes, so playing
  again after switching off is a new sitting, and `CLOSE_QUIET_MS` (1.5 s) means a USB
  blip mid-phrase does not split a session while reaching for the power switch after the
  final chord still counts. The client flushes its capture buffer first, so the last
  chord is inside the sitting before it is closed.
- **Segmentation retuned from the owner's own session** — 8 s rather than 20 s. Their
  42-minute sitting had piece-change gaps of 9.5 s and 11.7 s (invisible to 20 s) and
  within-piece pauses of 15.1 s and 15.6 s, so no threshold is perfect; erring towards
  more segments is cheaper because merging is one click and splitting means typing a
  position.

Two values were being decided in two places, and both are now one:

- `practice_status` derived "open" from the clock while ingest excluded closed sittings,
  so a closed sitting was still reported open; it now asks `_find_sitting`, the predicate
  ingest uses.
- The e2e assumed the sitting *list* materialises segments; only the detail read does.

Verified with the browser suite against a simulated device: unplugging closes and
segments the sitting, nothing stays open, and the poll is observed running (2 polled
reads over 22 s) with a new sitting in the list and no reload.

Impact on the other side: none. `practice-logger/` and `piano-progress/` untouched; one
additive column on `sittings`, which the JSON backup picks up automatically.

## 2026-09-14 — sight-reading agent — how fine a segment should be

The owner asked whether a piece is better logged as one long segment or as many small
ones, for identification and for statistics. Answered by measurement, and no default
moved: the 8 s rule stands.

Evidence, on the owner's own backup (the 42-minute sitting, 18,688 notes):

- At 8 s that session becomes 6 segments against the 3 they labelled by hand, and the
  three extra cuts are the sonata's own 15.6 s, 15.3 s and 26.7 s pauses. At 20 s the
  first segment holds Exercises + Intermezzo + 10,640 sonata notes, which no single
  label can be right about — so "one long segment per piece" is not an option either.
- A fine threshold cannot produce two-bar chunks out of playing anyway: at 2 s the same
  session is 20 segments with a median of 681 notes, because nobody pauses every two
  bars. Two-bar resolution would have to come from the score, not from silence.
- The repetition signal lives in the 3-8 s band: `restarts` counts pauses of at least
  3 s *inside* a segment, so at a 2 s threshold that sitting reports 0 loops where 8 s
  reports 5. Splitting finer destroys the most informative metric there is.
- Recognition degrades with span. New table in `tools/measure_autotag.py` (first N notes
  of each drill, leave-one-out): top-1 falls from 84.7% over a whole three-bar drill to
  68-78% over its prefixes, and offered precision from 81.0% to 66-72%. Below
  `autotag_min_notes` (8 notes) identification refuses outright.
- The price is labelling prompts per hour of practice: 9-17 at 8 s against 29-46 at 2 s.

Impact: no behaviour change. The measurement is now reproducible rather than remembered,
so the threshold can be re-argued when the corpus or the matcher changes.

## 2026-09-15 — sight-reading agent — Phase 19: a re-struck note is no longer silenced by the pedal

Scope: `frontend/src/lib/playback.ts`, `playback.test.ts`, `pianoPlayer.ts`, `midi.ts`;
`docs/ECOSYSTEM.md`. Nothing outside the frontend, and no schema or contract change.

The owner reported that holding a note and clearing the pedal leaves it ringing in real
life but not in playback, and suspected the PX-870's continuous pedal. Diagnosed against
their own backup (7 sittings, 84,709 notes, 209,072 pedal moves) rather than from the code
path, which is the only reason the real cause was found.

Did:

- **The continuous pedal is captured correctly and consumed per the MIDI spec.** All 128 CC
  values are in the log, spread across the range — genuinely continuous, not a switch. Every
  consumer then applies the specification's own switch rule (0–63 off, 64–127 on), so
  half-pedalling reads as released. Measured: 23.9%, 9.1% and 10.2% of pedal time sits in
  that partial band. Recorded as a limitation rather than "fixed", because modelling a
  damper from CC values would be inventing a claim about the instrument.
- **The actual defect: MIDI note-off is per pitch, and the player emitted one note-on/off
  pair per stored note.** `sustained()` extends a released note to the pedal-up, which is
  correct, but that routinely carries it past a re-strike of the same key — and the stale
  note-off then silenced the note the hand was still holding, exactly at the pedal-up. On
  the owner's sessions that was **1,747 notes**, median loss 407 ms, worst 14.5 s of a held
  note silenced after 27 ms.
- **Fix:** `resolveOverlaps()` in `playback.ts` — a pure function ending each note where the
  same key is struck again, which is what a re-struck string does — applied once in
  `PianoPlayer.play()` so the MIDI path, the sampled piano and the FM voice all consume the
  same list. Fixing the MIDI encoder alone would have left the sampler wrong; fixing each
  caller would have left the next caller wrong.
- **`PEDAL_DOWN` had two owners** (`playback.ts` and `midi.ts` wrote `64` out separately).
  It stays in `playback.ts` and is now imported. It did not move to `types.ts` because that
  would have made `playback.ts` — which runs under Node's test loader — need
  `allowImportingTsExtensions` project-wide for one constant.
- Verified with the shipped functions over the owner's real sittings: **1,747 cut-short
  notes before, 0 after**, worst loss 14.494 s → 0. Seven new tests; 72 passing, zero
  `svelte-check` errors, build clean.

Also found while reading, not fixed and not part of this phase: `CaptureClient.flush()`
aliases its batch array (`const batch = this.buffer`) and then slices by the aliased length
after awaiting, so anything captured during the in-flight request is discarded. Recorded as
defect 4 of Phase 18a.

Impact on the other side: none. No table, column, endpoint or wire format changed. The fix
is entirely in the playback path, which also means it applies **retroactively** — every
sitting already in the log gets the corrected playback, because the pedal interpretation is
derived at play time and the stored data was never wrong.

## 2026-09-15 — sight-reading agent — the browser suite does run here, and Phase 19 is now covered by it

Scope: `backend/tools/e2e_browser.py`, `docs/ECOSYSTEM.md`. Corrects the previous entry,
which stopped short of the browser suite for a reason that turned out to be false.

Did:

- **`scenario_playback` gained the re-strike case.** A new fixture seeds a sitting whose
  pedal carries a strike past a re-strike of the same key (pitch 79: released at 800 ms,
  pedal up at 2000 ms, struck again at 1200 ms and held to 5200 ms), plays it through the
  piano, and asserts with a new `__fakeMidi.samePitchOverlaps()` that the scheduled stream
  never has two note-ons for a pitch before a note-off. That is the wiring half — the unit
  tests own `resolveOverlaps` itself, and this is what proves the player applies it and
  orders the clamped release first.
- **The assertion was falsified before it was trusted.** With the `resolveOverlaps` call
  removed from `play()`, it fails: "1 overlapping pairs". Restored: 0. All twelve scenarios
  pass on a fresh database.

**A correction, recorded rather than quietly dropped.** The previous entry said the browser
suite could not be run here. That was wrong, and the way it was wrong matters. A standalone
`p.chromium.launch()` probe failed with "Executable doesn't exist at
`…/chromium_headless_shell-1234`", and that was read as a property of the suite. It is not:
`e2e_browser.py` passes `executable_path="/usr/bin/chromium"` and never uses Playwright's
bundled build at all. **The probe did not reproduce how the harness launches**, so its
result said nothing about the harness. The lesson is the one this suite exists to teach — a
check that does not exercise the real path is not evidence, whether it passes or fails.
No chromium install is needed; the system Chromium 148 is what the suite already uses.

- One unrelated observation from the full run, not investigated and not caused by this
  change: on the *accumulated* e2e database (many sittings from repeated runs), one
  `POST /api/practice/events` failed with `sqlite3.OperationalError: database is locked`
  past the 5 s `busy_timeout`, which surfaced as a console error in scenario 3. A fresh
  database runs the whole suite clean, so this is a robustness question about contention on
  a grown log rather than a regression. Worth a look before it is met on the piano machine.

Impact on the other side: none. Test harness and documentation only.

## 2026-09-16 — sight-reading agent — Phase 18 landed: the journal joins the measurement, and the logged pedal is read

Scope: `backend/app/repertoire/{schema,models,store,api}.py`,
`backend/app/practice/{schema,models,store,pedal}.py`, `frontend/src/lib/{types,api,state.svelte,capture}.ts`,
`frontend/src/components/{RepertoireView,SegmentTimeline,CalendarHeatmap}.svelte`,
`backend/tests/{test_pedal,test_practice_store,test_practice_api,test_repertoire}.py`,
`backend/tools/e2e_browser.py`, `docs/ECOSYSTEM.md`.

Two slices. The organising finding was the same in both: the app already stored facts it
never read. `pedal_events` was written on every CC64 move and read by exactly one caller, for
playback. `mean_velocity` and `velocity_stddev` were computed, persisted and served, and
rendered nowhere. `PATCH /api/repertoire/journal/{id}` was implemented, tested, and called by
no component.

**18a — the seam between playing and writing.**

- `piece_journal.sitting_id`, nullable, `ON DELETE SET NULL`. Linked to the **sitting** and
  not to a segment, because `resegment` deletes and rebuilds every segment of a sitting — a
  segment-level link would be destroyed by the app's own correction action.
- The journal is a `<textarea>` that edits in place through the PATCH that had been dead
  since it was written, and its date defaults to the **local** date rather than
  `toISOString()`, which is UTC and offers yesterday through the whole evening.
- *Write about this* on a timeline segment parks a draft in the app state, switches to
  Repertoire and attaches the sitting with the measured arithmetic. **The prose box stays
  empty** — the app has no language model and will not put words in the player's mouth.
- Written minutes joined the calendar as a **second series**, drawn as a border rather than
  another shade so the fill still means "minutes the piano heard". A day with prose and no
  notes reads as its own state. The two are never summed, which is the rule the per-piece
  view already followed.
- Journal `content` joined the library search, and a new `GET /api/repertoire/journal`
  provides a cross-piece feed — which is also what the detail pane shows when no piece is
  selected, and that used to be blank.

**Four defects, fixed at their owners.**

1. `SittingDetail.closed` derived "closed" from the clock alone and disagreed with
   `ensure_segments`, which also honours `closed_ms`. One question, now answered once.
2. `close_open_sitting` returned a bare `None` for both "nothing open" and "still playing",
   so a client could not tell a finished session from a USB blip. It returns a `CloseOutcome`
   now. **Seven existing assertions changed** to read `.sitting_id` and the new reason, and
   they are stronger for it.
3. `identification_outcomes.segment_id` was `NOT NULL ... ON DELETE CASCADE`, so
   re-segmenting destroyed the matcher's track record — the one thing that table exists to
   keep. Now nullable `SET NULL`, via a table rebuild, since SQLite cannot alter a
   constraint.
4. `CaptureClient.flush()` did `const batch = this.buffer` — a *reference* — and then sliced
   by the aliased length after awaiting, so anything played during the request was silently
   discarded. Copied now.

**18b — the measurements the app already had the data for.**

- `app/practice/pedal.py`, pure functions beside `metrics.py`: intervals from the raw CC64
  stream, threshold **crossings rather than message counts** (a continuous pedal sends
  dozens of values per press), the down-ratio, the blur count, and the touch figures.
- Eight additive columns on `segment_metrics`, written by `_refresh_metrics` — approach B.
  The table stays a cache of a pure function, which is what `metrics.py` already promises.
- `pedal_basis` is **stored, not re-derived**, so a score attached in March cannot
  retroactively relabel January's observed number. That is the seam the owner asked for, and
  the score path itself is explicitly out of scope.
- A sitting with no pedal rows reports *not recorded* through that basis rather than a zero.
  Imported history has no pedal events at all, and a figure over it would report a fault that
  was never observed.
- Register balance is **worded as registers, not as hands**. The piano sends both hands on
  one channel; it reports, it does not judge.

**Verified.**

- Backend **811 passing** (19 pedal units, 2 metric-integration, 7 journal, 5 for the defect
  fixes). Frontend **72 passing**, `svelte-check` clean, build clean.
- The migrations were exercised against a **real pre-18 database** — the e2e one, seven
  columns in `segment_metrics` and a `NOT NULL` outcome reference — with a row planted in the
  old shape first. Every column was added, the nullable rebuild ran, and the planted row
  survived with its action and score intact.
- All twelve browser scenarios pass, with three new assertions (editing an entry in place,
  the cross-piece feed, and the "pedal not recorded" state).

**A judgement worth recording.** The blur metric is the one place this phase makes a claim
about playing from indirect evidence, and the definition is deliberately narrow: it counts an
attack only when the pedal is *demonstrably* holding something — notes whose key was released
inside that stretch — and the attack brings at least a triad that the pedal is not already
holding. A key still held is playing, not pedalling, and is not counted. The proxy is labelled
as one everywhere it appears.

Impact on the other side: none. Two additive columns on `piece_journal` and `segment_metrics`;
one constraint widened on `identification_outcomes`; no endpoint removed and no wire format
changed. The JSON backup picks all of it up automatically, since the table list is read from
`sqlite_master`. `backend/data/real-backup.json` is the owner's real practice log, refreshed
by hand and kept out of git, for measuring against actual practice rather than a fixture.

## 2026-09-16 — sight-reading agent — Slice 0 of the test strategy: the suite is graded

Scope: `docs/TEST-STRATEGY.md`, `docs/PLAN-SLICE0.md`, `check.sh`,
`backend/tools/{run_e2e.sh,e2e_browser.py,falsify.sh,falsifications/}`,
`backend/{setup.cfg,requirements-dev.txt}`, `backend/tests/conftest.py`,
`backend/tests/test_repertoire.py`, `pytest.ini`, `.gitignore`.

Did: built the verification guardrail's first slice. The backend was already at 97% line
coverage, so this adds almost no tests — it makes the existing ones trustworthy and measures
whether they can fail.

- **The mutation baseline exists: 10,652 mutants, 10,289 killed, 305 survived, 97.1%.**
  `mutmut` 3.8 works with pytest 9, so the planned hand-rolled fallback was not needed. The
  survivors concentrate exactly where the gap analysis predicted: `app.music` 199,
  `app.config` 30, `app.skills_data` 29, `app.piano` 23, `app.main` 20. The sharpest single
  entry is `bass_patterns.x_free_line` at 62 — the free left hand this project's own README
  calls the harder half.
- **Nine places where a green tick meant nothing**, found by audit and repaired: four
  assertions that provably could not fail, four that passed while the feature was broken, and
  a pytest test named for a check it short-circuited past.
- **Every browser scenario now runs alone.** The database is reset between scenarios rather
  than once per process, and the reset is checked against `sqlite_master` so a table added in
  a later phase fails loudly.
- **A skip is loud.** A scenario that ran nothing exits non-zero, and pytest reports
  setup-time skips under their own separator.
- **`./check.sh --fast` / `--full`**, and `falsify.sh` to prove a check can fail.

Five findings, each invisible before this slice:

1. The upload cap's while-writing check cannot run through the endpoint — FastAPI receives the
   whole body first — so the cap protects the media directory, not the disk, and
   `_stage_upload`'s docstring said otherwise.
2. `tone_wav`'s "skip when ffmpeg is missing" branch had never executed; a machine without
   ffmpeg got twelve errors, not twelve skips.
3. `scenario_lan_viewer` was a third order-dependent scenario, not one of the two predicted.
4. Isolation reproduced the concurrency race the audit predicted, with a mechanism:
   `store.ingest` reads then writes, and a concurrent writer invalidates the WAL snapshot,
   which `busy_timeout` does not retry. Reproduced, not yet fixed — Slice 5.
5. `falsify.sh`'s first version reported a successful falsification of a check it never ran.

Two audit findings were rejected on evidence: the after-Stop assertion is correct as written,
and strengthening it made the scenario fail against working code.

Impact on the other side: none. No app behaviour changed except one docstring and one test
fixture. `pytest.ini` gained `--strict-markers --strict-config --timeout=120`, which no
existing test violates.

## 2026-09-16 — sight-reading agent — Slice 1 of the test strategy: the migration path finally runs, and the schema says which version it is

Scope: `backend/app/{db.py,main.py,practice/schema.py}`,
`backend/tests/{fixtures/pre_phase18_practice.sql,test_migration_upgrade.py,test_json_load.py,test_backup.py,test_repertoire.py}`,
`backend/tools/falsifications/`, `docs/{TEST-STRATEGY.md,PLAN-SLICE1.md}`, `AGENT-LOG.md`.

Did: made the one code path that runs on the player's real database observable in the tier
that runs after every edit, and fixed the defect the recon found in it.

- **A frozen pre-Phase-18 database now lives in the repository**, as SQL: the four CREATE
  scripts minus exactly the `ADDED_COLUMNS` columns, with the old `NOT NULL ... ON DELETE
  CASCADE` outcome reference, no `sitting_id`, no `performances.workout_id`, and one row per
  table. Before this slice nothing in the suite fabricated an old-shape practice database, so
  `migrate_practice`'s twelve ALTERs had never executed anywhere.
- **The upgrade test asserts the fixture is still old**, then upgrades it in place and checks
  every table's row count, the surviving outcome row, `duration_s` intact with `pedal_changes`
  NULL, and a second `init_db` a no-op. A later "fix the fixture" edit fails instead of
  silently deleting the coverage.
- **D1 fixed.** `segments.workout_id` was added to old databases with no `REFERENCES`, so an
  upgraded database let a deleted workout leave the segment pointing at nothing. The
  `ADDED_COLUMNS` type string now carries `REFERENCES workouts(id) ON DELETE SET NULL`, the
  same spelling `piece_journal.sitting_id` already used.
- **`PRAGMA user_version`**, written last in `init_db`, with `SCHEMA_VERSION = 1`, and a new
  `SchemaTooNew` refusal when the database is newer than the code — the downgrade guard that
  did not exist.
- **T9: corrupt JSON raises.** `db.json_load`'s malformed branch raises `CorruptJSON` naming the
  damaged value (truncated); the empty/`None` branch still returns the default; one
  `@app.exception_handler(CorruptJSON)` turns it into a legible 500 instead of a bare
  traceback. Every call site's route is driven on valid data.
- **Interrupted work.** An import that fails mid-`replace` leaves every table's row count
  unchanged — the first execution of `db.transaction`'s `ROLLBACK` in the suite; a raw
  `BEGIN`+insert+`close()` leaves no row and a readable database; the file is in WAL and
  `wal_checkpoint(TRUNCATE)` succeeds.
- **Backup shape compatibility**: a hand-written v1 document in the old shape imports, keeps
  `duration_s`, leaves `pedal_changes` NULL, and counts. `BACKUP_VERSION` is unchanged — the
  guarantee is one-directional.
- **The D7 corrections**: `TEST-STRATEGY.md` no longer claims the upload path has no
  transaction wrapper (it has one; the *file write* is what is not transactional) and no longer
  lists "migration" as a `--full` step (`check.sh` has none, and migration tests are ordinary
  pytest that must stay in `--fast`).
- **Verification:** backend **835 passing** (was 813); `./check.sh --fast` passes in **62-65 s**
  against the 180 s ceiling. Thirteen break scripts were written; because `falsify.sh` refuses a
  dirty tree and reverts with `git checkout`, 31 breaks were applied from a snapshot instead,
  each check observed to fail and then green again — 0 not falsified.

Findings, each invisible before this slice:

1. **The recon was wrong that column parity catches D1.** The column is present either way; only
   the `REFERENCES` is missing, so a comparison of names passes. Foreign-key parity (and a
   focused test that deletes a workout and watches the segment clear) is what catches it.
2. **`upgraded ⊇ fresh` cannot see a deleted index either** — the index is then absent from
   both sides. A second frozen literal, `EXPECTED_INDEXES`, is what makes "deleting
   `idx_sittings_legacy` fails `--fast`" true.
3. **`check.sh`'s per-step timing is shifted by one and the first step's time is never
   printed.** `step()` compares `step_start` against the script's `start`, so a step beginning in
   the same second as the script is mistaken for the first. The backend step — 58-60 s of a
   62-65 s run — is the one that goes unreported. Pre-existing; `check.sh` is Slice 2's file, so this is
   recorded, not fixed.
4. **`performances.workout_id` exists *only* in `workout/schema.py`'s `ADDED_COLUMNS`** —
   `db.py`'s own `performances` CREATE has no such column — so deleting that entry removes it
   from a fresh database too, and the frozen literal is the only check that can notice.
5. **A literal `backup.table_names` list is only caught when it is stale.** A complete literal
   list passes every Slice 1 test, because the assertion that a table created at runtime appears
   in the export is Slice 4's. The break script therefore uses the MVP's six tables, which is
   what a list looks like the day after somebody adds a table.

Impact on the other side: no route, response field, column, table or wire format is removed and
`BACKUP_VERSION` is unchanged. Additive/behavioural on three points: every database now gets
`PRAGMA user_version = 1`; a database from a newer build makes the server refuse to start rather
than misread it; and a corrupt stored JSON row now fails the request that reads it with a
message naming the value, where it previously degraded to an empty default (T9's decision).
A database that already has `segments.workout_id` from the old migration keeps the missing
reference — repair needs a table rebuild, which is recorded for a separate decision.

## 2026-09-16 — sight-reading agent — Phase 20 designed and recorded: five slices of deliberate practice, piano-side ergonomics and audio takes

Scope: `docs/ECOSYSTEM.md` only (the plan of record). No code, no schema, no route, no
component, and no other document is touched. Nothing is implemented.

Did: brainstormed non-sight-reading features against the current tree (models, routes,
components, `media_pipeline.py`, `deploy/chromium-policy.json`, `practice/store.py`) and wrote
the approved result into `ECOSYSTEM.md` as **Phase 20**, with a row in the §6 phase index, a
seven-entry decisions table (20-D1…20-D7), per-slice acceptance criteria, schema/migration
notes, an ADR-signal paragraph, and two new rows in the risks table. Five slices, in order:
20a practice kinds (`segments.practice_kind` + inferred-but-never-applied offers), 20b the
piano-side toolkit (sostenuto/CC66 hands-free after a discovery step, count-in choice, real
URLs, command palette), 20c undo over existing routes plus a grace-day streak and weekly
target, 20d journal tags/ratings and focus passages plus the `neglected()` status fix, 20e
in-app low-bitrate audio takes.

Three findings changed the design, and are recorded in the document rather than here alone:

1. **C2 is a defect, not a feature.** `pieces.status` already exists as
   `active | completed | paused`, but `neglected()` in `practice/store.py` filters only
   `NOT completed`, so a deliberately paused piece is reported as neglected for ever. The
   designed fix is `status = 'active'`; the proposed new stage system was dropped.
2. **Undo needs no new server surface.** `merge` is exactly reversed by `split` at the
   absorbed segment's known `start_ms`, `split` by `merge`, `assign` by `assign` with the
   previous label. Only `resegment` is irreversible. The one loss is stated in the spec: a
   merge nulls the absorbed segment's `identification_outcomes.segment_id`
   (`ON DELETE SET NULL`), so undo restores the segments but not the matcher's record of one.
3. **Focus passages cannot be inferred.** 18b made score alignment a non-goal, so a passage
   can never be marked *touched* from passive capture. They are manual, or seeded from a
   recording's existing A/B loop markers, and `last_worked_on` is stamped by the player.

Also recorded as deliberate refusals: hands-separate is never inferred (register balance is
registers, not hands — 18b's own promise), sight-reading is not a practice *kind* because
`source`/`workout_id` already own it, per-piece streaks are dropped, and captured audio is a
sharing convenience rather than an archive.

Impact on the other side: none. This is a planning document. `docs/ECOSYSTEM.md` gains a new
phase and two risk rows; no route, response field, column, table or wire format changes now,
and `BACKUP_VERSION` is untouched. When 20e ships it will add `AudioCaptureAllowedForUrls` to
`deploy/chromium-policy.json`, which is a kiosk-policy change the deployment docs must
describe at that point — noted in the document's doc-ownership section.

## 2026-09-16 — sight-reading agent — Phase 20a is planned and not started

Scope: `docs/PLAN-PHASE20A.md` and `AGENT-LOG.md`. No code, schema, route or component changed.

Did: wrote the implementation plan for Phase 20a (practice kinds) — five tasks with complete code,
exact commands and a falsification for every new assertion. Planned against the tree as it stands
after `d0aba27` (`./check.sh --fast` measured green in 65 s). Three defects were found and fixed
while planning and are recorded in the plan: the offer pass would have run before the matcher, when
a fresh segment still has no piece, so "slower than usual" could never fire (it now runs after
autotagging and again on label assignment); an offered kind was excluded from the split instead of
landing in the untagged bucket, which would have broken reconciliation (it is now a CASE); and the
"manual wins" guard test was built on a segment no offer would ever fire for, so it would have
passed with the guard deleted.

Impact on the other side: none — planning only. Anyone about to start 20a should read
`docs/PLAN-PHASE20A.md` first; `ECOSYSTEM.md` § Phase 20 remains the what/why, and the plan does not
restate it. 20b-20e are not planned yet.

## 2026-09-16 — sight-reading agent — Phase 20a landed (practice kinds), and a pre-existing metrics wipe found by it

Scope: `backend/app/practice/{schema,models,store,api,kinds}.py`, `backend/app/db.py`,
`backend/tests/{test_practice_kinds,test_practice_api,test_migration_upgrade}.py`,
`backend/tools/{falsifications/,e2e_browser.py}`, `frontend/src/lib/{types,api,kinds}.ts`,
`frontend/src/lib/kinds.test.ts`, `frontend/src/components/{SegmentTimeline,PracticeLogView}.svelte`,
`README.md`, `docs/PLAN-PHASE20A.md`.

Did: implemented `docs/PLAN-PHASE20A.md` in full — a second axis on a segment, `practice_kind` plus
`practice_kind_basis`, with `SCHEMA_VERSION` 1 -> 2; the pure taxonomy and offer rules in
`practice/kinds.py`; `offer_practice_kinds` / `set_practice_kind` / `kinds_breakdown` in the store;
`PATCH /api/practice/segments/{id}/kind`; the kind select and offer row on the timeline; and the
kind split in *How the time was spent* with the uncharacterised bucket shown so it reconciles.

**A defect this uncovered, which predates the slice (introduced in `2ee5003`, the Phase 1-7 port).**
`_refresh_metrics` ended with
`DELETE FROM segment_metrics WHERE segment_id NOT IN (SELECT id FROM segments WHERE sitting_id = ?)`
— "not a segment of *this* sitting", which is every *other* sitting's segment. Segmenting one
sitting therefore deleted every earlier sitting's metrics, and with them the piece tempo trend
(`tempo_series`) and the per-segment pedal and touch figures (Phase 18b's whole payload). The 20a
offer path is what found it, because "slower than usual for this piece" needs another sitting's
`median_tempo` to have survived at all. Fixed at the owner: the delete is now the orphan sweep its
comment always claimed — `segment_id NOT IN (SELECT id FROM segments)` — with a regression guard
(`test_segmenting_a_second_sitting_does_not_erase_the_first_s_metrics`) and a break script. **Anyone
with an existing database has already lost those metric rows for past sittings; they are derived,
so the repair is to re-segment or re-ingest the affected sittings, not to restore a backup.**

**Two deviations from the plan, both required.**
1. The plan called for one slice commit (Task 5.5), but `falsify.sh` refuses a dirty tree and
   reverts with `git checkout -- .`, and falsifications run in Tasks 1 and 3. Committed per task
   instead: one commit per verified task, which is what the plan's own execution route implies.
2. The metrics fix shipped inside the Task 3 commit rather than its own, because it and the 20a
   store work are the same file and the same commit is only coherent as "the feature plus the
   defect it needed fixed". The commit message and the code comment name the defect explicitly.

A third, smaller correction: the `drop_kind_basis_guard.sh` needle assumed `CASE` sat on its own
line, but in the real query it shares the line with `SELECT`, so the script could not apply its
break. `falsify.sh` correctly refused to call that a falsification; the needle and the plan's copy
of the snippet are fixed.

**Falsified, not merely green** — five breaks, each observed to fail and then restored:
`drop_practice_kind_added_column` (caught by the parity test and the explicit column test),
a temporary `hands_separate` return in `offer_for` (caught by the closed-set property test),
`drop_kind_basis_guard` (caught by `test_an_offer_is_a_question_until_it_is_answered`),
`let_inference_overwrite_manual` (caught by `test_inference_never_overwrites_a_kind_a_person_chose`),
`wipe_other_sittings_metrics` (caught by the metrics regression guard), and a temporary
`kindCounts` change in `lib/kinds.ts` (caught by the frontend unit).

Verified: backend 858 passing; frontend 76 passing; `svelte-check` 0 errors; build clean; the
practice-log browser scenario passes with four new assertions ("Slow · 0.1 min · 1 segment" beside
"Not characterised · 0 min · 1 segment"); `./check.sh --full` green.

Impact on the other side: two additive nullable columns on `segments`, one new route, and two
additive response fields (`SegmentSummary.practice_kind*`, `AnalyticsSummary.kinds`). `source` and
`workout_id` are unchanged and sight-reading is still owned by them alone — it is deliberately not
one of the seven kinds. `BACKUP_VERSION` is unchanged (the guarantee is one-directional). A
database created by this build reports `user_version = 2`, so an older build refuses it rather than
misreading it. `resegment` still discards kinds along with labels, and still asks first.

## 2026-09-16 — sight-reading agent — Phase 20b planned; a kind-tagged split no longer loses the tag

Scope: `docs/PLAN-PHASE20B.md` (new), `docs/ECOSYSTEM.md`, `backend/app/practice/store.py`,
`backend/tests/test_practice_api.py`, `backend/tools/falsifications/drop_split_kind_inheritance.sh`,
`AGENT-LOG.md`.

Did: wrote the executable plan for Phase 20b (the piano-side toolkit) and fixed a gap 20a left in
the two segment-boundary writers.

**The 20a gap, found while reading `split_segment` for 20c's undo design.** `split_segment` copied
`source` and `workout_id` to the new half and not `practice_kind`, so tagging a segment and then
splitting it silently dropped the tag on one half — and 20c's undo could never restore what was
never carried. Fixed at the owner: a split inherits a **counted** kind (`manual` or `accepted`) to
both halves and drops an unanswered `offered` one from both, because an offer was a question about
the stretch that no longer exists; a merge keeps whichever half carries a counted kind, preferring
the earlier one, mirroring the rule the piece label already follows. Three tests and one break
script, falsified.

**20b's plan.** Six tasks: the controller stream in `midi.ts` plus a pure `pedalGesture.ts`; the
discovery readout and the hands-free action; count-in bars and click volume; hash routes and deep
links; shortcuts and the first overlay in the app; then the browser scenario and docs. Two findings
worth naming here because they are the sharp edges:

1. **`midi.ts` drops every controller but CC64** (`if (status === 0xb0 && first === 64)`), so the
   sostenuto pedal has no path to any handler at all. 20b adds a second, read-only controller
   stream — and deliberately does **not** widen the pedal stream, because `pedal_events` has no
   controller column and `practice/pedal.py` reads it as CC64, so routing CC66 into it would record
   the sostenuto as sustain and corrupt the blur and basis figures.
2. **A preference nobody can observe is a preference nobody can verify.** The browser tier cannot
   hear the metronome, so the practice view now states the count-in it actually derived
   (`data-count-in-beats`), from the same value it hands the metronome rather than from the
   preference — otherwise the falsification would have nothing to fail against.

Impact on the other side: the store.py change is the only server-side one and it is additive
behaviour on an existing column, with no schema, route or wire change. `BACKUP_VERSION` and
`SCHEMA_VERSION` are untouched. 20b itself is client-only: no route, table, column or wire format
changes, and the practice log still means CC64 by `pedal_events`.

Still to plan: 20c (undo, grace-day streak, weekly target), 20d (journal and library depth) and
20e (audio takes).

## 2026-09-16 — sight-reading agent — Phase 20c planned (log trust and habit)

Scope: `docs/PLAN-PHASE20C.md` (new), `AGENT-LOG.md`.

Did: wrote the executable plan for Phase 20c in five tasks — a pure `segmentUndo.ts` that derives
the inverse of an edit by *diffing the segment rows*, the Undo control in `PracticeLogView`, the
grace-day streak, the weekly target, then the browser assertion and docs.

Two things the planning found, both recorded in the plan rather than discovered during execution:

1. **The naive grace-day streak reports one day too many for everybody.** Forgiving the first miss
   you meet extends *every* run by one, because a gap at the end of a run is just the end of the
   run. The rule needs a look-ahead: a rest day is only forgiven when it joins two stretches of
   practice. The plan's code has it and `test_an_unbroken_week_is_unchanged_by_the_grace_rule` is
   the assertion that pins it.
2. **The undo inverse cannot be remembered from the button that was pressed — it has to be derived.**
   `split` keeps the left half in the original row and inserts a new one; `merge` keeps the
   lower-start row and deletes the other. Diffing the two lists gives the inverse for all three
   reversible edits with one function, and returns null for `resegment` (many rows changed) and for
   answering the matcher — which is exactly what keeps the Undo control off the screen when there
   is nothing to reverse.

The plan also states the one thing undo cannot restore: a merge nulls the absorbed segment's
`identification_outcomes.segment_id` (`ON DELETE SET NULL`), so the segments and labels come back
and the matcher's record of one of them does not. The control therefore says "Undo merge" and
claims nothing more.

Impact on the other side: planning only. 20c adds one additive summary field
(`streak_grace_used`), no schema change, no new table — the undo stack is one component field and
dies with the page, which is decision 20-D3 as written.

Still to plan: 20d (journal and library depth) and 20e (audio takes).

## 2026-09-16 — sight-reading agent — Phase 20d planned (journal and library depth)

Scope: `docs/PLAN-PHASE20D.md` (new), `docs/ECOSYSTEM.md`, `AGENT-LOG.md`.

Did: wrote the executable plan for Phase 20d in seven tasks — the four `piece_journal` columns and
the `piece_passages` table, the `neglected()` defect fix, journal tags and two ratings with a take
link, focus passages, the practice read the sorts need, the library and journal UI, then the browser
assertions and docs.

Three findings from planning it, all recorded in the plan:

1. **A new table is a loud failure in the browser tier until it is named.** `e2e_browser.reset_all`
   checks every table in `sqlite_master` against an *explicit* `DATA_TABLES` list, on purpose ("a
   backup must not forget a table; a reset must not silently clear one that a later phase added
   without anyone deciding it should be cleared"). So `piece_passages` must be added to
   `DATA_TABLES` in the schema task, or `--fast` stays green while `--full` fails for a reason that
   has nothing to do with the feature.
2. **A new table needs no backup edit, and the spec said otherwise.** `backup.table_names` reads
   `sqlite_master`, so `piece_passages` is exported and imported with no `backup.py` change and no
   `BACKUP_VERSION` bump. `ECOSYSTEM.md` § Phase 20 claimed it "must join the exported table list";
   corrected here, and 20a's plan never carried the claim.
3. **`by_piece` inner-joins `segments`, so a piece with no practice in the window has no row at
   all** rather than a zero. The library's "least time invested" and "last played" sorts therefore
   read absence as *never played, zero minutes* — which is the strongest form of both answers, and
   the same distinction `neglected()` already draws. The plan states the rule rather than leaving the
   client to guess it.

The plan also keeps 20-D7 honest in a way the design section only implied: seeding a passage from a
recording's A/B loop records *which loop it came from* (`source='loop'`, `media_id` set) while the
bar numbers stay the player's, because converting seconds to bars would need the score alignment
that decision refuses.

Impact on the other side: planning only, plus the one-paragraph correction to `ECOSYSTEM.md`'s schema
note. 20d adds four additive `piece_journal` columns, one table, three repertoire routes, one
practice read and five additive response fields; `SCHEMA_VERSION` goes 2 -> 3 and `BACKUP_VERSION` is
untouched.

Still to plan: 20e (audio takes) — the last one.

## 2026-09-16 — sight-reading agent — Phase 20e planned: the phase is now fully specified

Scope: `docs/PLAN-PHASE20E.md` (new), `docs/ECOSYSTEM.md`, `AGENT-LOG.md`. Planning only; no code,
schema, route or component changed.

Did: wrote the executable plan for 20e (audio takes) in six tasks — the segment gap on the wire, four
`media` columns, attachment by epoch range, the capture client with a pure cutter, the takes view and
the playback rate, then the kiosk permission, the browser proof and the docs. **With 20a landed and
20b–20e planned, Phase 20 is fully specified**: five slices, five plans, every acceptance bullet
traced to a task.

Findings from planning it, each recorded in the plan:

1. **The store function is `create_media`, keyword-only — there is no `insert_media`.** The first
   draft of the plan invented one, with a positional signature, which would have broken the three
   existing callers (recording upload, score upload, legacy importer). Corrected: the four new
   arguments are keyword-only with defaults, so all three keep writing `source='uploaded'` untouched.
2. **A `MediaRecorder` blob must be given a `.webm` filename.** `_stage_upload` takes the suffix from
   `file.filename` and `store_recording` refuses anything outside `KNOWN_SUFFIXES`, so an unnamed
   blob is a 422 *even though* `.webm` is accepted and the pipeline already transcodes it to Opus.
   The failure would read as a format problem rather than a naming one.
3. **The segment gap belongs on `PracticeStatus`, not `HostInfo`.** `HostInfo`'s own docstring scopes
   it to "what this machine can see", and `ProfileOut` is the scoring and exercise settings surface;
   the segment gap is the practice domain's own rule, so it goes on the practice domain's own status.
   There is deliberately **no local fallback constant** — a server that cannot report its gap refuses
   the arming, because a take cut in the wrong place is worse than a take not recorded.
4. **The speed control is inside `{#if open}`**, so the browser scenario has to open the waveform
   before it can select a rate; and `preservesPitch` needs the `webkitPreservesPitch` spelling too,
   because a kiosk is exactly the kind of machine that runs an older Chromium.
5. **`AudioCaptureAllowed: false` is the half that is easy to get wrong.** Without it Chromium grants
   audio capture to *every* origin, not only the two named in `AudioCaptureAllowedForUrls`.

Impact on the other side: planning only. When 20e lands it adds four additive nullable `media`
columns (`SCHEMA_VERSION` 3 -> 4), one new route `POST /api/repertoire/takes`, one field on
`PracticeStatus`, one field on `SystemStatus`, and `AudioCaptureAllowedForUrls` in the kiosk policy —
which the deployment documents must describe at that point.

The phase's remaining work is execution: 20b, 20c, 20d and 20e in order, each with its plan already
written against the tree as it then stands.

## 2026-09-16 — sight-reading agent — Phase 21 landed: the blur tells you where, and an edit stops reloading the world

Scope: `backend/app/practice/{pedal,schema,store,models}.py`, `backend/app/db.py`,
`backend/tests/{test_pedal,test_practice_store,test_migration_upgrade}.py`,
`backend/tools/{e2e_browser.py,falsifications/}`, `frontend/src/lib/types.ts`,
`frontend/src/components/{SegmentTimeline,PracticeLogView}.svelte`, `docs/`, `README.md`.

Did: the two fixes the user asked for ahead of the remaining Phase 20 slices, both planned in
`docs/PLAN-PHASE21.md`.

**The blur count had no places.** `blurs()` counted attacks and threw away the onsets it had just
computed. It is now `blur_attacks()`, with `blurs()` defined as its length so the number and the
places cannot disagree, and the positions are cached in `segment_metrics.pedal_blur_ms` by the
`_refresh_metrics` pass that already computes the count with the notes and the pedal stream in hand.
The sitting strip draws a hairline at each one and the segment row reads "at 0:01, …" (capped at
four, full list in the tooltip). `SCHEMA_VERSION` 2 -> 3.

**Every edit reloaded the world.** Measured read-only against the live installation before touching
anything: `/api/practice/autotag/quality` **866 ms**, `summary` 96 ms, `sittings` 56 ms,
`ratings` 53 ms, `system` 16 ms, detail 12 ms — awaited in series by `load()` after every label,
split, merge and kind change, with the mutation's own response thrown away. `load()` is now split:
`edit()` applies the segments the mutation already returned and refreshes only `refreshTotals()`
(summary + list, ~96 ms in parallel), while the three panels load together via `allSettled` on mount
and on Refresh. `resegment` is the one exception and refetches the matcher's panel explicitly,
because it rebuilds the rows that panel is measured from.

**Three mistakes of my own, kept because they are the instructive kind.**

1. The plan's second example chord would not have produced a blur — it shared two pitch classes with
   what was ringing, so only one was new, against a threshold of three. Caught by running the rule
   before writing the test, and corrected in the plan.
2. The store invariant fixture started with **one** blur, so truncating the positions to one position
   still passed it: the break only showed up in the pedal unit test. The fixture now carries two.
3. My first insertion point for the new browser assertions changed *which sitting* the scenario's own
   tagging step landed on, so the target piece's measured minutes rounded to "0 min played" and an
   existing assertion failed. Moved both blocks to the end of the scenario, where they cannot
   redirect the steps that came before them. (The first attempt at *that* landed the block in
   `scenario_perfect`, because the console-error check I anchored on appears in every scenario.)

**Falsified, not merely green.** `drop_blur_positions.sh` (truncating the positions to one) fails both
the pedal unit test and the strengthened store invariant. `reload_everything_after_an_edit.sh`
(restoring `await load()` in `edit()`) fails the browser assertion *"but not the matcher's accuracy,
which a label cannot change"*.

**One gap closed after the first green run, because the user's own library is in it.** The column is
new, so a sitting segmented *before* Phase 21 has the blur count and no places — which is the state
their 14-blur sitting is in, and exactly what the feature exists to fix. Rather than a startup
migration that recomputes every sitting on every machine (including ones that never open the Log),
the first read of a sitting brings its own cache up to date: `ensure_segments` already decides "these
segments exist", so it is the one place that knows the work is needed. `drop_blur_backfill.sh`
falsifies it.

Verified: backend **867 passed**; frontend 76; `svelte-check` clean; build clean; the practice-log
scenario passes with six new assertions, including that an edit refreshes the totals and does **not**
fetch `/autotag/quality` or `/api/status/system`; three falsifications run; `./check.sh --full` green
in **548 s** before the backfill, and re-run after it.

Impact on the other side: planning documents were corrected for running this out of order —
`SCHEMA_VERSION` is now 3, so PLAN-PHASE20D's "2 → 3" is 3 → 4 and PLAN-PHASE20E's "3 → 4" is 4 → 5
(both plans now say so at the top), and PLAN-PHASE20C gained a note that Phase 21 rewrote the
`edit()` function its Task 2 also rewrites, so its anchor text must be re-read at execution time.
No route, table or wire format was removed; `segment_metrics` gained one nullable column and
`SegmentMetricsOut` one list.

## 2026-09-17 — sight-reading agent — Phase 20e landed (audio takes), out of order and with one repair the plan could not have caught

Scope: `backend/app/{practice,repertoire}` (schema, store, models, api), `backend/app/{db,models,main}.py`,
`backend/tests/{test_repertoire,test_migration_upgrade,test_practice_api}.py`,
`backend/tools/e2e_browser.py`, `backend/tools/falsifications/` (three new scripts),
`frontend/src/lib/{audioCut,audioCapture,audioCut.test,api,types,state.svelte}.ts`,
`frontend/src/components/{DeviceBar,TakeList,RecordingPlayer,RepertoireView,PracticeLogView}.svelte`,
`deploy/{chromium-policy.json,README.md,install.sh}`, `docs/{DEPLOYMENT,ECOSYSTEM}.md`, `README.md`.

Did: a captured take is an **ordinary media row** — content-hashed, probed, transcoded, with a
waveform and an A/B loop — so the whole library pipeline applies unchanged. `media` gains four
additive nullable columns (`source`, `sitting_id`, `segment_id`, `captured_start_ms`), the four reads
and `create_media` learn them, and `source` defaults to `'uploaded'` so every pre-existing row is
already correct. `POST /api/repertoire/takes` takes a multipart file plus the absolute epoch the
chunk started at, reuses `_stage_upload` and `store_recording` wholesale (so the size cap and the
hashing cannot diverge from the recording upload), and refuses byte-identical audio with a 409 that
names where it already lives. `PracticeStatus.segment_gap_s` is the only copy of the cutting rule:
the client cuts on the server's gap and there is no local fallback — a server that cannot report it
refuses the arming. `audioCut.ts` is the pure cutter, `audioCapture.ts` mirrors `CaptureClient`, and
the device bar arms it, classifying `getUserMedia`'s failure into *denied* and *unavailable*, both
rendered, because a switch that looks armed and records nothing is the failure this exists to avoid.
`TakeList.svelte` shows the takes of a piece with any two side by side; `RecordingPlayer` gains
0.85×/0.7×/0.5× with a readout that says whether pitch is held.

**The plan's central mechanism did not work, and the browser scenario was right to fail on it.**
Segments are materialised only for a *closed* sitting (`practice/store.py:ensure_segments`), and a
take is cut eight seconds after the player stops while the sitting stays open for the five-minute
gap. So at upload time there is no segment, `segment_id`/`piece_id` stay NULL, and the plan's
recovery — "the next take uploaded for that sitting" — is unreachable, because after a sitting closes
no new take can carry an epoch inside it. The user chose **catch-up on read**: `_catch_up_takes()`
runs on every take upload and on the piece read the takes view makes, asks the practice domain to
finish its own segmentation via `ensure_segments` (practice still writes `segments`, and it refuses a
still-open sitting, which is right), then sweeps `media` for takes missing a segment *or* a piece
(repertoire still writes `media`). A take whose segment is labelled later is picked up on the next
read instead of staying invisible. `drop_take_catch_up.sh` falsifies it.

**The browser run then found a second defect the unit test could not.** `lastNoteMs` is the newest
note any port has ever heard and never clears, so `shouldStart({lastNoteMs !== null})` re-opened a
take the instant the previous one closed and recorded silence for ever — two takes from one phrase,
and one every nine seconds thereafter. `shouldStart` now takes `takenThroughMs` (the newest note a
take already holds), which the client advances when it closes a take and sets on arming. The pure
unit that "a take starts on the first note" was true and still wrong; only the scenario that plays a
phrase and counts the takes could say so.

**One deliberate departure from the plan's migration advice, with its reason.** The plan held that
`ADDED_COLUMNS` "carries only a type string" and therefore could not express `DEFAULT 'uploaded'`,
accepting NULL on upgraded rows and normalising on read. That is not so: SQLite accepts a constant
default on `ADD COLUMN`, so the entry is `TEXT NOT NULL DEFAULT 'uploaded'`. A NULL would have been
exported by name and restored into a fresh database's NOT NULL column, where `merge` drops the row
silently and `replace` fails outright — the one path this phase could have broken for the machine
move the backup exists for. Same columns, no read-time workaround. `SCHEMA_VERSION` goes **3 → 4**,
not the plan's "4 → 5", because 20d has not landed; 20d's plan must become 4 → 5.

**Also repaired from an independent review of Tasks 1–3** (each reproduced before fixing):
`store_recording`'s `MediaError` was uncaught on the take route, so an unnamed `MediaRecorder` blob
was a 500 where the plan documents a 422; `sitting_at` used the bare note range instead of the
ingest rule (`ended_ms + sitting_gap_s`), refusing audio a beat after the last release, and it
deliberately does *not* require `closed_ms IS NULL` — a sitting closed by the piano going away still
owns the take being recorded; `found` is resolved after the transcode rather than before it, so a
concurrent `resegment` cannot turn into a foreign-key 500; and the client sends the **note that
opened the take** as its epoch, not the tick that noticed it, because a tick can be a second late and
an epoch from it falls outside the phrase it recorded.

`deploy/chromium-policy.json` gains `AudioCaptureAllowedForUrls` for `localhost`/`127.0.0.1` **and**
`AudioCaptureAllowed: false`. The boolean is the half that is easy to get wrong: left unset, Chromium
*prompts* for every other origin rather than refusing it, which on a kiosk is a question nobody can
answer; `false` keeps the named origins' grant and refuses the rest silently. Both documents say it
that way, and the installer's own echo now names the microphone.

Impact on the other side: **the phase is not complete** — 20b, 20c and 20d remain planned, and 20e
shipped without 20b's pedal arm/stop gesture, so the device-bar button is the only way to arm capture.
`SCHEMA_VERSION` 4 means 20d's planned bump is now 4 → 5, and 20c/20d must re-read their anchors:
`repertoire/store.py`'s media reads, `create_media` and `api.py`'s route table have all changed shape.
`GET /api/repertoire/pieces/{id}` now writes (it may attach waiting takes); it is idempotent and
bounded by the unplaced takes in the library, and it is the same "read path that writes" pattern
`ensure_segments` already uses. No route changed shape, no table was added, `BACKUP_VERSION` is
unchanged, and the recording upload still writes `source='uploaded'`.

**A second, adversarial review of the final tree found four things worth fixing, all verified before
the fix.** (1) Write-on-read made the catch-up racy: `db.transaction` used a deferred `BEGIN`, so the
sweep's SELECT fixed a snapshot and a commit from another connection in between turned its UPDATE into
`OperationalError: database is locked` — `SQLITE_BUSY_SNAPSHOT`, which `busy_timeout` does *not*
retry, on a plain piece GET (reproduced with two threads in three lines). `db.transaction` gained
`immediate=True` (`BEGIN IMMEDIATE`) and it is used by the sweep, by the take insert — which had the
same read-then-write shape behind its documented 409 — and by `ensure_segments`, which a read route
now calls. That last change made the pre-existing half of the defect surface immediately: the full
tier then failed with `sqlite3.OperationalError: database is locked` at `practice/store.py`'s `ingest`,
because **every** write transaction in the practice store reads a row and then writes what it read
(`_find_sitting` then INSERT, `_segment_or_raise` then UPDATE, and so on), so each could have its
snapshot invalidated by any other writer. All nine are now `BEGIN IMMEDIATE`, which is the invariant
`db.transaction` documents; the full browser suite is green again. This is a pre-existing latent bug
in a design that explicitly has two machines writing the file, not something written here — but a
read route that writes is what made it reproducible. (2) Arming while the note log was paused produced takes the server refused and the client
silently discarded, which is the exact failure 20e-D1 exists to prevent: the switch now refuses to arm
without logging and MIDI, saying why, and pausing the log stops an armed switch rather than leaving it
lying; the browser scenario asserts the refusal. (3) `close()` could strand itself for ever if the
recorder had already stopped (a device going away means `onstop` never fires again), and it held
`busy` across the upload, so a slow server stopped all further recording; the blob is now built
defensively and the switch is free to record again while the upload is in flight. (4) The segment gap
was captured from the first arm's closure, contradicting 20e-D2's "from the server, every time" — it
is a field refreshed on every arm. Smaller: a nonsense `started_ms` is now a 422 rather than an
overflow 500, `link_unlinked_takes` uses `COALESCE` on `segment_id` so a re-read can fill a missing
piece without ever moving a take to another passage, `loadSegments` takes the media rows it was given
rather than reading mutable state, the pitch readout reports property *support* instead of reading
back a value it just wrote, and the unused `captured` counter is gone.

**One acceptance bullet is measured unmet, and it is a spec/plan conflict rather than a slip.**
ECOSYSTEM § 20e asks for "a take whose duration is within a second of the notes it covers". The plan
cuts a take on the server's own silence gap, which necessarily appends that whole gap to the file, so
the file is the phrase *plus* the silence that ended it. Measured in the browser run: take 64 is
**7.99 s for a 0.350 s passage** (7.64 s of trailing silence) and take 65 is **8.95 s for 0.350 s**.
Attaching, playing and comparing are all unaffected — the take is a correct recording, just a padded
one — and nothing in the plan's six decisions asks for a trim. Closing it means cutting the stored
audio to the last note at upload (the notes are already ingested, so `note_events` can supply the
end; `store_recording` would need a limit), which is a change to the shared pipeline and outside what
the plan authorized, so it is recorded here rather than done quietly. A second, smaller residual: the
recorder polls once a second, so a take can miss up to the first second of the phrase that opened it —
quality, which 20-D4 explicitly does not make an acceptance criterion.

Verified: backend **882 passed**; frontend 81; `svelte-check` clean; build clean; the new `takes`
browser scenario passes seventeen assertions against a fake microphone, including that the switch
refuses to arm while the log is paused, that two takes attach to *their own* passages rather than both
to the first, that both render for comparison, that 0.5× reaches one element and leaves the other
alone with the same-pitch readout, and that a loop marker saved on one take leaves the other unmarked;
four falsifications run and caught their breaks (`drop_media_source_column.sh`,
`drop_capture_segment_link.sh`, `drop_take_catch_up.sh`, `cut_takes_at_the_wrong_gap.sh`);
`./check.sh --full` green in **566 s** before the review-driven repairs, with `--fast` re-run green
after them.

## 2026-09-17 — sight-reading agent — Phase 20b landed (the piano-side toolkit), after 20e and with two mappings the plan left open

Scope: `frontend/src/lib/{pedalGesture,countIn,route}.ts` + their tests, `frontend/src/lib/midi.ts`,
`state.svelte.ts`, `metronome.ts`, `App.svelte`, `app.css`,
`frontend/src/components/{DeviceBar,PracticeView,CalibrationView,RepertoireView,PracticeLogView,StatsView,CommandPalette}.svelte`,
`backend/tools/e2e_browser.py`, `backend/tools/falsifications/` (four new scripts), `README.md`,
`docs/ECOSYSTEM.md`.

Did: four additive, client-only additions. `midi.ts` gained a **second, read-only controller stream**
(`MonitorController`, `onController`, one emit site) because `handleMessage` dropped every CC but 64
before any handler saw it; `pedalGesture.ts` is the pure decision over those moves; `countIn.ts` turns
the bars preference into beats per meter and `metronome.ts` reads a click volume on the same 0..127
scale as a MIDI velocity; `route.ts` parses and serialises `#/section/entity/id` and the store holds
the route while each view consumes a one-shot pending entity; `CommandPalette.svelte` is the app's
first overlay, over the two searches that already existed plus the recent-sittings list, which has no
endpoint and is therefore filtered client-side **and says so**.

**The one decision a reviewer must check (20b-D4).** `onController` is a *second* stream, not a
widened one. `onPedalMonitor` stays the only thing the practice log consumes and stays CC64-only,
because `pedal_events` has no controller column and `practice/pedal.py` reads it as CC64 — routing the
sostenuto into it would have recorded the middle pedal as sustain and corrupted `pedal_basis` and the
blur figures. `drop_controller_stream.sh` proves the new stream is load-bearing without touching that.

**Two mappings the plan could not have settled, because it was written before 20e.** (1) The plan
named one hands-free action, but the acceptance bullet asks the gesture to "arm and stop capture"
too, so `HandsfreeAction` is `'toggle_workout' | 'toggle_audio_capture'`: the dedicated pedals (CC66,
then CC67) toggle a workout, and the damper's double tap **in silence** arms and stops capture — the
played pedal carries the action reached for least often, and only when nothing is being played. The
pedal path calls the same `toggleAudioCapture` the button does, so it inherits the guards (the log
must be running, the server must report its gap) rather than bypassing them; the bench scenario
asserts both arming and stopping. (2) `ECOSYSTEM`'s acceptance names a deep link to a **take**, and
the plan's route module deliberately refuses one. Resolving a media id to its piece would need a
server lookup, and this slice's compatibility boundary is "no server route, table, column or wire
format changes at all" — so a take is reached through the piece link that lists it, and the gap is
recorded in `ECOSYSTEM.md` rather than papered over.

**Three smaller decisions worth naming.** `exerciseActive` is *derived* from each view's phase
(`countin | playing | submitting`) with an `onDestroy` clearing it, rather than poked in at every
transition: the plan's rule ("every assignment other than countin/playing is an end of run") is easy
to miss one of, and leaving the view mid-run must not leave the hands-free switch inert for the
session. The transport now draws the count-in it **actually derived** (`data-count-in-beats`), because
the browser tier cannot hear a metronome and a preference nobody can observe cannot be falsified. The
palette is a `div[role=dialog]` with the backdrop comparing `event.target` rather than a
`stopPropagation` handler on the panel, which is what keeps `svelte-check` at zero warnings.

Impact on the other side: **client-only.** No route, table, column, wire format, `SCHEMA_VERSION` or
`BACKUP_VERSION` changed, and `pedal_events` still means CC64. 20c and 20d remain planned; 20b landed
after 20e, so the two plans meet here only at `runHandsfree`. The gesture is inert during a scored
attempt, and one press of the sostenuto starts or finishes a workout — the bench scenario asserts
that a press mid-run starts nothing.

**One falsification the plan wrote did not falsify, which is the reason the falsification exists.**
`misroute_a_piece.sh` breaks `routeHash` by dropping the entity, and the plan expected "a piece link
opens that piece" to catch it — but that assertion navigates to a hand-written URL and so exercises
only the *parser*. With the break applied the check passed, and `falsify.sh` said so. The scenario now
also opens a piece by clicking its row and asserts that the app itself wrote
`#/repertoire/piece/<id>`, which is the direction the serialiser break can fail; the falsification
catches it. Worth knowing when running these by hand: `falsify.sh` reverts tracked source with
`git checkout`, and `frontend/dist` is gitignored, so a browser falsification leaves a **broken
build** behind — every one of the three check commands starts with `npm run build` for exactly that
reason, and a manual run after one must rebuild first.

Verified: frontend **97 passed**, `svelte-check` clean, build clean; the new `bench` browser scenario
passes twenty-one assertions (unseen pedal, discovered pedal, workout start/finish, capture arm/stop,
inert during a run, a piece link opening its piece, Back closing it, the palette finding a piece and
Escape closing it, a section URL opening nothing on its own, opening a piece writing its address, two
bars reaching the metronome and surviving a reload, no console errors); four committed falsifications
run and all four caught their breaks (`drop_handsfree_silence_gate.sh` at the unit tier;
`drop_controller_stream.sh`, `ignore_count_in_preference.sh` and `misroute_a_piece.sh` against the
built frontend); `./check.sh --full` green.

## 2026-09-17 — sight-reading agent — Phase 20d landed (journal and library depth), the last slice but 20c

Scope: `backend/app/repertoire/{schema,models,store,api}.py`, `backend/app/{db,practice/{store,api}}.py`,
`backend/tests/{test_migration_upgrade,test_repertoire,test_practice_api}.py`,
`backend/tools/e2e_browser.py`, `backend/tools/falsifications/` (four new scripts),
`frontend/src/lib/{types,api}.ts`, `frontend/src/components/{RepertoireView,PassageList}.svelte`,
`README.md`, `docs/ECOSYSTEM.md`.

Did: four additive `piece_journal` columns (`tags`, `difficulty`, `fluency`, `media_id`), one new
table (`piece_passages`), three repertoire routes and one thin practice read. A **tag** is a JSON
array in one column and the feed filters by label; an entry carries two ratings (how hard it felt,
how well it went) and can point at the take it was written about; a **focus passage** is a bar range
with a note and a *Worked on it* button; the library sorts by last played or by time invested, edits
status in bulk, and remembers the filters and sort. `neglected()` now reports `active` pieces only,
so a piece the player deliberately paused stops nagging — a defect the 20d survey found rather than
a feature. `SCHEMA_VERSION` 4 → 5; `BACKUP_VERSION` unchanged (the table list is derived, and an
older document simply carries no rows for the new table).

**The one boundary a reviewer should check (20-D7).** Nothing here claims to know a score. The bars
are the player's own; `source`/`media_id` record that a passage was seeded from a recording's A/B
loop, not a seconds-to-bars conversion the app cannot make; and `last_worked_on` is only ever set by
a button. `PassageOut.source` is the evidence, and the panel's empty state says in words that the app
cannot find passages for you.

**A reviewer found three real defects, each fixed with a test seen to fail first.** (1) The tag
filter used `LIKE` over the stored JSON, which `db.json_dump` escapes — so `café` was stored as
`caf\u00e9` and a chip the player clicked found nothing, `"` and `\` broke the same way, and `%`/`_`
acted as wildcards that matched other labels. It now matches through `json_each` with `COLLATE
NOCASE`: exact labels, escape-proof, wildcard-proof, case-insensitive.
(2) `PATCH /passages/{id}` with an explicit `null` bar was a 500 — the pair-merge returned `None`
and the comparison raised. Both columns are `NOT NULL`, so a null is now a 422.
(3) Deleting a piece cascaded its passages but did not report them, against the route's own
docstring; `cascaded` now carries `passages`. Also tightened while there: `source='loop'` must name
the recording it came from (a claim about provenance with no loop is a claim about nothing), and
`get_journal_entry` now selects `created_at` so a write response matches the read.

**Two things the plan could not settle, because it was written before 20b and 20e.** The
`ignore_the_tag_filter.sh` break script targeted the old LIKE and had to be rewritten for the new
predicate; and the browser assertions needed adapting in four places where the plan's sketch did not
match the built UI: the feed had no tag pills (so the tag is now one shared `{#entryMeta}`
snippet used by the journal and the feed), the create form's *Add* is disabled without content
so the scenario has to type an entry, the neglected list is `.neglected` rather than `.review`, and
the passage assertions had to wait for the *state* rather than the always-present section — reading
it straight after the POST raced the refresh and read the empty state. `scenario_repertoire` also
has to come back to the piece after the Log-tab assertion, because the rest of that scenario works
on it.

Impact on the other side: **20c is now the only planned slice in Phase 20.** The repertoire domain
still owns `media`, `piece_journal` and now `piece_passages`, and reads practice tables read-only;
the practice route exposes `by_piece` rather than duplicating it, so the library's "least time
invested" and the Log's dashboard cannot disagree — `test_the_piece_practice_read_agrees_with_the_dashboard`
asserts they are equal field for field. A new table is a loud failure in the browser tier until it is
named in `e2e_browser.DATA_TABLES`, which is why `piece_passages` is in the schema task.

**One residual, named rather than papered over.** `RepertoireView.svelte` is **1,864 lines**, past
the ~1,600 its risk table names as the point to stop adding sections. Extracting the library list, as
that table prescribes, would not bring it under the line — the component owns the library list, the
piece detail, the journal, the media list and now the passage panel, and a partial extraction would
add a dozen new props and bindings for no measurable gain. The next addition to it should extract
the library list or the journal panel as a whole, not add a sixth section.

Verified: backend **898 passed**; frontend 97; `svelte-check` clean; build clean; `scenario_repertoire`
passes its four new assertions (the entry carries the tag and the difficulty it was given, the feed
filters by a tag, the passage is listed with the player's bars and *Worked on it* stops it reading
as untouched, and a paused piece is left out of Neglected); four committed falsifications run and all
four caught their breaks (`drop_journal_added_column.sh`, `let_paused_pieces_nag.sh`,
`ignore_the_tag_filter.sh`, `forget_the_passage_provenance.sh`); `./check.sh --full` green.

## 2026-09-17 — sight-reading agent — the two pedal gestures swap actions, at the user's request

Scope: `frontend/src/lib/pedalGesture.ts` and its test, `frontend/src/lib/state.svelte.ts` (the
dispatch comment), `frontend/src/components/DeviceBar.svelte` (the readout), `backend/tools/e2e_browser.py`
(`scenario_bench`), `README.md`, `docs/ECOSYSTEM.md`, `docs/PLAN-PHASE20{B,D}.md` (status lines).

Did: **the sostenuto (CC66, then CC67 as the fallback) now arms and stops audio capture, and the
damper's double tap in silence now toggles a workout** — the exact inverse of what 20b landed a few
hours ago. The reasoning is the one the original mapping got backwards: arming a take is what a
player does every session, so it belongs on the pedal nobody plays, while starting a workout is
rarer and can afford a deliberate double tap. The two gestures stay separate; a single damper tap
still carries nothing.

**The silence gate stays, and that is the part worth stating.** It was never about which action the
damper carried — it is about the damper being *played*: two taps during ordinary pedalling are
pedalling, not a request to start anything. `drop_handsfree_silence_gate.sh` still guards it, and the
bench scenario still asserts that a double tap during a scored attempt starts nothing. A player who
wants an ungated damper would get a workout started mid-piece, so the gate is a safety property
rather than a detail of the mapping.

**What this cost, and what it caught.** The pure module, its four units, the store's dispatch
(a `toggle_audio_capture` branch and a workout branch that did not change), and the device-bar
sentence all had to move together — and the browser scenario's assertions were asserting the *old*
mapping, so they had to be inverted too rather than merely re-run. Because the two actions dispatch
through one function, only the recogniser needed a code change; the wiring, the guards (a take still
cannot arm while the log is paused or with no MIDI) and the pedal-inert-during-a-run rule were
untouched. The 20b plan's Status line now says landed and names the inversion, because its own test
and module snippets show the superseded mapping and a reader would otherwise be misled.

Verified: frontend **97 passed**, `svelte-check` clean, build clean; `scenario_bench` passes all
twenty-one assertions with the new mapping (sostenuto arms then stops the recording; a damper double
tap starts then finishes a workout; a double tap mid-run starts nothing); the silence-gate
falsification still catches its break; `./check.sh --full` green.

## 2026-09-17 — sight-reading agent — the soft pedal is unbound: it is played

Scope: `frontend/src/lib/pedalGesture.ts` and its test, `frontend/src/lib/state.svelte.ts` (the
dispatch comment), `frontend/src/components/DeviceBar.svelte` (the pedals readout),
`backend/tools/e2e_browser.py` (`scenario_bench`),
`backend/tools/falsifications/let_the_soft_pedal_stop_the_take.sh` (new), `README.md`,
`docs/ECOSYSTEM.md`, `docs/PLAN-PHASE20B.md` (status line).

Did: **`HANDSFREE_CONTROLLERS` is now `[66]` alone.** The user reported the defect in use, not in
review: *"I actually do use the soft pedal… tapping it will stop the recording."* The previous
mapping bound CC66 and CC67 to the same arm/stop gesture, on the assumption that both were pedals
nobody plays. That assumption is false for the soft pedal, and the failure mode is the worst one
this feature has — a press mid-phrase silently ends the take being recorded, and the player is
playing, so they will not see it happen. The sostenuto remains the arm/stop gesture; the soft pedal
is bound to nothing at all.

**The pedal report now names the binding, per pedal.** An unbound pedal and a broken feature look
identical from the bench, which is how this got past review in the first place, so each pill in the
Pedals panel reads `<label> · CC<n> · <binding> · <seen state>`: `press: arm or stop a take` for
CC66, `double tap in silence: workout` for CC64, `deliberately not bound` for CC67. The panel's
prose says the same thing and says why.

**Order of work.** The soft-pedal unit test was inverted first and watched to fail (it returned
`toggle_audio_capture` where it now expects `null`), then `HANDSFREE_CONTROLLERS` lost the 67, then
the browser scenario gained two assertions: a soft press while a take is armed leaves
`data-audio-capture="armed"`, and the panel reports `deliberately not bound` rather than leaving the
pedal unexplained. Both are in `scenario_bench`, next to the sostenuto assertions they qualify.

**What was deliberately not added.** The new gesture is *not* silence-gated. The gate on the damper
exists because the damper is played; the sostenuto is not, so a press on it is unambiguous and a
gate would only make arming fail during playing — which is exactly when a player wants to arm. A
player who wants the soft pedal to keep a gesture would need a different action than a take's
arm/stop, because that is the one the pedal's ordinary use collides with.

Verified: frontend **97 passed** (the inverted soft-pedal test is RED before the one-line change and
green after); `svelte-check` clean; build clean; `scenario_bench` green with the two new assertions;
`let_the_soft_pedal_stop_the_take.sh` falsifies both halves — `cd frontend && npm test` caught the
unit break, and the browser check (`(cd frontend && npm run build) && backend/tools/run_e2e.sh
bench`) caught it end to end at "and the soft pedal, which is played, leaves the armed take alone";
`drop_the_pedal_binding_readout.sh` (new) likewise caught only the panel-text assertion, so that
string is not resting on a check nobody has seen fail; `frontend/dist` was rebuilt after each
browser falsification, since it is gitignored and `falsify.sh` leaves the broken bundle in it;
`./check.sh --fast` green in 72s, and `./check.sh --full` green in 518s (backend suite, coverage, the
whole browser tier and the mutation report) against commit `3aee82c`; this paragraph is the only
change after it.

## 2026-09-20 — sight-reading agent — the microphone was refused by a policy key that does not exist

Scope: `deploy/chromium-policy.json`, `deploy/browser.test.sh`, `check.sh`, `deploy/README.md`,
`docs/DEPLOYMENT.md`, `docs/ECOSYSTEM.md`, `docs/PLAN-PHASE20E.md`, `docs/PLAN-PHASE8-9.md`,
`backend/tools/falsifications/invent_a_microphone_policy_name.sh` (new).

The user reported it from the bench, testing audio capture for the first time: *"The browser refused
microphone."* The attached kiosk log (`~/.local/state/piano-kiosk.log`) has **nothing about the
microphone in it** — no media error, no permission line, no crash on that path — and that silence was
the first real clue rather than a missing one: a policy denial produces no log line at all.

**Did.** `deploy/chromium-policy.json` named the microphone allow-list `AudioCaptureAllowedForUrls`.
**Chromium has no such policy.** Its capture policies are `AudioCaptureAllowed` and
`AudioCaptureAllowedUrls`; the `...ForUrls` suffix belongs to content settings, and the file's own
`MidiAllowedForUrls` on the line above is exactly that shape, which is why the name looked like a
template. Checked against Chromium's own index rather than a docs page:
`components/policy/resources/templates/policies.yaml` at **the tag the notebook actually runs**
(`refs/tags/152.0.7977.82`, the version in the log) — 1544 policies, listing `AudioCaptureAllowed`
and `AudioCaptureAllowedUrls`, and no `AudioCaptureAllowedForUrls`. The schema
text of `AudioCaptureAllowed` is what makes the misspelling fatal rather than cosmetic: *"Setting the
policy to Disabled turns off prompts, and audio capture is only available to URLs set in the
AudioCaptureAllowedUrls list."* The file sets `AudioCaptureAllowed: false`, so prompts were off and
the only permitted URLs were the ones in a list Chromium never read — an allow-list of nothing. Every
origin, `http://localhost:8000` included, was refused with no dialog; `getUserMedia` rejected with
`NotAllowedError`, which is precisely the `data-audio-device="denied"` sentence the DeviceBar already
had. One key was renamed.

**Why nothing caught it, three ways.** The line above it is inert too, and nobody could tell:
the same index at the same tag has **no MIDI policy at all** — no `MidiAllowedForUrls`, no
`MidiSysexAllowedForUrls`, nothing — while MIDI works on the notebook regardless. Why it works is not
something this log settles: either that build does not gate non-sysex Web MIDI behind a prompt, or the
kiosk profile carries a grant remembered from an earlier click (the installer's own flatpak note tells
the operator to click Allow once and says the profile remembers it). Either way the MIDI key is not
doing it, so the file *looked* like it was working and could not be checked by the one feature next to
it. The browser tier launches Chromium
with `--use-fake-ui-for-media-stream` against a machine with no managed policy installed, so it
grants the microphone by flag and never touches the file. And `deploy/browser.test.sh` existed with
ten passing cases and was wired into **nothing**, so `./check.sh --fast` never read the policy.

**What was added, and what was deliberately not.** The policy file's keys are now pinned in
`deploy/browser.test.sh` against Chromium's index — adding a policy means looking its name up, which
is the step whose absence shipped this — and that file is now a `check.sh --fast` step, so the
assertions are executed rather than admired. `MidiAllowedForUrls` is kept on purpose: it is a real
name on the builds that gate Web MIDI, it costs nothing where it is not, and removing it would break
those builds to tidy a file. The frontend is untouched: its `denied` sentence was accurate and is now
actionable. No install-time "unknown policy" warning was added — that needs Chromium's policy list at
install time, and the pinned names in the repo test give the same protection earlier and offline.

**Falsified before it was trusted.** The new cases were run against the *unfixed* file first: five
fail (`the microphone allow-list uses Chromium's name`, the invented spelling still present, both
loopback origins not granted, and `every key is a policy name that was looked up, not guessed`),
0.15 s; after the rename all seventeen pass. The break is kept as
`invent_a_microphone_policy_name.sh` and was rehearsed the way `falsify.sh` would run it — applied,
caught by `bash deploy/browser.test.sh` (exit 1), restored, green — so re-certifying the guard does
not depend on this paragraph. The plan snippets that carried the wrong name were annotated in place
(`PLAN-PHASE20E.md`, and the `PLAN-PHASE8-9.md` MIDI rationale it was copied from), because a reader
copying from them would otherwise re-ship the defect.

**To fix the notebook** (the code being right is not the machine being right): `git pull` and
`sudo ./deploy/install.sh` there — it is idempotent and rewrites the managed policy — then click
*Record takes*; both policies are `dynamic_refresh: true`, so no reboot and no kiosk restart is
needed. `chrome://policy` in the kiosk profile should now show `AudioCaptureAllowedUrls` with the two
loopback origins, and the device bar should read `microphone ready`.

Verified: `bash deploy/browser.test.sh` green (17 cases, five of them new and seen to fail first);
`./check.sh --fast` green in 74 s with `deploy tests` wired in as its own step (0 s of that, and the
only step that reads the policy file). The changes after that run are this entry, the corrected prose
in the two plans, and the break script — no behaviour, and the policy file is byte-identical to the
one it was run against.

## 2026-09-20 — sight-reading agent — the synthesiser and the sampled piano were scheduled onto a clock nobody started

Scope: `frontend/src/lib/pianoPlayer.ts`, `backend/tools/e2e_browser.py` (`AUDIO_TAP` and
`scenario_playback`), `backend/tools/falsifications/let_the_part_ride_a_stopped_transport.sh` (new),
`README.md`, `docs/ECOSYSTEM.md`, `docs/TEST-STRATEGY.md`.

The user reported it from use, not from review: *the piano itself plays, and neither the
synthesiser nor the Salamander samples make a sound* — on the piano machine, on their phone and on
their personal computer — *while both report that audio is ready*. Three machines is what made it a
code bug rather than a device one, and "audio is ready" was true the whole time.

**Did.** `playThrough` built a `Tone.Part` and called `part.start(Tone.now() + LEAD_IN_S)`. A
`Tone.Part` does not schedule on the audio clock. `ToneEvent.start()` converts its time with
`toTicks` and hands every event to `this.context.transport.schedule`
(`tone/build/esm/event/ToneEvent.js:95`), and a stopped Transport never fires them — and nothing in
this app has *ever* started the Transport (`grep -rn "Transport" frontend/src` returned nothing).
So the part was cancelled correctly by Stop, `data-playing` was right, the position advanced from
`performance.now()`, the context reported `running`, and not one note was ever going to sound. The
fix starts the clock the part rides and stops it with the part: `transport.stop()`,
`transport.cancel(0)`, `transport.seconds = 0`, then `part.start(0)` — the part's event times are
onsets within the material, so its zero is the Transport's zero — then
`transport.start(Tone.now() + LEAD_IN_S)` carries the lead-in. `stop()` clears the Transport inside
the existing `if (this.part)` block, so a stop with nothing playing never builds an audio context.

**Why MIDI and the metronome were never affected.** Web MIDI does not touch Tone at all, which is
why "through the piano" was the one instrument that worked. The metronome calls
`triggerAttackRelease(freq, dur, absoluteTime)`; `Source.start` schedules on the audio clock unless
`.sync()` has been called (`tone/build/esm/source/Source.js:124-168`), and nothing here syncs. Only
`Part`/`ToneEvent` ride the Transport — which is exactly why the Part was chosen (a note scheduled
four seconds out has to be cancellable by Stop, and `releaseAll()` only releases what is already
sounding), and exactly why the one class that needs the Transport is the one that was silent.

**The old assertion said sound was unobservable, and that was the bug's habitat.** `scenario_playback`
contained, in as many words, *"Nothing here asserts sound — that is not observable from a test"*.
It is observable: an `AnalyserNode` connected in parallel with the master output reads what the
speakers get, and it does not change what is heard. The harness now injects `AUDIO_TAP` before any
page script — it hooks the last `connect(destination)` hop, keeps the loudest sample since the last
reset, and samples every 16 ms — and `scenario_playback` requires the output to be **silent before**
the chord and **non-zero during** it, for the sampled piano and the synthesiser. Measured: piano
`peak 0` before the fix, `0.151` after; synthesiser `0.120`. The `--mute-audio` the suite launches
with mutes the output *device*, not the graph, which is what lets the tap work underneath it.

**Falsified before it was trusted.** `let_the_part_ride_a_stopped_transport.sh` puts the bug back —
`part.start(start)` with no Transport start — and the scenario fails at *"the sampled piano puts
sound on the master output (peak 0)"*; restored, it passes. One trap worth recording: the browser is
served `frontend/dist`, which is gitignored, so a falsification of frontend behaviour that does not
`npm run build` first proves nothing at all.

**A skip narrowed while here.** The synthesiser arm of `scenario_playback` was nested inside
`if installed["available"]:`, so a machine without the samples skipped the synthesiser too — the one
instrument that is always available, and in practice the one a viewer with no piano hears. It sits
outside that branch now and asserts sound unconditionally; `TEST-STRATEGY.md`'s register of
self-skipping green ticks carries the correction rather than being left to claim otherwise.

**What was deliberately not asserted.** Stop's effect on Tone playback: the Test chord is under a
second, so it falls silent on its own and an assertion about the silence would pass with Stop
deleted. The cancellation that can be observed is MIDI's, and the scenario already checks that
exhaustively. Notes are in the file where the temptation would be.

No frontend unit test was added: `node --test` has no Web Audio, and a test of the player would have
to be a browser test, which is what this now is.

Verified: `scenario_playback` green — 38 assertions, three of them new and seen to fail first; the
**whole browser tier** green (`backend/tools/run_e2e.sh`, all fourteen scenarios) rather than only
the playback one, because the change makes the player a second owner of the global Transport clock
and the metronome scenarios had to be re-run rather than assumed; `./check.sh --fast` green.

## 2026-09-20 — sight-reading agent — the app is renamed Opus Note, and the bar it was hiding behind

The product is called **Opus Note** now. The user chose the name; the plan is
`docs/PLAN-OPUS-NOTE-IDENTITY.md`. Four slices landed, each verified by `./check.sh --fast` and the
whole browser tier, not just the scenario being edited.

**The rename is display-only, and that boundary is the point.** What changed is what a *person*
reads: the `<h1>`, `<title>`, meta description, favicon, README, `package.json` description, and the
FastAPI title (which is user-visible at `/docs`, so leaving it would have been the app still
introducing itself by the old name). What deliberately did **not** change: `SRT_*` environment
variables, `srt.*` browser storage, the data directories, the service names, the `sight_reading`
practice source and the `#/repertoire/*` routes. Those are domain language and durable surfaces, not
branding — renaming them would have risked the deployed piano machine to buy nothing a reader can
see. The README says so out loud, so the next person does not "finish the job".

**Slice 0 existed to de-risk the rename, and it found the suite already red.** Sixteen call sites in
`e2e_browser.py` used `text=Sight-Reading Trainer` as the app-ready sentinel, so renaming the `<h1>`
would have broken all fourteen scenarios at their first assertion — and the failure would have
pointed at the brand rather than at anything real. They now wait on `[data-app-ready]`, a hook the
app owns, in the same style as the other ninety-odd `data-*` markers the suite already keys off.
While doing that, `check.sh --fast` turned out to be failing *before* any of this work: commit
`90fdb93` ("Remove workout from sustain (Human Decision)") had disabled the damper double-tap but
left its retirement unfinished in six places, two of them user-facing. The app was telling the reader
that the damper starts a workout when a damper tap did nothing at all. The user chose to finish the
retirement rather than restore it, so the dead branch, its constants, the unreachable
`toggle_workout` member and the now-pointless `lastNoteMs` parameter are gone, and the label, the
README, the unit tests and `scenario_bench` all agree with the code. The bench assertion that a
gesture is inert during a scored attempt was retargeted at the sostenuto — the live gesture — rather
than deleted, so it now proves something true.

**The identity is ivory and petrol, in one owner.** `app.css` holds the palette; `--chart-*` are
declared as `var(--accent)`/`var(--good)`/`var(--warn)` and `theme.svelte.ts` reads them through
`getComputedStyle`, which removed six hex literals that had been copied into TypeScript and could
drift. Verified, not assumed: browsers substitute `var()` inside a custom property at computed-value
time (probed against Chromium before relying on it), and `color-mix()` deliberately does *not*
resolve — it is left for `fill: var(--radar-fill)` to evaluate, which is why the audit checks for a
dangling `var()` rather than for a resolved colour. A contrast audit over 28 token pairs in both
themes passes at ≥4.5:1.

**The font is one weight because the first attempt shipped two.** Spectral 400 was included, and
Chromium never fetched it: only `h1`/`h2` use the serif and both are semibold. A dead 21 kB in an app
whose whole point is that play time touches no network. Removed, with the reason left in the CSS.

**One real defect found by looking rather than by testing.** The dark-mode screenshot showed the
journal's search and tag fields as white boxes: the shared control rule covered `select` and
`input[type='number']` and nothing else, so every text input fell back to the UA's white. Invisible
on a white page, glaring on a dark one. Fixed, and `accent-color` now themes the slider and the
checkbox so the app's one non-palette colour — the browser's default blue — is gone too.

**The device bar is one line.** `DeviceBar.svelte` (409 lines, ten concerns: status, ports, pedals,
latency, count-in, click, instrument, sample install, test, capture) became `DeviceStatus.svelte`
(state you must *notice*) and `SetupPanel.svelte` (everything you configure). `Calibrate` is off the
tab bar — it is a diagnostic, and it was sitting as a peer of Practice — and `Repertoire` is
`Library`. The split has a rule: **state stays, configuration goes.** Three things stayed in tier 1
against the plan's tidy-up: the take switch (a standing switch whose failure mode is the trap the
module exists to prevent), the audio state (`suspended` is the commonest cause of silence and is
invisible everywhere else) and the latency offer (an offer in a closed drawer is not an offer).

The plan was wrong in three further places and the code was right, which is recorded in §6.2 of it
rather than quietly worked around: `WorkoutBar` stays app-wide because the suite asserts a workout
can be started from anywhere, `HostBanner` stays inline because it is a warning and warnings in
drawers are not read, and the navigation is four sections rather than three until the Progress/Log
merge is done as its own change.

**A note for next time.** The first pass at migrating the browser suite was driven off an inventory
of `data-*` hooks, and it missed `data-audio-note` (not on the list) and `#count-in` (a plain
element id). Each cost a full browser run. A hook inventory is not an inventory of how the suite is
coupled to the DOM — grep the ids and the role names too.

One falsification script was retired rather than repaired: `drop_handsfree_silence_gate.sh` broke the
silence gate that no longer exists, so it could only ever report a false alarm.
`drop_the_pedal_binding_readout.sh` was retargeted at `SetupPanel.svelte`; its needle still matches
unchanged.

Verified: `./check.sh --fast` green at every slice; **all fourteen browser scenarios, 420 checks** —
the same 420 as before the device bar was restructured, which is the evidence that moving the markup
did not quietly drop an assertion; a token/contrast audit over both themes; and screenshots in light
and dark, which is how the white-input defect was found at all.

**Slices 4–6, and the end of the plan.** The navigation is three sections now — Practice, Library,
Progress — and Progress holds **Ratings** and **Log** as two views of one question, which is what
they always were: two tabs a reader could not tell apart from the outside. The merge is
*navigation-only*, and the evidence is that `route.ts` was not touched: `stats` and `log` are still
separate views with separate routes, so a pasted `#/stats/attempt/56` or `#/log/sitting/34` opens
exactly what it names. Checked by hand rather than assumed — every documented route was loaded in
Chromium and reported the right view, and `#/nonsense/1/2` correctly left the app where it was,
which is what the parser documents itself as doing.

A tab now carries `owns: AppView[]`, so clicking the section you are already in is a no-op instead
of shuffling you between Progress' two views, and arriving from elsewhere returns you to the one you
last used — remembered for the session, not persisted. `1`–`3` replaces `1`–`4`.

**Two bugs in the skill radar that no test could have caught.** The Progress screenshot showed a
label reading *"in And Dynamics"* sitting on top of *"KeysSignatures"*. Two independent causes: the
axis names already arrive correctly cased and `text-transform: capitalize` was turning
"Articulation and dynamics" into "Articulation And Dynamics"; and that name is 25 characters, which
at the 9 o'clock position ran off the left of the viewBox and collided with its neighbour. Both
fixed by removing the transform and word-wrapping to two lines. A wrap needing a third line folds
the remainder onto the second rather than truncating, because a truncated axis name is a wrong axis
name. Worth recording as a method note: **a screenshot found what 420 assertions did not**, and this
is the second defect this session that only looking could find — the white dark-mode inputs were the
first.

**One invariant hardened against a gap rather than a failure.** `[data-playing='true'] .setup`
now hides the Setup panel. No scenario opens Setup mid-run, so nothing would ever have caught the
panel competing with the score for height — and the music never being allowed to scroll is the one
thing this app exists to train against, so it is written down where the tests are silent.

**What was deliberately not done, and why it is recorded rather than done.** A dozen components
still carry 7/8/9px radii where `--radius-sm` exists. At those sizes the difference is invisible and
the sweep would touch a dozen files for no visual gain: that is diff noise, not polish. The tokens
are there for new work. `RepertoireView` (1867 lines, carrying list, detail, editor, journal,
passages, scores, recordings and takes) is still one component; splitting it is a layout refactor
rather than an identity change, and it is the largest and least identity-critical file in the app.

**On `--full`.** Its mutation tier was not run: `backend/setup.cfg` mutates all of `backend/app`
against 883 tests and describes the score as *"a report, not a gate"*, so it neither gates nor
terminates in a bounded time. The browser tier that `--full` actually adds — the part this work
could break — was run at every slice and is green. Stated here so the omission is a decision on the
record rather than a gap somebody finds later.

**The README was then restructured, at the user's request, for presentation.** The old one was 699
lines of genuinely good engineering writing that had become a diary: excellent as documentation and
poor as a front page, because a reader arriving at the repository met the hard-won detail before
they met the project. It is now three documents with one job each:

| File | Role | Lines |
| --- | --- | --- |
| `README.md` | Front page: what it is, screenshots, architecture, quick start, the adaptive hook, verification, doc index, limitations, credits | 261 |
| `docs/FEATURES.md` | Reference for every feature's behaviour | 338 |
| `docs/ENGINEERING.md` | Difficulty model, adaptive engine derivation, scorer, timing, integration notes, configuration | 221 |

**Nothing was dropped, and that was checked mechanically rather than by eye.** The old README was
diffed against the three new documents for 86 distinctive tokens — CamelCase names, snake_case
identifiers, `SRT_*` variables, numbers with units, code spans. Five were absent at the end, all
trivial (`MVP`, a `$PWD` false positive, the term `SPA`, a test scenario name, and "2 bars" which
the new text spells "two bars"). One substantive gap was found by that check and restored: the
**LAN viewer** boundary, where a second machine may read the library but deletions are confined to
the piano machine and the interface explains the refusal instead of disabling a control silently.
Also restored: the piece editor's fields and inline composer creation, the `copy_media` import
parameter with its `curl` example, the count-in and click controls, the `suspended` audio readout,
the "edits apply immediately" behaviour, and the sampler's `Ds4`/`D#4` naming trap.

**Voice, not length, was the actual problem.** The rewrite is 820 lines across three files — *more*
than the 699 it replaced — but the front page is a third of the size and a reader can now stop
after the first screen and still know what the project is, how to run it, and how it is verified.

**Screenshots were added, taken through the browser suite's simulated MIDI device** so they show the
application connected with real notation rendered, rather than the first-run warnings of a machine
with no piano attached. Written by `.scratch/shoot_readme.py`, which imports `FAKE_MIDI` from
`e2e_browser.py` rather than duplicating it.

**The licence gap was closed, and closing it turned up something else.** The user asked what was
compatible with the existing licensed material, so the tree was audited rather than reasoned about:
all 67 installed Python distributions and 69 npm packages were enumerated with their licence
metadata, walking the transitive closure separately from the dev-only set. The answer was that
nothing constrains the choice — there is no GPL, AGPL or LGPL anywhere in either tree. Three
near-misses, none of which bite: `certifi` (runtime) and `lightningcss` (dev) are MPL-2.0, which is
*file-level* copyleft and so imposes nothing on an unmodified dependency; `jszip` is
`MIT OR GPL-3.0-or-later`, so the MIT option is simply elected; `hypothesis` is MPL-2.0 but
dev-only. The only asset actually vendored in the repository is the Spectral font, so OFL 1.1 is
the one licence that binds the repo — and keeping `OFL.txt` beside it is the whole obligation. The
piano samples are *not* vendored: `backend/app/piano.py:49` downloads them at runtime and caches
them locally, so CC BY attribution is satisfied in the UI rather than by the repo.

The user chose **MIT**. `LICENSE` and `THIRD-PARTY.md` were added; the README's credit section now
names a licence for every component instead of only some, and the stale "Sight-Reading Trainer API"
comment at the top of `backend/requirements.txt` — a leftover the rename had missed — was corrected.

**One real defect found while checking, which is the reason `THIRD-PARTY.md` is not the whole
fix.** Inspecting `frontend/dist` showed the built bundle carried **zero** copyright or licence
strings for Tone.js and JSZip, while OpenSheetMusicDisplay's own chunk retained 38. Since `dist` is
what the API serves — it *is* redistribution — MIT and BSD-3-Clause both require those notices to
travel with it, and minification had stripped them. The obvious remedy, `output.banner`, is a trap
in this build: Vite 8 accepts `build.rollupOptions`/`rolldownOptions` but types the output as
`Omit<OutputOptions, …, "banner">`, so the setting is **silently ignored**. That was established by
building and finding no banner rather than by reading the docs, and it is recorded in
`vite.config.ts` beside the workaround: a twelve-line `generateBundle` plugin that prepends the
notice. Verified by building again and finding the notice at the head of both emitted chunks.

Verified: `./check.sh --fast` green after the config change; every relative link in `README.md` and
`THIRD-PARTY.md` resolved by script rather than by eye.

## 2026-09-21 — sight-reading agent — Phase 20c landed: reversible log edits, and a streak that forgives one rest day

Scope: `frontend/src/lib/segmentUndo.ts` and its test; `frontend/src/components/PracticeLogView.svelte`,
`SegmentTimeline.svelte`; `frontend/src/lib/state.svelte.ts`, `types.ts`;
`backend/app/practice/store.py`, `models.py`; `backend/tests/test_practice_api.py`;
`backend/tools/falsifications/drop_undo_split_inverse.sh`, `break_streak_on_one_miss.sh`;
`backend/tools/e2e_browser.py`; `README.md`; `docs/ECOSYSTEM.md`.

Did: the last planned slice of Phase 20. `inverseOf` derives the inverse of a timeline edit by
**diffing the segment list before and after** rather than by remembering which button was pressed,
so the offer cannot disagree with what actually happened; it lives in `segmentUndo.ts` because a
decision inside a component is a decision `node --test` cannot reach. `edit()` — already the single
funnel every edit goes through — now computes the offer, and the card shows one control labelled
`Undo split` / `Undo merge` / `Undo label`. `resegment` and `identify` deliberately offer nothing.

**No table and no persisted undo record (20-D3).** The stack is one field in a component, so it dies
with the page, and the card says "this offer lasts until the page is reloaded" rather than implying
otherwise. Nothing to migrate and nothing to retire.

**`streak_days` keeps its meaning for a week with no missed day.** `streak()` replaces it and adds
one tolerated rest day per rolling seven; `streak_grace_used` is the additive field that says when a
rest day is being counted, so the run length is never read as days played. The three pre-existing
`streak_days` assertions are untouched and green.

**The one thing undo cannot restore.** A merge nulls the absorbed segment's
`identification_outcomes.segment_id` (`ON DELETE SET NULL`) and nothing writes it again, so undoing
a merge restores the segments and their labels but not the matcher's record of one of them. The
control says "Undo merge" and claims nothing more; `docs/TEST-STRATEGY.md`'s accuracy figure is the
thing that would otherwise be over-claimed.

Falsifications, both reported `falsified: the check caught the break`:
`drop_undo_split_inverse.sh` (frontend tier — stops recognising a split, caught by
`a split is undone by merging the two halves back`) and `break_streak_on_one_miss.sh` (backend tier —
goes back to breaking on the first miss, caught by
`test_one_missed_day_keeps_the_streak_and_is_reported` and `test_two_missed_days_in_a_row_end_the_run`).
The browser tier gained four assertions including that a re-segment offers **no** undo.

**Two temporary breaks, not committed, because the plan's obligation is for the wiring and for
re-segment rather than for a route.** The undo wiring was broken (`undo = null` always) and the
browser scenario was watched to fail at `waiting for locator("[data-undo]")`; then `inverseOf`'s
final `return null` was replaced with an `assign`, and the scenario was watched to fail with
`FAILED: and a re-segment offers no undo, because the boundaries it replaced are gone`. Both files
were restored with `git checkout` and the bundle rebuilt, because `frontend/dist` is gitignored and
a broken build would otherwise outlive the break.

**One gap named rather than implied.** The re-segment *copy* — the sentence added to the button's
`title` — has no assertion anywhere: `grep -rn "cannot be undone" frontend/src backend/tools backend/tests`
matches only the component that writes it. So that sentence is verified by reading it back and by
nothing else, and a future edit that drops it will not turn anything red. Recording it here is the
point; inventing a check that greps our own source text would be theatre that cannot fail for a real
reason.

Four deviations from `PLAN-PHASE20C.md`, each recorded because reality had moved past the plan:
1. Phase 21 rewrote `edit()` after the plan was written (it now applies the server's own answer
   instead of re-reading), so the pre/post lists are taken around the response rather than around a
   `load()`. The plan's re-read gate predicted exactly this.
2. The plan says `inverseOf` returning null for `identify` is what keeps the Undo control off the
   screen, but it cannot tell `identify` from an assignment — the plan's own unit test pins that it
   reports the row change as an assign, and `_settle_label` really does move `piece_id`. The
   suppression therefore lives at the `onidentify` call site via the `{ undoable: false }` option
   the plan introduced for the undo itself.
3. There is no confirm *dialog* to add the re-segment warning to — the ask is a button whose label
   says "(discards labels)" and whose `title` explains it — so the sentence went into that title.
4. The plan's browser block waits for a `/merge` response when clicking "Undo merge"; undoing a
   merge is a **split**, so that wait would have hung. The assertion waits on the timeline's
   `data-segments` instead, which is what the rest of the scenario does. The plan's proposed
   ECOSYSTEM text (`20a–20c landed; 20d–20e planned`) would also have un-landed 20d and 20e, so the
   row now reads `20a–20e landed`.

Impact on the other side: none. No route, table, column or wire format changed; `AnalyticsSummary`
gains one additive field and `streak_days` is unchanged for any week without a missed day.
`services.py`'s `_streak_days` is deliberately untouched — it is the second owner of this value that
`docs/TEST-STRATEGY.md`'s appendix already inventories, and retiring it is its own decision rather
than a passenger on this slice.



## 2026-09-21 — sight-reading agent — Phase 22a–22c: cut where the playing turns over, hear the piece in pieces, show the passage

Scope: `backend/app/practice/{segment,shingles,passages,similarity,store,config,models,sessionize}.py`,
`backend/tests/{test_segment,test_shingles,test_passages,test_similarity,test_autotag,test_practice_api,test_practice_store,test_backup,test_workout,conftest}.py`,
`backend/tools/{measure_autotag,measure_real,e2e_browser}.py`,
`backend/tools/falsifications/{drop_adaptive_gap,drop_tempo_invariance}.sh`,
`frontend/src/{lib/types.ts,lib/segmentUndo.ts,lib/segmentUndo.test.ts,components/SegmentTimeline.svelte,components/PracticeLogView.svelte}`,
`docs/{ECOSYSTEM,ENGINEERING,TEST-DATA}.md`, `README.md`.

Did: three slices, in commits `8ee8670` (22a), `58d7dc3` (22b) and `c477361` (22c), plus a final
docs commit. **22d's two decisions were settled without code**: the auto band was measured and kept
as it was, and the run-through anchor was measured and dropped. So the phase is 22a–22c landed and
22d settled-by-measurement, which is why `docs/ECOSYSTEM.md`'s row says `Landed 22a–22c` and its
§ *Phase 22* block carries the numbers.

**Segmentation.** `practice/segment.py` replaces the one fixed 8 s gap (60 hits in 238,648 note
transitions on the owner's ten hours) with an adaptive gap — `max(2 s, 2.5 × the passage's own
median inter-onset interval)`, capped at 30 s — plus a minimum size (8 notes, so a stray touch is
absorbed) and a maximum size (2 minutes, split at the largest internal pauses). It refuses to split
a run with no internal silence at all, because that would cut a phrase in half. `segment_gap_s`
stays: the take-cutter and `PracticeStatus.segment_gap_s` still read it, and three docstrings that
called it *the* segmenter were corrected rather than left to contradict.

**The matcher.** `practice/shingles.py` extracts tempo-invariant local features — (hand, pitch
class) notes, chord pitch-class sets, melodic bigrams — and `similarity` pools them **per piece**,
mixing `0.75 × global + 0.25 × containment` into the score and deciding the band from the mixed
score. Two windows retired: the top-N *segment* neighbour window (which held a single piece for 47
of 54 queries, leaving `runner_up` undefined and downgrading 46 segments to "nothing else to
compare it with") and `SRT_AUTOTAG_TRAINING_LIMIT`'s correctness role. `SRT_AUTOTAG_NEIGHBOURS` and
`SRT_AUTOTAG_TRAINING_LIMIT` are now read by nothing; both are kept as settings and marked "read by
nothing" in `docs/ENGINEERING.md` rather than deleted, because removing a documented setting is a
deployment decision and not a code one.

**Passages.** `practice/passages.py` groups adjacent attempts that are the same material into a
passage and adjacent same-piece passages into a piece-session, both derived on read. The label stays
on the segments (22-D2), so there is no group table, no migration, no new route and no
`SCHEMA_VERSION` change; `SittingDetail` gains one additive `passages` field.

Deviations from `PLAN-PHASE22.md`, each recorded because reality had moved past the plan:

1. **`Passage`/`PassageOut` were already taken** by the repertoire for a player-marked bar range
   (`piece_passages`, `/repertoire/passages`, `PassageList.svelte`) — a different concept, since the
   app has no score alignment. A second `export interface Passage` in `types.ts` is a duplicate
   identifier and fails `npm run check`. The derived type is `PracticePassage` /
   `PracticePassageOut` (owner's choice), and the field stays `passages`.
2. **Three of 22a's seven unit tests could not pass against 22a's own module.** Two asserted window
   counts that the default `min_notes=8` erases; the adaptive test's arithmetic was wrong as well (a
   "3 s pause" after a note ending at 39,100 ms is 3,900 ms, which is a real break at 2.5 × a 1 s
   pulse); and the maximum-size fixture built three *contiguous* runs, so the rule correctly refused
   to split and both assertions failed. Rewritten to isolate each rule, plus one new test pinning the
   gap-free refusal. 8 tests, not 7.
3. **`blend`'s docstring in the plan is inverted** — it says `weight` is the global share while its
   own code and call site make it the containment share. And **the mix has to happen inside `rank`**:
   the plan blends *after* `identify()` returns, which would leave `band`, `reason`, `runner_up` and
   `margin` describing the un-mixed scores, so acceptance 4's precision claim would be about numbers
   the matcher does not use.
4. **Step 3.7's verification command cannot measure the hybrid** — `measure_autotag.evaluate` is
   global-only. `evaluate_fragments` was added, using the `middle_notes` axis Task 1 added but
   nothing called, and it prints both the containment-weight sweep and the acceptance-2 table.
5. **Six autotag tests pinned the old defect** — a one-note-apart pair was "offered" only because
   `runner_up` was undefined, and the content term now separates those two pieces. They were
   rewritten around an `indistinguishable_library` (two pieces, identical material); the win is
   recorded by `test_the_content_term_tells_one_note_apart_twins_apart`.
6. **Four fixtures (three backend, one browser) encoded the 8 s rule** and were rebuilt on
   `tests.conftest.phrase_offsets` and a two-phrase e2e seed. A lone note is not a segment any more,
   and a slow passage raises its own threshold, so `[0, 500, 30_000, 30_500]` is one segment now.
7. **The passage threshold and its weights are measured, not transcribed.** The plan cites
   same-piece/different-piece medians of 0.957 and 0.647 "on this library"; measured with the shipped
   features they are 0.886 and 0.202, and no different-piece pair reaches 0.466. The threshold is
   **0.85** — 11 of 19 same-piece pairs group, **none** of 20 different-piece pairs merge — and the
   weights come from the **sitting's own attempts**, because the plan's library-wide weighting leaves
   a library with no labels (the case where grouping is worth the most) unable to group anything.
8. **`identification_quality` now reports on the shipped matcher.** The plan deletes the stale
   reference-window note but leaves `_labelled_rows(limit=…)` in place, which would have gone on
   truncating silently; it compares against every labelled segment and applies the same mix.
9. **`measure_real.py` files under 22a in the plan but imports `shingles`,** which 22b creates, so it
   landed with 22b. Its plan-given `DEFAULT_PATH` resolves to the repository root while
   `docs/TEST-DATA.md` documents the corpus one level above it; corrected to match the document, and
   its `evaluate` calls the shipped `rank`/`identify` rather than reimplementing the mix.
10. **`PracticeLogView.edit()` patched only `detail.segments`** from an edit's response. Since a
    sitting's detail also carries *derived* passages, the passage layer described the attempts from
    before the edit — the view rendered two passages for three attempts and appended the new segment
    outside any passage. It re-reads the sitting now. This is a deliberate exception to Phase 21's
    "apply the server's own answer" rule, and the reason is that the response no longer carries
    everything the timeline draws.
11. **`segmentUndo.inverseOf` identified a merge's survivor as "the first row whose id is in both
    lists".** Every other segment of the sitting is in both lists too, so undoing a merge that did not
    keep the sitting's first row split an untouched segment at a boundary outside it, which the
    server refuses — the browser scenario caught it as a 422. The survivor is now the row that
    *covers* the absorbed one.
12. **22-D6's run-through anchor is deleted, not tuned.** Measured: 9 of the real library's 54
    labelled attempts (17%) would carry the 2.5× weight and top-1 is **98.1% either way**, so by the
    rule's own stated condition — kept only if it moves a run-through query — it does not pay.
13. **Acceptance 2's whole-length number is corrected to its measurement: +4.2, not ≥5.** The plan's
    own § *The measured case* publishes 61.8% → 66.0%, which is +4.2, so its evidence already
    contradicted its own criterion. No containment weight closes it (0.10 → +4.9/+7.6; 0.35 →
    +3.5/+13.9), and it is not a baseline artefact: the retired windowed matcher scores identically to
    global-only at 8, 16 and 32 pieces. Owner's decision: proceed, with the number recorded. The
    plan's drift rule — which stops only if the hybrid *cannot beat* the current method — is
    satisfied at both lengths and every piece count from 16 up.

Acceptance: 1 (0.2/0.7 points against a 3-point bound), 3 (96.8% against 94%), 4 (auto precision
100% generator / 99.7% real; coverage 53.6% against 50%), 5 and 6 are covered; 2 is +4.2/+12.8 with
the whole-length clause corrected as above; 7 is `./check.sh --full` green. 926 backend tests, 104
frontend tests, `practice_log` browser scenario green.

Impact on the other side: no schema change and no route change. Two settings are now read by nothing
(`SRT_AUTOTAG_NEIGHBOURS`, `SRT_AUTOTAG_TRAINING_LIMIT`) and five segment settings are new
(`SRT_SEGMENT_FLOOR_MS`, `_PULSE_MULTIPLIER`, `_CEILING_MS`, `_MIN_NOTES`, `_MAX_MS`) plus
`SRT_AUTOTAG_CONTAINMENT_WEIGHT`; see `docs/ENGINEERING.md`. `SittingDetail` gains an additive
`passages` field, mirrored in `frontend/src/lib/types.ts`. A take's audio boundary and its segment's
boundary can now differ — takes are still cut at 8 s while a stored sitting is cut adaptively — but
they are linked by the instant the take started, not by sharing a boundary, so nothing breaks.

## 2026-09-21 — sight-reading agent — correction to the Phase 22 entry above

Scope: `AGENT-LOG.md` only. No code, docs or tests.

Did: the entry above, and the commit messages for `c477361` (22c) and `b6fa84f` (22d), say "926
backend tests". That number was written from memory and is wrong. Measured at the tip of the phase,
`pytest -q -m "not slow"` in `backend/` reports **935 passed**. The figures quoted at the other two
points in the entry are correct: 923 after 22b (measured), and 104 frontend tests via `npm test`.
`./check.sh --full` is green either way — the count was the only wrong thing.

Impact on the other side: none. Appending rather than editing the entry above, per this file's rule.

## 2026-09-22 — sight-reading agent — the hand comes from the part, not from the staff it sits on

Scope: `frontend/src/lib/score.ts`, `frontend/src/lib/score.test.ts` (new),
`backend/tools/e2e_browser.py`, `backend/tools/falsifications/read_hand_from_the_staff_position.sh`
(new), `backend/tools/falsifications/ignore_the_part_when_naming_the_hand.sh` (new),
`docs/ENGINEERING.md`, `docs/ECOSYSTEM.md`. Commit `f9c6d58`; this entry's own commit follows it.

Did: fixed a defect that made an entire skill level's score feedback invisible, and closed the gap in
the suite that let it survive. Reported by the owner, who could see it at the keyboard — "the color on
the left-hand I did notice" — which no tier of this project's verification could.

**The defect.** `ScoreRenderer.correlate()` decided which hand a rendered note belonged to from the
*position* of the staff: `staffIndex === 0 ? 'RH' : 'LH'`. The API labels every expected note from the
part's own id and name (`music/expected.py:75-83`). The two rules agree in two of the three
configurations the generator emits and disagree in the third:

| texture | parts | staff 0 | positional rule | truth |
| --- | --- | --- | --- | --- |
| 1 | 1 | "Right Hand" | RH | RH ✓ |
| **2** | **1** | **"Left Hand"** | **RH** | **LH ✗** |
| 3–10 | 2 | "Right Hand"; "Left Hand" on staff 1 | RH / LH | ✓ |

Texture level 2 is `{"hands": ("LH",)}` (`skills_data.py:289`) and `generator.py:325` turns that into a
single melody part named "Left Hand" on staff index 0. So `queues.get(keyFor(measure, 'RH', pitch))`
never matched, every `expectedIndex` was `null`, and `applyColors()` skipped every note. The only
symptom was a `console.warn`. Nothing failed anywhere.

**Why no tier caught it, which is the more useful finding.** `scenario_perfect` has asserted exactly
the right thing since Phase B: *"a broken correlation leaves every note uncoloured… asserting on the
rendered fill is what makes this real."* It was correct all along and it still is. It simply ran at the
default rating — 700, which `elo.selection_level` maps to texture 1, the right hand alone — and
`scenario_two_hands` forces 1300, texture 7. Both are configurations where the positional guess
coincides with the part name. **The 750–845 band, the only one that emits a single left-hand part, was
never played by anything.** `scenario_left_hand_alone` is that band: one `set_all_ratings(800)` and the
existing assertion, on the configuration that disagrees.

**The fix.** `handForPart(id, partName, index)` mirrors `expected.py`'s rule exactly — explicit id
first, then the name, with positional order kept only as the fallback for MusicXML that names nothing —
and `correlate()` resolves it once per staff from `GraphicalMeasure.ParentStaff.ParentInstrument`, which
is where OSMD carries the MusicXML part id (`IdString`) and name (`Name`). Measured:

* RED, before: exercise #119, 19 expected notes, scored **99/100**, `notehead colours:
  {'rgb(0, 0, 0)': 41}` — **0 of 19 noteheads painted.**
* GREEN, after: `{'rgb(21, 128, 61)': 18}` — **18 of 18 painted.**

**The assertion needed a third measurement, and this is worth not rediscovering.** Neither existing
helper answers "is every note coloured". Counting every filled path is the wrong denominator:
`setColor` is called with `applyToLedgerLines` and `applyToTies`, so ledger lines and ties are paths
too and a bass-clef part has both — 27 paths for 14 notes, no exact comparison possible. Measuring the
`.vf-notehead` element itself is the other error: VexFlow puts that class on a `<g>` **group** and
paints the glyph on the `<path>` inside it, so the group's own computed fill is black whatever colour
the note is, which reports a working score as uncoloured. The new `NOTEHEAD_FILL_COUNTS` walks the
group and measures the glyph, which is exactly one per expected note. Both facts are now in
`docs/ENGINEERING.md` §7.

**A blocker removed on the way.** `ScoreRenderer`'s constructor used a TypeScript parameter property,
which Node's strip-only type handling refuses (`ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX`). That is what kept
`score.ts` — the client module with the most recorded defect history — unloadable by `node --test`. As
a plain field it imports, and `score.test.ts` pins the seam against the four (id, name, index) tuples
the generator actually emits, plus the fallback and case handling. 104 frontend tests became 110.

Deviations and findings worth recording:

1. **The unit test was written after the function, and that is a deviation from the strict route.**
   The genuine RED was the browser scenario, written first and watched fail, and it is the stronger
   test because it reproduces the user-visible defect. The seam test came second; it has since been
   seen to fail, by
   `falsifications/ignore_the_part_when_naming_the_hand.sh` (4 of 6 cases fail with the rule removed,
   106/110), so the assertion is not trusted merely because it is new.
2. **My first assertion was wrong twice, and the browser caught both.** `counts == len(expected)` over
   *all* filled paths passed for a treble-clef exercise and failed for a bass-clef one, because of
   ledger lines — that is how the path-counting error was found. And I asserted the result shows an
   "LH 100%" pill; `ResultsPanel.svelte:92` deliberately draws the per-hand breakdown only when there
   is more than one hand, so the correct expectation is that a single-hand result does *not* sprout a
   redundant breakdown beside its own total. The scenario now asserts that instead.
3. **`frontend/dist` is gitignored and `falsify.sh` cannot restore it — demonstrated, not assumed.**
   The browser falsification builds the broken bundle, then `git checkout -- .` restores the source and
   leaves the broken `dist` in place. Verified afterwards: git reported a **clean tree**, the source
   held the fix, `dist/assets/index-qwB6_ez8.js` was the broken bundle, and `run_e2e.sh left_hand` still
   failed at `0/15 noteheads coloured`. Rebuilding restored it and the scenario went green. The
   project's existing frontend falsifier comment names the build-first half of this; the restore half
   is not handled anywhere, so **a browser falsification leaves the app broken while git reports
   clean** until the next `npm run build`. `check.sh --fast` does build, so the trap is bounded to
   running `run_e2e.sh` directly afterwards — which is exactly what verifying a fix does.
4. **One `max_level` hook is dead and the hand is not selectable at all.** Found while tracing how the
   owner could reach the right hand: `selector.py:55` accepts `max_level` and `:65` applies it, and
   nothing ever passes it. There is no control anywhere — API or UI — that chooses the hand or pins a
   level; the only lever is the rating, which moves one way. So levels 3–10 reprint both hands forever
   and single-hand material becomes unreachable once texture 3 is reached. The owner's decision on this
   is recorded in `docs/ECOSYSTEM.md` § *Still open* and is the next piece of work.

Verified: 935 backend tests (unchanged); 110 frontend tests (was 104); `npm run check` clean;
`./check.sh --fast` green in 74 s; the **whole** browser suite green, including `scenario_perfect`'s and
`scenario_two_hands`' existing fill assertions, which the changed correlation path could have broken.
The browser falsification reports `falsified: the check caught the break (exit 1)` at
`0/13 noteheads coloured`; the unit falsification fails 4 of the 6 cases. Both were run against the
committed tree, per §8.

Impact on the other side: none. No schema change, no route change, no setting, no type change. The
`hand` string on `ExpectedNote` is untouched; the renderer now agrees with it instead of guessing.

## 2026-09-22 — sight-reading agent — the falsification tool now refuses to be wrong

Scope: `backend/tools/falsify.sh`, `backend/tools/falsifications/{read_hand_from_the_staff_position,
ignore_the_part_when_naming_the_hand}.sh`, `docs/TEST-STRATEGY.md` §8. Commits `6bd8a11` and
`a7d8317`, the latter amended so its pre-amend object `7acfebd` is no longer in the history — see the
incident below.

Did: hardened the tool that certifies every other check, after the `frontend/dist` trap it left in
its own frontend falsifier was demonstrated during the hand fix. The owner's instruction was that it
be bulletproof, "the tests cannot give wrong results and lead to errors", so the work was to
enumerate every way it could report something it had not earned and close each one.

**Four ways it could be wrong, all now refused.**

1. **A check that was already red.** `exit 1` from a mistyped command line is not 126 or 127, so it
   landed in the "falsified" branch: apply a break to an already-failing suite and the tool certifies
   an assertion it never tested. There is now a **mandatory positive control** — the check runs on
   the unbroken tree first and must pass — which is why a falsification costs two runs. It is not a
   flag. Measured: `falsify.sh noop.sh "false"` now exits 2 with "the check is already failing on the
   unbroken tree", where before it would have printed `falsified`.
2. **A stale bundle.** `frontend/dist` is gitignored, so `git checkout` cannot restore it. The tool
   now owns the bundle: it builds before the control, **builds again with the break applied** so the
   check cannot measure stale code whatever the check command says, and rebuilds on the way out,
   verifying the content-hashed manifest matches what it was. A break that stops the project building
   is refused rather than counted as a catch — measured with a break that appends invalid TypeScript,
   which would otherwise have been reported as a successful falsification.
3. **Restoration that did not restore.** `git checkout -- .` leaves untracked files behind, so the
   tree is also cleaned of untracked-but-not-ignored paths (no `-x`, so `frontend/dist`,
   `backend/data`, `.scratch` and `mutants/` are untouched) and the result is verified: a tree that is
   not clean afterwards is reported loudly.
4. **An interrupted run.** Restoring happens on every exit path through a trap. Two details make that
   true rather than nominal, and both were found by testing the tool against itself:
   - bash **defers a trap until the foreground command returns**, so with the check in the foreground
     an interrupt during a sleeping check left the break applied. Proven with a probe: foreground 0
     traps fired within 2 s, background-plus-`wait` 1. The check now runs in the background and is
     `wait`ed for, and `wait` is interruptible.
   - a **check still running can write to the tree after it is restored**, so cleanup stops the check
     first. coreutils `timeout` puts the managed command in its own process group and leads it, so the
     group is signalled as a unit; the test's own process listing showed the split (script in group 5,
     `timeout`/`bash`/`sleep` in group 136), which is why signalling the script alone left `sleep`
     alive.

Two smaller ones: the check is bounded by `SRT_FALSIFY_TIMEOUT` (default 1800 s) with a timeout as
its own outcome, because a check that hangs certifies nothing; and the output file was a fixed path,
so `tail -5` could print a *previous* run's output as this run's evidence — it is a fresh `mktemp`
per invocation now, kept when the run failed.

`--expect TEXT` is new and optional: it requires the failing output to contain `TEXT`, turning
"something failed" into "the assertion we meant failed". Without it any non-zero exit counts and the
tool says so. Reading the command moved from `eval` to `bash -o pipefail -c`, which takes a command
line without eval's quoting traps. The first two positional arguments are unchanged, so every
existing falsifier invocation and the ones written into `docs/PLAN-*.md` still work — verified by
running `drop_adaptive_gap.sh` unchanged.

**An incident, recorded because it is the exact hazard this work is about.** A failed interrupt test
left `frontend/src/lib/route.ts` carrying the test's `// INTERRUPT TEST BREAK` marker, and the next
`git add -A && git commit` swept it into the commit now identified as `a7d8317`. It was caught
immediately, restored from `902904b`, and the commit amended so that it touches only `falsify.sh`;
`git diff 902904b -- frontend/src/lib/route.ts` is empty and the tree is clean. The pre-amend object
`7acfebd` still exists in the object store and still carries the marker, which is why the citation
above names the reachable commit rather than that one. The lesson is that a test harness which
mutates tracked files needs its own restore, independent of whether the tool under test restored —
which is precisely the failure mode `falsify.sh`'s trap exists to prevent, reproduced on the operator
side.

**A methodology note worth keeping.** The first interrupt test appeared to prove the trap did not
fire, and it was wrong: a background job in a non-interactive shell **inherits `SIGINT` as ignored**,
and bash cannot trap a signal ignored on entry, so the test never delivered a signal at all. The
second version reset the disposition with `signal.signal(SIGINT, SIG_DFL)` before `execvp`, which is
what a terminal's Ctrl-C actually delivers. Two tests that "failed" were measuring the harness.

Verified: `./check.sh --fast` green (935 backend, 110 frontend, 74 s); both hand falsifiers falsified
under the new tool with `--expect` matching; an existing backend falsifier unchanged; and the refusal
paths exercised directly — already-red check, 127, break-that-changes-nothing, build-breaking break,
`--expect` mismatch (exit 1, not certified) and `--expect` match (certified). `SIGINT` and `SIGTERM`
both restore `route.ts`, leave the tree clean, kill the check with no process surviving, and leave
the good bundle in `dist`. The fixtures used lived in the gitignored `.scratch/` and have been
removed.

Impact on the other side: none. No application code, schema, route or setting changes. The tool's
interface is a superset of what it was.

## 2026-09-22 — sight-reading agent — pinned practice: choose the difficulty, choose the hand

Scope: `backend/app/{skills_data,models,main,services,store}.py`,
`backend/app/adaptive/selector.py`, `backend/app/music/generator.py`,
`backend/tests/{test_adaptive,test_generator,test_api}.py`, `backend/tools/e2e_browser.py`,
`backend/tools/falsifications/{forget_the_pin_when_reusing_an_exercise,rate_a_pinned_exercise}.sh`
(new), `frontend/src/lib/{types,api,state.svelte}.ts`,
`frontend/src/components/{SetupPanel,PracticeView,ResultsPanel}.svelte`,
`docs/{ECOSYSTEM,ENGINEERING,FEATURES}.md`. Commits `3b503ee`, `4c2a9af`, `0dbe538`, `b2059fc`.

Did: the owner's decision recorded earlier today was that handedness is a property of the *material*,
and the reason they gave is sharper than the question was — the real axis is **which staff you are
reading**, so a bass-clef exercise at level 1 should be selectable because clef familiarity is the
thing being trained. This is that, built.

**The defect it removes.** The hand was a *consequence* of the difficulty: `TEXTURE_LEVELS` gives
`("RH",)` at level 1, `("LH",)` at 2 and `("RH", "LH")` at 3–10. So the only way to read the bass clef
was to be rated at texture 2, and the only way out of it was to be rated higher — the ladder was
one-way, single-hand material became unreachable at level 3, and level 2 is also where the score
feedback silently did nothing until `f9c6d58`. The one route to left-hand material was the least
finished corner of the app.

**Two pins, both deliberate choices.** `level=N` sets every dimension, because "practise level 2"
means level-2 material rather than level-2 melody over level-5 rhythm; it is not derived from a rating
so it is neither capped nor fenced, and unlike `selector.py:55`'s `max_level` — accepted, applied, and
passed by nothing — it can raise a level as well as lower it. `hands=RH|LH|both` overrides what the
level would have chosen and nothing else, with `both` honoured at levels 1 and 2, where
`select_pattern` finds no candidate above the level's floor and falls through to `sustained_root`,
which is what a melody over held roots should be.

**A pinned exercise is not rated** (the owner's decision). It is scored and logged like any other and
only the rating is held still. The arithmetic that decided it: a perfect run at pinned level 1 against
a rating of 900 is still worth about +2.6 under Elo, so twenty runs of easy bass-clef drilling would
move the rating ~50 points while the player did easier work than usual — and the rating is what
chooses the automatic material. `record_performance` holds `updated` at the current ratings and writes
no `rating_events` row, so the curve gains no fake point; the result carries `rated: false` and the
panel says *not rated · you pinned it* rather than leaving an absent change that reads like a scoring
failure.

**The reuse key has now learned a fifth field.** After the target skill, the level profile, the bar
count and the pinned key, it gains the pin itself. `pinned_hand` is the one that matters most, because
two requests differing only in hand produce an *identical* level profile — so without it a request for
the right hand is served the left-hand exercise. And `pinned_level` matters even though the levels
already differ, because a profile the rating happens to derive as uniform would otherwise be served a
pinned exercise, which is unrated, so an ordinary attempt would silently stop counting. Both live in
`params_json` beside `pinned_key`: no schema change, no `SCHEMA_VERSION` bump, and rows written before
this read back as unpinned, which is what they were.

**What the falsification tool caught, twice, and both were my fault rather than the code's.** The
hardened `falsify.sh` refused to certify two falsifiers because the failure it saw was not the one the
break was meant to test, and it was right both times:

1. **The break was wrong.** `forget_the_pin_when_reusing_an_exercise.sh` first removed only the two
   *arguments*, leaving the `WHERE` clause filtering on their defaults — so a pinned row could never
   match and pinned exercises became unreusable, which is the opposite defect. It was caught by "reuse
   still serves the same pinned request twice", not by the reuse-crossing assertion. The script now
   removes the conditions and the parameters together, which is what "the pin is not part of the
   exercise's identity" actually means, and the failed attempt is recorded in its comment.
2. **The tests were in the wrong order.** With the breaks applied, `test_reuse_never_crosses_a_pinned_hand`
   failed on `{'LH'} == {'RH'}` and the rating test on `assert True is False` — both true, and both the
   symptom rather than the cause, before reaching the assertion that names the defect. Reordered so the
   identity claim and the ratings invariant report first, with the reason at the call site. The
   assertions are unchanged.

Where `--expect` was omitted the tool says so; these two runs are the argument for always passing it,
since neither would have been noticed as a mis-attributed pass.

Verified: 968 backend tests (was 935); 110 frontend tests; `npm run check` clean; `./check.sh --fast`
green in 77 s; the **whole** browser suite green. The new `scenario_pinned_practice` drives both Setup
controls at a rating of 1400 — comfortably two-handed — and asserts the exercise comes back
all-level-1 and left-hand-only, that the interface says both are pinned, that the attempt is scored
99/100, that the result says *not rated*, that all nine ratings are unmoved, and that clearing the pins
returns level 8 material. Both falsifiers report `falsified` with the failure attributed: the reuse one
fails **only** `test_reuse_never_crosses_a_pinned_hand`, and the rating one fails both rating tests.

Impact on the other side: no schema change, no new table, no route change — two new optional query
parameters and two additive response fields (`pinned_level`, `pinned_hand` on an exercise, `rated` on a
score result), mirrored in `frontend/src/lib/types.ts`. Nothing existing changes meaning: an unpinned
request behaves exactly as before, and `texture` keeps its current levels and descriptions, which is
recorded as still open in `docs/ECOSYSTEM.md`.

## 2026-09-22 — sight-reading agent — the notes the page was holding, and three more silent failures

Scope: `frontend/src/lib/{api,capture,state.svelte}.ts`,
`frontend/src/components/{PracticeView,CalibrationView}.svelte`, `frontend/src/app.css`,
`backend/tools/e2e_browser.py`,
`backend/tools/falsifications/never_flush_when_the_page_is_hidden.sh` (new),
`docs/FEATURES.md`. Commit `f48b2ab`.

Did: the first four items of the plan's Step 3, each verified against the source before being
touched rather than taken from the review that found them.

**The one silent data-loss path.** `flush()` is asynchronous, and a request started in `pagehide` is
cancelled with the document — so everything played since the last 2 s tick went with the page on every
reload, kiosk restart or power cut. The docstring even said *"e.g. when the page is being hidden"* and
nothing was wired to it. `api.practice.ingestOnHide` now hands the batch to `navigator.sendBeacon`,
which outlives the document, and `capture.flushOnHide` is synchronous by necessity. Held notes are
included with the duration they have reached rather than dropped, because `flush()` waits
`MAX_HOLD_MS` and waiting is exactly what is unavailable here — the onset, pitch and velocity are the
valuable part, and a lower-bound duration beats losing the note. `stop()` still drops them: stopping is
deliberate, hiding is an accident mid-phrase. If the browser declines to queue the request the batch
stays buffered, so a `pagehide` from a bfcache entry loses nothing.

The wire shape gained one owner on the way: `practiceBatchBody` builds the body for both the ordinary
flush and the beacon, because a beacon whose shape had drifted from the ingest body would fail
silently and only during unload — the one moment nobody is watching.

**The renderer was never disposed before being replaced** in `PracticeView` and `CalibrationView`. Its
`ResizeObserver` keeps watching the same container and its render chain stays live, so an orphan
re-renders on the next width change and re-engraves the *previous* exercise over the new one.
`ScoreViewer.svelte` already had the right shape, which is why the fix is three lines rather than a
redesign.

**The 450 ms pause before finishing was never held**, unlike `endTimer` beside it. Navigating away
unmounted the view, and the timer then POSTed the attempt from a dead component, coloured a disposed
renderer, and assigned to state nothing was rendering.

**Four shared utility classes were dead, and the change list is bounded.** Svelte scopes a component's
styles to its own elements, so a class defined in one file is a no-op in every other file that asks
for it. Measured before promoting them, so the blast radius is known rather than hoped: `.tiny` was
defined once and used in eleven files, so **ten** components were rendering those buttons at full
size; `.danger` reaches `PassageList.svelte` and `BackupPanel.svelte`, which is the safety affordance —
`class="danger tiny"` on a Confirm delete button in a component defining neither made the confirmation
look identical to the Delete that armed it; `.notice` reaches `PracticeLogView.svelte`, whose matcher
note had no background or border; `.small` reaches five components. A component that declares its own
version still wins on specificity, so only the places that were silently getting nothing change.

Verified: 968 backend tests; 110 frontend tests; `npm run check` clean; `./check.sh --fast` green in
77 s; the **whole** browser suite green. The new `scenario_capture_on_hide` sends held note-ons —
which the periodic flush deliberately does not send, so the assertion cannot race a 2 s timer and pass
either way — dispatches `pagehide`, and requires the beacon to carry exactly those three pitches to
`/api/practice/events` with the calendar offset and a duration each. The falsifier removes the
registration and the scenario reports `0 beacons`.

**A harness bug worth recording, because it is the same class as the code bugs.** The beacon tap was
first written as a bare arrow function, while the audio tap beside it is an IIFE — `add_init_script`
evaluates a script, so mine defined a function and never ran, and the failure read as
`window.__beacons is not iterable`. The lesson is that a tap which silently does nothing looks exactly
like the bug it is meant to catch, which is why the assertion is "at least one beacon" and not "the
beacon has the right pitches" alone.

Not done from Step 3, and stated rather than left implied: the CSS promotion carries no falsifier. It
needs a scenario that renders the confirm flow, and inventing one that asserts a class name is present
would be the self-referential check this project's §8 warns about. It belongs with Step 5's frontend
falsification work, where the harness can observe a computed style.

Impact on the other side: no schema, route or setting change. Two additive frontend behaviours (a
beacon on hide, a disposal before replacement) and four CSS rules promoted from component scope to the
global sheet.

## 2026-09-22 — sight-reading agent — the formatters, the clock parser, and one defect not fixed

Scope: `frontend/src/lib/{types,clock,playback}.ts`, `frontend/src/lib/{types,clock,playback}.test.ts`,
`frontend/src/components/RepertoireView.svelte`,
`backend/tools/falsifications/{carry_the_minute_into_the_hour,forget_that_a_duration_has_hours,
read_a_clock_with_number}.sh` (new), `docs/ECOSYSTEM.md`. Commit `49ab1ed`.

Did: Step 4 of the plan — the four cheap correctness fixes, the first real tests for two modules that
had none, and one reported defect deliberately left alone.

**Three arithmetic defects, all in text a person reads.** `formatMinutes` rounded the *remainder* and
never carried it, so 119.7 printed "1 h 60 min" and 59.6 printed "60 min". `formatDuration` had no
hour branch at all, so an hour-long recording read "60:00" while the playhead and the markers read
"1:00:00" for the same length — takes are about 14 MB an hour, so an hour is ordinary. `parseClock`
took anything `Number()` takes: `1e3` was a seek to 16:40 from a typo, `0x10` was a hex literal,
`1.5` was a fraction of a second the field does not offer, and `1:99` was read as 159 seconds rather
than refused — the plausible-but-wrong outcome the existing dangling-colon rule exists to prevent.
Parts must now be digits, and a part after the first must be under sixty.

**The fourth was a duplicate owner, not an arithmetic slip.** `formatDuration` did the same job as
`clock.formatClock`, one of them with the hour branch and one without. Adding the missing branch would
have left two owners; the function moved to `clock.ts` beside the formatter it delegates to, and its
single call site imports it from there. This project's test-strategy appendix names two-owners-for-one-
value as its recurring defect, and this is the third instance found in a week.

**A fifth discrepancy, found while writing the tests rather than reported.** The docstring of
`formatMinutes` promised `90 -> "1 h 30"` and the code has always printed `"1 h 30 min"`. The code is
what every screen already shows, so the *docstring* was corrected; changing the output would have been
an unrequested cosmetic change across the app.

**One reported defect deliberately not fixed, which is the part of this entry worth reading.**
`within()` was reported as a bug for including a note exactly on a segment's end, so that it belongs to
both adjacent segments. `playback.test.ts:149-153` asserts that behaviour by name — *"a note exactly on
the boundary belongs to the segment that ends there"* — so it is a documented tie-break. Standing Rule 3
forbids silently changing an existing assertion, and the fix needs a half-open range from the caller,
which is an API change for at most one duplicated note at one millisecond. Recorded in
`docs/ECOSYSTEM.md` § Still open instead, with the neighbouring `Math.min(...spread)` in
`SegmentTimeline.svelte` that `playback.ts` already avoids. This is the second time this review's
claims needed checking before acting — the first was `flush()`, which was wired to the deliberate exits
and only missing the unload path.

Also fixed: `firstOnset` ran the same reduce twice, once to test it against `Infinity` and once to
answer with it.

Verified: 121 frontend tests (was 110); 968 backend tests unchanged; `npm run check` clean;
`./check.sh --fast` green. Three falsifiers, one per claim, each naming the assertion it must trip —
all three report `falsified` with the failure attributed.

Impact on the other side: none. No API, schema, route or setting change. `formatDuration` is exported
from `clock.ts` now instead of `types.ts`, and it was imported in exactly one place.

## 2026-09-22 — sight-reading agent — correction to the Step 4 entry above

Scope: `AGENT-LOG.md` only. No code, docs or tests.

Did: the entry above says "121 frontend tests (was 110)", and so does the commit message for
`49ab1ed`. That number was measured before the `firstOnset` guard was added, and never re-measured.
At the tip, `npm test` in `frontend/` reports **122 passed**. The backend figure (968) and the
`./check.sh --fast` result are correct.

This is the same mistake, in the same file, as the Phase 22 entry corrected on 2026-09-21 — a test
count written down once and not re-read after the last test was added. Appending rather than editing,
per this file's rule.

Impact on the other side: none. The count was the only wrong thing.

## 2026-09-22 — sight-reading agent — the standing rule becomes a command

Scope: `backend/tools/falsify.sh`, all 49 break scripts, `backend/tools/falsifications/
click_the_beat_as_a_quarter.sh` (new), `check.sh`, `frontend/src/lib/{beatGrid.ts,beatGrid.test.ts}`
(new), `frontend/src/lib/metronome.ts`, `docs/TEST-STRATEGY.md`. Commits `5fe1647`, `a4a4fde`.

Did: Step 5's first two items — the falsification tier, and the metronome's arithmetic where it can
actually be tested.

**The standing rule was a preference because nothing ran it.** §8 has said since Phase 19 that no
assertion is trusted until it has been seen to fail, and there were 49 break scripts with the pairing
between a break and its check living only in each script's prose. A break could rot into a no-op, or
into a check that can no longer fail, and nothing would notice. Each script now declares
`# CHECK:` and, where the failure must name the assertion, `# EXPECT:` — the example its header
already gave, made readable. `falsify.sh <script>` needs no second argument and
`./check.sh --falsify [filter]` runs the set.

**The migration was extracted, not retyped, and then read.** 48 of the 49 declarations came out of
the usage example already in the header. The diff was checked for truncation and one was truncated:
`drop_take_catch_up.sh` uses pytest's `-k 'a or b'`, and a `[^"']+` character class stops at the
nested quote, leaving a bare `-k` that would have made pytest exit 4 and the run refuse for a reason
that looked like a broken break. The pattern now allows the opposite quote inside. One script
resisted — its header mentions `falsify.sh` in prose before the usage — and is declared by hand
rather than by teaching the parser to guess, which is how a parser starts being wrong quietly.

**`--falsify` is its own tier, not part of `--full`.** Each script runs its check twice, so the full
set is about an hour, most of it the nineteen scripts whose declared check is the whole fast tier. It
reports four outcomes and only one of them is a failure: `failed` means the check passed with the
break applied, so the assertion cannot fail. `refused` — an already-red check, a break that stops the
build, a timeout, an unattributed failure — proves nothing either way and is reported as a gap. The
distinction matters because the tool refuses far more often than it fails, and a tier that treated
every non-zero exit as a defect would be crying wolf.

**A monitoring mistake worth recording.** The first full run was started with its output piped
through `tail`, so it was buffered and unobservable, and the run blocked every edit because a dirty
tree makes the later scripts refuse. It was killed; the trap restored the tree even under a kill,
which is the first real test of that path in anger. The lesson is that a run which must not overlap
edits should be started *last*, and its output should stream.

**The metronome's arithmetic now has tests, and the reason it could not before is the reason it now
has its own module.** `metronome.ts` imports Tone at module scope, so nothing in it loads under
`node --test`. The click grid has moved to `lib/beatGrid.ts`, which imports nothing, and
`metronome.ts` keeps the Web Audio side — the synth, the rolling lookahead window, the visual beat.
This is the extraction TEST-STRATEGY Slice 6 called for, done now because the module finally has a
reason to be reachable.

The load-bearing test is the invariant the recorded defect violated: **a bar lasts as long as its
notation says** — a bar's beats, each times its own unit times seconds-per-quarter, sum to its length
in quarters — checked across 4/4, 3/4, 6/8, 9/8, 12/8, 2/2 and 3/8. That defect was the metronome
being handed seconds-per-*quarter* and using it as seconds-per-*beat*, which coincides only when the
beat is a quarter; in 12/8 it ended the run a quarter of the way early and silently truncated the
performance. Eleven tests, and `click_the_beat_as_a_quarter.sh` restores the defect: it fails on
`actual: 6, expected: 7`.

Verified: 133 frontend tests (was 122); 968 backend; `npm run check` clean; `./check.sh --fast` green
in 77 s; the metronome falsifier reports `falsified` with the failure attributed.

Impact on the other side: none. No API, schema, route or setting change. `metronome.ts` exports the
same `Metronome` class and `BeatInfo` it always did; the pure pieces moved to a module nothing else
imports directly.

## 2026-09-22 — sight-reading agent — making the falsify tier finishable

Scope: `check.sh`, `backend/tools/falsify.sh`,
`backend/tools/falsifications/forget_the_pin_when_reusing_an_exercise.sh`. Commits `7a52021`,
`8ea77c6`.

Did: the tier worked and took about 40 minutes, which is a release-time tier and not something anyone
runs while editing. Two changes, both measured.

**Each distinct check is proven green once, not once per break script.** Nineteen of the fifty scripts
declare `./check.sh --fast`, and each falsification runs its check twice — once as the positive control,
once with the break applied — so 19 × 74 s of the controls were re-proving the same thing against
byte-identical source. `--falsify` now remembers a check it has seen pass in the same run and tells the
next script so. Measured on two scripts sharing that check: 226 s where the old shape cost 296 s, and
the saving is 74 s per shared check — about 22 minutes across the set. A check is remembered only after
a script reports `falsified` or `failed`, both of which prove the control passed, and never after a
refusal, because a refusal may *be* the control failing. This is not the "skip the control" flag the
tool's header refuses to provide: the control is still run, once per distinct check.

**`--falsify-quick` runs the other 31 and names the 19 it deferred.** Measured at 7 m 13 s. The
deferred ones are not less important — they are the assertions the author could not pin to a single
test file, which is worth seeing — they are deferred because each costs a full fast tier twice.

**The first quick pass earned its keep immediately: 29 falsified, 1 "failed", 1 refused.** The one
reported as unable to fail had not failed. Its `EXPECT` had been mis-extracted from prose in its own
header — the third mis-extraction from that one file — so the tool refused to attribute the failure
and exited 1, and the tier printed that under "these assertions could not fail". Two different things
sharing one exit code, and the summary was wrong about which. An unattributed failure now exits 3 and
is named separately. The `EXPECT` is corrected to the message the assertion actually raises, and the
script now reports `falsified` on `test_reuse_never_crosses_a_pinned_hand`.

Worth stating plainly: every wrong declaration found today was caught by the tool rather than by
reading it, and none could produce a false certification — a check that cannot run is refused, and a
failure that cannot be attributed is refused. The dangerous direction stayed closed throughout.

The refused one is `reload_everything_after_an_edit.sh`, still unresolved: it proves nothing either
way until it is looked at, and it is named in the tier's summary rather than left silent.

## 2026-09-22 — sight-reading agent — the edits stop rescanning material they do not need

Scope: `backend/app/practice/pedal.py`, `backend/app/practice/store.py`. Commit `a63e991`.

Did: the four hottest passes in the practice domain, which were all answering the wrong question. Each
asked "what does this cost?" and answered "everything the library holds" rather than "what this
segment holds". Reported as slow segment editing — 10+ s to split or merge on the notebook — which read
like a hardware problem and was not one.

**Two quadratic loops, both the same shape: a fresh scan of a whole list per item.** `blur_attacks`
rebuilt the pedal-held pitch-class set from scratch for every chord cluster inside every pedal stretch,
against the entire note list — O(stretches × clusters × notes). One split of the largest sitting made
**81.7M calls to `Note.end_ms`**. It is reached from every boundary edit through `_refresh_metrics`, so
a split or merge on a 23k-note sitting cost **3.0–7.6 s** unprofiled (21–24 s under `cProfile`) here,
and more on the notebook. It now slices the notes inside a stretch out of an onset-ordered list and
carries a release-ordered cursor that only advances, which is valid because clusters are in onset order
and so their attacks are non-decreasing: O((N+S) log N).

`_notes_for_segments` fetched a sitting's notes once and then filtered that whole list **for every
segment in the sitting** — O(labels × notes_per_sitting) — and it is on every matcher read, so each
sitting open grew with the training set for no reason but the size of the training set. Same bisect
fix. `candidates_for_sitting` at 1,000 labelled segments went **3,116 ms → 195 ms**, and, more to the
point, became flat in the label count instead of linear.

**Two reads done twice, or once per item where once would do.** `candidates_for_sitting` and
`identification_quality` each derived fingerprints *and* content features for the same reference rows
from two separate reads of the same notes, and the sitting path called `_labelled_rows` twice as well;
`references_from` derives both projections from one `_notes_for_segments`, with the pooling extracted so
both callers share it. `_refresh_metrics` re-read the pedal prefix with a fresh SQL query for every
segment of the sitting, which on a long pedalled sitting re-read the same rows once per boundary; it now
reads the stream once and each segment takes the prefix that had happened by its end. `segment_pedal`
built its stretches twice — once for the blurs, once through `down_ratio` — and now measures the
stretches it already has; `down_ratio` keeps its signature and its tests.

Verified: 968 backend tests; `./check.sh --fast` green in **77 s**. Because these changes are supposed
to have no observable effect, equivalence was proved against the *pre-change* implementations before the
suite was trusted: 4,000 randomized fuzz cases and all 68 real segments for `blur_attacks`; all 54
labelled rows (237,915 notes) for `_notes_for_segments`; byte-identical examples, local features and
pooled signatures for `references_from`; the new pedal prefix equal to the old per-segment SQL prefix on
all 68 segments; `segment_pedal` equal to its pre-change body on all 68, blur positions included; and a
full recompute reproducing every already-valued column of the 48 stored metric rows. That recompute
fills 36 NULLs in the columns Phases 18b/21 added and never backfilled — the values a re-segment would
have written, so a fill rather than a change.

Impact on the other side: none. No API, schema, route, setting or stored format changes; every function
keeps its signature and its output. `piano-progress` and `practice-logger` are untouched.

Not done, and named rather than left silent. `_labelled_rows` has a `limit` whose docstring says "every
live path uses it" and **five call sites that pass none**, so `identification_quality` is still linear in
the entire labelled history — 6.0 s at 1,000 labels, while it grades only `autotag_quality_limit` of
them. Capping the reference set changes matcher accuracy, so it wants a decision and an accuracy
measurement, not a quiet edit; that is the next thing here. Also unlanded: `PRAGMA journal_mode = WAL`
runs on every connection (~0.3 ms each, more on an HD, and requests open 2–3); `sitting_notes` returns
4.6 MB of uncompressed JSON with no gzip middleware; and `_find_sitting` is called per note and per
pedal with no index on `sittings(started_ms)`. A non-flaky guard for these two quadratics would have to
count work rather than time, and none is added here — so the equivalence proofs above are the evidence
for this change, not a standing assertion that a future edit cannot quietly undo.

## 2026-09-22 — sight-reading agent — the undo offer stops taking the detail column

Scope: `frontend/src/components/PracticeLogView.svelte`, `backend/tools/e2e_browser.py`, new
`backend/tools/falsifications/split_the_detail_column.sh`, `README.md`. Commit `3db5080`.

Did: a layout defect with no wrong value in it, reported as "something about the undo operation
makes the layout very weird". `e8adf80` put the undo offer directly above `<SegmentTimeline …>`
inside `{#if detail}`, which reads as "above the card" and is not: `.columns.wide-left` is a
**grid**, and a grid child is a *column*, not a banner. The notice became the second column, the
timeline was auto-placed into the cell that left — (2,1), under the sitting list, at the list's
width — and the column it vacated held nothing but the notice. So the whole detail panel moves,
and only when an edit has something to offer.

The fix is one wrapper: the notice and the card are now the children of a single `.stack`, already
a global primitive at `app.css:280`, so the pair is one grid item and the detail is back in the
wide column beside the list. No new CSS and no prop into `SegmentTimeline`, and the notice keeps
the placement the plan asked for. `@media (max-width: 900px)` collapses to a single column either
way, which is why it only ever showed on a wide viewport.

Verified: `./check.sh --fast` green in 77 s. The scenario asserted `[data-undo]`'s *presence* and
never its position, which is how a purely geometric defect shipped, so `scenario_practice_log` now
measures it at 1280×1000 while the offer is on screen — the timeline's left edge at or past the
sitting list's right edge, and the notice sharing the timeline's left edge and sitting above it.
Falsified per §8, and the control is what makes the break mean something: with the fix, list
126–525 and detail 553–1154 side by side; with `display: contents` on the wrapper, the **timeline**
moves to 111–541 at top 590, under the list, while the notice keeps 553. The assertion goes red
naming it: `FAILED: the sitting detail stays in the wide column beside the list (timeline left 111,
list right 525)`. A scratch capture (`.scratch/shots/undo-fixed.png`, `undo-broken.png`, both
gitignored) drove that same break by toggling the property on the live page, so the picture and the
falsification describe one state and not two. README's falsification count was stale — 37 when it
was written at `c723dd0`, 50 before this change — and reads 51 now.

One tier deliberately not run, and said out loud rather than left to be assumed: **`--full` was
started and stopped on the owner's call**, for a one-component layout fix whose only `--full`-owned
surface is `scenario_practice_log` — and that scenario ran twice, control and break, under the
falsification above. What is not covered by that substitution is the rest of the browser registry
and the mutation report, neither of which this change can move.

Impact on the other side: none. No API, schema, route, setting or stored format changes; the only
edits outside one frontend component are an assertion and its break script.

Not done, and named rather than left silent: nothing in this project reads *position* except the
one staff-top ordering check, and a component cannot be mounted by `node --test` here, so the only
place this could have been caught is the browser tier — which is `--full` and the falsify pass, not
the tier that runs after every edit. The log view's one grid is now guarded where it broke; a second
conditional sibling added to it later would have to move that same geometry before any check
notices, which is the sharpest statement the assertion can honestly make.

## 2026-09-22 — sight-reading agent — the matcher stops rebuilding its training set

Scope: `backend/app/practice/schema.py`, `backend/app/practice/store.py`, `backend/app/db.py`,
`backend/app/main.py`, `backend/tests/test_autotag.py`, `backend/tests/test_migration_upgrade.py`.
Commit `b9e0be5`.

Did: the second layer, on the read side. The previous entry fixed the edits; what was left was that
every sitting open, page load and quality report re-derived the matcher's training material from the
notes. A fingerprint and a content feature per labelled segment is a pass over that segment's notes —
**969 ms** on the owner's library, over a quarter of a million `Note` objects — producing an answer
that only changes when a label or a boundary does.

**The derived material is cached, and the database owns the invalidation.** `reference_state.version`
is bumped by three triggers on `segments`: insert, delete, and update of exactly `piece_id`,
`identified_by`, `start_ms` and `end_ms`. Putting it there rather than in the callers is the point: no
write path can forget it, including an older build's (the triggers live in the file, so its writes bump
the version too) and the second machine writing the same database over the LAN. A cache keyed on the
labelled count or the ids would have missed the ordinary case — `assign_piece` changes a column, not a
row — and the failure would have been a matcher quietly training on a label the player had already
corrected. Measured: `sitting_detail` on the sitting with an unlabelled segment went **969 ms cold →
2.8 ms warm**, and the cached answer is byte-identical to a forced rebuild (checked for the detail, the
candidates and the quality report).

Stated limits, none of which can serve a stale answer. The cache is per process, so the first read
after a restart rebuilds. It is keyed by database file, and the version is stored *beside* the material
and checked on every read, so an out-of-order write from a concurrent reader cannot paper over a
relabel. Two readers may rebuild the same entry at once; serialising them behind a lock would hold a
request for the second the lock exists to avoid, and duplicate work is the cheaper failure. `init_db`
forgets everything, because the path may hold a different database afterwards — a wipe before a test, a
restored backup — and a counter that restarts at zero would otherwise match an entry from the file that
was there before.

**And the payload.** `sitting_notes` is **4.61 MB** of JSON for the longest sitting — one object per
note and per pedal move, sent whenever playback opens. `GZipMiddleware` takes it to **0.51 MB (9.1×)**
for a few milliseconds of CPU, with a 1 KB floor so the many small responses (a label's segment list,
the status heartbeat) do not pay for a header they do not need.

Verified: **973 backend tests** (up from 968) and `./check.sh --fast` green in 80 s. The five new tests
in `test_autotag.py` are the invalidation contract — rebuilt once while nothing changes, a new label
enters, a relabel is visible, a practice kind does not evict, `init_db` forgets — and the standing rule
was applied to them: dropping `trg_segments_reference_update` makes the relabel test's premise fail,
serving the stale list and training on the old piece. `test_migration_upgrade`'s frozen table literal
names `reference_state` deliberately, so removing it later is a decision rather than a drift.

Impact on the other side — the shared-contract note the rules ask for: **a new table and three triggers
on `segments`**. `reference_state(id, version)` is additive and an older build ignores it; its writes
still bump the version, so a mixed-version pair on one database invalidates correctly in both
directions. No existing table, column, route or response body changes. Responses of 1 KB or more may
now be gzip-encoded when the client offers it, which is transparent to any HTTP client.

Still not done, and named rather than left silent: `_labelled_rows`'s `limit` is still passed by
nobody, so `identification_quality` remains linear in the whole labelled history — the cache removes
the *rebuild* from that path, not the leave-one-out scoring, which is real work. The piano roll still
filters every note of a sitting twice per animation frame, which is the largest remaining per-frame
cost on a long sitting. `PRAGMA journal_mode = WAL` still runs on every connection, and `_find_sitting`
still scans `sittings` per note and per pedal with no index on `started_ms`.

## 2026-09-22 — sight-reading agent — correction to the entry above

The entry above listed the piano roll's per-frame note filter as a remaining cost and called it "the
largest remaining per-frame cost on a long sitting". It was asserted and not measured, and measured it
is not worth acting on. On 23,482 notes — the owner's longest sitting — one pass of the `nearby`
filter is **0.140 ms per frame**, about 0.8% of a 16.7 ms budget at 60 fps. The entry also said "twice
per animation frame"; `visibleNotes` is called with the already-filtered `nearby`, so the work over the
whole sitting is a single pass, and the second number was double the truth.

So the windowed binary search that entry implied is not scheduled: it would buy about a seventh of a
millisecond for a sorted-order contract and a long-note lookback bound, which is a bad trade. The rest
of that entry's "not done" list stands unchanged — `_labelled_rows`'s unused cap and the leave-one-out
scoring in `identification_quality`, `journal_mode = WAL` on every connection, and `_find_sitting`'s
unindexed scan per event.

## 2026-09-22 — sight-reading agent — the invalidation break script, and what the tier said

Scope: `backend/tools/falsifications/drop_reference_invalidation.sh` (new). Commit `3898100`.

The reference-cache entry named a falsification that was done by hand; the standing rule wants it to be
a command, so the break is now a script. `./falsify.sh backend/tools/falsifications/drop_reference_invalidation.sh`
runs the fast tier on the clean tree first (it passed), removes `trg_segments_reference_update` from
`schema.py`, rebuilds, and runs it again: **`falsified`**, with the failure attributed to
`test_relabelling_a_segment_invalidates_the_cached_references` — `1 failed, 972 passed`, and nothing
else red. That is the narrowest possible catch: the insert and delete triggers, the kind-does-not-evict
assertion and `init_db`'s clear all still pass with the update trigger gone, so the script proves the
update path specifically rather than "some test noticed something".

## 2026-09-22 — sight-reading agent — the cap that must not be applied

Scope: `backend/app/practice/store.py`, `backend/tests/test_autotag.py`,
`backend/tools/falsifications/cap_the_reference_set.sh` (new). Commit `94590af`.

Did: the item the two entries above left open — "`_labelled_rows`'s `limit` is passed by nobody" — and
the answer is that it must stay that way. The docstring claimed "``limit`` … is what every live path
uses"; nothing does, and `docs/PLAN-PHASE22.md` §Step 3.6, `backend/app/config.py` and
`docs/ECOSYSTEM.md` all record that Phase 22b retired the reference window **as a correctness
boundary**. The parameter and the sentence were the leftover, and the honest fix was to delete them
rather than to start passing one.

The measurement that settles it, on the owner's own library — 54 labelled segments across **four**
pieces: a newest-20 reference set leaves the answer alone (piece 20, 0.699 against 0.701), newest-10
**evicts a piece**, and newest-5 loses half the library and answers with a *different piece* (19 at
0.535 where 20 scored 0.701). That is the shape of the defect Phase 22b retired: the old window held
one piece for 47 of 54 queries, left the runner-up undefined for 46 of them, and the auto band never
fired once. A cap here is a correctness change wearing a performance fix's clothes, and "make sure it
doesn't break anything" is answered by not applying it.

So the `limit` parameter is gone and the docstring now says why there is no cap, and where the cost is
bounded instead: `autotag_quality_limit` caps how many segments the accuracy report evaluates and names
the number in the report rather than sampling silently. `labelled_count`'s "ignoring the matcher's cap"
is corrected with it.

The remaining cost, stated honestly rather than implied to be fixed: `identification_quality` is still
O(evaluated × labels). With the reference cache warm it is **129 ms** at the owner's 54 labels today,
**869 ms** at 200 and **2.9 s** at 1,000. The cache removed the *rebuild*, not the leave-one-out
scoring, and no cap removes the scoring without changing what the matcher is allowed to know. The lever
that does not touch the matcher is on the frontend: `load()` awaits the quality panel before
`openSelectedSitting()`, so a slow report holds the timeline behind a panel nobody is waiting for. That
is where a fix belongs if the number ever matters.

Verified: **974 backend tests** (up from 973) and `./check.sh --fast` green. The guard pins the decision
through `cached_references`, the material every live path reads — one quiet piece labelled once plus
thirty newer labels of another must both remain references — and it was falsified with the project's
tool: `cap_the_reference_set.sh` puts a `LIMIT 20` back on the SELECT, the control passes, and the run
reports **`falsified`** attributed to `test_every_label_is_a_reference_however_lopsided_the_library`
(`1 failed, 973 passed`, nothing else red).

Not done, deliberately: the two settings Phase 22b left dead, `SRT_AUTOTAG_NEIGHBOURS` and
`SRT_AUTOTAG_TRAINING_LIMIT`. `config.py` records their removal as a deployment decision — an operator
may have set the env vars and a documented setting is not withdrawn in a code commit — so they are
untouched, and this entry is the reminder rather than the removal.

## 2026-09-22 — sight-reading agent — the cost that vanished when the last section was labelled

Scope: `backend/app/practice/store.py`, `backend/tests/test_autotag.py`,
`backend/tools/falsifications/read_the_sitting_notes_per_segment.sh` (new). Commit `8b775c3`.

Did: a reported symptom — "operations are slow while a sitting still has an unlabelled section, and snap
back the moment everything is labelled". Not an impression, and the cause was precise.

**The gate is in the code.** `candidates_for_sitting` returns `{}` the instant nothing is undecided, so
the cost is exactly zero once the last label lands — which is why the boundary the owner noticed is so
sharp, and worth naming in the answer rather than leaving as folklore. Every edit reaches that function
because `PracticeLogView.edit()` re-reads the sitting after writing, deliberately, so the derived
passages match the segments.

**Each question re-read the whole sitting's notes.** `segment_identification` fetched the segment's
notes with a query by *sitting* — `WHERE sitting_id = ?` returns every note in the sitting, and the
caller keeps one segment's share. Asking it once per open section meant a sitting read its own notes n
times per edit. Measured on the owner's library, `sitting_detail` on a 23k-note sitting: **1 section
171 ms, 5 → 241 ms, 20 → 516 ms, 50 → 1062 ms**, with `_notes_for_segments` called 51 times and 734 ms
of the run inside `fetchall` alone.

`segment_identification` now accepts the notes it is about to use, and both callers read once for the
whole run. The second caller is the one that would have been missed: `_autotag_rows` had the same shape
on the pass that runs when a sitting is *first* segmented — the other half of "I just finished and
opened it" — and it also rebuilt the entire reference set uncached; it reads `cached_references` now,
the material the timeline already caches. After: **1 → 171 ms, 5 → 173, 20 → 207, 50 → 259** — flat in
the open sections instead of linear.

Verified: **975 backend tests** and `./check.sh --fast` green. Equivalence is direct rather than argued:
the batched note read returns exactly what the per-segment read returned for all 68 segments, and the
cached references equal `examples_from` + `_pooled_signatures` for the autotag pass. The guard counts
note reads rather than timing them, so it cannot pass by running on a quiet machine — the first draft of
the test failed for the honest reason that a cold reference cache costs one extra read on the *first*
sitting, which is why it now warms the cache before counting. It was falsified with the tool: deleting
the handed-down `notes=` argument restores the defect, and the run reports **`falsified`** attributed to
`test_reading_a_sitting_does_not_read_its_notes_once_per_open_section` (`1 failed, 974 passed`).

Not done, and the shape of what is left: the per-edit cost is flat now but not zero — one passage pass
and one suggestion pass over the sitting's notes remain, about 80 ms with nothing open and 260 ms with
fifty sections on this machine. The deeper shape is that every edit re-reads the whole detail so the
derived passages stay honest; returning the passages with the edit's own response would remove the
re-read, and that is a contract change rather than a fix.

## 2026-09-23 — sight-reading agent — CI was red for two reasons, and the first hid the second

Scope: `.github/workflows/ci.yml`, `backend/tests/test_server_hardening.py`,
`backend/tools/falsifications/require_both_sequencer_signals.sh` (new), `frontend/package.json`,
`README.md`. Commit `c4ef01b`.

Did: the CI failure. It was two failures: `check.sh --fast` stops at the step that fails, so only the
first was ever visible and the frontend step had never run on the runner at all.

**The test asserted a fact about the machine it ran on.**
`test_the_sequencer_probe_accepts_either_signal` pointed one path at a nonexistent directory and the
other at `/proc/asound/seq/clients` — the machine's own. That file is present on a box with the ALSA
sequencer loaded and absent on a GitHub runner, so the test passed here and failed on every CI run for a
reason that had nothing to do with the probe. It now uses two files under `tmp_path`, which is also the
only way to cover both directions its docstring claims: the procfs listing alone, and the device alone.
The production probe was already right — `SEQUENCER_PATH.exists() or SEQ_CLIENTS_PATH.exists()`.

**And the runner could not have run the frontend tests anyway.** `ci.yml` pinned
`node-version: '20'` while the frontend units are TypeScript executed by `node --test`. Node only
learned to strip types itself in 23.6, so on 20 each of them dies with
`ERR_UNKNOWN_FILE_EXTENSION: Unknown file extension ".ts"` — reproduced with
`npx -y node@20 --test src/lib/clock.test.ts` rather than inferred from release notes. The backend step
failed first, so that pin had never been exercised. It is 26 now: what `docs/PLAN-PHASE8-9.md` verified
("Node 26 strips TypeScript types itself, so this needs no vitest") and what the project is developed
on. The real floor is recorded as `engines: {node: ">=23.6"}` and the README's "Node 20+" is corrected,
so the next pin cannot drift the same way in silence. `npm ci`'s lockfile sync still passes with the
field added, and `actions/setup-node`'s own versions manifest lists 26.x (through 26.10.0), so the pin
resolves rather than becoming a new red badge at the setup step.

Verified by reproducing the runner rather than reasoning about it: a pytest plugin makes those two paths
report absent, which fails the old test and passes the new one, and the whole backend suite (975) passes
under it. `./check.sh --fast` green in 80 s. The either-signal property now has a break script and was
falsified with the tool: `and` in place of `or` fails
`test_the_sequencer_probe_accepts_either_signal` — which is exactly the wrong diagnosis the probe exists
to prevent, since a container has the sequencer running and no `/dev/snd/seq`.

Stated plainly, because it is the one thing this entry cannot claim: the CI has not been seen green on
the runner. What is verified is the failure mode reproduced locally and the fix passing under it; the
next push is the first run of the corrected workflow, and the Node-26 pin is backed by the version
manifest rather than by a green action.

Still not covered by CI, unchanged and deliberate: the browser tier, which needs `/usr/bin/chromium`
and whose absence would make the badge mean "the runner has no Chromium" — the workflow's own header
makes that argument, and it stays run locally and via `./check.sh --full`.

## 2026-09-23 — sight-reading agent — the sostenuto stops being a single button

Scope: `frontend/src/lib/pedalGesture{,.test}.ts`, `frontend/src/lib/pedalBindings{,.test}.ts` (new),
`frontend/src/lib/{state.svelte,capture,api,types}.ts`,
`frontend/src/components/{SetupPanel,SegmentTimeline}.svelte`,
`backend/app/practice/{models,schema,store,api}.py`, `backend/tests/test_practice_{store,api}.py`,
`backend/tests/test_migration_upgrade.py`, `backend/tools/e2e_browser.py`,
`backend/tools/falsifications/` (four new scripts), `docs/PLAN-PHASE23.md` (new), and
`README`-adjacent docs: `docs/{ECOSYSTEM,FEATURES,PLAN-PHASE20B}.md`.

Did: **the middle pedal now carries three gestures instead of one.** The request was to "bind the
pedals to a list of quick actions", and the design went out of its way to narrow that, because read
literally it re-opens a defect the owner reported in use. `HandsfreeAction` was a single-member union
whose own comment said a second action would be a type change the compiler points at; it is now
`mark_review | toggle_workout | toggle_audio_capture | finish_sitting`, and `PedalGesture` tells a
*press*, a *double press* and a *press and hold* apart on CC66 alone. Each gesture is bound in Setup
to one action or to nothing, and the partition is a pure module (`pedalBindings.ts`) rather than three
fields in the store, because "one action occupies one gesture" is a rule the store cannot test.

**Why not the damper and the soft pedal, which is what was asked for.** Both are *played*, and this
project has paid for that twice: the soft pedal was bound to take recording in 20b and unbound the
same day after the owner reported that tapping it stopped the recording, and the damper's double tap
was retired for firing during ordinary pedalling. The damper is the worse case — pressed constantly, so
even an additive action would fire throughout normal playing and bury the strip in flags nobody asked
for. So the customization is *which action each gesture on CC66 carries*, not which pedal carries a
gesture. The sostenuto is unused musically, which is what makes three gestures on it free.

**The safest action takes the easiest gesture, and that is a behaviour change.** A press flags the
place for review; a double press starts or finishes a workout; the hold — the one gesture that cannot
be accidental — arms or stops the take. Take recording therefore moves *off* the single press, which
is the owner's daily habit, so the bench scenario's assertions were inverted in the same commit rather
than left to be discovered. `finish_sitting` ships unbound.

**A review flag is the blur hairline's shape with a different meaning** — the owner's words were "like
we have pedal blurs … a little flag saying you should review near here". A blur is a place the app
*measured*; a flag is a place a person *asserted*. It travels as its own raw stream: a `sitting_marks`
table, an optional `EventBatch.marks` (so a client that predates it is unaffected), `review_marks_ms`
on the sitting detail, and a `.review` layer on the strip. `CaptureClient.mark()` is deliberately not
a subscription to CC66 — a mark is written only when the flag action is bound *and* fired, so an
unbound pedal writes nothing. It is not a JSON column on `sittings` (the client cannot know the open
sitting, so a retried press could land in the wrong one) and not a widened `pedal_events` (`midi.ts`
warns that routing CC66 down the sustain path records the middle pedal as sustain and corrupts
`pedal_blur` and `pedal_basis`).

**The property that makes the extra gesture free.** With single and double both bound, a tap cannot be
recognised until the double window closes. A fire therefore carries the **press** timestamp, not the
dispatch one, so a flag resolved 300 ms late still lands where the player was; only the confirmation
is late. There is a break script for exactly that, because it is the kind of thing a later
"simplification" would quietly undo.

**Two defects the tests found that reading did not.** (1) The private field `pending` shadowed the
`pending` getter on the prototype, so the accessor was dead and the recogniser's public "is anything
still waiting on the clock" always read the raw field — the new unit test failed on its first run, and
the field is `pendingTap` now. (2) `EventBatch` and `store.ingest` were widened for marks, but the
API-level emptiness guard in `practice/api.py` was not, so a mark-only flush — the *ordinary* case,
since a flag is pressed between phrases — returned 422 and the client would have retried it forever,
blocking every note behind it. The browser tier caught that one; both now have assertions.

**A pre-existing failure, and why it had sat there.** Running the bench at all was impossible: the
tier died in `reset_all()` with `reset_all does not cover ['reference_state']`, before reaching a
single scenario. `reference_state` was added in 22b and is in neither `DATA_TABLES` nor
`REFERENCE_TABLES`, so **the whole browser tier was red at HEAD** — and it is the tier the CI workflow
deliberately does not run (it needs Chromium), which is how a table added in September went
unregistered. It belongs in `REFERENCE_TABLES`, not `DATA_TABLES`: its one row is seeded by `init_db`
and advanced from then on by triggers on `segments`, so deleting it between scenarios would leave it
absent for the rest of the process, the triggers would update nothing, and the matcher's in-process
reference cache would stop invalidating — each scenario would read the one before it. Named there with
the reason; the gate's own refusal message is what makes that decision a lookup rather than a guess.

Verified: frontend **145 passed**, `svelte-check` clean, build clean. Backend **982 passed** (the
frozen-shape test refused the new table until it was named in `EXPECTED_COLUMNS`/`EXPECTED_INDEXES`,
which is that gate working). `scenario_bench` green, with three new assertions: a press and hold arms
the take, a single tap leaves it alone *and* leaves a flag on the sitting (`0 -> 1 marks`), and a press
during a scored run leaves neither. Four falsifications each caught their break **by name** with
`--expect`: `stamp_the_flag_when_it_fires.sh` (`expected: 1000` — the deferred tap stamped at 1300),
`let_a_single_press_stop_the_take.sh` (`expected: 'mark_review'`), `refuse_a_mark_only_flush.sh`
(422), and `drop_the_mark_stream.sh` end to end in the browser ("flags the place instead"). The tree
was committed first so the harness could restore cleanly, which is the rule it enforces.

Not done, deliberately: no binding for the damper or the soft pedal and no silence gate that would make
one safe; no deletion or editing of a flag (a mis-fired flag is inert and costs one hairline, and the
fix if it becomes noise is a click-to-remove rather than a delete mode); no per-segment flag count; no
`SCHEMA_VERSION` bump, since a brand-new table is created by `CREATE TABLE IF NOT EXISTS` on every
`init_db`; and `README.md` needed no change — its only mention of pedals is the Setup grouping label,
with no behavioural claim to go stale.

## 2026-09-23 — documentation agent — the docs are audited, and their stale status is corrected

Scope: `docs/`, `README.md`, `deploy/README.md`, `check.sh` (comments only), `AGENT-LOG.md` header.
No code or test changed.

Did: a read-only audit of every document against the code, then a correction pass. The findings worth
naming, because each was a reader-visible falsehood rather than a typo: `ECOSYSTEM.md`'s status line
stopped five phases short and its phase table had no rows for phases 15, 16 or 17; its
`SCHEMA_VERSION` note said 3 where the code says 5; its table list named
`identification_corrections`, a table the same document records as never ported; and its CC64
double-tap was still described as live in three places after it had been retired. `FEATURES.md` still
cut segments at a fixed 8 seconds, which Phase 22a replaced, and `ENGINEERING.md` already said so —
the two reference documents disagreed. `ENGINEERING.md` claimed "every threshold lives in config"
while four scoring constants are hardcoded, and documented a texture level 10 that writes four voices
when the generator writes two. `DEPLOYMENT.md` pointed at a README configuration table that no longer
exists, and named a kiosk systemd unit that was deliberately never created. Four `PLAN-PHASE*` files
still said **planned** for landed work and four still ended with "Next step: execute with the
`executing-plans` skill". `TEST-STRATEGY.md` carried three different test counts for one suite and
promised a `docs/TESTING.md` that does not exist. `ROADMAP.md` called itself the plan of record three
lines above its own superseded banner. `PLAN-PHASE20B.md` asserted a damper gesture that `987c9ec`
had already removed.

Test counts, scenario counts and script counts were date-stamped or replaced by the command that
prints them, and `TEST-STRATEGY.md` §1 is now labelled as the 2026-09-20 snapshot it always was — the
suite moved twice during the audit (975 then 982 backend tests), which is exactly why bare totals are
not used.

One item is left deliberately unfixed: `check.sh:106` prints `$refused` twice and never labels
`$skipped`. It is a real bug in the summary line, but fixing it changes an executable's output rather
than a comment, which is outside this pass's remit. It is recorded here so that it is not lost.

Impact on the other side: none. No contract, table, endpoint or schema changed; the only
non-documentation file touched is `check.sh`, and only its comments.

## 2026-09-23 — documentation agent — the docs gain a standing rule, and a trigger table

Scope: `docs/ECOSYSTEM.md`, `docs/TEST-STRATEGY.md`, `README.md`, `AGENT-LOG.md` (rules). No code
changed.

Did: **a change is now not done until the documents it invalidates are updated, in the same commit
that lands it.** That is the documentation half of the test strategy's standing rule. It is written
into the section that already owned "update the owning docs, not new siblings" rather than as a new
document, because a second authority for the same facts is always the one that goes stale.

The rule is a trigger table: what to update for a landed phase, a schema change, a route, a tunable,
player-visible behaviour, a scoring constant, a deploy mechanism, a limitation, a plan that
finishes, and a contract change. It also carries the two habits whose absence the clean-up commit
exposed — never write a bare count (this suite moved 975 → 982 *during* that pass, and three stale
claims were found inside the clean-up's own drafts), and supersede a landed plan rather than
rewriting it.

`TEST-STRATEGY.md` §8's definition of done gained the third clause and points at the table, because
plans already cite that blockquote as their authority; `AGENT-LOG.md` gained it as rule 4; and
`README.md`'s verification section points at it for a human reader.

The honest part, stated in the rule itself: nothing enforces it yet. The three greps that catch the
common cases are in the document, and a link-and-status checker wired into `check.sh --fast` is the
real enforcement — it is not built.

Impact on the other side: none. No contract, table, endpoint or schema changed.

## 2026-09-23 — documentation agent — check_docs, so the standing rule can fail a build

Scope: `backend/tools/check_docs.py` (new), `backend/tools/falsifications/` (four new break scripts),
`check.sh` (one step), `docs/ECOSYSTEM.md`, `docs/TEST-STRATEGY.md`, `README.md`.

Did: **the documentation standing rule now has a command behind it.** The rule says a change is not
done until the documents it invalidates are updated in the same commit. Nothing checked it, and that
is how `ECOSYSTEM.md` came to describe a shipped phase as **Planned** for three commits with every
tier green.

`backend/tools/check_docs.py` runs in `--fast` — sub-second, so the 82 s tier is unchanged — and
gates on four objective things: a relative link or `#anchor` that does not resolve; a `docs/*.md`
that nothing links to from the README; a plan and the phase table disagreeing about whether a phase
shipped (reading the table row, and falling back to the status line for the phases the table leaves
unmarked); and a landed plan still ending in "Next step: execute…". It also reports, without gating,
a short canary list of exact phrases whose return would mean a fixed bug has come back — a heuristic
that can be wrong must not be allowed to fail a build.

It refuses rather than guessing: if `ECOSYSTEM.md`'s phase table or status line cannot be parsed it
exits 2 and says which, instead of printing a clean run it has not earned.

**Two defects it found on its first run, in this repository's own new text.** The README index
reached only three of the five Phase 20 plans — the `[20A] … [20E]` elision left B, C and D
unlinked — and the row-status matcher missed `**20a–20e landed.**` because it was case-sensitive, so
five of the ten plan/phase pairs were silently uncompared. Both are fixed here, and the pair count
is now the full ten.

Each gate has a break script under `backend/tools/falsifications/`; the falsification results are
recorded in the next entry.

Impact on the other side: none. `check.sh` gained a step; no application code changed.

## 2026-09-23 — documentation agent — the docs gates falsified, and the one that could not fail

Scope: `backend/tools/check_docs.py`, `AGENT-LOG.md`.

Did: ran the four break scripts from the entry above through `falsify.sh`. **Three caught their break
by name; one did not** — which is the entire reason this repository falsifies an assertion before
trusting it.

- `stale_phase_status.sh` → `docs/PLAN-PHASE22.md:7: says **planned**, but ECOSYSTEM.md marks phase 22 **landed** (table row, line 216) — one of them is stale`
- `restore_the_execute_footer.sh` → `docs/PLAN-PHASE21.md:944: landed plan still carries a Next step`
- `break_a_document_link.sh` → `README.md:297: link does not resolve: docs/FEATURES-MISSING.md`
- `make_a_document_unreachable.sh` → **passed with the break applied**, so that gate could not fail.

**The reachability check searched for the path *text*, not for a *link*.** The break replaces
`[docs/TEST-DATA.md](docs/TEST-DATA.md)` with backticked prose, and the string `docs/TEST-DATA.md`
was still in the README, so the check stayed green while the document was unreachable from the index
— the exact condition it exists to catch. It now resolves the README's link targets and compares
resolved paths, so prose that merely *mentions* a document no longer satisfies it.

Worth stating plainly: that gate would have reported success forever while checking nothing. It is
the same failure as the unfailable assertions `TEST-STRATEGY.md` §8 was written about, reproduced in
the tool built to enforce the documentation half of §8.

Impact on the other side: none.

## 2026-09-23 — documentation agent — the four docs gates re-run, and a filter that tests nothing

Scope: `docs/ECOSYSTEM.md`, `AGENT-LOG.md`.

Did: re-ran all four documentation break scripts after the reachability fix. **Four breaks, four
catches, each naming what it was expected to name, and the tree clean after every run:**

| Break | Caught with |
| --- | --- |
| `break_a_document_link.sh` | `link does not resolve` |
| `make_a_document_unreachable.sh` | `no link to docs/TEST-DATA.md` |
| `stale_phase_status.sh` | `one of them is stale` |
| `restore_the_execute_footer.sh` | `Next step` |

Corrected a false claim in the rule while recording this: it suggested `./check.sh --falsify
check_docs`, and no break script's name contains `check_docs`, so that filter matches nothing. The
document now names a filter that does exist.

**And that exposes a real defect in the falsify tier, left unfixed because it is outside this
change.** `./check.sh --falsify <filter>` skips every script whose name does not contain the filter
and then passes on `failed == 0` — so a filter that matches nothing reports a clean run having
tested nothing, and a typo reads as a green light. It belongs to the same family as the reachability
gate fixed above, and as the unfailable assertions §8 exists to prevent. It is recorded here rather
than fixed here: it is one condition in `check.sh`'s `--falsify` branch, and it wants a
falsification of its own.

Impact on the other side: none.

