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
