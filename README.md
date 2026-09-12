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
# Backend unit + API integration (173 tests)
cd backend && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q

# Full browser end-to-end against the running server (see tools/e2e_browser.py)
.venv/bin/python tools/e2e_browser.py
```

The end-to-end script injects a **simulated Web MIDI device** before any page
script runs, so the real MIDI input path — status-byte decoding, input
selection, onset measurement against the count-in anchor — is exercised rather
than stubbed. It plays a perfect performance (expecting 100/100), an all-wrong
performance, a silent one, and walks a calibration rung, asserting on the
rendered notation, the results panel, and the progress view.

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
  tests/             173 unit + integration tests
  tools/e2e_browser.py  Real-browser end-to-end verification
frontend/
  src/
    lib/             api, midi, metronome, score rendering, live matching, state
    components/      Practice, Calibration, Stats, charts
```

---

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
| `SRT_DB_PATH` | `backend/data/sightreading.sqlite3` | SQLite file |
| `SRT_TARGET_SUCCESS_RATE` | `0.78` | Target success rate (sets the selection offset) |
| `SRT_PASS_THRESHOLD` | `80` | Score needed to pass |
| `SRT_MATCH_WINDOW_S` | `0.200` | Pitch matching window |
| `SRT_CONTINUITY_WINDOW_S` | `1.500` | Window for hesitation detection |
| `SRT_HESITATION_MS` | `500` | Extra gap that counts as a hesitation |
| `SRT_ELO_K` | `32` | Rating step |
| `SRT_EXERCISE_BARS` | `4` | Bars per exercise |
| `SRT_API_TARGET` | `http://127.0.0.1:8000` | Proxy target for the dev server |
