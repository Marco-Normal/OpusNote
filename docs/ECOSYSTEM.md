# The piano ecosystem — target architecture and migration

Written by the sight-reading agent. Supersedes the "share `piano.db` with the
Rust app" premise of
[`INTEGRATION-practice-logger.md`](./INTEGRATION-practice-logger.md), which
remains accurate about *what exists today* but is no longer the destination.

Status: **decided; Phases 1-9 are landed.** See §9 and §10 for what each one delivered.

---

## 1. The one thing to get straight first

You said the problem is the Rust dependency, and the fix is a rewrite in Python.
I agree with the destination but not with that diagnosis, and the difference
matters because it decides what we actually build.

**Rewriting in Python does not fix the multi-machine problem.** Moving from
Rust + SQLite to Python + SQLite leaves the data exactly as machine-local as it
is today. You would have a nicer stack and the same two diverging databases.

The thing that fixes it is **having one database, on one machine, that every
other machine reaches over the network.** Everything else — language, framework,
number of apps — is secondary to that.

There is also a hard constraint that settles where that machine must be:

> **Web MIDI requires a secure context.** `localhost` counts as secure;
> `http://192.168.1.50` does not. Chrome will not give a remote LAN page access
> to MIDI inputs.

So the backend that captures MIDI must run **on the piano machine**, reached as
`http://localhost:8000`. Other machines can browse to it for viewing (no MIDI
needed there, so plain HTTP over the LAN is fine). That single fact removes the
duplication you are worried about: there is one database, and it lives where the
piano is.

Two consequences worth accepting up front:

- The piano machine is authoritative. If it is off, the dev machine cannot browse
  the log. For a personal practice tracker that is a fair trade.
- If you ever practise at **two** instruments, single-host is not enough and we
  need export/import or a small sync. That is decision **D1** below, and it is
  the one answer that could change this whole plan.

---

## 2. So is the Python rewrite worth it?

**Yes — for reasons other than sync.** Judged on its own merits, dropping Rust is
sound:

| Reason | Weight |
| --- | --- |
| One stack. Python + Svelte everywhere; one set of conventions, one test idiom, one way to add a feature | high |
| The library becomes reachable from any browser, which the desktop app can never be | high |
| No cross-process database sharing, so the whole "two owners, one file, WAL, never write their tables" discipline — which your own logger design calls *the load-bearing rule* — simply ceases to exist | high |
| Cross-domain features become joins instead of HTTP calls | high |
| Sync is not fixed by it | **zero** — see §1 |

What it costs, honestly:

| Cost | Estimate |
| --- | --- |
| Library CRUD + filters + grouping + statistics | moderate |
| Daily practice journal | small |
| **Media: import, ffmpeg probe/transcode, content-hashed storage, playback** | **large — this is the real work** |
| Data migration | small; it is one SQLite file |

The Rust app is 2,195 lines: `app.rs` 1,300 (the egui UI), `db.rs` 513,
`media.rs` 252, `models.rs` 105. The media pipeline is the part that does not get
cheaper in Python — ffmpeg calls, hashing, and 138 MB of files that need a home
and a way to be served.

---

## 3. Target architecture

**One application. One database. One host. Three domains.**

```
                        ┌──────────────────────────────┐
   piano machine ──────▶│  one FastAPI app  +  Svelte  │
   (authoritative)      │  one SQLite DB + media/      │
                        └──────────────────────────────┘
                                     ▲
   dev machine ────── browser ───────┘   (viewing; no MIDI, so plain HTTP is fine)
```

Inside, three domains as packages, not as separate processes:

```
backend/app/
  config.py          one settings object, one data dir
  db.py              one schema, one connection policy
  main.py            one FastAPI app mounting the route modules
  repertoire/        composers, pieces, journal, media      ← new, replaces piano-progress
  practice/          capture, sittings, segments, analytics ← ported from practice-logger
  music/ scoring/ adaptive/ services.py …                   ← the existing sight-reading code
```

Deliberately **no restructuring of the existing sight-reading modules.** They
work, they have 418 tests, and moving files for tidiness buys nothing. New
domains are added beside them.

Why one app rather than three:

- One process means one capture path, which **structurally eliminates the
  double-capture hazard** I flagged in the integration design. Two browser tabs
  racing to log the same MIDI is a coordination problem; one app cannot have it.
- The valuable features are cross-domain: *"generate sight-reading in the key of
  this piece"*, *"time per piece, including sight-reading"*. Those are joins, not
  integrations.
- One thing to install, one thing to back up, one URL.

What we lose: independent lifecycles for the two apps, and the ability for two
agents to work in separate repos without stepping on each other. The mitigation
is keeping the domains as separate packages with explicit interfaces — agents can
still own a package each.

---

## 4. Data model, and a naming collision to fix

One database, three domains:

