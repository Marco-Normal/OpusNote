# Roadmap

Incremental expansion of the sight-reading trainer. Each slice is independently
shippable, independently verifiable, and small enough to review in one sitting.

This document is the plan of record. Update it in place as slices land; do not
create sibling roadmaps.

> **Superseded, and delivered.** The ecosystem plan in
> [`ECOSYSTEM.md`](./ECOSYSTEM.md) took over as the plan of record once the web app
> reached parity with the Rust app (its Phase 4), and it has since carried the work
> behind slices A-E. In particular
> **Slice E is delivered**: workouts (the `workouts` table, start/current/finish
> routes, the app-shell banner, attempt attribution, and the streak) landed as
> ecosystem Phase 6, along with the rename this document called for —
> `SRT_SESSION_LENGTH` is now `SRT_WORKOUT_LENGTH`. What follows is kept for its
> history and its reasoning, which are still accurate.

---

## Standing rules

These do not change per slice.

1. **The API is the contract.** `/api/exercise/next` and `/api/score` keep their
   current shape unless a slice explicitly says otherwise. The client makes no
   musical judgements.
2. **Every slice lands with tests.** Backend unit/integration coverage in
   `backend/tests/`, and the browser end-to-end script
   (`backend/tools/e2e_browser.py`) extended when the slice is user-visible.
   "It looked right when I ran it" is not verification. **Superseded in detail by
   [`TEST-STRATEGY.md`](./TEST-STRATEGY.md)**, which owns what each kind of change owes;
   this rule stands as the history of why.
3. **Nothing regresses the 173 existing tests.** A slice that needs an existing
   assertion changed must say so in its PR description and explain why.
4. **Notation legibility wins ties.** Where a UI preference fights how music is
   actually read, the notation wins.
5. **No dead configurability.** A setting that nothing reads gets deleted or
   wired up. (`SRT_SESSION_LENGTH` is currently dead — see Slice E.)

---

## Slice overview

**Landed: A, B, C, D.** Decisions recorded below. E–G remain planned.

| # | Slice | Effort | Risk | Depends on | Status |
| --- | --- | --- | --- | --- | --- |
| A | Notation hygiene (time signature) | S | Low | — | **done** |
| B | Theming + dark mode | M | Low | — | **done** |
| C | Layout that scales to longer scores | M–L | Medium | — | **done** |
| D | Real two-hand material | M–L | Medium | C | **done** |
| E | Sessions (the daily loop) | M | Low | — | planned |
| F | Musical depth (pedal, playback, looping) | M–L | Medium | — | planned |
| G | Platform (auth, Postgres, deploy) | L | High | E | planned |

Recommended order: **A → B → C → D → E → F → G**, with F1 (hear your
performance) as a cheap win that can slot in anywhere.

---

## A. Notation hygiene — time signature only at the start and on change

**Problem.** Every measure carries a `<time>` element, so a 4-bar exercise prints
four time signatures. Nothing in the app needs this; it is an artefact of
`generate_exercise` appending `meter.TimeSignature(...)` to every measure at
`backend/app/music/generator.py:628` (melody) and `:666` (accompaniment).

**Design.** Emit a `TimeSignature` only when it differs from the previous bar.

```python
previous_meter = None
for index in range(bars):
    measure = stream.Measure(number=index + 1)
    if meters[index] != previous_meter:
        measure.append(m21meter.TimeSignature(meters[index]))
        previous_meter = meters[index]
```

This is safe because nothing downstream depends on the per-measure signature:

- `_bar_plan` computes bar lengths and beat units from `TimeSignature(label)`
  directly, not from the appended object.
- `measure_time_signature()` in `music/expected.py` already carries the previous
  signature forward for bars that omit it (added for exactly this reason).
- `measure_meta()` uses the same carry-forward.

**Also in scope** (same class of defect — engraving noise):

- Confirm OSMD prints a **courtesy time signature at each system break** once a
  score spans multiple systems, and that it still does after this change. If it
  does not, restore it deliberately via EngravingRules rather than by
  re-emitting `<time>` everywhere.
- Confirm the same for redundant clef and key elements (music21 emits those once
  already; verify, do not assume).

**Acceptance.**
- A 4-bar 4/4 exercise contains exactly one `<time>` element.
- A mixed-meter exercise contains exactly one `<time>` per meter change.
- Mixed-meter bar filling still holds exactly (existing test
  `test_generator_survives_every_skill_level` covers this).
