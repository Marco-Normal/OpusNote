# The piano ecosystem — target architecture and migration

Written by the sight-reading agent. Supersedes the "share `piano.db` with the
Rust app" premise of
[`INTEGRATION-practice-logger.md`](./INTEGRATION-practice-logger.md), which
remains accurate about *what exists today* but is no longer the destination.

Status: **decided; Phases 1-13 and 15-19 are landed.** See §9 and §10 for what each
delivered, and §10 for the Phase 18 and 19 specifications.

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
| 13 | **Library depth** | Attach and render scores (PDF and MusicXML), waveform with A/B loop, sustain pedal captured, self-similarity auto-tagging. **Landed in full (13a and 13b).** | medium |
| 14 | **More musical content** | Unusual meters, clef reading, dynamics and articulation depth. | medium |
| 10 | **Playback** | Hear a scored attempt back (either hand, or the exercise as written) and hear a logged sitting or segment from the practice log, with a playhead. | low |
| 9 | **LAN server** | A planted notebook serving the whole app on the local network: `deploy/`, kiosk autostart, capture heartbeat, upload cap, concurrent-write hardening. | medium |
| 18 | **The data the logger already has** | 18a: the journal joins the measurement — a sitting link, a real editor, a calendar series. 18b: the pedal, touch and register numbers that are recorded and unused. **Landed.** | medium |
| 19 | **Playing back what was actually played** | A stale same-pitch note-off silences re-struck notes at the pedal-up — 1,747 notes in the owner's own sessions. Plus one owner for the pedal threshold. **Landed.** | S–M |
| 20 | **Deliberate practice, the piano-side toolkit, and audio takes** | *How* a segment was practised (20a); hands-free control from the unused sostenuto pedal, count-in choice, real URLs and a command palette (20b); undo and a humane streak (20c); journal and library depth (20d); low-bitrate audio takes captured in-app (20e). Five slices, independently shippable. **20a landed; 20b–20e planned.** | medium–high |

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
| Self-similarity identification | **Ported as Phase 13b** — see §10; the original design's `identification_corrections` became `identification_outcomes` so acceptances are recorded too |
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

### Phase 13 — library depth, in two slices

Decided with the user: the three self-contained parts land first, and the matcher
follows as its own slice so its effect on tagging can be judged on its own rather than
buried in a large change.

### Phase 13a — landed (scores, waveform, pedal)

