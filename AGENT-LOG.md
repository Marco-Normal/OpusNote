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
unchanged, and the recording upload still writes `source='uploaded'`. Residual risk worth naming: the
recorder polls once a second, so a take can miss up to the first second of the phrase that opened it;
that is quality, which 20-D4 explicitly does not make an acceptance criterion.

Verified: backend **880 passed**; frontend 81; `svelte-check` clean; build clean; the new
`takes` browser scenario passes ten assertions against a fake microphone, including that the take is
attached to the piece, the playing and the passage, and that 0.5× reaches the element with the
same-pitch readout; four falsifications run and caught their breaks
(`drop_media_source_column.sh`, `drop_capture_segment_link.sh`, `drop_take_catch_up.sh`,
`cut_takes_at_the_wrong_gap.sh`); `./check.sh --full` green in **566 s**.
