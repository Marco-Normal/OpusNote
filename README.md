# Sight-Reading Trainer

An adaptive sight-reading trainer for a real piano. It shows a short,
level-appropriate excerpt, counts you in over a metronome, listens to your MIDI
keyboard, and scores pitch, rhythm, and continuity. The next exercise is chosen
from your weakest skill, with the difficulty aimed so you succeed about 78% of
the time.

Built for a **Casio PX-870** over USB Type-B, but it works with any
class-compliant MIDI keyboard.

---

## Quick start

Two processes: the API and the browser client.

```bash
# 1. API  (from the repo root)
cd backend
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# 2. Client  (in a second terminal)
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**, click **Connect MIDI**, pick your keyboard, and
press **Get my first exercise**.

> Use `localhost`, not `127.0.0.1`, for the dev server — that is where Vite binds
> by default. Web MIDI requires a secure context, and `localhost` counts as one.

### MIDI devices

The app connects by itself and picks the port that actually carries notes. That
matters on Linux, where ALSA always exposes a virtual `Midi Through Port-0` beside
your keyboard: it is a real Web MIDI input that never sends anything, and choosing a
device by position picks it roughly half the time.

Open **Ports** in the device bar to see every input with what has been heard from it
— `17 notes · last 4 s ago`, or `no notes yet` for the loopback port — and which one
is in use (`Auto · CASIO USB-MIDI MIDI 1`).

- **Nothing to click.** The app connects on load and again when the piano is switched
  on later, so a machine left running picks it up by itself. Press **Connect MIDI**
  once if the browser has never been granted MIDI access.
- **Use only this** pins a device when you would rather be certain than inferred; the
  choice survives a reload. **Back to automatic selection** undoes it.
- **Echoes are dropped, not ports ignored.** Every port stays attached, and a note
  reported twice within 30 ms by two different ports is counted once — so a keyboard
  that splits zones across ports loses nothing.
- On the piano machine use `http://localhost:8000`: Web MIDI requires a secure
  context, and a LAN hostname is not one.

### Two hands and the left-hand library

From texture level 3 up, exercises are written on a grand staff and both hands
are read together. The left hand is drawn from a library of **18 named
accompaniment figures** spanning the common vocabulary:

- **Sustained** — held root, root-and-fifth, block chords
- **Pulse** — root-fifth "boom-chick", march bass, waltz bass, stride bass, tenths
- **Broken chord** — Alberti bass, the 6/8 (compound) form, ascending broken
  chords, wide arpeggios, broken octaves
- **Independent** — walking bass, a free left-hand line, countermelody, and canon
  (the left hand answers the melody a bar later)

The figure is chosen from the meter and the texture level — a waltz bass never
appears in 4/4 — and every figure is unit-tested for exact bar fill, register,
and diatonicism. The exercise header shows which figure you are reading.

Figures need something to outline, so a small diatonic progression engine
supplies a chord per bar (I–V at the beginner end, through vi and ii and
inversions later) and always cadences onto the dominant then the tonic. When both
hands play, the melody's downbeats are anchored to the chord; a solo line is left
free because it has nothing to clash with.

### Exercise length and Focus mode

The **Bars** control picks 4 / 8 / 12 / 16 bars. Length is a *preference*, not
part of difficulty, so `difficulty_elo` keeps meaning one thing.

The hard rule for sight-reading is that **the music must never scroll during a
performance** — looking away is the failure this app exists to train against.
So:

- The engraving scales down (to a floor of 55%) until the whole exercise fits.
- While a run is in progress the surrounding chrome collapses, so nothing is
  competing with the score for height.
- **Focus** hides the header, device bar, and note strip outright, which is the
  right choice for a small window.
- If a length genuinely cannot fit even at minimum zoom, the app says so and
  offers a shorter one. It never leaves you with a score that scrolls.

### Adding to the library

**Repertoire** tab, top right: **New piece**. The editor takes a title, opus, key,
difficulty, status and a description, and it can create a **composer** inline
(*+ new composer…* in the composer list), so a fresh install needs nothing else. From
a piece's detail you can add journal entries, edit it, attach a score, upload a
recording and delete it. All of it works from any machine on the LAN except deleting,
which is piano-machine only (see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)).

**Scores** go in beside the recordings: a **PDF** is shown in the browser's own viewer,
and **MusicXML** is engraved in the app by the same renderer the exercises use. Neither
is re-encoded — the file you attach is the file you read — and both are checked on
upload, so a `.pdf` that is not a PDF or an XML file that is not MusicXML is refused
before it can become a blank frame at the piano. (A compressed `.mxl` has to be unzipped
first.) Scores are counted separately from recordings everywhere.