- **A score attached to a piece** — PDF (the browser's own viewer; no library) and
  MusicXML (engraved in-app by the OSMD that was already there). Stored through the
  existing content-hashed media pipeline as `media.kind='score'`, with **no ffmpeg in
  that path**: a score is not probed (its own bytes are the honest description) and not
  re-encoded, so the file you attach is the file you read. Identification is real rather
  than trusting the suffix — `%PDF-` for a PDF, a parsed `score-partwise`/`score-timewise`
  root for MusicXML — because the only other symptom of a wrong file would be a blank
  frame at the piano. `.mxl` is refused with a message about unzipping it rather than an
  unzip dependency. Scores are excluded from the recording counts and from
  present/pending/missing, since a score is never "not copied from the legacy library";
  `score_count` and `status.scores` keep the two separable.
- **A waveform with an A/B loop.** Peaks are decoded client-side with WebAudio and drawn
  on two stacked canvases (the picture changes rarely, the playhead sixty times a
  second), so there is no new endpoint and no second ffmpeg pass. Markers live on the
  `media` row (`loop_start_s`/`loop_end_s`, additive migration) and the route validates
  the *merged* pair — a PATCH carries one marker at a time, so checking the body alone
  would let an inverted loop through. Audio outside the loop is dimmed rather than
  hidden: a passage is found by its surroundings, which is the reason to look at a
  waveform at all. Decoding is declined past 64 MB with a message that says so, because
  expanding a compressed recording into raw samples is how a practice machine starts
  swapping to draw a picture.
- **Sustain pedal captured.** CC64 was parsed and thrown away. Now a `pedal_events`
  table stores the raw value stream (onset + value), the ingest batch takes an optional
  `pedals` list, and `sustained()` in the client extends each note to the pedal-up that
  covers its release. A pedal move never opens or extends a sitting — a foot resting on
  the pedal is not practice — so a move with no music around it is dropped and counted
  rather than invented into one, and a pedal-only batch is accepted so a client's queued
  flush cannot block the notes behind it.

### Phase 13b — landed (recognising what you played)

The design in `practice-logger/docs/DESIGN.md` §5, built at last: a pitch-class profile,
tempo proximity and register overlap per segment, k-nearest over your own labelled
segments, confidence bands, and the "was this right?" prompt. The reference is *you* —
there is still no symbolic score to match against, and every segment you tag becomes an
example.

- **A GET that writes labels, deliberately.** When a sitting is segmented it is also
  identified, so it arrives already tagged rather than waiting for a button. Only the
  unambiguous band is written; it is marked `identified_by='similarity'` with the score
  it came from, and the timeline shows it as *guessed* with "It's right" and "Not this"
  beside it. `POST /api/practice/autotag` is the same pass as a backfill, for practice
  logged before the matcher existed.
- **The confident band is conservative, and the margin is what makes it so.** A high
  score is not enough on its own: two pieces that sound alike both score high, so a
  match is written only when it also leads the runner-up by `SRT_AUTOTAG_MIN_MARGIN`.
  Between the two thresholds the match is *offered* — ranked, with the notes/tempo/
  register arithmetic behind each candidate visible on hover — and written only if you
  accept it. Nothing is applied silently, which is the same rule the latency suggestion
  follows. Declining a suggestion records a dismissal so it is not asked again, and a
  dismissal is deliberately not counted as the matcher being wrong.
- **What the sitting is already about.** A sitting is usually one piece at a time, so a
  near-tie is broken towards the piece the earlier segments of the same sitting are. The
  candidate moved is the candidate, not its score: the number on screen still means what
  it says.
- **One owner for a decision.** Accepting, rejecting and correcting all write through
  `_settle_label`, including the piece dropdown, so every overruled guess is recorded
  rather than only the ones made through the buttons. An inferred label is never training
  data — training on your own guesses compounds the first mistake — and it is never
  overwritten by a later pass.
- **A bounded reference window.** Every read derives a fingerprint per reference, so the
  matcher compares against your newest `SRT_AUTOTAG_TRAINING_LIMIT` (600) labelled
  segments rather than all of them — otherwise the log would get slower every month for
  the rest of the library's life. The count in the accuracy panel is still of everything
  you have tagged, and the report says when the window is doing the cutting.
- **The accuracy claim, measured two ways.** `GET /api/practice/autotag/quality`
  hides each hand-tagged segment in turn and asks whether the matcher names the right
  piece without it (leave-one-out), reporting coverage *and* precision at each band with
  their counts, and `null` rather than `0%` where there is no denominator. The live
  figure is the share of written guesses left alone, so the two can be compared: a
  measurement that does not survive contact with real use is the thing worth knowing. The
  Log tab's *Recognising what you played* panel shows both.
- **`identification_outcomes`** holds one row per guess that was acted on —
  confirmed/changed/rejected/dismissed — because "how often is it right?" has to come
  from the database rather than from memory. This is the original design's
  `identification_corrections` table with one deliberate change: it records the
  *acceptances* too. A corrections table that only holds mistakes cannot tell you the
  error *rate*, which is the number that decides whether to trust the band.

**Weights: measured, not inherited.** The design's 0.60/0.25/0.15 assumed whole-piece
run-throughs at performance tempo, and that is not what practice is. `tools/measure_autotag.py`
builds a corpus from the app's own generator — eight pieces, nine drills each, under the
transformations that actually happen: sections, half speed, one hand, staccato, repeats
of an earlier passage, plus wrong and dropped notes — and scores the schemes
leave-one-out. At 0.60/0.25/0.15 it got 79.2% right; at the shipped **0.75/0.10/0.15**,
84.7%. The tempo term is the least trustworthy of the three, exactly as a player who
drills slowly would expect.

The same measurement, honestly reported, with the numbers that shaped the defaults:

| | top-1 | written unasked | offered |
| --- | --- | --- | --- |
| all drills (72) | 91.7% | 18.1% coverage @ 100% (13/13) | 80.6% @ 89.7% |
| repeat of an earlier passage | 16/16 | | |
| at tempo | 18/19 | | |
| slow, staccato | 12/13 | | |
| **right hand only** | **9/13** | | |
| **left hand only** | **6/11** | | |
| cold start, 1 drill per piece | 71.9% | | top-3 90.6% |
| cold start, 4 drills per piece | 82.5% | | top-3 97.5% |

The single-hand rows are the honest finding: half the notes of a passage is often not
enough to tell two pieces apart, and one-hand drilling is exactly what this player does.
What rescues it is the sitting context above — 84.7% → 91.7% overall — and, where that
does not apply, being asked rather than told. Loosening `SRT_AUTOTAG_MIN_MARGIN` to 0.05
roughly doubles the coverage at about a 3% measured error rate; it is a setting rather
than a constant because that trade is the player's to make.

### Originally planned as Phase 13 (library depth)

Attach a score to a piece — **PDF** (the browser renders it; no library) and
**MusicXML** (rendered in-app through the OSMD already present) — stored through the
existing content-hashed media pipeline with `kind='score'` rather than a new table.
Plus a waveform with an A/B loop for recordings (peaks decoded client-side; markers in
the database so they are visible from any machine), sustain pedal captured at last
(CC64 is parsed and dropped today), and the self-similarity auto-tagging that the
original design specified but never built.

### Phase 15 — landed (playback you can navigate, and a real piano)

Four things found by using Phase 10's playback on a real sitting, plus one question
about a field nobody could identify.

- **Two things could sound at once, and Stop did not stop.** Every component built its
  own `PianoPlayer`, so a results panel and a history row could play over each other and
  neither Stop button knew about the other — and `releaseAll()` only releases voices
  sounding *now*, while `triggerAttackRelease` had already scheduled notes for seconds
  ahead. There is now one shared player, playback is a `Tone.Part` that is cancelled on
  stop, and MIDI output is handed out in a rolling window so at most a fraction of a
  second is in flight. **Stop means stop** is checked in the browser suite against a
  simulated piano: a note-off for the note still sounding, an all-notes-off sweep on
  every channel, and a second sweep after the window drains — because a note-on already
  given to the MIDI stack can be followed by silence but not recalled.
- **Play through the piano itself.** Web MIDI exposes outputs too, so the best available
  piano sound is the piano: notes go to the PX-870 over MIDI, chosen automatically by
  matching the output's device fingerprint to the input we listen to. Three instruments
  in the device bar — through the piano, the sampled Salamander piano, or the built-in FM
  voice — with the synthesiser as the fallback whenever the others are unavailable.
- **The sampled piano is a one-time 2 MB download.** `@tonejs/piano` was rejected: it
  ships no samples and fetches 30 MB from a CDN at play time, which a LAN piano machine
  cannot rely on. Instead `app/piano.py` fetches the 30 Salamander files (measured: 2.0
  MB, all reachable, minor thirds from A0 to C8) once, writes them atomically beside the
  data, and serves them from this host at `/piano/…`. Attribution travels in the status
  payload and is shown next to the button, because a credit that lives only in a README
  is not really a credit.
- **Seeking into a long sitting.** The timeline strip is a transport: click anywhere to
  play from there, arrow keys move by five seconds, `« 30 s` / `30 s »` jump, and a
  position readout shows where you are. Playing a range with a start position is a new
  capability in the player — `fromTime()` rebases the notes and a note still sounding at
  the seek point is kept, shortened, rather than dropped.
- **Falling notes.** `PianoRoll.svelte` draws a keyboard with the notes falling onto it,
  driven by the same playhead. The geometry is a pure module (`pianoRoll.ts`) because
  the direction notes fall is exactly the thing that is miserable to debug on a canvas —
  and doing it that way caught a sign error that a `max(sliver, …)` had been hiding, so
  every note was drawn as a hairline.
- **The field nobody could identify.** *Split at* is now labelled and shows a clock
  rather than a count of seconds: it is the position at which *Split here* cuts the
  segment in two. `parseClock` accepts `5412`, `1:30:12` or `m:ss`, and a half-typed
  value is refused rather than read as something plausible.

**The sampled piano never started the audio context.** The `piano` branch of `play()`
returned before reaching `Tone.start()`, so the instrument played through a *suspended*
context: silent, and reporting nothing. Only the synth branch started it, and even that
did so *after* `await loadPiano()`/`loadNotes()` — by which point the click that began
the playback is over. Now the context is resumed for every Tone-based instrument, and
separately on the first gesture anywhere in the page (`unlockOnFirstGesture`), which is
where a browser allows it. The device bar reports the context state and has a **Test**
button, because "no sound" with no explanation is the worst possible failure — and in
this case the app had been producing it in three different ways at once.

**The sampled piano did not play at all either**, and the reason is worth writing down: the
files are spelled with an `s` (`Ds4.mp3`) because a `#` in a URL starts a fragment, while
a note name needs the `#` (`D#4`) because that is what a music library parses — Tone's own
pattern accepts `#`, `b` and `x`, and not `s`. The sampler's `urls` map was keyed on the
file stems, so **every sharp sample failed to parse** and the instrument fell back to the
synthesiser in silence. `pianoSamples.ts` now owns that translation, with a test that
checks every stem against Tone's own pattern, and the bypassed check was verified by
putting the bug back: the browser scenario fails without it and passes with it. The
failure is no longer swallowed either — the device bar says *samples failed to load —
using the synthesiser*, because falling back silently made a broken sample set look like
a wrong setting.

One real bug came out of writing the browser scenario: the sitting's notes were cached
per *component* rather than per sitting, so choosing a second sitting played the first
one's notes. The cache is keyed on the sitting id now, and the scenario uses pitches no
other sitting plays so a stale cache cannot pass by accident.

### Phase 17 — landed (a sitting ends when the piano does)

Three things from using it at the instrument, two of them behaviours and one a measured
retune.

- **The dashboard updates itself.** A sitting only exists once it has been quiet for the
  sitting gap, and nothing told the open page about it — so the newest sitting was
  invisible until a reload. The Log view now polls every 20 s while it is on screen, and
  the poll deliberately cannot move the player's attention: it refreshes the tiles, the
  list and the open sitting's detail and leaves the selection exactly as it was.
- **Switching the piano off ends the sitting.** A MIDI disconnect is a far sooner answer
  to "are they done?" than five minutes of silence, and it is the difference between the
  sitting appearing at once and appearing later. The client reports the event; the server
  decides whether it was real, because only it can see how long the piano has been quiet
  (`CLOSE_QUIET_MS`, 1.5 s — short enough that reaching for the power switch after the
  final chord still counts, long enough that a USB blip mid-phrase does not split a
  session). The client flushes its capture buffer before asking, so the last chord is in
  the sitting before it is closed. `sittings.closed_ms` is what makes it stick: a closed
  sitting takes no further notes, so coming back after switching off is a new sitting.
- **Segmentation, retuned from the real thing.** A 42-minute sitting of the owner's:
  18,688 notes, a 99th-percentile gap of 1.4 s, and exactly ten gaps over 3 s. The two
  boundaries they drew by hand sat on gaps of **9.5 s and 11.7 s**, which the 20 s default
  could not see, while two within-piece pauses sat at 15.1 s and 15.6 s — so no single
  threshold separates those events. `SRT_SEGMENT_GAP_S` is now **8 s**: it catches every
  real change and costs about two merges per session, and merging a boundary is one click
  where splitting one means typing a position. Erring towards more segments is the cheaper
  error, and the knob is there for the day that judgement changes.

Two divergences of one kind were found while doing it — a value decided in two places:

- `practice_status` computed "open" from the clock alone while ingest excluded explicitly
  closed sittings, so a closed sitting was still reported open. It now asks
  `_find_sitting`, the same predicate ingest uses.
- The e2e fixture assumed the *list* endpoint's `segment_count` would materialise
  segments; only the detail read does.

### Phase 16 — landed (the exercise ladder actually climbs)

Reported from a real library: 25 attempts per skill, a rating near 800, and every
generated exercise still level 1 and trivial. Diagnosed from the backup rather than
from the code path, and the data was unambiguous — 306 of 324 `exercise_skills` rows
were level 1, every `exercises.difficulty_elo` was 600, and the recent scores were 96-98
with pitch accuracy 100%.

The cause is arithmetic in the anchor. The selector deliberately aims `offset = -220`
Elo below the rating (for a 78% success target), and a level is 100 Elo, so the practice
offset costs **2.2 levels**. With `elo_base = 600`, level 2 did not open until a rating
of 870: a learner rated 792 was served 600-Elo material for as long as they stayed under
870, and their rating could only creep up ~7 points an attempt, because Elo correctly
says that scoring 97% on material far below you is not new evidence. The bottom of the
ladder was a plateau, and the tests missed it because they only probed 620, 1000 and
1600 — never the middle, which is where learners actually live.

`elo_base` is now **480**, which is the only value that satisfies three constraints at
once: the documented example ("a rating of 1000 gets exercises around Elo 780") becomes
*exact* rather than approximate (780 = 480 + 3 × 100); an unrated learner still starts on
level 1 (which now covers ratings up to 750); and it is the smallest such value, so every
level opens exactly 100 points above the last. The same ratings from the backup now
select level 2 instead of level 1, with the served difficulty at 580 — the design's own
target for a 790 rating.

Two display paths were also computing a level from the rating with an **inline copy** of
the formula, so the radar showed the level the rating implied (~4) while the exercise on
screen was level 2. Both now use the selector's level, which is the number the player can
act on, and the radar says so. New tests pin the three constraints, the even spacing of
the levels, and the exact case from the backup.

### Phase 14 — planned (musical content)

Unusual meters (5/4, 7/8, 3/8, 2/2) via the existing meter table.

**Clef reading is a modifier, not a tenth dimension** — decided with the user. Clef
variety is added inside the existing dimensions (`hand_position` most directly, and
`intervals` for reading across the staves), so the radar chart, the calibration ladder
and the default levels keep their current shape. The accepted cost, recorded rather than
glossed: clef reading cannot then be tracked as a skill in its own right, and its
difficulty will surface inside `hand_position`'s rating.

Dynamics: notation first, velocity scoring later, because scoring a dynamic is a new
contract — `ExpectedNote` carries no velocity today.

### Phase 18 — landed (the data the logger already has)

Chosen by the user from a survey of the logger, in preference to making the log a coach
(score-aware practice map, hotspots, coverage) and to planning the next session (goals,
milestones, a daily plan). Both remain on the list; this phase is the one where the work
is mostly *finishing* what capture already produces.

Two slices, split the way Phase 13 was, because they are independently shippable and
independently verifiable. The organising finding is the same in both: **the app already
records facts it never reads.** `pedal_events` is written on every CC64 move and read by
exactly one caller — `sitting_notes`, for playback. `mean_velocity` and
`velocity_stddev` are computed per segment, persisted, served in `SegmentMetricsOut`, and
rendered nowhere. `identification_outcomes` keeps four columns
(`guessed_piece_id`, `resolved_piece_id`, `accepted`, `score`) that no query reads.
`PATCH /api/repertoire/journal/{id}` is implemented, tested, and called by no component.

#### 18a — the seam between playing and writing

**Problem.** Practice is measured automatically and written down manually, and nothing
joins the two. `piece_journal` is dated prose plus an optional `practice_minutes`, and the
piano knows the same session to the millisecond. Every journal aggregate in the app is
`SUM(practice_minutes)` per piece, and `calendar()` is built from `sittings` alone, so
written time is invisible in every calendar and streak view. The entry itself is a
single-line `<input>` that can be deleted but not edited.

**Design.**

- `piece_journal.sitting_id INTEGER REFERENCES sittings(id) ON DELETE SET NULL` —
  additive, nullable, no backfill. `SET NULL` rather than `CASCADE` because deleting a
  sitting must never delete prose. The link is to the **sitting**, not the segment:
  `resegment` deletes and rebuilds every segment in a sitting, so a segment-level link
  would be destroyed by the app's own correction action. Sitting-level survives it.
- The entry form becomes a `<textarea>` that edits in place through the PATCH that already
  exists. Save on Cmd/Ctrl+Enter; Cancel restores. The delete-and-retype path goes away.
- `SittingDetail` gains **Write about this**, which opens the piece's form with the sitting
  attached and a header drawn from stored numbers — minutes, tempo against the piece's own
  previous segments, restarts, and the longest pause. **The prose box stays empty.** The
  app has no language model, and a generated entry would put words in the player's mouth;
  the draft is the arithmetic, not the sentence.
- The calendar gains written minutes **as a second series, never summed with measured
  minutes**. The README already states the rule and its reason — a session can be both
  played and written about, and adding them counts it twice — and this phase must not
  quietly reverse it. A day with prose and no notes reads *written, not measured*. The
  streak stays sitting-based, for the reason Phase 6 gave.
- **The reconciliation names which minute it means.** Two definitions already coexist:
  the dashboard's `total_minutes`, `today_minutes` and the source split use *sitting
  wall-clock span*, while `by_piece` and `piece_practice` use *summed segment note-span*.
  They do not agree. The per-piece "you wrote N min, the piano heard M" therefore uses
  the segment-span figure, because that is the one attributed to the piece, and says so.
  Reconciling the two definitions themselves is out of scope and is not pretended here.
- Journal `content` joins the library search, which today matches only title, composer and
  opus. A `GET /api/repertoire/journal?limit=` gives a cross-piece recent-entries feed;
  the whole journal is currently inlined, unpaginated, into `PieceDetail`.
- The journal date defaults to the **local** date. It is `toISOString().slice(0, 10)`
  today, which is UTC, and so is off by one for anyone east or west of it.

**Four defects in the same files, fixed here because they are the same surface:**

1. `SittingDetail.closed` is computed from the clock (`ended_ms + sitting_gap < now`) and
   ignores `closed_ms`, so a sitting closed by switching the piano off reports
   `closed: false` while `ensure_segments` treats it as closed. One predicate, one owner.
2. `SittingCloseResult.reason` cannot express *still playing*: the store distinguishes it
   and the route collapses both `None` cases into "nothing open to close", so the client
   cannot tell a blip from a finished session.
3. `resegment` runs `DELETE FROM segments WHERE sitting_id = ?`, and both
   `identification_outcomes` and `segment_metrics` cascade. Re-segmenting therefore
   destroys the evidence that `identification_outcomes` exists to keep, and the
   *Recognising what you played* panel quietly loses its denominators. Either the outcomes
   survive a re-segment or the panel reports that they were reset; losing them in silence
   is the one option that is not allowed.
4. **`CaptureClient.flush()` loses whatever arrives during the request.** It does
   `const batch = this.buffer` — a *reference*, not a copy — and then, after awaiting the
   ingest, does `this.buffer = this.buffer.slice(batch.length)`. Notes and pedal moves
   captured while the request was in flight were pushed onto that same array, so
   `batch.length` is no longer the number that was sent and those arrivals are sliced
   away. The window is one round trip (usually a few milliseconds, but a locked database
   or a slow LAN widens it), the loss is silent, and `lastSentAt` is misreported from the
   same aliasing. The fix is to take the length before awaiting, or copy the batch.

#### 18b — the measurements the app already takes

**Where the new numbers live — approach B.** `segment_metrics` gains the columns, written
by `_refresh_metrics`, rather than being recomputed on every read (A) or moving to a second
table (C). `metrics.py` already states the governing rule — these are pure functions of
the note list, so the table is a *cache and never the truth* — and that is exactly what a
new column has to be. It also keeps `calendar()` and `by_piece()` aggregating in SQL
instead of re-deriving the whole history on every dashboard load, which is what A costs.

**A new owner for one purpose.** The pedal work lands in `practice/pedal.py`, a sibling of
`metrics.py`, as pure functions over `(notes, pedal_moves)`. It is justified rather than
folded in because 18b makes `metrics.py`'s scope ambiguous: that module is documented as
"five metrics, the practice-logger's MVP set", and pedal *intervals* plus a harmonic
judgement are a different concern with a different future. The raw CC64 stream stays raw;
intervals are a projection, never a second stored truth.

- `pedal_changes`, `pedal_down_ratio`, and **pedal blur**.
- **"No pedal recorded" is a third state, not a zero.** `legacy.py` imports `note_events`
  and never reads a pedal table, so imported sittings have no `pedal_events` at all. A
  pedal figure computed over them would report a fault that was never observed. The metric
  therefore distinguishes *not recorded* from *recorded and none used*, the same
  distinction `media.state` already makes between *pending* and *missing*.
- Soft pedal (CC67), sostenuto (CC66) and note-off velocity are not captured at all; this
  slice does not pretend otherwise.

**The harmonic question is a named seam with exactly one owner.** Without a score the app
cannot know the harmony — only which pitches are sounding. So *blur* can only mean "a
pedal-down span in which the sounding pitch-class set changed". That is a proxy, in the
same class as `median_tempo` being a note rate rather than a metronome reading, and it is
labelled as one.

When a MusicXML score is attached to a piece, the same question can be answered from the
score's own chord and measure boundaries instead of inferred from the sounding pitches. The
seam is therefore one function answering one question — *where does the harmony change?* —
with a recorded `basis`:

| basis | Where the boundaries come from | Available |
| --- | --- | --- |
| `observed` | pitch-class set changes in the sounding notes | now |
| `score` | chord and measure boundaries from the attached MusicXML, aligned to the performance | when alignment exists |

Three rules make that extension cheap without building any of it now:

1. **The basis is stored, not re-derived** — `segment_metrics.pedal_basis`. A score
   attached in March must not retroactively relabel January's blur as score-derived, which
   is the same rule that makes `identified_by`, `media.state` and the `legacy_id`
   provenance columns trustworthy.
2. **Bases are never mixed in one series.** The piece's pedal trend draws one basis at a
   time, because an observed number and a score number are not the same measurement.
3. **The blur is derived, so a future recompute needs no migration of results** — only a
   backfill pass that re-derives with a different basis, which is precisely what
   `POST /api/practice/autotag` already is for labels.

The alignment work itself stays out of scope and is not pretended into existence. Mapping
a performance onto a score is the same problem as the practice map, and it is where the
real cost of a score-aware logger lives — this slice buys the seam, not the capability.

**Touch, finally rendered.** `mean_velocity` and `velocity_stddev` appear in the timeline,
with `median_velocity` and a dynamic range beside them. Labelled the way tempo already is:
MIDI velocity is a controller value, not decibels, so it is comparable with itself over
weeks and is not a claim about loudness. **Register balance** splits by pitch as an
explicitly-stated proxy for hands, because the piano sends both hands on one channel and
`note_events.channel` is write-only.

#### Decisions taken

| ID | Question | Decision | Consequence |
| --- | --- | --- | --- |
| 18-D1 | Does a journal entry belong to a sitting or a piece? | **The piece owns it; the sitting is an optional link** | Imported entries stay valid with no backfill, an entry survives re-segmentation, and "write about this sitting" is a convenience rather than a home |
| 18-D2 | Are measured and written minutes summed? | **Never** — a second series, and the reconciliation names which measured figure it means | Preserves the Phase 6 rule; a prose-only day is visible as written-not-measured |
| 18-D3 | Where do the pedal and touch numbers live? | **`segment_metrics` columns**, derived in `practice/pedal.py` | Aggregable in SQL; the table stays a cache of a pure function, as `metrics.py` already promises |
| 18-D4 | Is pedal blur a judgement about the player? | **No — a reported proxy with a recorded basis**, and no score path until alignment exists | The same restraint the latency suggestion and the autotag bands follow: nothing is asserted silently |

#### Acceptance — 18a

- *Write about this* on a sitting produces an entry carrying that sitting's id, and its
  measured header reconciles with the segment metrics it was drawn from.
- The entry is editable in place; the browser suite exercises
  `PATCH /api/repertoire/journal/{id}`, which no component calls today.
- Deleting a sitting leaves its entries with `sitting_id` NULL; re-segmenting a sitting
  leaves them linked.
- Written and measured minutes render as separate series and are never added; a day with
  prose and no notes reads *written, not measured*.
- Search finds an entry by a word that appears only in `content`.
- With the machine set to a non-UTC offset, the date field defaults to the local date.

#### Acceptance — 18b

- Pedal intervals derived from the raw stream match the raw moves for a fixture, and a
  pedal-down with no matching up closes at the end of the sitting rather than being lost.
- A sitting with no `pedal_events` reports *not recorded*; it never reports zero changes.
- Blur is computed for the `observed` basis and the basis is persisted. Re-running the
  derivation with a different basis leaves existing rows' basis untouched.
- `mean_velocity`, `velocity_stddev` and `median_velocity` are rendered, and nothing
  derived from velocity is labelled as loudness.
- Register balance states that it is inferred from register, not from hands.

**Effort:** 18a S–M, 18b M. **Depends on:** nothing — every table it needs already exists.

**Non-goals, stated so the plan cannot drift:** aligning a performance to a score (the
practice map), generating journal prose, per-hand attribution, and any claim about
dynamics that is not a MIDI controller value.

#### Landed

**18a.** `piece_journal.sitting_id` (nullable, `ON DELETE SET NULL`); the journal is a
`<textarea>` that edits in place through the PATCH that had been written, tested and called
by nothing; *Write about this* on a timeline segment parks a draft in the app state, switches
to Repertoire and attaches the sitting with the measured arithmetic — the prose box stays
empty, because the app has no language model and will not put words in the player's mouth.
Written minutes joined the calendar as a **second series**, drawn as a border rather than
another shade so the heat still means "minutes the piano heard" and nothing else, and a day
with prose and no notes reads as its own state. Journal `content` joined the library search
and gained a cross-piece feed, which is also what the detail pane shows when no piece is
selected — it used to be blank. The date default is the local date, not `toISOString()`.

Three defects fixed at their owners: `SittingDetail.closed` now asks the same question
`ensure_segments` asks instead of reading the clock alone; `close_open_sitting` returns a
`CloseOutcome` so *still playing* is distinguishable from *nothing open* (seven existing
assertions changed, and they now check the reason rather than only the id); and
`identification_outcomes.segment_id` is `ON DELETE SET NULL`, so re-segmenting no longer
destroys the matcher's track record. A fourth, in the client: `CaptureClient.flush()` copied
its batch by reference and sliced by the aliased length, discarding whatever was played during
the request.

**18b.** `app/practice/pedal.py` — pure functions beside `metrics.py`: intervals from the raw
CC64 stream, threshold crossings rather than message counts, the down-ratio, the blur count,
and the touch figures. Eight additive columns on `segment_metrics`, written by
`_refresh_metrics`, which is approach B and keeps the table a cache of a pure function as
`metrics.py` already promises. `pedal_basis` is stored rather than re-derived, so a score
attached later cannot retroactively relabel an observed number. A sitting with no pedal rows
reports *not recorded* through that basis rather than a zero, which is how imported history
is kept from reading as a fault that was never observed. The timeline renders pedal changes,
blur, median velocity and register balance, each with the label that says what it is:
**register balance is worded as registers, not as hands**, because that is what it measures.

**Verified.** Backend 811 passing (19 new pedal units, 2 metric-integration, 7 journal, 5 for
the defect fixes). Frontend 72 passing, `svelte-check` clean, build clean. All twelve browser
scenarios pass. The migrations were exercised against a **real pre-18 database** — the e2e
one, whose `segment_metrics` had seven columns and whose `identification_outcomes.segment_id`
was `NOT NULL` — with a row planted in the old shape first: every column was added, the
nullable rebuild ran, and the planted row survived it with its action and score intact.

### Phase 19 — landed (playing back what was actually played)

Found by using Phase 10's playback at the instrument, and diagnosed from the owner's own
backup (7 sittings, 84,709 notes, 209,072 pedal moves) rather than from the code path. The
report was: *holding a note and lifting the pedal, the note lingers on in real life because
the key is still down, but in playback it vanishes.*

#### Root cause

**MIDI note-off is per pitch, and the player emits one note-on/note-off pair per stored
note.** `pianoPlayer.sendMidi` schedules `note-on(pitch)` and `note-off(pitch)` for each
event independently. When two notes of the same pitch overlap in time, the earlier note's
note-off silences the later one — MIDI has no way to say "this off belongs to that on".

`sustained()` is what makes the overlap common, and it is not itself at fault. Extending a
released note to the pedal-up is correct piano behaviour, but it lengthens that note past a
later re-strike of the same key. Measured on the real sessions:

| | |
| --- | --- |
| Same-pitch overlaps created by the pedal extension | 2,841 – 7,119 per sitting |
| Notes audibly silenced early by a stale note-off | **1,747** across the four pedalled sittings |
| Median duration lost | 407 ms |
| Losses over 200 ms | 968 |
| Worst case | a note held 14.5 s, silenced after **27 ms** |

The mechanism reproduces the report exactly: the stale note-off is scheduled at the
pedal-up, so *the note the key is still holding dies at the moment the pedal is cleared*.

#### Design

- **One pure function, one call site.** `resolveOverlaps(notes)` in `playback.ts` — already
  the module whose docstring claims this class of arithmetic, because it is "tedious to
  check by ear and trivial to check in a test". Per pitch it clamps each note's end to the
  next note's onset on that pitch, which is what a re-struck string physically does.
  `pianoPlayer.play()` applies it once, so the Tone path and the MIDI path, and every
  caller, are covered by construction — a fix in the MIDI encoder alone would leave the
  sampler wrong, and a fix in each caller would leave the next caller wrong.
- **Verified before planning it**: replaying the owner's four pedalled sittings through
  the proposed transform takes the cut-short count from **1,747 to 0**.
- **Retirement.** The per-note note-off scheduling is replaced, not kept behind a flag:
  there is no instrument for which the un-normalised list is correct.
- **Ordering detail to pin with a test:** a clamped note-off and the next note-on share a
  timestamp, so the off must be submitted first. That is the standard re-trigger idiom, but
  it is exactly the kind of thing that is silently wrong on one instrument only.

#### The continuous pedal: captured, consumed binarily

The suspicion was right, and the honest answer has two halves.

**It is captured continuously.** All 128 CC values are present in the log, spread across the
range — this is a genuine continuous pedal streaming its position, not a switch with
occasional intermediate values. Nothing collapses it on the way to the database, and
`pedal_events.value` is stored raw.

**Then every consumer collapses it at `value >= 64`,** which is the MIDI specification's
own rule for a switch controller: 0–63 is off, 64–127 is on. That is the correct
interoperable reading — it is what makes a plain on/off pedal work at all — but on a
continuous pedal it means **half-pedalling reads as fully released.** Measured over the
pedal time in the owner's sittings: 23.9%, 9.1% and 10.2% of it sits in the partial band,
during which a note released under the pedal is not held by playback at all.

Two things follow, and neither is a new damper model — inventing one would be inventing a
claim about the instrument, which is the thing this project refuses to do:

1. **The threshold has two owners and must have one.** `PEDAL_DOWN = 64` in `playback.ts`
   and `second >= 64` in `midi.ts` are the same decision written twice, which is the defect
   class Phase 16 and Phase 17 each already had to fix once. One named constant, one owner.
2. **The gap is recorded, not papered over.** The partial-band share becomes a stated
   limitation on the pedal metrics of 18b, in the same voice as "tempo is a note rate, not
   a metronome reading".

#### The pedal is not sent to the output, and that is deliberate

The player emits no CC64 at all — verified across the whole frontend: the only controller
messages it sends are all-notes-off and all-sound-off on Stop. Through-the-piano playback
therefore has no pedal; the pedal is already baked into each note's duration by
`sustained()`. Sending it as well would double the pedalling. That is the right design, but
it is currently nowhere written down, so it reads as an omission — which is how the whole
of Phase 10 started.

#### Acceptance

- Replaying a fixture containing a pedal-extended note overlapped by a re-strike of the same
  pitch produces no same-pitch overlap in the scheduled material, and the later note keeps
  its full key-held duration.
- The regression is pinned on the count, not on a screenshot: the four pedalled sittings
  from the owner's backup go from 1,747 cut-short notes to 0, and the check is a unit test
  over a synthesised fixture rather than a dependency on the backup.
- The player's own wiring is checked in the browser, not assumed: `scenario_playback` plays
  such a sitting through the piano and asserts the scheduled stream never overlaps on a
  pitch — and that assertion fails when the normalisation is removed.
- Both instruments are covered by one test, because both consume the same normalised list.
- A plain on/off pedal and a continuous pedal produce identical playback for the same
  gestures, since the binary rule is the specification's and is applied in one place.
- Stopping still silences everything, including notes whose clamped off was moved earlier.

**Effort:** S–M. **Depends on:** nothing; it is independent of 18a and 18b, and could ship
first if the playback defect is the more annoying of the two.

#### Landed

`resolveOverlaps` is in `playback.ts` and applied once in `PianoPlayer.play()`, so the MIDI
path, the sampled piano and the FM voice all consume the same normalised list and no caller
can forget it. `PEDAL_DOWN` is exported from `playback.ts` and imported by `midi.ts` — it
stays at the owner it already had rather than moving into `types.ts`, because `playback.ts`
is reachable from the Node test runner and a runtime import there would have needed
`allowImportingTsExtensions` turned on for the whole project to support one constant.
Seven tests, and the frontend suite is 72 passing with `svelte-check` clean. The browser
suite gained one scenario assertion and all twelve scenarios pass.

Verified against the owner's own backup with the shipped functions rather than a
re-implementation of them — `sustained()` then `resolveOverlaps()` over the four pedalled
sittings:

| sitting | notes | pedal moves | cut short before | after |
| --- | --- | --- | --- | --- |
| 2 | 18,688 | 36,200 | 297 | 0 |
| 5 | 18,444 | 58,302 | 423 | 0 |
| 6 | 18,600 | 52,322 | 493 | 0 |
| 7 | 20,454 | 62,248 | 534 | 0 |
| **total** | | | **1,747** | **0** |

Worst loss 14.494 s before, 0 after.

**Retirement:** the per-note note-off scheduling is gone rather than kept behind a flag.
There is no instrument for which an overlapping same-pitch list is correct, so there is
nothing to retain and no trigger to schedule.

**What this does not fix, and does not claim to:** the partial-pedal band still reads as
released, and the pedal is still not sent to the output. Both are recorded above as
decisions rather than defects.

**The browser scenario covers the wiring, and was falsified before it was trusted.**
`scenario_playback` now seeds a sitting whose pedal carries a strike past a re-strike of the
same key — pitch 79, released at 800 ms, pedal up at 2000 ms, struck again at 1200 ms and
held to 5200 ms — plays it through the piano, and asserts that the scheduled stream for that
pitch never has two note-ons before a note-off. `__fakeMidi.samePitchOverlaps()` reads the
timestamps `send()` already records, so no new harness was needed. Removing the
`resolveOverlaps` call from `play()` makes it fail with "1 overlapping pairs"; restoring it
gives 0. All twelve scenarios pass on a fresh database.

**A wrong conclusion, kept because it is instructive.** The first attempt to run the suite
used a standalone `p.chromium.launch()` probe, which failed with "Executable doesn't exist
at `…/chromium_headless_shell-1234`", and that was written up here as "the browser suite
cannot be run on this machine". It can: `e2e_browser.py` passes
`executable_path="/usr/bin/chromium"` and never touches Playwright's bundled build at all.
The probe did not reproduce how the harness actually launches, and a conclusion drawn from
a test that does not match the real path is worth nothing — which is the same failure the
scenarios exist to catch, arriving from the other direction. The system Chromium (148) is
fine and no install is needed.

### Phase 20 — planned (deliberate practice, the piano-side toolkit, and audio takes)

Chosen by the user from a survey of everything in the app *except* the sight-reading loop,
and approved as five independently shippable slices. The organising finding is the mirror
image of Phase 18's. That phase read facts the app already stored; this one closes the gap
that the app **measures everything and plans nothing**. The log knows how long, on what, at
what tempo and with which pedal. It does not know *how* you practised, it cannot be undone
when an edit goes wrong, it holds no audio of its own, and the piano's middle pedal does
nothing at all.

**Order, and why: 20a → 20b → 20c → 20d → 20e.** The 20b-before-20e dependency is
load-bearing: the hands-free gesture is what arms audio capture from the piano bench
without reaching for the computer.

#### 20a — practice kinds (A1, A3) — landed

**Implementation plan:** [`PLAN-PHASE20A.md`](./PLAN-PHASE20A.md), which records the two deviations
and the two findings from executing this section — including a pre-existing metrics wipe in
`_refresh_metrics` (introduced in `2ee5003`) that this slice's baseline check surfaced and that is
now fixed with a regression guard.

**Problem.** A segment records what was played and for how long, never how. A stumbling
run-through at tempo and a careful slow pass over eight bars are the same row. The one
existing axis, `segments.source`, is *provenance* — `'sight_reading'` when a workout
produced the segment, `NULL` for passive practice — which is a different fact and must not
be overloaded to carry this one.

**Design.**

- `segments.practice_kind TEXT NULL` and `segments.practice_kind_basis TEXT NULL`, added
  through `practice/schema.py`'s `ADDED_COLUMNS` loop like every other additive column. The
  basis is `'manual'` or `'accepted'`, stored rather than re-derived, following
  `segment_metrics.pedal_basis`.
- Kinds: `run_through`, `slow`, `section`, `hands_separate`, `memory`, `warm_up`, `other`.
  **Sight-reading is deliberately not a kind**: it is already fully determined by
  `source`/`workout_id`, and a second owner for the same fact is exactly what Phase 18
  refused.
- **Inference is offered, never applied** — the autotag rule, reused:
  - *slower than usual for this piece*, from the segment's own `median_tempo` against the
    distribution of that piece's other segments. No new per-piece baseline is stored; the
    metrics are already a cache of a pure function.
  - *repeated starts*, from `restarts` (mid-segment silences ≥ `SRT_RESTART_GAP_MS`), which
    is what section work looks like from the outside.
  - **Hands-separate is never inferred.** `mean_velocity_low`/`high` is a register balance,
    not hands, and 18b already refused that claim in the UI; inferring it here would break
    that promise from the other direction.
- A manual kind always wins: re-running inference never overwrites a row whose basis is
  `manual`.
- UI: a kind chip per segment on the timeline, and the existing *How the time was spent*
  card gains a kind split beside the source split.

**Acceptance.**

- A kind set by hand survives a reload and is returned by the sitting detail.
- Re-running inference leaves every `basis='manual'` row's kind untouched.
- Accepting an offer records `basis='accepted'`; declining records nothing.
- A one-register segment never produces a `hands_separate` offer (the refusal, tested).
- The kind split reconciles with the window's logged minutes.

#### 20b — the piano-side toolkit (G2, G3, G4, G6)

**Problem.** The app is used from the piano bench, and every action needs a hand that is
supposed to be on the keys. The PX-870 has three pedals; only the damper is read, and the
sostenuto — the one a pianist almost never uses — does nothing. There is no count-in
choice, no URL for anything, and no keyboard path through the app.

**Design.**

- **Pedal discovery first, assumption second.** The device bar gains a readout of which
  controller numbers (`64`, `66`, `67`) have *ever* been seen from the connected piano, and
  says `none yet` before a pedal is pressed. The sostenuto (CC66) becomes the primary
  hands-free trigger; if it never arrives, the fallback is CC67 (soft, equally unused), then
  a double-tap of CC64 gated on two seconds of silence. Nothing is bound to a message the
  piano has not been observed to send.
- Hands-free actions: start and finish a workout, arm and stop audio capture (20e), and
  stop playback. The gesture is **inert during a scored attempt**, so it can never be
  mistaken for a musical event.
- Count-in: one bar, two bars, or none, plus click volume, persisted as a client preference
  beside the existing latency and theme values. `metronome.ts` reads it instead of the
  hard-wired one bar.
- URLs: view plus entity (piece, attempt, sitting, take) so a link opens the same thing on
  the LAN client and the Back button works. The view is plain in-memory state today.
- Keyboard shortcuts (`space`, `/`, `1`–`5`, `Esc`) and a command palette over pieces,
  journal content, sittings and media, composed from the search endpoints that already
  exist rather than a new one.

**Acceptance.**

- Before any pedal is pressed the device bar says so; after the sostenuto is pressed it
  names CC66; a piano that never sends CC66 falls back rather than appearing broken.
- The gesture starts and finishes a workout and arms and stops capture, and is ignored while
  an exercise is being scored.
- A two-bar count-in is honoured by the metronome and survives a reload.
- A deep link to a piece, attempt, sitting and take each open that thing; Back returns to
  the previous view.
- The palette finds a piece by title, a journal entry by a word that appears only in its
  content, and a sitting by date.

#### 20c — log trust and habit (F1, B3)

**Problem.** Merge, split and re-segment are one-way, and the matcher writes labels without
being asked. The streak resets on a single missed day, which punishes the recovery days a
pianist needs.

**Design.**

- **Undo with no new server surface.** Merge is exactly reversed by splitting at the
  absorbed segment's known `start_ms`; split by merging; assign by assigning the previous
  piece. The client already holds the pre-action list it rendered, so it can compute the
  inverse and call the route that exists.
- `resegment` is the only genuinely irreversible action: it keeps its confirm and gains an
  explicit *this cannot be undone* line. **Stated rather than hidden:** a merge sets the
  absorbed segment's `identification_outcomes.segment_id` to NULL (`ON DELETE SET NULL`), so
  undoing the merge restores the segments but not the matcher's record of that segment. The
  UI must not claim otherwise.
- Streak: `streak_days()` tolerates one missed day per rolling seven and reports whether the
  grace was used, so the number can be explained rather than merely displayed. The weekly
  target (`N` of 7 days) is a client preference computed from the `calendar` series the
  summary already returns — no new server setting, no new config key.

**Acceptance.**

- Undo after merge restores both boundaries and both labels; after split restores the single
  segment; after assign restores the previous piece.
- Undo is not offered after re-segmenting, which says so before it runs.
- One missed day preserves the streak and the UI says the grace was used; two consecutive
  missed days reset it; today still does not count against you.
- The weekly target needs no request beyond the existing summary.

#### 20d — journal and library depth (A2, C1–C4)

**Problem.** The journal is prose with a sitting link; it cannot be filtered by subject or
compared over time. There is nowhere to write down "bars 12–14 are the problem". A paused
piece nags for ever.

**Design.**

- **Focus passages, and the constraint that shapes them.** There is no score alignment and
  18b made that an explicit non-goal, so a passage can never be marked *touched* by passive
  capture. `piece_passages(id, piece_id, start_bar, end_bar, label, created_at,
  last_worked_on)` is therefore created **by hand, or seeded from a recording's existing A/B
  loop markers** — the one honest provenance available — and `last_worked_on` is stamped
  when you say you worked on it. Staleness sorts the list; nothing is inferred.
- Journal gains `tags` (a JSON array, the storage the project already uses for lists),
  `difficulty` and `fluency` (1–5, nullable), and `media_id` alongside the existing
  `sitting_id`, `ON DELETE SET NULL` for the same reason: deleting the take must not delete
  what you wrote about it. Tags filter the cross-piece feed and the ratings draw a line per
  piece.
- **The neglected list is a defect, not a feature.** `pieces.status` already exists as
  `active | completed | paused`, and `neglected()` filters only `NOT completed`, so a piece
  the player deliberately paused is reported as neglected for ever. The fix is
  `status = 'active'`. No new stage system, no per-piece checklist.
- Sorts (least time invested, last played), saved filters and bulk edits are composed
  client-side from the existing `/repertoire` list and the analytics `by_piece` the Log tab
  already fetches. No new route.

**Acceptance.**

- A passage seeded from an A/B loop carries that recording's bars and records the loop as
  its source; a hand-made one works with no recording at all.
- A `paused` piece never appears in Neglected; a `completed` one does not either.
- Tags filter the cross-piece feed and a rating is editable in place.
- A journal entry can be linked to a recording, and the link survives the recording being
  deleted.
- Least-time-invested and last-played agree with the analytics `by_piece` numbers.

#### 20e — audio takes (D1, D2, D3)

**Problem.** Every recording in the library got there by upload, and the piano's own
pen-drive recording already exists — so in-app capture is not an archive. It is the
convenience layer: the take you want to send someone, or hear once, without finding a
memory stick. The user's own words: *"the audio is a plus on top of that for quick audio
sharing."*

**Design.**

- Capture follows the **standing capture switch**, in the same spirit as MIDI capture. Mono,
  Opus, ~32 kbps: quality is explicitly not a gate, which is what makes a standing switch
  affordable at roughly **14 MB per hour**.
- A segment is computed server-side after ingest, so the client cannot cut on it directly.
  It cuts on the *same* silence rule instead — the server serves `SRT_SEGMENT_GAP_S` so the
  constant is not forked into the client — and uploads each chunk with its epoch range
  through the existing recording import route. The server attaches it to the segment whose
  window it overlaps, which is the same absolute-epoch-ms reasoning the note wire format
  already relies on.
- `media` gains `source` (`'uploaded' | 'captured'`), `sitting_id` and `segment_id`, all
  nullable and additive. The content-hashing, ffprobe pass, waveform and A/B machinery are
  unchanged: a captured take is an ordinary recording row.
- Deployment gains `AudioCaptureAllowedForUrls` beside the existing `MidiAllowedForUrls` in
  `deploy/chromium-policy.json`.
- **No automatic pruning.** The System panel reports captured-audio size, and deletion stays
  on the loopback-only side of the D8 boundary. If the machine has no input device at all,
  the UI says so rather than cheerfully writing silence.
- D2 is a takes timeline per piece (date, duration, and the metrics of the segment it
  covers) with any two selected for A/B. D3 is playback rate (0.5×–1×) on that loop, with
  the pitch-preservation setting stated in the UI rather than assumed.

**Acceptance.**

- With capture armed and an input present, playing produces a take whose duration is within
  a second of the notes it covers, attached to the right segment.
- With no input device, the UI reports that instead of writing a silent file.
- A captured row is `source='captured'`; an imported one is `source='uploaded'`.
- Two takes of one piece can be A/B'd and each keeps its own loop markers.
- 0.5× playback is honoured and the pitch behaviour is stated.
- Deleting a captured take is refused from the LAN.

#### Decisions taken

| ID | Question | Decision | Consequence |
| --- | --- | --- | --- |
| 20-D1 | Is practice kind a second axis, or an extension of `source`? | **A second axis** — `source` keeps meaning provenance | Sight-reading is not owned twice; the deliberate-practice taxonomy covers repertoire practice only |
| 20-D2 | Is an inferred kind ever applied? | **No — offered only**, with the basis recorded | The autotag restraint is preserved; a manual tag can never be silently overwritten |
| 20-D3 | Does undo survive a restart? | **No** — inverse operations over existing routes, and `resegment` stays irreversible | No new table, no backup change, no second source of truth for segment boundaries; the one loss (an absorbed segment's identification outcome) is stated rather than papered over |
| 20-D4 | Does in-app audio replace the piano's pen-drive recording? | **No** — a low-bitrate convenience for sharing, never an archive | Quality is not an acceptance criterion, so a standing switch is affordable and privacy/retention stay simple |
| 20-D5 | Which pedal is the hands-free trigger? | **The sostenuto (CC66), discovered rather than assumed**, with CC67 then a CC64 double-tap as fallbacks | No gesture is bound to a message the piano has not been seen to send; the device bar reports the discovery |
| 20-D6 | Does one missed day break the streak? | **No — one grace day per rolling seven**, with a weekly target carrying the habit | The familiar consecutive-day number survives; the weekly target needs no server-side setting |
| 20-D7 | Are focus passages inferred from the log? | **No — manual, or seeded from an existing A/B loop** | There is no score alignment to infer from, and 18b made that a non-goal; nothing is claimed about bars the app cannot see |

**Schema and migration.** 20a adds two `segments` columns; 20d adds four `piece_journal`
columns (`tags`, `difficulty`, `fluency`, `media_id`) and the `piece_passages` table; 20e adds
three `media` columns. Each slice that touches the schema bumps `SCHEMA_VERSION` and adds its
`ADDED_COLUMNS`/`CREATE TABLE` entries through the Slice 1 mechanisms, and `piece_passages`
must join the exported table list so a backup round trip still covers every domain.

**ADR signal.** 20-D3 (undo without a persisted record), 20-D5 (binding behaviour to a
controller message the app discovers) and 20e's audio-capture permission are durable
decisions that extend D7/D8's runtime and trust boundaries. This document plus its decisions
tables remains the decision record; no ADR directory is created.

#### Effort, risk and order

| Slice | Contents | Effort | Risk | Depends on |
| --- | --- | --- | --- | --- |
| 20a | Practice kinds, inference, timeline chips | M | low | — |
| 20b | Pedal discovery and hands-free, count-in, URLs, palette | M–L | medium — the routing touches the shell | — |
| 20c | Undo, grace-day streak, weekly target | S–M | low | — |
| 20d | Focus passages, journal tags and ratings, neglected fix, list QoL | M | low | — |
| 20e | Audio capture, takes timeline, playback rate | L | medium — a permission, an input device, and disk growth | 20b (the gesture arms it) |

#### Non-goals, stated so the plan cannot drift

- No score alignment, therefore no automatic passage marking, no per-bar error map, and no
  claim about a bar the log cannot see.
- No hands-separate inference from register balance.
- No audio archival, no quality work, and no replacement for the piano's own recording.
- No per-piece streaks.
- Section practice (pick bars, slow down, loop until clean) and per-hand practice remain
  deferred, unchanged. 20a's *section* kind records that you did section work; it does not
  generate or loop the section.

### Still open, from the earlier brainstorm

**Section practice** (pick bars, slow down, loop until clean) and **per-hand practice**,
both offered and both deferred by the user, and both still deferred after Phase 20's
survey — the slice that came closest, 20a's `section` kind, records that section work
happened without generating or looping anything. They remain the highest-value items on this
list by my estimate, since they change what the app is *for* rather than what it shows.

Also open: **retiring `practice-logger/`** — its code and history are ported and
importable, so deleting the directory is the user's call — and the **courtesy time
signature** at system breaks, which OSMD cannot be talked into.

### Risks, stated plainly

| Risk | Treatment |
| --- | --- |
| The kiosk browser dies (session lock, crash, OOM) and capture silently stops | The capture heartbeat and the "last note N min ago" indicator make it visible from the main computer; the kiosk is on `Restart=always` |
| `snd_seq` not loaded → Web MIDI sees **zero** devices, which looks like a hardware fault | Loaded at boot by the deployment, and reported by `GET /api/host` |
| A blanked screen looks like a stopped machine | Documented: blanking does not stop capture, because MIDI delivery and flush timers are not tied to the display |
| `note_events` grows without bound | ~1–5 k rows per hour of playing is a few MB per year; the JSON export excludes media, so backups stay small. Retention policy is not needed yet |
| An unauthenticated LAN can still *edit* and *upload* (D8) | Visible banner; the irreversible paths are loopback-only, which is the part that cannot be undone by hand |
| A future move to a reverse proxy or a non-loopback deployment breaks the boundary silently | `request.client.host` is the check today and there is no proxy in this topology; if one is ever added, the check must move to a trusted header, and this row is the reminder |
| Captured audio (Phase 20e) grows without bound and is the first thing in the app whose size matters | ~14 MB per hour at 32 kbps mono, against a few MB per *year* for notes. Deliberately not auto-pruned: the System panel reports captured-audio size and deletion stays loopback-only, so the player decides rather than a policy |
| The sostenuto pedal is bound to a controller message the piano may not send (Phase 20-D5) | The device bar reports which of CC64/66/67 have actually been seen before anything is bound, and CC67 then a CC64 double-tap are the fallbacks. A piano that sends none of them keeps every feature except the gesture |

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

Phase 20 follows the same rule rather than adding documents. The audio-capture permission
lands in `deploy/chromium-policy.json` and is described in `DEPLOYMENT.md` and
`deploy/README.md` when 20e ships, not before. `README.md` gains a line for each slice that
a player can see, and what a slice owes the suite is owned by
[`TEST-STRATEGY.md`](./TEST-STRATEGY.md) as it already is for every other change.