```
repertoire     composers, pieces, piece_journal, media
practice       sittings, note_events, segments, segment_metrics, identification_corrections
sight-reading  users, skills, user_skills, exercises, exercise_skills, performances, workouts
```

**The word "note" currently means three different things** across the projects,
and one of them is already in the Rust schema:

| Meaning | Current name | Proposed |
| --- | --- | --- |
| A dated text observation about a piece | `piano-progress.notes` | **`piece_journal`** |
| A raw MIDI note in a performance | `practice-logger.note_events` | `note_events` (fine) |
| A note the notation asks for | trainer's expected-note timeline | `expected_notes` (fine) |

`piano-progress.notes` is the odd one out and renaming it at import time is free.
Leaving it would guarantee confusion in a database that also stores MIDI notes.

---

## 5. Migrating off the Rust app without losing anything

The Rust app must keep working until the replacement actually covers what you
use. So this is a cutover, not a big bang:

1. **Import, never write back.** A one-time importer reads `~/.local/share/piano-progress/piano.db`
   (read-only, as the logger already does) plus the `media/` directory, and
   populates our own tables. The Rust database is never modified.
2. **Run both while parity is incomplete.** You keep using the Rust app to add
   pieces; the importer can be re-run to pick up whatever it has gained.
3. **Cut over when the web app can edit.** At that point the Rust app is retired,
   the importer becomes a migration tool rather than a sync mechanism, and the
   data directory stops being `piano-progress`'s.
4. **Media is the gate.** Until the web app can at least *serve* the 138 MB of
   recordings, retiring Rust means losing playback.

Our own data directory, so we stop borrowing another app's:

```
~/.local/share/piano-ecosystem/     ← default, env-overridable
├── piano.db
└── media/
```

Portable IDs are **not** needed under single-host, so keep integer primary keys
and provide JSON export/import for backup and machine moves. UUIDs are the escape
hatch if §8 D1 turns out to be "yes, two instruments".

---

## 6. Phased plan

Each phase ships on its own and leaves the system working. Nothing here discards
existing code: the sight-reading modules stay put, and `practice-logger`'s
sessionizer and segmentation move across as-is with their tests.

| # | Phase | Delivers | Risk |
| --- | --- | --- | --- |
| 0 | **Stop the bleeding** *(optional)* | Point both apps at a configurable data dir and run them on the piano machine. Fixes the sync pain today, with no rewrite. | none |
| 1 | **Spine** | One DB and one data dir owned by us; `repertoire/` package; importer from the Rust DB; read-only API for pieces/composers/journal. | low |
| 2 | **Repertoire UI** | A Repertoire section: list, filter, group, per-piece stats and journal. Read-only at first, then editing. | low |
| 3 | **Repertoire editing** | Create/edit pieces, composers, journal entries. **Parity point** — the Rust app can now be retired except for media. | medium |
| 4 | **Media** | Serve existing recordings; import new ones with ffmpeg probe/transcode and content hashing. **Full parity point.** | high |
| 5 | **Port practice-logger** | Its tables and its sessionize/segment/ingest code move into `practice/`, tests included; capture moves into our frontend; the old repo is retired. | medium |
| 6 | **Cross-domain features** | Sight-reading generated from your active pieces; unified time-per-piece; one dashboard; workouts (roadmap Slice E). | low |
| 7 | **Portability** | JSON export/import, deployment notes for the piano machine, backup guidance for WAL. | low |
| 8 | **MIDI that sets itself up** | Auto-connect and auto-select on a piano that is switched on later, across a device list that includes ALSA's dead *Midi Through* port. | low |
| 11 | **Progress you can see** | Rating history per skill, click-and-hear a past attempt, sub-score trends, week in review. | low |
| 12 | **Ops polish** | Nightly rotating backups, a health panel, latency suggested from your own timing bias. | low |
| 13 | **Library depth** | Attach and render scores (PDF and MusicXML), waveform with A/B loop, sustain pedal captured, self-similarity auto-tagging. | medium |
| 14 | **More musical content** | Unusual meters, clef reading, dynamics and articulation depth. | medium |
| 10 | **Playback** | Hear a scored attempt back (either hand, or the exercise as written) and hear a logged sitting or segment from the practice log, with a playhead. | low |
| 9 | **LAN server** | A planted notebook serving the whole app on the local network: `deploy/`, kiosk autostart, capture heartbeat, upload cap, concurrent-write hardening. | medium |

Phases 1-2 are the useful minimum: they get the library out of the Rust app's
directory and into a browser, which is most of what you asked for.

---

## 7. What this means for `practice-logger`

Your logger is not wrong and its code is not wasted — its *premise* changes. Three
things it was built around stop being true:

| Its assumption | New reality |
| --- | --- |
| Shares `piano.db` with the Rust app, two owners, WAL, never write their tables | One app owns everything; the ownership discipline becomes an internal package boundary, which is much cheaper to hold |
| Its own FastAPI app on port 8001 with its own Svelte client | Becomes a package and a section inside one app |
| Faces the double-capture hazard | Gone structurally — one capture path |