**Recordings** get a waveform and an **A/B loop**. Open a recording, press *Waveform*,
and the peaks are decoded in the browser (nothing new is generated server-side); click
the picture to move the playhead, then *Set A* and *Set B*. Playback then stays inside
those markers, the audio outside them is dimmed, and the markers are saved with the
recording rather than in the browser — so the same passage is there on the other
machine. A recording over 64 MB is not decoded for a picture (it still plays).

Starting empty is a supported path: with no pieces at all, the Repertoire tab offers
both *Import from piano-progress* (if that database is on this machine) and **New
piece**.

### Practice log

Everything you play is logged without pressing anything, once a MIDI device is
connected — capture is a standing switch, not a per-sitting button. The server
groups notes into **sittings** by silence (five minutes closes one) and into
**segments** by shorter silence (twenty seconds), which is normally one piece per
segment. Nothing is recomputed behind your back: a boundary you move by hand stays
moved.

- **Log** tab: today, streak, a twelve-week calendar, time per piece, neglected
  pieces, and the sitting timeline where you tag a segment with a piece, split a
  boundary the silence detector got wrong, merge two it split, or re-segment.
  Re-segmenting is the only destructive action and asks first when segments carry
  labels. Each segment row has two fields: the **piece** it was, and **Split at** — a
  position to cut the segment in two, typed as a clock (`1:30:12`) or in seconds
  (`5412`), which is what the *Split here* button then does.
- **Workouts** are declared, not inferred: *Start workout* in the banner, play,
  *Finish workout*. Everything inside the window is labelled sight-reading rather
  than mistaken for ordinary practice, and a finished workout links to the sitting
  it happened inside. The Progress/Log views then separate "how long did I play"
  from "how much deliberate sight-reading did I do".
- **The app learns which piece you are drilling.** Tag a segment by hand and it becomes
  a reference; the next time you play something similar the timeline offers the piece it
  thinks it was, with the percentage and the arithmetic behind it. A match it is sure of
  is filled in on its own, marked *guessed*, with "It's right" and "Not this" beside it —
  and the piece dropdown corrects it either way. Nothing is ever applied without a way to
  disagree, and correcting a guess is what teaches it that two of your pieces sound
  alike. The **Recognising what you played** panel reports how often it is right *on your
  own library*, measured by hiding each of your tagged segments in turn, and how often
  the labels it wrote unasked survived you looking at them. One-hand drilling is the
  case it finds hardest, and the panel says so rather than hiding it.
- Per-piece, the Repertoire detail shows measured minutes from MIDI beside the
  minutes written in the journal — deliberately not summed, because a session can
  be both measured and written down, and adding them would count it twice.

Pieces are measured, not claimed: `median_tempo` is a **note rate** over attack
clusters (chords are one attack, so they do not read as infinite BPM). It is
comparable with itself over time, not an absolute metronome reading.

### Progress, and hearing the past

- **Rating over time** (Progress tab): every rating change is recorded, so each skill
  has a curve rather than a single number. The Elo engine nudges all nine dimensions on
  every attempt, so each point records whether its skill was that attempt's *focus*;
  the chart draws the whole line and tells you how many points were focus attempts.
- **Click a row in Recent exercises** to open that attempt: its sub-scores, its counts,
  and the same *Hear it* player a fresh result gets — your performance, or the exercise
  as written, either hand.
- **This week** (Log tab): minutes over the last seven days, workouts and streak, the
  most improved skill, and the piece you have neglected longest.

### Hearing it back

Two players, because there are two things worth hearing:

- **After an attempt**, the results panel has *Hear it*: **Play yours**, **Play as
  written**, or either hand alone. Written notes are played at the tempo you were
  counted in at, and your own notes carry the hands the scorer matched them to. This is
  the one that teaches something — a hesitation or a wrong note you only saw as a
  colour becomes audible.
- **In the Log tab**, a sitting or a single segment can be played back from the notes
  themselves. **Click anywhere on the timeline strip to start from there** — a two-hour
  sitting is unusable if the only way in is the beginning — and `« 30 s` / `30 s »` move
  the playhead without losing the range you were playing. The position readout shows
  where you are, and notes are fetched on demand (a long sitting is thousands of them).
  A segment starts at its first note rather than waiting out the silence before it.

**Which instrument** is chosen in the device bar, and there are three because they suit
three situations:

