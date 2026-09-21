# Local test data — the real backup

Status: **local only.** Not in this repository, not in a clone, not in CI.

This document owns one question: **where is the real backup, and what is in it?** It exists so
that a test can one day be written against real data on purpose, rather than somebody finding
the fixture and having to guess what it proves. The fixture is the only real data this project
has; everything else in the suite is invented.

---

## 1. Where it is

Three items, all **siblings of this repository's root** rather than inside it:

| Item | Path, relative to this repo | Size |
| --- | --- | --- |
| Database document | `../piano-ecosystem-backup(3).json` | 61.1 MiB |
| Media blobs | `../media/` | 55.2 MiB |
| Git bundle of an earlier state | `../opusnote-backup-20260920-2144.bundle` | 1.8 MiB |

As of writing that is `/home/marco_normal/tmp/SighRTracker/`. **If these move, update this
table** — a path in a document is stale the moment somebody tidies a directory.

The first two are one fixture in two halves and are useless apart. The document sets
`includes_media_files: false`, and says so in its own `notes`:

> Recording files are not inside this document. The media rows are, so copy the media directory
> alongside it to restore playback.

`.gitignore` at the repo root carries an anchored guard (`/piano-ecosystem-backup*.json`,
`/media/`, `/*.bundle`). It is a guard against the **accident** of one being copied in — the
files are outside the repo, so nothing here is currently committable. The patterns are anchored
to the repo root deliberately: an unanchored `media/` would swallow any directory of that name
at any depth.

## 2. What it is

A real export from the running piano server, `exported_at` **2026-09-21T17:27:37+00:00**, format
`piano-ecosystem-backup` version **1**. That is the same `BACKUP_VERSION` that
`backend/app/backup.py` reads today, so it imports without translation — but note that it is a
*snapshot of a schema*, and a future `BACKUP_VERSION` bump is exactly the event that would make
this fixture stop loading. Check the version before assuming it still works.

| Table | Rows | | Table | Rows |
| --- | ---: | --- | --- | ---: |
| `note_events` | 238,665 | | `segments` | 68 |
| `pedal_events` | 539,726 | | `performances` | 58 |
| `exercise_skills` | 459 | | `exercises` | 51 |
| `rating_events` | 369 | | `pieces` | 20 |
| `media` | 17 | | `sittings` | 17 |
| `composers` | 9 | | `skills` / `user_skills` | 9 / 9 |
| `workouts` | 9 | | `piece_journal` | 7 |
| `identification_outcomes` | 6 | | `users` | 1 |
| `segment_metrics` | 48 | | `piece_passages` | 0 |

Completeness was verified, not assumed: all 17 `media` rows resolve to a file in `../media/`,
with no row missing its file and no file unreferenced. The `media` rows are 15 audio and 2
scores (one MusicXML, one PDF).

## 3. The trap: four of the fifteen audio files are silent

**This is the thing to know before writing any test against this data.**

The 15 audio files are not one population. Four carry `source: "captured"` — they are the app's
own browser-microphone takes — and they contain nothing but the microphone's self-noise. The
other eleven carry `source: "uploaded"` — the piano's own USB-stick recordings — and contain
real playing. Measured across all fifteen, the two groups separate on every axis with **no
overlap**:

| Feature | `uploaded` (n=11) | `captured` (n=4) |
| --- | --- | --- |
| mean level | −41.6 … −32.0 dBFS | −52.0 … −51.1 dBFS |
| peak level | −20.5 … −10.0 dBFS | −38.4 … −35.6 dBFS |
| spectral centroid | 335 … 568 Hz | 7,989 … 8,735 Hz |
| energy 100–500 Hz | 31 … 90 % | 8 … 9 % |
| energy above 12 kHz | 0 % | 32 … 45 % |
| L/R correlation | +0.27 … +0.51 | +0.07 … +0.14 |

So a captured take is a *valid, playable, correctly-transcoded Opus file that is silent*. **A
test that asserts "the take has audio in it" will fail against this fixture, and that is not a
playback bug.** The distinguishing features above are a ready-made oracle if one is wanted —
centroid or >12 kHz energy identifies the group unambiguously.

Why they are silent, because it is a fact about the deployment and not a defect in the capture
code: the recorder opens the host's **default audio input** through `getUserMedia` with no
`deviceId` (`frontend/src/lib/audioCapture.ts`), and the notebook is deployed on the piano with
its **lid shut** (`deploy/logind/50-piano.conf`). The microphone therefore records its own
electronics sealed inside the lid. MIDI is unaffected and complete throughout — the 600-second
captured take is exactly `MAX_TAKE_MS`, and the segment it belongs to holds 3,449 note events
spanning 604 s. The notes are all there; the audio was never in the signal path.

## 4. Restoring it

Both halves, in this order:

1. **The document** — `POST /api/backup/import` with
   `{"document": <the JSON>, "mode": "merge"}`. `merge` adds rows that are absent and keeps
   local ones, so it is safe and available over the LAN. `mode: "replace"` empties every table
   first and is refused unless the request comes from the piano machine itself
   (`require_loopback`) and carries `confirm: true`.
2. **The blobs** — copy `../media/` to the configured media directory, `SRT_MEDIA_DIR`
   (default `~/.local/share/piano-ecosystem/media`). The database rows and the files are
   matched by `file_name`, which is a content hash, so the copy is a plain directory copy.

Importing the document without the directory gives a library whose every recording 404s.

## 5. Rules

* **Never commit it.** It is real personal practice history: 238k note events, 539k pedal
  events, ratings, and a `users` table. It does not go in the repository, in a release, in an
  issue, or pasted into a test as an inline literal.
* **Do not let a test require it.** It is absent from a fresh clone and from CI, so anything
  that needs it must skip cleanly when the path is missing. A test suite that fails on a clean
  checkout because a fixture on one machine is gone is worse than not having the fixture.
* **Prefer it for read-only work** — metrics, sessionising, scoring, MusicXML parsing, the
  import path. It is a snapshot, not a scratch database: if a test needs to *write*, copy it
  first.