What survives untouched and is genuinely valuable: the sessionizer (live and
rebuild agree), gap segmentation with frozen boundaries, the idempotency design,
the attack-clustering fix for tempo, and the whole test suite. Phase 5 is a port,
not a rewrite.

I have updated the brief in your `docs/` and the shared log accordingly.

---

## 8. Decisions needed

| ID | Question | My recommendation | Why it changes the plan |
| --- | --- | --- | --- |
| **D1** | **Do you practise at more than one instrument or machine?** | Assume one | If two, single-host is insufficient and we need export/import or real sync — which changes the ID strategy and adds a phase |
| D2 | One app, or keep separate apps on one database? | One app | Determines whether the double-capture hazard and the ownership discipline stay |
| D3 | Media: full import/playback in the browser, or "open in system player" only? | Full, but deferred to Phase 4 | It is the single largest cost and the gate on retiring Rust |
| D4 | Retire the Rust app at Phase 3 (pre-media) or only at Phase 4? | Phase 4 | Decides whether you keep a working player through the transition |
| D5 | Data directory name, and whether to rename the repo | `piano-ecosystem`; repo rename is cosmetic, decide later | Low impact, but it is in every path and doc |
| D6 | Does the library get edited from the piano machine only, or anywhere? | Anywhere, over the LAN | Confirms plain-HTTP viewing is acceptable |

**D1 is the only one that can invalidate the architecture.** The rest are
sequencing.

---

## 9. Decisions taken, and what Phase 1 delivered

| ID | Decision | Consequence |
| --- | --- | --- |
| D1 | **One instrument, one machine** | Single-host it is. Integer primary keys stay; no UUIDs, no sync code, no merge logic. This is the simplest architecture available and it is sufficient. |
| D2 | **One app, three packages** | `repertoire/`, `practice/`, and the existing sight-reading modules live in one FastAPI app with one database. The double-capture hazard is gone structurally. |
| D3 | **Full media import and in-browser playback** | Media stays in scope; it lands in Phase 4 and it remains the largest single cost. |

### Phase 1 — landed

- **Our own data directory.** `~/.local/share/piano-ecosystem/` holding `piano.db`
  and `media/`, overridable with `SRT_DB_PATH` and `SRT_MEDIA_DIR`. The app no
  longer writes into, or depends on, `piano-progress`'s directory.
- **`app/repertoire/`** — schema, models, queries, importer, and HTTP routes,
  mounted by the main app. The sight-reading modules were not moved.
- **One-time importer** from the legacy database, read-only, idempotent, and safe
  to re-run while the Rust app is still in use. It refuses a missing file or a
  database of the wrong shape rather than importing nothing quietly.
- **`app/bridge.py`** — the only module that knows both domains. Maps a piece's
  key and difficulty onto a sight-reading key and starting level.
- **41 new tests**, and the existing 418 still pass.

Verified against the real library: 7 composers, 17 pieces, 3 journal entries and
42 media rows imported, matching the source counts exactly, with every piece's key
mapping onto a sight-reading key.

Two things found and fixed while building it: the importer created an empty media
directory even for a metadata-only import, and `normalise_key` mishandled
hand-written capitalisation (`"BB Major"` for B-flat).

### Phase 2 — landed

A **Repertoire** section in the browser, read-only, against the API from Phase 1:

- The library grouped by composer or difficulty, with a search box and status and
  composer filters.
- Per-piece detail: description, the journal, and the recording catalogue with a
  present/missing indicator per file.
- The **sight-reading fit** for a piece — its key and starting level — with
  completed pieces deliberately excluded, since you do not sight-read around a
  piece you have finished.
- An import flow that appears when the library is empty and a legacy database is
  found, with an option to copy the recordings across.

Verified against the real library (17 pieces, 7 composers, 42 recordings) and by
an e2e scenario against a deterministic fixture.

### What Phase 2 uncovered

**A latent threading bug that had been in the app since the beginning.** FastAPI
resolves a sync dependency and then runs a sync endpoint in *different* threadpool
threads, so a SQLite connection created in the dependency is used from another
thread and SQLite refuses it:

```
sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread.
```

It surfaced only for the repertoire routes because included routers take a
different scheduling path than top-level ones — the existing endpoints had been
getting away with it by luck, not by design. Fixed once, in the single connection
factory, where it protects every route.

It was invisible to `TestClient`, which does not schedule the way uvicorn does.
The browser e2e caught it in seconds. That is the argument for keeping the browser
scenario in the loop rather than trusting the unit suite alone.

Also fixed: the frontend API client read the error body twice (`json()` then
`text()` on failure), which replaces the server's message with "body stream
already read" — at exactly the moment you need the real error. It now reads once
and includes the server's `detail` in the message.