- Visual: one time signature at the start; a second only where the meter changes.
- All 173 existing tests pass unchanged.

**Effort:** S (~20 lines, 2 new tests).

---

## B. Theming and dark mode

**Problem.** `frontend/src/app.css` defines design tokens on `:root` only. There
is one theme, and the score is hard-coded to a white "paper" surface.

**Design.**

*Theme plumbing*
- Tokens move to `:root` (light) plus `[data-theme='dark']` overrides.
- Three-way preference: `system | light | dark`, stored in `localStorage`
  alongside the existing latency value (same pattern as `state.svelte.ts`).
- `data-theme` is applied by a **tiny inline script in `index.html`** before
  first paint, so there is no flash of the wrong theme.
- `prefers-color-scheme` is honoured live while the preference is `system`.

*The score*
OSMD supports this natively, so no hack is needed:

- `darkMode: true` — documented as "black background, white notes"; it sets
  `defaultColorMusic` and `EngravingRules.PageBackgroundColor`.
- Fine-grained alternatives exist if we want a softer inversion:
  `defaultColorMusic`, `defaultColorNotehead`, `defaultColorStem`,
  `defaultColorRest`, `defaultColorLabel`.
- `defaultColorNotehead` is only honoured **before loading**, so a theme change
  re-renders the current exercise rather than recolouring in place. At ~50 ms
  that is imperceptible.

*Feedback colours*
The current green/red/amber are tuned for white paper and are illegible on
black. Dark variants are required, and the choice is made per-theme at the point
where `ScoreRenderer.colorByExpectedIndex` builds its palette.

*Decision B1 — how far the theme reaches into the notation:*
**Resolved: follow the theme into the notation, user-overridable.** The dark UI
gets a genuinely dark score; a "score: follow theme / always light" toggle covers
people who read better on paper-white. Inverted notation divides pianists, so it
is a preference rather than a mandate.

