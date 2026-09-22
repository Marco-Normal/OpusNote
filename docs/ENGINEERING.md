# Engineering notes

The difficulty model, the adaptive engine, the scorer, the timing model, and the integration
behaviours that are not obvious from the code. The [README](../README.md) is the front page;
[FEATURES.md](FEATURES.md) covers user-facing behaviour.

- [1. Architecture](#1-architecture)
- [2. The API contract](#2-the-api-contract)
- [3. Difficulty model](#3-difficulty-model)
- [4. The adaptive engine](#4-the-adaptive-engine)
- [5. Scoring](#5-scoring)
- [6. Timing](#6-timing)
- [7. Notation rendering: integration notes](#7-notation-rendering-integration-notes)
- [8. Configuration](#8-configuration)
- [9. Known limitations](#9-known-limitations)

---

## 1. Architecture

Three layers, with a deliberate separation of responsibility:

| Layer | Location | Responsibility |
| --- | --- | --- |
| Client | `frontend/src` | Render notation, capture MIDI, run the metronome, display feedback |
| API | `backend/app/main.py` | Serve exercises as MusicXML, score performances |
| Storage | `backend/app/store.py` + SQLite | Profiles, skill ratings, exercise library, attempt history |

The client makes **no musical judgements of its own**. Every score comes from the API. That is
what makes the generator and the scorer replaceable without touching the browser.

Technology: Python 3.11 / FastAPI / SQLite / music21 on the server; Svelte 5 / TypeScript / Vite
in the browser, with OpenSheetMusicDisplay for engraving and Tone.js for audio.

## 2. The API contract

Two endpoints carry the whole interaction:

- `GET /api/exercise/next` → MusicXML plus the expected-note timeline
- `POST /api/score` → played notes in, per-note feedback and sub-scores out

Everything else — `/api/calibration/next`, `/api/stats`, `/api/profile` — is convenience on top.

## 3. Difficulty model

Nine independent skills, each on a level from 1 to 10. `backend/app/skills_data.py` is the single
source of truth, and it asserts at import time that every parameter table defines all ten levels.

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

## 4. The adaptive engine

Elo, with one twist that matters.

- Each **skill** has a rating; each **exercise** has a difficulty.
- Each skill is scored against the Elo implied by **its own level** in the exercise — *not* the
  exercise's blended difficulty. Otherwise a hard rhythm in an otherwise easy piece would drag
  every unrelated skill rating down.
- The targeted skill moves at the full `K`; the others at half `K`.

**The twist.** A learner's Elo is the difficulty at which they score 50%, so selecting exercises
*at* the rating would hold them at a 50% success rate — demoralising, and nowhere near the
70–85% zone the design targets. The selector deliberately aims below the rating:

```
offset = 400 · log10(1/target − 1)      # target = 0.78  →  offset ≈ −220
```

A rating of 1000 therefore receives exercises around Elo 780. `SRT_TARGET_SUCCESS_RATE` tunes
this. A simulation in `backend/tests/test_adaptive.py` walks a learner with a fixed true ability
and asserts that the served difficulty converges into the 70–85% band.

**The base anchor.** The other half of that arithmetic is `SRT_ELO_BASE`, the Elo of the easiest
material, and it must sit low enough that the offset still lands inside the ten-level ladder. An
earlier value of 600 did not: level 2 was unreachable below a rating of 870, so every learner
below that was served level 1 indefinitely — 270 points of ability collapsed into one level of
material and the exercises never became harder. `480` is the value that satisfies all three
constraints simultaneously:

| Constraint | Rationale |
| --- | --- |
| 780 must be a level boundary | the line above is then exact rather than approximate: 780 = 480 + 3 × 100 |
| an unrated learner (700) stays on level 1 | level 1 covers ratings up to 480 + 220 + 50 = 750 |
| as early as possible otherwise | it is the smallest such value, so each level opens 100 rating points above the last |

## 5. Scoring

For each expected note, within a ±200 ms window:

- **Pitch** — greedy nearest-first matching on equal pitch, then precision, recall and F1. Extra
  notes cost precision; missing notes cost recall. Written over *lists* of notes, so chords are
  handled natively.
- **Rhythm** — mean absolute onset error and its spread, converted to beats at the exercise's
  tempo.
- **Continuity** — hesitations (a gap more than 500 ms longer than notated) and tempo
  instability. This uses a separate, much wider matching window, because a hesitation is *late*,
  not *wrong*: reusing the tight pitch window made stalls invisible.

Overall = 0.5·pitch + 0.3·rhythm + 0.2·continuity. Pass at 80. Every threshold lives in
`backend/app/config.py` and is overridable by environment variable.

**Hand attribution.** MIDI does not report which hand played a note, so the hand is derived from
the notation: the generator emits the right hand as part 1 and the left as part 2, and each
expected note carries its hand. Feedback is reported per hand.

**Latency.** *Setup › Timing › Calibrate by playing…* measures round-trip delay by having the
player perform alongside a metronome and taking the median offset; the scorer subtracts it.
Calibration is suggested but never applied automatically, because it changes what the scorer
subtracts and so affects comparability with past scores.

## 6. Timing

Two clocks, deliberately kept apart:

- **Audio** — clicks are scheduled ahead through Tone.js so the Web Audio clock stays accurate.
- **Capture** — onsets are measured with `performance.now()`, the same clock the MIDI timestamps
  use.

Metronome clicks are scheduled from the audio clock; the beat indicator and recorded onsets both
come from `performance.now()`, so what is seen and what is captured agree with what was heard.
The count-in length follows the first bar's meter, and per-bar meter is served by the API
(`measures[]`), so mixed-meter exercises count in correctly.

## 7. Notation rendering: integration notes

Behaviours of OpenSheetMusicDisplay that are not obvious from its documentation. They are
commented at the call site in `frontend/src/lib/score.ts` and summarised here so they are not
rediscovered.

- **`Pitch.getHalfTone()` is not a MIDI number.** It returns `12 × (MusicXML octave) +
  fundamental`, exactly one octave below MIDI. A written C4 comes back as 48. The renderer adds
  12, and warns to the console if fewer notes correlate than the exercise contains.
- **`autoResize` wipes per-note colours.** The resize observer re-renders on ordinary layout
  shifts — the results panel appearing is sufficient — and a re-render rebuilds the SVG.
  `autoResize` is therefore disabled and the renderer owns layout, re-rendering only when the
  *width* changes.
- **`darkMode` does not colour noteheads.** It lightens the music but leaves
  `defaultColorNotehead` at black, producing black noteheads on a black page. Explicit ink
  colours are passed for music, noteheads, stems and rests.
- **Noteheads carry no class of their own** — they are plain `<path>` elements — so any check on
  notation colour must measure the painted `fill` rather than select on a class.
- **`render()` appends rather than replaces.** Calling it twice stacks two complete scores and
  the container height becomes their sum. Every re-render clears first, and renders are
  serialized.
- **No courtesy time signature at system breaks.** OSMD reprints the clef but not the time
  signature and exposes no rule for it. Meter changes are rendered correctly; a constant meter
  across systems is shown once.
- **Layout can oscillate.** Growing content can toggle the page scrollbar, which changes the
  available width, which re-wraps the music. `scrollbar-gutter: stable` plus a coarse resize
  threshold breaks the loop.
- **A tempo marking is not a beat.** Tempo is quarter notes per minute; the beat is whatever the
  meter says — a dotted quarter in 6/8, a half note in cut time. Treating seconds-per-quarter as
  seconds-per-beat made the metronome, the count-in and the end-of-run timer wrong in every
  compound meter.
- **Two note-naming schemes meet at the sampler and are not interchangeable.** The sample files
  use `Ds4`, because a `#` in a URL begins a fragment and `D#4.mp3` would fetch `D`. Tone.js
  requires `D#4`. Using the wrong one leaves the sampled piano silent and falls back to the
  synthesiser, so the Setup panel reports a sample failure rather than leaving it to be guessed.
- **A part's identity is not its staff position.** The renderer has to know which hand a staff
  belongs to, and the answer is on the part, not on the index: `GraphicalMeasure.ParentStaff` →
  `Staff.ParentInstrument` carries the MusicXML part id (`IdString`) and name (`Name`). Reading
  `staffIndex` instead is right for a two-hand exercise and for a right-hand-alone one, and wrong
  for a left-hand-alone one — a single part named "Left Hand" on staff index 0 — which cost every
  note its colour at texture level 2 for as long as the level has existed. The authority is
  `music/expected.py`; the browser mirrors its rule rather than re-deciding it.
- **A notehead is a group, and painted colours are not one path per note.** VexFlow puts
  `vf-notehead` on a `<g>` and paints the glyph on the `<path>` inside it, so the group's own
  computed `fill` is black whatever colour the note is — measuring it reports a working score as
  uncoloured. Counting every filled `path` fails the other way: `setColor` is called with
  `applyToLedgerLines` and `applyToTies`, so ledger lines and ties are painted too, and a bass-clef
  part has far more painted paths than notes (27 for 14). Assert on the `<path>` inside each
  `.vf-notehead`; the harness's `NOTEHEAD_FILL_COUNTS` is that measurement.

## 8. Configuration

Every environment variable is optional.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SRT_DB_PATH` | `~/.local/share/piano-ecosystem/piano.db` | SQLite file for the whole ecosystem |
| `SRT_MEDIA_DIR` | `~/.local/share/piano-ecosystem/media` | Recordings, content-hashed |
| `SRT_LEGACY_DB` | `~/.local/share/piano-progress/piano.db` | The Rust application's database, read once by the importer |
| `SRT_TARGET_SUCCESS_RATE` | `0.78` | Target success rate (sets the selection offset) |
| `SRT_PASS_THRESHOLD` | `80` | Score required to pass |
| `SRT_MATCH_WINDOW_S` | `0.200` | Pitch matching window |
| `SRT_CONTINUITY_WINDOW_S` | `1.500` | Window for hesitation detection |
| `SRT_HESITATION_MS` | `500` | Extra gap that counts as a hesitation |
| `SRT_ELO_BASE` | `480` | Elo of the easiest material — see §4 |
| `SRT_ELO_PER_LEVEL` | `100` | Elo between one level and the next |
| `SRT_DEFAULT_RATING` | `700` | Where an uncalibrated learner starts |
| `SRT_ELO_K` | `32` | Rating step |
| `SRT_EXERCISE_BARS` | `4` | Bars per exercise |
| `SRT_WORKOUT_LENGTH` | `8` | Exercises in a workout |
| `SRT_SITTING_GAP_S` | `300` | Silence that closes a sitting |
| `SRT_SEGMENT_GAP_S` | `8` | Silence after which a *take* being recorded is cut. Superseded for segmenting a stored sitting by Phase 22a's adaptive rule below; measured against a real session; see [FEATURES.md](FEATURES.md) §6 |
| `SRT_SEGMENT_FLOOR_MS` | `2000` | Phase 22a: the shortest pause that can be a segment boundary |
| `SRT_SEGMENT_PULSE_MULTIPLIER` | `2.5` | Phase 22a: how many times the passage's own pulse a pause must be to cut |
| `SRT_SEGMENT_CEILING_MS` | `30000` | Phase 22a: past this, a pause is a break whatever the pulse says |
| `SRT_SEGMENT_MIN_NOTES` | `8` | Phase 22a: below this, a group is absorbed into its neighbour |
| `SRT_SEGMENT_MAX_MS` | `120000` | Phase 22a: above this, a group is split at its largest internal pauses |
| `SRT_RESTART_GAP_MS` | `3000` | Mid-segment silence counted as a restart |
| `SRT_ATTACK_WINDOW_MS` | `50` | Notes closer than this are one attack, for tempo |
| `SRT_AUTOTAG_SCORE_AUTO` | `0.85` | Score at or above which a match is written without asking |
| `SRT_AUTOTAG_MIN_MARGIN` | `0.10` | Required lead over the runner-up. `0.05` roughly doubles the labels written, at about a 3% measured error rate |
| `SRT_AUTOTAG_SCORE_PROMPT` | `0.55` | Score at or above which a match is offered |
| `SRT_AUTOTAG_MIN_NOTES` | `8` | Below this many notes a segment is not recognised at all |
| `SRT_AUTOTAG_CONTAINMENT_WEIGHT` | `0.25` | Phase 22b: how much of a match's score comes from local content rather than from the whole-segment average. Chosen by the sweep in `tools/measure_autotag.py` |
| `SRT_AUTOTAG_NEIGHBOURS` | `6` | **Retired by Phase 22b, read by nothing.** Evidence is pooled per piece, so a window over segments has no meaning. Kept intact pending a deployment decision |
| `SRT_AUTOTAG_TRAINING_LIMIT` | `600` | **Retired by Phase 22b, read by nothing.** A piece learned a year ago is exactly as strong as yesterday's. Kept intact pending a deployment decision |
| `SRT_MAX_UPLOAD_MB` | `512` | Largest recording accepted by the upload endpoint |
| `SRT_PIANO_DIR` | `<data dir>/piano` | Where the one-time sampled piano is kept and served from |
| `SRT_BACKUP_DIR` | `<data dir>/backups` | Where the nightly JSON exports are written |
| `SRT_BACKUP_KEEP` | `14` | How many daily backups to keep |
| `SRT_API_TARGET` | `http://127.0.0.1:8000` | Proxy target for the dev server |

## 9. Known limitations

- **Browser support.** Web MIDI requires Chrome, Edge or Opera on desktop. Safari and Firefox are
  limited; the interface detects this and reports it rather than failing silently.
- **Tempo is constant per exercise.** No ritardando or tempo changes, which keeps the beat grid
  exact.
- **Polyphony is approximated at the top of the range.** Textures 1–6 are generated properly;
  7–10 (inner voices, imitation, dense writing) are deliberate simplifications. Scoring handles
  them correctly — only the composition is simplified.
- **Generated music is generated music.** It is musical and correctly notated, but a curated
  library can be substituted behind the same API.
- **No authentication.** One local profile, by design. `POST /api/profile/reset` clears it.
- **Startup cost.** Importing music21 takes a second or two; exercises themselves generate in
  roughly 20 ms.