### Phase 4a — recordings now play (landed)

Triggered by using the thing: the first import left every recording labelled
"file missing", which reads as data loss when the file is sitting in the old
directory untouched. Three fixes:

- **Three states instead of a boolean.** `present` (copied into our media
  directory), `pending` (still only in the legacy library), `missing` (in
  neither). "Uncopied" and "lost" are different facts and were being conflated.
- **Copying is the import default.** A library whose recordings all read as
  missing is the wrong first impression, and the copy is what makes the app
  self-contained rather than pointing back at the old app's directory. Verified:
  42 files, 138 MB, `media_present: 42`.
- **Recordings stream and play in the browser**, from our copy when we have one
  and from the legacy library until then, so they are audible immediately. The
  endpoint validates the file name as a bare name — recording names are content
  hashes, so a path separator means the row was tampered with — and returns 410
  when a file is in neither place. Starlette's `FileResponse` handles Range
  requests, so seeking works (verified: 206 Partial Content).

Still to come in Phase 4: **importing new recordings** — upload, ffmpeg probing
and transcoding, content hashing. That is the remaining large piece and the last
thing the Rust app does that we do not.

### Phase 3 — landed (repertoire editing)

Create and change pieces, composers and journal entries, with PATCH semantics that
distinguish "not mentioned" from "cleared". **Parity point** — after this the Rust
app can be retired except for recording import.

### Phase 4b — landed (recording import)

Upload a recording, `ffprobe` it, transcode to Opus, content-hash the *original*
and store the result under that name. Re-importing the same audio is refused with
409 rather than stored twice, which is what makes the hash a real dedupe key.
**Full parity point:** the Rust app can be retired.

### Phase 5 — landed (port of `practice-logger`)

`app/practice/` holds the ported sessionizer, gap segmentation with frozen
boundaries, absolute-time ingest and idempotent dedupe, with their tests. Three
things changed, and only three:

| Change | Why |
| --- | --- |
| Tables are `sittings` / `note_events` / `segments` / `segment_metrics` | The agreed vocabulary: a *sitting* is emergent, a *workout* is declared, a *segment* is one piece or one workout |
| `segments.piece_id` references our own `pieces` | One app owns the library now, so the "never write their tables" discipline — and the two-owner WAL arrangement it existed for — is gone |
| `client_id` dropped from the ingest contract | It was validated and never stored; with one capture client it would be a value nothing reads |

What was **not** ported: self-similarity identification and its
`identification_corrections` table. The original's Phase 3 never landed, so there
was no matcher to correct and the table would have been dead weight.
`segments.confidence` and `segments.identified_by` remain, so a matcher can be
added later without a migration.

The port also finished the original's Phase 4: `segment_metrics` is now written,
with tempo measured over attack clusters (the fix that stops a chord reading as
infinite BPM). One honest caveat is documented in the code and surfaced in the UI:
that tempo is a **note rate**, comparable with itself over weeks, not a metronome
reading — with no score there is no way to know where the beat falls.

Capture moved into this frontend (`lib/capture.ts`) and is **app-level, not
view-level**: it is on whenever a device is connected, so the log fills without
anyone remembering to open a tab. That structurally removes the double-capture
hazard the integration design flagged: there is now one capture path.

Importing the old logger's history is one more idempotent read of the legacy
database, exposed as `POST /api/practice/import-legacy` and called by the same
Import button as the repertoire import.

### Phase 6 — landed (cross-domain features)

- **Workouts** (`app/workout/`): the `workouts` table,
  `POST /api/workout/start`, `GET /api/workout/current`,
  `POST /api/workout/{id}/finish`, a banner in the app shell, and
  `performances.workout_id` to attribute each attempt. Finishing resolves the
  sitting it happened inside by *overlap*, so a workout that ended after its last
  note still links; and segments overlapping a finished workout are tagged
  `sight_reading` when they materialise. "Deliberate sight-reading" and "time at
  the piano" therefore become two readable numbers instead of one blurred one.
- **Unified time per piece**: `GET /api/practice/pieces/{id}` gives measured
  minutes, segment and note counts, last played and the tempo trend, shown in the
  Repertoire detail *beside* the journal's written-down minutes. They are
  deliberately not summed: a session can be both measured and written down.
- **One dashboard**: the Log tab — today, streak, a twelve-week calendar, time per
  piece, neglected pieces, the source split, and the sitting timeline.
- `SRT_SESSION_LENGTH` — dead config since the beginning — became
  `SRT_WORKOUT_LENGTH`, because a workout is what it always meant.

**A decision worth recording:** the streak counts consecutive days with *any*
logged sitting, not days with a completed workout. A day you sat down and played is
a practice day whether or not you pressed Start, and a streak that only advanced on
declared workouts would nag about the very practice it exists to encourage. Workout
counts are shown separately.

### Phase 7 — landed (portability)