| | What it is | When |
| --- | --- | --- |
| *Through the piano* | The notes go out of a MIDI **output** to the PX-870 itself | Wherever a piano is connected — the piano machine, always. The only genuinely real piano sound, and it costs nothing |
| *Sampled piano* | The Salamander Grand Piano (a Yamaha C5), 30 samples, CC BY 3.0 | A viewer with no piano attached, or when you would rather not hear the room |
| *Synthesiser* | An FM voice built from Tone's oscillators | Before the samples are installed, and as the fallback when nothing else is available |

The sampled piano is a **one-time 2 MB download**, fetched by the backend and served
from this machine from then on: install it from the device bar (*Install (2 MB, once)*),
and nothing at play time touches the network. Salamander Grand Piano V3 by Alexander
Holm, [CC BY 3.0](https://archive.org/details/SalamanderGrandPianoV3).

**Falling notes.** Tick *Falling notes* in the sitting transport for a piano-roll view —
a keyboard along the bottom, the notes you played falling onto it, held notes drawn as
long as they sound. It follows the playhead, so it is also a way to *see* a hesitation
that is hard to hear.

**Stop means stop.** There is one player for the whole app, so nothing can play over the
top of anything else, and stopping cancels the notes that were scheduled but had not
sounded yet — as well as sending note-off and all-notes-off to the piano, so nothing is
left hanging on the instrument.

What is faithful is *timing and touch* — every onset, duration and velocity is the one
your playing produced, because a note's length is measured at its release — and, in the
log, **the sustain pedal**: CC64 is stored as it arrived and each note is held to the
pedal-up that covers its release, so a pedalled chord rings on instead of stopping dead.
In the passive log the two hands cannot be separated: the piano sends them on one MIDI
channel, and that is all that is stored. A scored attempt can separate them, because the
exercise knows which hand each note is.

### Keeping it healthy

- **Nightly backups.** `python -m app.backup` writes `piano-ecosystem-<date>.json` into
  `SRT_BACKUP_DIR` and keeps the newest `SRT_BACKUP_KEEP` (14 by default); the installer
  enables a systemd timer at 03:10 with `Persistent=true`. Run it by hand any time —
  it is the same code the *Download backup* button uses.
- **A System panel** in the Log tab: database size and WAL, recordings present, pending
  or missing, backups kept and how old the newest is, whether ALSA's sequencer is there,
  and which clients it can see — which is how you tell "the piano is off" from "the
  kernel module is missing".
- **Latency is suggested, never changed behind your back.** After a few attempts the
  device bar offers *Use N ms* when your own timing has been consistently early or late.
  Accepting it is your click, because it changes what the scorer subtracts.

### Export and backup

**Log → Export & backup** downloads one JSON document containing every table:
library, journal, media rows, sittings, note events, segments, workouts and
ratings. Recording *files* are not inside it; copy the media directory alongside
it. Restoring defaults to *add what is missing*, which never deletes local work;
*replace everything* empties every table first and takes two clicks.

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for running it on the piano machine,
WAL-aware backup, and a machine move — and [`deploy/README.md`](deploy/README.md) for
the planted-notebook setup: a systemd service, a Chromium kiosk at `localhost` (Web
MIDI needs a secure context), the policy that grants MIDI with no prompt, and the
loopback boundary that keeps deletions on the piano machine.

### Repertoire

The app also owns your piece library — composers, pieces, the journal you write
about them, and your recordings. It is the successor to a separate Rust desktop
app; see [`docs/ECOSYSTEM.md`](docs/ECOSYSTEM.md) for why the ecosystem is one
web app rather than three programs sharing a file.

Open the **Repertoire** tab to browse pieces grouped by composer or difficulty,
filter them, and read the journal and recording catalogue for any piece. Each
piece shows its *sight-reading fit* — the key and starting level the exercise
generator would use for it.

To bring an existing `piano-progress` library across:

```bash
curl -X POST http://127.0.0.1:8000/api/repertoire/import \
     -H 'Content-Type: application/json' -d '{"copy_media": false}'
```

The import reads that database **read-only**, can be run again to pick up changes
while you are still using the old app, and refuses a missing file or a database of
the wrong shape rather than importing nothing quietly. It copies the recordings
into the ecosystem media directory by default (`"copy_media": false` to skip a
large copy).

Recordings are playable straight away. Each one is reported as **in library**
(copied into this app), **not copied yet** (still only in the old
`piano-progress` directory, and streamed from there), or **file missing** (in
neither place). The Repertoire tab offers a one-click copy for anything still
pending.

`GET /api/practice-suggestions` maps the pieces you are working on onto a
sight-reading key and level — so exercises can be built around the piece in front
of you.

### Appearance

The **Appearance** control in the header offers:

- **Interface**: Auto (follows the OS), Light, Dark — persisted, and applied by
  an inline script before first paint so a dark reload never flashes white.
- **Sheet music**: Themed, or always paper-white. Inverting notation divides
  readers, so it is a choice rather than a rule; the notation can be dark while
  the chrome stays light, or vice versa.

### Single-process mode (production-style)

The API serves the built SPA itself, which is handy for a self-contained setup
and is what the end-to-end test exercises:

```bash
cd frontend && npm run build
cd ../backend && .venv/bin/python -m uvicorn app.main:app --port 8000
# everything on http://127.0.0.1:8000
```

### Tests

```bash
# Backend unit + API integration
cd backend && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q

# Full browser end-to-end against the running server (see tools/e2e_browser.py).
# It wants its own database and media directory, and a writable piano directory —
# the app serves the samples from a static mount it creates at startup:
SRT_DB_PATH=$PWD/data/e2e.sqlite3 SRT_LEGACY_DB=$PWD/data/legacy-fixture.db \
  SRT_MEDIA_DIR=$PWD/data/e2e-media SRT_PIANO_DIR=$PWD/data/e2e-piano \
  .venv/bin/python tools/e2e_browser.py

# How well the matcher recognises a drilled section, on generated material
# (see tools/measure_autotag.py — this is where the shipped weights come from)
.venv/bin/python tools/measure_autotag.py
```

The end-to-end script injects a **simulated Web MIDI device** before any page
script runs, so the real MIDI input path — status-byte decoding, input
selection, onset measurement against the count-in anchor — is exercised rather
than stubbed. It plays a perfect performance (expecting 100/100), an all-wrong
performance, a silent one, and walks a calibration rung, asserting on the
rendered notation, the results panel, and the progress view. Twelve scenarios in
all: they cover the sight-reading loop, the Repertoire library (import, edit,
scores, upload, stream, playback, the waveform and its A/B loop), the practice log
(passive capture, the pedal, a workout, tagging, splitting, merging,
re-segmenting, a backup round trip), MIDI auto-detection, the LAN viewer — and
recognising a drilled passage (including the case where the matcher is sure and
wrong, which is the one that matters), and playback — that notes reach the piano's
MIDI output, that Stop silences them, that clicking the strip seeks, and that the
falling-notes view draws.

---

## How it works

### Three layers

| Layer | Lives in | Responsibility |
| --- | --- | --- |
| Client | `frontend/src` | Render notation, capture MIDI, run the metronome, display feedback |
| API | `backend/app/main.py` | Serve exercises as MusicXML, score performances |
| Storage | `backend/app/store.py` + SQLite | Profiles, skill ratings, exercise library, attempt history |

The client makes **no musical judgements of its own**. Every score comes from the
API. That is what makes the generator and the scorer replaceable without
touching the browser.

### The contract

Two endpoints carry the whole interaction:

- `GET /api/exercise/next` → MusicXML plus the expected-note timeline
- `POST /api/score` → played notes in, per-note feedback and sub-scores out

Everything else (`/api/calibration/next`, `/api/stats`, `/api/profile`) is
convenience on top.

---

## Difficulty model

Nine independent skills, each level 1–10. `backend/app/skills_data.py` is the
single source of truth, and it asserts at import time that every parameter table
defines all ten levels.

| Skill | Level 1 | Level 10 |
| --- | --- | --- |
| Key signatures | C major | minor keys with 3+ accidentals |
| Meter | 4/4 | alternating irregular meters |
| Rhythm | quarters/halves | mixed tuplets and syncopation |
| Intervals | steps only | fully disjunct |
| Hand position | five-finger RH | free position changes |
| Texture | right hand alone | four-voice writing |
| Accidentals | diatonic only | highly chromatic |
| Tempo | 50–60 BPM | 160–200 BPM |
| Articulation | legato, no marks | full expressive marking set |

Each exercise is generated from a level per skill, then tagged with them.

### The adaptive engine

Elo, with one twist that matters.

- Each **skill** has a rating; each **exercise** has a difficulty.
- Each skill is scored against the Elo implied by **its own level** in the
  exercise — *not* the exercise's blended difficulty. Otherwise a hard rhythm in
  an otherwise easy piece would drag every unrelated skill rating down.
- The targeted skill moves at the full `K`; the others at half `K`.

The twist: **a learner's Elo is the difficulty at which they score 50%**, so
picking exercises *at* your rating would keep you at a 50% success rate —
demoralising, and nowhere near the 70–85% zone the design calls for. The
selector deliberately aims below the rating:

```
offset = 400 · log10(1/target − 1)      # target = 0.78  →  offset ≈ −220
```

So a rating of 1000 gets exercises around Elo 780. `SRT_TARGET_SUCCESS_RATE`
tunes this. A simulation in `tests/test_adaptive.py` walks a learner with a
fixed true ability and asserts the served difficulty converges into the
70–85% band.

---

## Scoring

For each expected note, within a ±200 ms window:

- **Pitch** — greedy nearest-first matching on equal pitch, then precision,
  recall, and F1. Extra notes cost precision; missing notes cost recall. Written
  over *lists* of notes, so chords already work.
- **Rhythm** — mean absolute onset error and its spread, converted to beats at
  the exercise's tempo.
- **Continuity** — hesitations (a gap more than 500 ms longer than notated) and
  tempo instability. This uses a separate, much wider matching window, because a
  hesitation is *late*, not *wrong*: reusing the tight pitch window made stalls
  invisible.

Overall = 0.5·pitch + 0.3·rhythm + 0.2·continuity. Pass at 80.
`backend/app/config.py` holds every threshold, all overridable by environment
variable.

**Hand attribution.** MIDI never says which hand played a note, so the hand
comes from the notation: the generator emits the right hand as part 1 and the
left as part 2, and each expected note carries its hand. Feedback is reported
per hand.

**Latency.** The Calibrate tab measures your round-trip delay by having you play
along with a metronome and taking the median offset; the scorer subtracts it.

---

## Timing

Two clocks, deliberately kept apart:

- **Audio** — clicks are scheduled ahead through Tone.js so the Web Audio clock
  stays accurate.
- **Capture** — onsets are measured with `performance.now()`, the same clock the
  MIDI timestamps use.

Metronome clicks are scheduled from the audio clock; the beat indicator and
recorded onsets both come from `performance.now()`, so what you see and what is
captured agree with what you heard. The count-in length follows the first bar's
meter, and per-bar meter is served by the API (`measures[]`) so mixed-meter
exercises count in correctly.

---

## Project layout

```
backend/
  app/
    main.py          FastAPI app — thin HTTP layer
    services.py      Orchestration: generate, score, adapt, persist
    store.py         All SQL
    db.py            Schema + connection handling
    models.py        Request/response schemas
    skills_data.py   The difficulty model (single source of truth)
    config.py        Every tunable, env-overridable
    music/
      generator.py   skill levels → music21 score
      expected.py    score → expected-note timeline
    scoring/engine.py  pitch / rhythm / continuity
    adaptive/
      elo.py         Rating maths
      selector.py    Which skill, how hard
  tests/             unit + integration tests
  tools/e2e_browser.py     Real-browser end-to-end verification
  tools/measure_autotag.py How well the matcher does on drill-shaped practice
frontend/
  src/
    lib/             api, midi, metronome, score rendering, live matching, state
    components/      Practice, Calibration, Stats, charts
```

---

## OSMD integration notes

Three non-obvious behaviours cost real debugging time. They are commented at the
call site in `frontend/src/lib/score.ts`; summarised here so they are not
rediscovered:

- **`Pitch.getHalfTone()` is not a MIDI number.** It returns
  `12 * (MusicXML octave) + fundamental`, exactly one octave below MIDI. A
  written C4 comes back as 48. The renderer adds 12 and warns to the console if
  fewer notes correlate than the exercise contains.
- **`autoResize` wipes per-note colours.** OSMD's resize observer re-renders on
  ordinary layout shifts (the results panel appearing is enough), and a
  re-render rebuilds the SVG. `autoResize` is therefore off and the renderer owns
  layout, re-rendering only when the *width* changes.
- **`darkMode` does not colour noteheads.** It lightens the music but leaves
  `defaultColorNotehead` at black, giving black noteheads on a black page.
  Explicit ink colours are passed for music, noteheads, stems, and rests.
- Noteheads are plain `<path>` elements with no class of their own, so any check
  on notation colour must measure the painted `fill` rather than a selector.
- **`render()` appends, it does not replace.** Calling it twice stacks two whole
  scores and the container height becomes their sum. Every re-render clears
  first, and renders are serialized.
- **No courtesy time signature at system breaks.** OSMD reprints the clef but not
  the time signature, and exposes no rule for it. Meter changes are rendered
  correctly; a constant meter across systems is only shown once. Forcing system
  breaks with an explicit `<time>` is the alternative — see the roadmap.
- **Layout can oscillate.** Growing content can toggle the page scrollbar, which
  changes the width, which re-wraps the music. `scrollbar-gutter: stable` plus a
  coarse resize threshold breaks that loop.
- **A tempo marking is not a beat.** Tempo is quarter notes per minute; the beat
  is whatever the meter says — a dotted quarter in 6/8, a half note in cut time.
  Treating seconds-per-quarter as seconds-per-beat made the metronome, the
  count-in, and the end-of-run timer wrong in every compound meter, and the
  timer silently truncated the performance.

## Notes and limitations

- **Browser support.** Web MIDI needs Chrome, Edge, or Opera on desktop.
  Safari and Firefox are limited; the UI detects this and says so rather than
  failing silently.
- **Tempo is constant per exercise.** No ritardando or tempo changes yet, which
  keeps the beat grid exact.
- **Polyphony is approximated at the top of the range.** Textures 1–6 are
  generated properly; 7–10 (inner voices, imitation, dense writing) are
  deliberate simplifications. Scoring handles them correctly — only the
  composition is simple.
- **Generated music is generated music.** It is musical and correctly notated,
  but a curated library can be dropped in behind the same API.
- **No authentication.** One local profile, per the MVP design. `POST
  /api/profile/reset` wipes it.
- **Startup cost.** Importing music21 takes a second or two; exercises
  themselves generate in ~20 ms.

---

## Configuration

Environment variables, all optional:

| Variable | Default | Meaning |
| --- | --- | --- |
| `SRT_DB_PATH` | `~/.local/share/piano-ecosystem/piano.db` | SQLite file for the whole ecosystem |
| `SRT_MEDIA_DIR` | `~/.local/share/piano-ecosystem/media` | Recordings, content-hashed |
| `SRT_LEGACY_DB` | `~/.local/share/piano-progress/piano.db` | The Rust app's database, read once by the importer |
| `SRT_TARGET_SUCCESS_RATE` | `0.78` | Target success rate (sets the selection offset) |
| `SRT_PASS_THRESHOLD` | `80` | Score needed to pass |
| `SRT_MATCH_WINDOW_S` | `0.200` | Pitch matching window |
| `SRT_CONTINUITY_WINDOW_S` | `1.500` | Window for hesitation detection |
| `SRT_HESITATION_MS` | `500` | Extra gap that counts as a hesitation |
| `SRT_ELO_K` | `32` | Rating step |
| `SRT_EXERCISE_BARS` | `4` | Bars per exercise |
| `SRT_WORKOUT_LENGTH` | `8` | Exercises in a workout |
| `SRT_SITTING_GAP_S` | `300` | Silence that closes a sitting |
| `SRT_SEGMENT_GAP_S` | `20` | Silence that splits a sitting into segments |
| `SRT_RESTART_GAP_MS` | `3000` | Mid-segment silence counted as a restart |
| `SRT_ATTACK_WINDOW_MS` | `50` | Notes closer than this are one attack, for tempo |
| `SRT_AUTOTAG_SCORE_AUTO` | `0.85` | Score at or above which a match is written without asking |
| `SRT_AUTOTAG_MIN_MARGIN` | `0.10` | How far ahead of the runner-up it must be to be written. `0.05` roughly doubles the labels written, at about a 3% measured error rate |
| `SRT_AUTOTAG_SCORE_PROMPT` | `0.55` | Score at or above which a match is offered |
| `SRT_AUTOTAG_MIN_NOTES` | `8` | Below this many notes a segment is not recognised at all |
| `SRT_AUTOTAG_NEIGHBOURS` | `6` | How many of your closest tagged segments count as evidence |
| `SRT_AUTOTAG_TRAINING_LIMIT` | `600` | How many of your most recent tagged segments the matcher compares against |
| `SRT_MAX_UPLOAD_MB` | `512` | Largest recording accepted by the upload endpoint |
| `SRT_PIANO_DIR` | `<data dir>/piano` | Where the one-time sampled piano is kept, and served from |
| `SRT_BACKUP_DIR` | `<data dir>/backups` | Where the nightly JSON exports are written |
| `SRT_BACKUP_KEEP` | `14` | How many daily backups to keep |
| `SRT_API_TARGET` | `http://127.0.0.1:8000` | Proxy target for the dev server |