**Acceptance.**
- Toggle switches theme instantly with no reload and no flash on reload.
- Preference survives a restart; `system` follows the OS live.
- Score re-renders in the new theme; note feedback colours change with it.
- **Measured** contrast: every feedback colour reaches ≥ 3:1 against the score
  background in both themes (WCAG's threshold for graphical objects). Asserted in
  the e2e harness, not eyeballed.
- Both themes captured as e2e screenshots.

**Effort:** M.

---

### What B uncovered

Two pre-existing defects surfaced while making the score theme-aware. Both are
now fixed and covered by tests, but they are worth remembering:

1. **Score feedback colouring had never worked at all.** OSMD's
   `Pitch.getHalfTone()` is not a MIDI number — it returns
   `12 * (MusicXML octave) + fundamental`, exactly one octave below MIDI. So the
   `(measure, hand, pitch)` correlation never matched a single note, every note
   stayed at OSMD's default black, and `setColor` was never reached. It went
   unnoticed because the note strip below the score is coloured independently and
   looked perfect. The e2e now asserts on the *rendered fill* of the notation, so
   the score can no longer be silently uncoloured.
2. **OSMD's `autoResize` wiped per-note colours.** Its resize observer
   re-renders on ordinary layout shifts — such as the results panel appearing —
   and a re-render rebuilds the SVG from scratch. Layout is now ours:
   `autoResize` is off and the renderer re-renders itself when the *width*
   changes, which also lays the groundwork for the fit-to-viewport work in
   Slice C.

A third, smaller one: `darkMode` lightens the music but leaves noteheads at their
own separate default (`defaultColorNotehead`), which produced black noteheads on
a black page. Explicit ink colours are now passed for music, noteheads, stems,
and rests.

---

## C. Layout that scales to longer scores

**Problem.** `SRT_EXERCISE_BARS` is 4 and the UI never offers more. At 8–16 bars
OSMD wraps onto multiple systems. The hard constraint for sight-reading is that
**the player must never scroll or turn a page mid-performance** — looking away
from the music is exactly the failure mode this app exists to train.

**Design principle.** The whole exercise is visible at once, always.

Mechanisms, in the order they should be tried:

1. **Continuous vertical layout.** `pageFormat: 'Endless'` is already OSMD's
   default, so systems stack instead of paginating. Lock this in explicitly so a
   future option change cannot silently introduce page breaks.
2. **Fit-to-viewport zoom.** After `render()`, measure the rendered height and
   set `osmd.Zoom` so the score fits the available box:
   `zoom = clamp(availableHeight / renderedHeight, minZoom, 1)`. Recompute on a
   debounced resize. `osmd.Zoom` is a documented get/set property.
3. **Bound the exercise length by what fits.** If the score still overflows at
   `minZoom` (~0.55), the exercise is too long for the screen. Expose a bar-count
   control (4 / 8 / 12 / 16) and refuse lengths that cannot fit rather than
   silently scrolling.
4. **Sticky transport**, as a fallback for small viewports: the beat indicator
   and note progress pin to the top while the score is the only scrollable
   region.
5. **Focus mode.** A toggle that hides the header, skill chips, and note strip so
   the score owns the full viewport height. Cheap, and the best default for
   actual practice.

**Decision C1 — is exercise length a skill or a preference?**
**Resolved: a user preference.** The user picks 4/8/12/16; `difficulty_elo` stays
purely skill-based and keeps meaning one thing.

Note the honest caveat either way: 8 bars at level 5 *is* harder than 4 bars at
level 5, in stamina and concentration if not in reading. The UI should say so
rather than pretend otherwise.

**Acceptance (met).**
- 4/8/12/16-bar exercises render fully inside the viewport at 1280×800 and
  1440×900, measured in the e2e harness during *play*, which is when scrolling
  would actually hurt.
- Zoom stays within bounds and the fit converges; a resize keeps the score fitted.
- The invariant asserted is: the score is **either fully visible or explicitly
  refused** — never a silent scrollbar.
- Layout is stable, and exactly one SVG is ever rendered.
- Focus mode demonstrably buys room: 16 bars at 1280×600 is refused normally and
  fits once focus mode is on.

**Effort:** M–L.

---

### What C uncovered

Extending the score past one system exposed four defects, all now fixed and
covered by the e2e sweep:

1. **OSMD appends rather than replaces on `render()`.** Calling it twice stacked
   two complete scores, and the container height silently became their sum. Every
   re-render now clears first, and renders are serialized so two overlapping
   calls cannot both draw into the same container.
2. **A scrollbar feedback loop made the layout oscillate.** The score grew, the
   page scrollbar appeared, the width shrank, OSMD re-wrapped onto another
   system, the height changed, the scrollbar disappeared — repeatedly. Fixed with
   `scrollbar-gutter: stable` plus a coarse (24px) width threshold, because
   scrollbars and sub-pixel jitter must not trigger a re-wrap.
3. **A single rescale did not converge.** Shrinking changes how many bars fit per
   system, so height is not linear in zoom; one pass consistently landed above
   budget. The fit now iterates until it converges or reaches `MIN_ZOOM`.
4. **The UI's zoom and "too long" state went stale.** Resize-driven renders
   bypass the caller, so the renderer now reports back after every render.

Also worth recording: the reuse lookup ignored bar count, so a request for 12
bars could be served a stored 4-bar exercise — the same class of bug as the
`target_skill` one found earlier. Filtered and tested.

### Open decision: courtesy time signatures

OSMD prints a courtesy clef at a system break but **not** a courtesy time
signature, and it exposes no engraving rule for one (only a global
`RenderTimeSignatures` on/off). Meter *changes* are rendered correctly, so this
only affects a constant meter spanning several systems.

Two options:

1. **Leave it** *(current behaviour)*. OSMD breaks systems wherever they fit —
   around 9 bars per line at 1280px — which is dense but responsive, and the
   meter is shown at the start and in the UI badge.
2. **Forced phrase breaks + courtesy signatures.** Emit a system break every 4
   bars with an explicit `<time>` there, matching how printed sight-reading
   books are laid out. Predictable and more readable, at the cost of OSMD's
   responsive line breaking: a 4-bar system on a wide window looks sparse, and
   narrow windows must scale further down.

Not chosen unilaterally, because it changes layout policy rather than fixing a
defect. Option 2 is a small change to the generator plus `newSystemFromXML`.

---

## D. Real two-hand material

**Where it stands.** Two hands already appear from `texture >= 3`, and scoring
already reports accuracy per hand. Two things are genuinely wrong.

**Defect 1 — the taxonomy lies.** `hand_position` levels 1 and 2 read "five-finger
position, right hand" and "five-finger position, left hand", but `hand_position`
does not decide which hand plays — `texture` does. A user is shown "hand position
2" as if it meant left-hand work while the left hand may not be playing at all.

*Fix:* re-cut the boundary and rewrite the level descriptions so they are true.
`texture` decides how many voices there are and what each does; `hand_position`
decides position, range, and shifts **within** a hand. Levels 1–2 become about
narrow position and absence of shifts, not about a specific hand. Because level
descriptions are served to the UI from `skills_data.py`, this is a
single-source-of-truth edit plus a test that the two skills no longer overlap in
meaning.

**Defect 2 — no left-hand vocabulary.** `_bass_events` in `generator.py` has five
hard-coded styles (`sustain`, `mirror`, `imitation`, `moving`, `quarters`). This
is why the accompaniment sounds samey, and it is the main thing standing between
"hands together" and music a pianist would recognise.

*Fix:* extract a named, unit-tested **left-hand pattern library**
(`backend/app/music/bass_patterns.py`): sustained roots, root–fifth pulse, waltz
bass (root–chord–chord), Alberti, block chords, broken octaves, walking bass.
Each is a pure function `(bar_length, beat_unit, tonality, base_midi, rng) ->
[events]`, independently testable, selected by texture/level. This replaces
branching inside `_bass_events` with data.

**Decision D1 — what "expand to two hands" means:*
**Resolved: traditional two-staff sight-reading material.**

Concretely, the target is what a graded sight-reading book looks like: a grand
staff where both staves are read together, not a melody with a token bass note.
Two kinds of left hand are wanted, and they are different generator problems:

1. **A free left hand** — an independent line that is genuinely *read* rather
   than predicted. This is the harder half: it needs its own melodic
   generation (its own position window, its own interval profile, its own
   rhythm), not a formula. It is the difference between reading and guessing.
2. **Common patterns** — waltz bass (root–chord–chord), Alberti, canon/imitation
   between the hands, plus the existing sustained roots, root–fifth pulse,
   broken octaves, and walking bass. These are recognisable, learnable idioms,
   and they are exactly what the pattern library in Defect 2 should provide.

Both are selected through `texture`/`hand_position`, and `imitation` already
half-exists in `_bass_events` as a special case — the library generalises it into
a first-class canon pattern with a controllable entry delay.

A per-hand practice mode (practise right alone, left alone, or both, on the same
exercise) stays a separate, later slice: it filters `expected_notes` by hand and
so changes the scoring contract.

**Acceptance (met).**
- No skill description claims to control something it does not.
- Every left-hand figure is unit-tested for exact bar fill, register, and
  diatonicism.
- Generated two-hand exercises round-trip through MusicXML with hands intact.
- Results report per-hand accuracy; the e2e asserts both hands appear.
- e2e: two staves are engraved, the whole performance is captured, every note
  matches by pitch, and both hands score separately.

**Effort:** M–L (mostly generator work plus tests).

---

### What D delivered

**The taxonomy no longer lies.** `texture` describes voicing and names the
accompaniment family; `hand_position` describes reach and movement *within* a
hand rather than claiming to choose which hand plays. Level 1-2 of
`hand_position` used to read "five-finger position, right/left hand" while the
hand was actually chosen by `texture`.

**A module split.** The generator was doing six jobs. It is now orchestration
over `music/events.py`, `music/tonality.py`, `music/melody.py`,
`music/harmony.py`, and `music/bass_patterns.py`.

**A real left-hand vocabulary — 18 figures**, replacing five hard-coded styles:

| Family | Figures |
| --- | --- |
| Sustained | sustained root, sustained root-and-fifth, block chords |
| Pulse | root-fifth pulse, march bass, waltz bass, stride bass, tenths |
| Broken chord | Alberti, compound broken chords (6/8), broken chord, wide arpeggio, broken octaves |
| Independent | walking bass, free left-hand line, countermelody, canon |
| Shared | hands in similar rhythm |

Selected by meter and texture level, one figure per exercise, restricted to
figures that suit *every* bar so a waltz bass is never asked to play in 4/4.
Every figure is unit-tested for exact bar fill, register, diatonicism,
determinism, and behaviour across remote keys — 127 tests.

**Harmony.** Patterns need something to outline, so a small diatonic progression
engine supplies a chord per bar (I-V at level 1, through to vi/ii and inversions
at level 9-10), always cadencing onto the dominant then the tonic. When both
hands play, the melody's downbeats are anchored to a chord tone; a solo line is
left free, since it has nothing to clash with.

### Four more defects D uncovered

1. **Exercise reuse matched too loosely — twice more.** It keyed on the target
   skill alone, so a plan calling for two hands could be served a stored
   right-hand-alone exercise; and it ignored bar count. It now pins the full
   level profile, the focus, the length, and the source.
2. **Reuse made the trainer a memory test.** Once a profile had a handful of
   exercises it cycled them forever. It now prefers genuinely unplayed material
   up to a per-profile cap, which is the difference between sight-reading and
   recall.
3. **The difficulty ceiling swallowed real capability.** Capping every dimension
   at `target + 1` meant a player strong at texture but weak at accidentals was
   held at left-hand-alone and could never be given two hands at all. The
   allowance is now `+3`, which still stops one runaway dimension dominating.
4. **The metronome was wrong in every compound meter.** It was handed
   seconds-per-*quarter* and treated it as seconds-per-*beat*; those coincide
   only when the beat is a quarter, so 6/8, 9/8, 12/8, 2/2 and 3/8 all clicked at
   the wrong rate, counted in wrongly, and — worst — ended the run early, silently
   truncating the performance. In 12/8 it dropped a quarter of the notes. The
   metronome now schedules from real notated beat units per bar, which also makes
   mixed meter correct.

---

## E. Workouts — the missing daily loop

**Problem.** The original design calls for a 5–10 minute daily session of 5–10
exercises. Only single exercises exist. `SRT_SESSION_LENGTH` is configured and
never read, and the "streak" is counted from *any* single attempt, which makes it
a weak signal.

**Naming.** This is a **workout**, not a session. `practice-logger` already owns
the word "session" for a different object — a continuous stretch at the piano
inferred from silence. The two are not the same thing and must not share a name
in any schema, API or document. See
[`INTEGRATION-practice-logger.md`](./INTEGRATION-practice-logger.md) §2:

| Term | Owner | Meaning |
| --- | --- | --- |
| **sitting** | practice-logger (`practice_sessions`) | continuous stretch at the piano, emergent from silence |
| **workout** | this app | a deliberate, bounded set of exercises |
| **segment** | practice-logger | one piece — or one workout — within a sitting |

The player-facing UI may say "session"; everything else says workout.

**Design.**
- `workouts` table: `id, user_id, mode, target_count, started_at, finished_at`.
  `performances` gains a nullable `workout_id`.
- `POST /api/workout/start`, `GET /api/workout/current`,
  `POST /api/workout/{id}/finish`, `GET /api/workout/{id}`.
- Exercise selection is unchanged — a workout is a container, not a new adaptive
  mechanism. The Elo engine is untouched.
- **Summary screen**: score trend across the workout, which skills moved and by
  how much, the weakest moment, and what the next workout will target. This is
  the payoff screen the app lacks today; right now practice just trails off.
- Streak redefined as *days with a completed workout*, keeping the attempts-based
  number in the payload as a secondary stat so nothing changes meaning silently.

**Integration touchpoints.** Designed now, so E does not have to be reworked when
the merge lands:

- Each completed attempt is posted to `practice-logger`'s ingest with
  `source='sight_reading'`, so a workout shows up as one segment of one sitting
  (integration Stage 2). Posting is fire-and-forget and must never block scoring.
- `workouts.practice_session_id` is a nullable integer recorded for
  cross-reference. It is **not** a foreign key while the two apps live in
  different files, and must be documented as such. It becomes a real FK if the
  tables move into `piano.db` (integration Stage 5).
- `SRT_SESSION_LENGTH` is renamed `SRT_WORKOUT_LENGTH`, because it finally has a
  reader.

**Acceptance.**
- A workout can be started, played through, and finished; a partial workout
  survives a page reload and can be resumed.
- `performances.workout_id` is populated for workout attempts and null otherwise.
- Summary numbers reconcile with the underlying performances.
- Streak counts completed workouts; existing stats tests updated with the reason
  recorded.
- With `practice-logger` running, a workout produces one `practice_sessions` row
  with `source='sight_reading'`; with it stopped, scoring is unaffected and the
  batch is delivered later.

**Depends on:** integration decision I2 (reuse their `POST /api/events`) for the
last acceptance point only while the two apps are still separate. If the
ecosystem merge happens first, that point becomes an internal call and the
dependency disappears.

**Effort:** M.

---

## F. Musical depth

Ordered by value per unit of effort.

**F1. Hear your performance** *(S–M, recommended as the first of these)*
Play the recorded MIDI back over the metronome so you can hear what you actually
played. The notes are already stored per performance (`played_notes_json`) and
Tone.js is already a dependency. High perceived value, small change, and it makes
the "wrong note" list meaningful by ear.

**F2. Sustain pedal awareness** *(S)*
`MidiInput` already parses CC64 and nothing consumes it. Realistic use: stop
penalising re-struck or overlapping notes as "extra" when the pedal is down, so
pedalled playing is not scored as an error. A pedal *skill* is a later question.

**F3. Slow-down and loop** *(L)*
Scale the exercise tempo to 60/80/100% and loop a single bar or phrase. The
highest-value practice feature here, but it touches the timing model, so it needs
its own design pass.

**F4. Curated exercise library** *(M)*
`exercises.source` already supports `'curated'`; the selector already filters on
`source`. Needs an importer that tags MusicXML with skill levels. Lets real
repertoire fragments in without touching the API.

**F5. Error heatmap by measure** *(S)*
"Bar 3 catches you every time." Cheap extension of `common_mistakes`, which
already parses per-note feedback with measure numbers.

---

## G. The piano ecosystem

This slice grew: it is no longer "deploy the trainer" but "become the app that
owns the whole practice picture". See
[`ECOSYSTEM.md`](./ECOSYSTEM.md) for the target architecture, the staged
migration, and the decisions.

In one line: **one Python + Svelte app, one SQLite database, one host — running
on the piano machine, because Web MIDI needs a secure context and
`http://<lan-ip>` is not one.**

The three domains become packages in one app rather than three programs sharing
a file:

| Domain | Source | Becomes |
| --- | --- | --- |
| Repertoire | `piano-progress` (Rust, 2,195 lines) | `app/repertoire/` — composers, pieces, journal, media |
| Practice log | `practice-logger` | `app/practice/` — ported, tests included |
| Sight-reading | this repo | stays where it is |

Later, and only if the app earns it: multi-user, PostgreSQL (the SQL is ANSI
apart from `AUTOINCREMENT`), Bayesian Knowledge Tracing in place of Elo.

---

## Small quality-of-life (fold into whichever slice touches the area)

- Count-in length: 1 bar / 2 bars / none.
- Hands-free start: begin on first note, or trigger from the sustain pedal.
- Metronome: subdivision clicks, accent control, volume.
- Keyboard shortcuts (space to start/stop).
- Persist the practice/performance mode choice.
- Accessibility: keyboard navigation, `aria-live` for results,
  `prefers-reduced-motion` for the beat pulse.

---

## Verification additions

The e2e harness needs three upgrades to carry these slices honestly:

1. **Multiple viewports** — run the layout assertions at 1280×800 and 1440×900.
2. **Theme sweep** — screenshot and measure contrast in both themes.
3. **Computed-style assertions** — for contrast and for "no scroll during play",
   measure real geometry and colours rather than asserting on class names.

Everything else about the harness stays: the injected fake Web MIDI device
exercises the real input path, and a profile reset at the start keeps runs
deterministic.

**All three landed** during slices B, C and the phase work that followed. The
verification surface has since outgrown this section: what the suite must cover,
which tier a change owes, and how a new check is proven able to fail are owned by
[`TEST-STRATEGY.md`](./TEST-STRATEGY.md).

---

## Explicit non-goals

- Social features, leaderboards, sharing.
- Mobile/touch layout. Web MIDI on mobile is unreliable and the target is a real
  piano.
- Ear training, theory drills, or anything not driven by reading notation at the
  keyboard.
- Replacing Elo before a session model exists to attach better data to.

---

## Decisions

| ID | Question | Decision |
| --- | --- | --- |
| B1 | How far does dark mode reach into the notation? | Follow the theme, user-overridable via a "score paper" setting |
| C1 | Is exercise length a preference or part of difficulty? | User preference (4/8/12/16); difficulty stays skill-based |
| D1 | What does "expand to two hands" mean? | Traditional two-staff material: a free, genuinely-read left hand *and* named common patterns (waltz, Alberti, canon). Per-hand practice deferred to its own slice |
| — | Approved for the current round | A + B |