`GET /api/backup/export` writes one JSON document with **every table**, the table
list read from `sqlite_master` rather than written down — a hand-maintained list
goes stale the first time somebody adds a table, and a backup that quietly omits
one is worse than no backup. `POST /api/backup/import` restores it in two modes:
*merge* adds only what is missing, so importing last month's backup cannot delete
this month's practice, and *replace* empties every table first and requires an
explicit `confirm`. Foreign keys are deferred to commit, so the import does not
depend on the alphabetical order of table names.

The round trip is tested the only way that proves anything: populate every domain,
wipe every table, restore, and compare row counts and sample rows.

`docs/DEPLOYMENT.md` covers running it on the piano machine, the WAL caveat
(`piano.db` alone is a silently truncated backup), and a machine move.

### What is still open

| Item | Note |
| --- | --- |
| Retiring `practice-logger/` | Its code is ported and its history is importable; deleting the directory is the user's call, not mine |
| Courtesy clef/time-signature at system breaks | OSMD has no rule for it; recorded as an open decision, unchanged |
| Self-similarity identification | Not ported; columns and confidence bands exist if it is ever wanted |
| `SRT_*` env prefix on non-sight-reading settings | Cosmetic debt, noted and deferred |

---

## 10. Planned: unattended capture (Phase 8) and the LAN server (Phase 9)

**Implementation plan:** [`PLAN-PHASE8-9.md`](./PLAN-PHASE8-9.md) owns the
step-by-step *how* for both phases — 15 tasks with complete code, exact commands,
and the acceptance clause each one satisfies. This section owns the *what* and
*why*, and must not be edited to match drift in the plan.

Written after checking the machine rather than assuming. The user's report — the
device list showing two MIDI inputs, one called something like `0` and one called
`Casio MIDI 1`, with only the Casio working — has a specific cause:

```
$ cat /proc/asound/seq/clients
Client   0 : "System" [Kernel Legacy]
  Port   0 : "Timer" (Rwe-) [In/Out]
Client  14 : "Midi Through" [Kernel Legacy]
  Port   0 : "Midi Through Port-0" (RWe-) [In/Out]
```

**Midi Through Port-0 is the "0" in the device list.** ALSA's sequencer always
creates that virtual client, and Chromium enumerates every sequencer port as a Web
MIDI input, so a plugged-in Casio appears *beside* a port that can never carry a
note. Today's code selects `devices[0]`, which is precisely the kind of choice that
picks the wrong one.

(The first version of this section claimed the sequencer was not loaded, because
`aconnect` reported `/dev/snd/seq` missing. That was a sandbox artefact: the module
was loaded and procfs listed its clients. The probe now accepts either signal — see
`hostinfo.sequencer_available` — because reporting a missing kernel module on a
machine that has one is the wrong diagnosis in the most confusing possible way.)

Two browser facts make this fixable without ceremony, both managed policy
settings:

| Policy | Effect on a planted notebook |
| --- | --- |
| `MidiAllowedForUrls` | Grants the MIDI permission for an origin automatically — no prompt, ever |
| `HighEfficiencyModeEnabled` | Memory Saver off, so a backgrounded tab is never discarded |

Timer throttling in a background tab is harmless here **because the wire format
carries absolute epoch milliseconds**: a batch flushed a minute late still lands in
the correct sitting, with the correct gaps. Throttling costs latency, not
correctness; tab *discarding* would cost notes, which the policy prevents.

### Decisions taken

| ID | Question | Decision | Consequence |
| --- | --- | --- | --- |
| **D7** | Where does capture live on the notebook? | **A kiosk browser on its own session.** Exercises need Web MIDI anyway, and the two unattended risks (permission prompt, tab discard) are policy settings, not code | No second capture path, so no exercise-window filter and no new always-on process. The daemon stays available as a later phase with the ingest contract already compatible |
| **D8** | What does the LAN side require? | **No authentication, but the irreversible actions are loopback-only.** Read, listen, upload, edit pieces and tag segments work from any machine; deleting a piece, composer, journal entry or recording, resetting the profile, replacing the database from a backup and re-segmenting over labels are refused off the piano machine | The stated intent was "see statistics and maybe upload", so the LAN gets exactly that plus the harmless edits. No password, no login screen, and the boundary is a property of the route rather than of the person using it |
| **D9** | Which URL is used to play? | **`http://localhost:8000` on the notebook; `http://piano.local:8000` from the main computer.** No TLS | Remote MIDI stays impossible by design, which is what was asked for. If it is ever wanted, it needs a locally trusted certificate or an insecure-origin browser flag |

### Phase 8 — design

1. **Open every input and dedupe across ports**, instead of selecting one. Duplicate
   notes are collapsed on `(pitch, velocity, |Δt| ≤ 30 ms)`; 30 ms is far below any
   human repetition of the same pitch, so a real note cannot be eaten, and a genuine
   second port (some keyboards split zones across ports) cannot lose one.
2. **Learn which port is live.** The device bar labels whichever input has actually
   delivered a note, and marks ports that have delivered nothing as such. The
   diagnosis is then visible instead of guessed.
3. **Auto-connect with no gesture.** Attempted on load; the managed policy makes it
   resolve silently. The Connect button remains the fallback for a browser without
   the policy, and the grant is remembered.
4. **Reconnect by itself:** `statechange`, plus a 5 s poll while no device is
   present, plus a re-check when the window regains focus — so switching the piano
   on ten minutes later just works.
5. **A pin** for strictness: "use only this device", remembered as a fingerprint of
   `manufacturer + normalised name`, with Chromium's per-origin salted `input.id` as
   the fast path.
6. **A "last note seen" indicator**, so "is it working?" needs no chord and no hope.

**Acceptance.** With two simulated inputs — a dead `Midi Through Port-0` and a live
`CASIO USB-MIDI` — the app connects and labels the Casio with no click, and a note
delivered on both ports is logged and scored once. A device that appears after load
is picked up by itself. Existing scenarios are unchanged. On the real notebook:
`snd_seq` is loaded, and the device bar names the Casio.

The browser e2e grows the two-port fake device, which reproduces the user's report
exactly; no new JS test runner is introduced for it.

**Landed.** The selection rules live in `frontend/src/lib/midiDevice.ts` with unit
tests (`npm test` — Node's own runner, no new dependency): `NoteGate` drops a note
reported by a *different* port within 30 ms, `PortActivity` records which port has
actually carried notes, and `chooseActive` prefers a pin, then a remembered device,
then the loudest port, then a port that is not `looksSilent`, and only then the first.
`MidiInput` attaches to every input and publishes a port snapshot; the device bar
shows which port is live and what has been heard from it; capture and exercises share
the same gate, so an echo can neither inflate a score nor duplicate a log row.

The browser e2e reproduces the reported device list — a dead `Midi Through Port-0`
beside a live Casio — in scenario 9, and it earned its keep three times over: it
caught the tie-break announcing the dead port as "in use" before the first note, a
restored pin being labelled "Auto" while it was being honoured, and the harness's own
toggle misuse. Two design corrections and one scenario bug, all recorded in the plan
rather than quietly fixed.

### Phase 9 — design

- **`deploy/`** — `install.sh`; `piano-ecosystem.service` (uvicorn on `0.0.0.0:8000`,
  `Restart=always`, `EnvironmentFile`, `After=network-online.target`); a Chromium
  managed-policy JSON with the two settings above; kiosk autostart
  (`--kiosk --no-first-run http://localhost:8000`); `modules-load.d` for `snd_seq`;
  a `logind` drop-in so a closed lid does not suspend the machine; firewall line;
  optional `avahi` for `piano.local`.
- **Concurrency hardening** — `PRAGMA busy_timeout` on the connection (`db.connect`
  sets WAL today but no busy timeout, and two machines now write), and a configurable
  upload size cap.
- **`GET /api/host`** — whether this request arrived over loopback, whether
  `/dev/snd/seq` exists, and which ALSA sequencer clients are visible (read from
  `/proc/asound/seq/clients`, which needs no device open). This is what lets a
  headless-ish notebook be diagnosed from the main computer.
- **Capture heartbeat** — the browser posts a small status ping; the Log view shows
  "notebook · capturing · last note 2 min ago" wherever it is opened, and the same
  place reports "piano not connected" or "sequencer not loaded" when that is the
  truth.
- **A viewing-machine hint** when the page is opened from a non-loopback address:
  MIDI cannot work there by design, so the UI says so instead of offering a device
  picker that will never find anything. It also carries the D8 warning.
- **The destructive-action boundary, enforced once.** A single
  `require_loopback(request)` dependency on the routes that discard data — the four
  `DELETE`s, `POST /api/profile/reset`, `POST /api/backup/import` when
  `mode="replace"`, and `POST /api/practice/sittings/{id}/resegment` when
  `confirm=true` — returning 403 with the actionable message "this action is only
  available on the piano machine; open http://localhost:8000 there". The condition
  is *would this discard data*, not *which route is it*, so a non-destructive
  merge-import or an unlabelled re-segment still works over the LAN. The UI disables
  the same controls (with the reason in a tooltip) when `GET /api/host` reports a
  non-loopback client, so the 403 is a backstop rather than a surprise.

**Acceptance.** From the main computer: the SPA loads over the LAN, the Log and
Repertoire views show the notebook's data, an upload lands and plays back, the
open-LAN warning and the no-MIDI hint appear — and on the notebook neither appears.
A capture batch posting while an upload runs produces no "database is locked".
Deleting a piece from the main computer is refused with the loopback message while
the Delete control is disabled there, and the same delete succeeds on the notebook;
a merge-import and an unlabelled re-segment still work from the main computer.
`deploy/install.sh` on a clean machine yields a service that survives a reboot, with
the kiosk returning and MIDI reconnecting when the piano is switched on.

**Corrected after a real install on Linux Mint.** The first `deploy/install.sh` put
the kiosk in a systemd *user* unit and enabled it with `sudo -u … systemctl --user`,
which fails with `Failed to connect to bus: No medium found` because sudo drops the
session environment and the machine may have no user session. The kiosk is now an
**XDG autostart** entry (no bus, and honoured by Cinnamon, MATE and XFCE), started
through a wrapper that waits for the API and restarts the browser if it dies. Two
further Mint facts came out of the same install: Mint ships **no chromium package**
(flatpak is the route, and Firefox has no Web MIDI), and the policy directory depends
on the package — Ubuntu's chromium reads `/etc/chromium-browser/policies`, not
Chromium's own `/etc/chromium/policies`, while Chrome reads
`/etc/opt/chrome/policies`. Both are now detected rather than assumed, with ten cases
in `deploy/browser.test.sh` and an `install.sh --check` that reports what it found
without writing anything.

**Landed.** `app/hostinfo.py` answers "where did this request come from" and "can
this machine see the piano at all": `/api/host` reports the client address, loopback,
`sequencer` (accepting `/dev/snd/seq` *or* the procfs client list, because containers
have one without the other) and the ALSA clients, which is how a headless notebook
can be diagnosed from another room. The irreversible routes — four DELETEs, profile
reset, `mode="replace"` restores and `confirm=true` re-segments — are refused from
anywhere but the piano machine, with an error that names the address to use; the
interface disables the same controls and explains why. `PRAGMA busy_timeout` and an
upload cap enforced *while writing* cover the two new failure modes of two writers on
one file. A capture heartbeat plus `last_note_ms` (read from the database, not
claimed by the client) make "is the notebook still logging?" a reading rather than a
guess, in the Log tab from any machine.

`deploy/` contains the service, the kiosk unit, the Chromium policy that grants MIDI
without a prompt and stops Memory Saver discarding the tab, `snd_seq` in
`modules-load.d`, the lid-switch drop-in and an idempotent installer.

One correction to this plan, kept because the mistake is instructive: it first
claimed the sequencer was not loaded, on the strength of `aconnect` failing to open
`/dev/snd/seq`. The module was loaded — the sandbox simply has no `/dev/snd` — and
procfs named the phantom input the user reported: `Client 14 : "Midi Through" Port 0
: "Midi Through Port-0"`. The probe now accepts either signal, and the diagnosis is
recorded as confirmed rather than inferred.

### Phase 10 — playback

Triggered by the user asking why the logger records every note and cannot play any of
it. The answer was that nothing did: `Tone.js` was imported by one file (the count-in
click), and the practice API did not expose individual notes at all — `SegmentSummary`
carried counts and metrics, so the browser could not have played them even if it wanted
to. The original logger's pipeline was capture → sessions → segments → metrics →
dashboard, and its Phase 4 "media" work meant *recordings*, a different feature. So it
was an omission, not a decision.

Two players, from the two ends of the data:

- **The attempt you just played** (results panel): no backend change, because the played
  notes, the expected notes and the per-note analysis are all still in the browser.
  `lib/playback.ts` converts both sides into one shape — written durations from quarter
  notes at the exercise's own tempo, so playback matches the count-in that was heard,
  and each played note's **hand** recovered by reconstructing
  `played.onset = expected.onset_s + onset_error_s` from the scorer's own feedback.
- **A logged sitting or segment** (Log tab): `GET /api/practice/sittings/{id}/notes`,
  read on demand because it is the only payload in the domain that grows with how long
  you played, plus a playhead positioned across the segment strip.

Both go through `lib/pianoPlayer.ts`, a Tone `PolySynth` — a dependency already present
— with `releaseAll()` on stop so a stopped playback cannot leave notes ringing. The
interface says what it is: synthesised, not the piano. Timing and touch are faithful
because they are *stored* that way (durations come from note-off); the instrument is
not, and no sample library is being pretended into existence.

**What playback cannot do**, stated rather than discovered later: in the passive log the
hands are not separable, because the piano sends both hands on one MIDI channel and only
that channel is stored. A scored attempt does not have that limit, because the exercise
knows which hand each note belongs to.

### Phase 11 — landed (progress you can see)

Chosen by the user from a brainstorm, in preference to section practice and per-hand
practice (both still on the list below). The half of the app that makes effort visible.

- **Rating history.** `user_skills` holds one number per skill, so there was no curve to
  draw and no way to say "rhythm is up 40 points this month". A `rating_events` row is
  written for every skill whose rating moves, one per attempt. It turned out that the
  Elo engine moves *all nine* dimensions a little on every attempt, so each point also
  records whether its skill was the attempt's **focus** — otherwise eight incidental
  nudges of a fifth of a point would bury the series that means something. The chart
  draws the whole line and reports how many of its points were focus attempts.
- **A past attempt, opened and heard.** `GET /api/performances/{id}` reads the stored
  `played_notes_json`, the analysis and the exercise back in the same shapes the results
  panel used, so a history row is a thing you can listen to rather than only count. The
  player UI moved into `HearIt.svelte` so a fresh result and a past attempt share one
  owner and cannot drift.
- **Week in review** in the Log tab: minutes over the last seven days, workouts and
  streak, the most improved skill, and the most neglected piece.

### Phase 12 — landed (ops polish)

- **A nightly rotating backup.** `python -m app.backup` writes one dated JSON export
  per day and keeps the newest `SRT_BACKUP_KEEP` (14). A systemd timer runs it at 03:10
  with `Persistent=true`, so a notebook that was off does not silently skip a day, and
  the installer writes the first one immediately — an unexercised backup is a file
  nobody has proved works. Named by *date*, so a second run on the same day replaces
  the day's file instead of growing a directory of near-identical copies.
- **A health panel** (`GET /api/status/system`, in the Log tab): database size and WAL,
  recordings present/pending/missing, backups kept and the age of the newest, whether
  the sequencer is present, which ALSA clients are visible — and therefore whether the
  server can see the piano at all — plus the capture heartbeat.
- **A latency suggestion, never a latency change.** `store.onset_bias_ms` takes the
  median bias of the last twelve attempts (and needs three before it will speak), and
  the device bar offers "Use N ms". It is never applied on its own: the number corrects
  for the delay of a keyboard, a browser and a sound card, and silently changing what
  the scorer subtracts would make every past score incomparable with the next one.

### Originally planned as Phase 12 (ops polish)

A nightly rotating JSON backup (a systemd timer reusing the export), a health panel
(database size, media present/pending/missing, last backup age, sequencer, capture
heartbeat), and a latency suggestion derived from your own median onset bias —
suggested with one click, never applied silently.

### Phase 13 — planned (library depth)

Attach a score to a piece — **PDF** (the browser renders it; no library) and
**MusicXML** (rendered in-app through the OSMD already present) — stored through the
existing content-hashed media pipeline with `kind='score'` rather than a new table.
Plus a waveform with an A/B loop for recordings (peaks decoded client-side; markers in
the database so they are visible from any machine), sustain pedal captured at last
(CC64 is parsed and dropped today), and the self-similarity auto-tagging that the
original design specified but never built.

### Phase 14 — planned (musical content)

Unusual meters (5/4, 7/8, 3/8, 2/2) via the existing meter table; **clef reading** as a
new skill dimension (a real, independently trainable skill, with the honest cost that
it ripples into the radar chart, the calibration ladder and the defaults); and dynamics
— notation first, velocity scoring later, because scoring a dynamic is a new contract.

### Still open, from the earlier brainstorm

**Section practice** (pick bars, slow down, loop until clean) and **per-hand practice**,
both offered and both deferred by the user. They remain the highest-value items on this
list by my estimate, since they change what the app is *for* rather than what it shows.

### Risks, stated plainly

| Risk | Treatment |
| --- | --- |
| The kiosk browser dies (session lock, crash, OOM) and capture silently stops | The capture heartbeat and the "last note N min ago" indicator make it visible from the main computer; the kiosk is on `Restart=always` |
| `snd_seq` not loaded → Web MIDI sees **zero** devices, which looks like a hardware fault | Loaded at boot by the deployment, and reported by `GET /api/host` |
| A blanked screen looks like a stopped machine | Documented: blanking does not stop capture, because MIDI delivery and flush timers are not tied to the display |
| `note_events` grows without bound | ~1–5 k rows per hour of playing is a few MB per year; the JSON export excludes media, so backups stay small. Retention policy is not needed yet |
| An unauthenticated LAN can still *edit* and *upload* (D8) | Visible banner; the irreversible paths are loopback-only, which is the part that cannot be undone by hand |
| A future move to a reverse proxy or a non-loopback deployment breaks the boundary silently | `request.client.host` is the check today and there is no proxy in this topology; if one is ever added, the check must move to a trusted header, and this row is the reminder |

### Non-goals

HTTPS/TLS on the LAN, remote MIDI from the main computer, multi-user accounts,
syncing two databases, and the headless capture daemon (deferred until
the kiosk path proves insufficient in real use).

**ADR signal.** D8 is a trust-boundary decision (what the LAN may do without
authentication) and D7 fixes the runtime owner of capture. Both are durable, but
this project's decision record *is* this document plus its decisions tables — no ADR
directory exists, and inventing one now would create a second authority for the same
facts.

### Update the owning docs, not new siblings

The deployment chapter in [`DEPLOYMENT.md`](./DEPLOYMENT.md) is extended when Phase
9 lands, so it describes files that exist; this section is the plan until then.
