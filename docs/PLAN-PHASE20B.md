# Plan — Phase 20b: the piano-side toolkit

**Parent spec:** [`ECOSYSTEM.md`](./ECOSYSTEM.md) § *Phase 20* § *20b — the piano-side toolkit
(G2, G3, G4, G6)*, with decisions 20-D5 and 20b-D1…D6 below. That section owns what and why;
this document owns the how.

**Status: landed.** Two deviations, recorded in `AGENT-LOG.md` (2026-09-17): the plan was written
before audio capture existed and named one hands-free action, so the mapping it sketches below — CC66
and CC67 toggling a *workout*, the damper double tap arming *capture* — was settled the other way
at the user's request after 20e landed, and then narrowed again when the user pointed out that they
play the soft pedal. The code is the authority: **the sostenuto (CC66) alone arms and stops capture,
the soft pedal (CC67) is bound to nothing because it is played, and the damper's silent double tap
toggles a workout.** The unit tests in Step 1.1 and the module in Step 1.3 show the superseded
mapping; everything else (discovery, the silence gate, `onController` being read-only) landed as
written.

**Superseded in part by Phase 23** (`PLAN-PHASE23.md`), which keeps the pedal and the discovery rule
but replaces the one-action mapping with three configurable gestures on CC66: a single press flags a
place for review, a double press starts or finishes a workout, and a press and hold arms or stops the
take — so take recording is no longer on the single press, and the damper carries nothing at all (its
double tap retired earlier, on the same day, for firing mid-phrase). Read the paragraphs above as the
state after 20b, not as the current behaviour; `docs/FEATURES.md` § 2 is the current one.

**Goal.** Make the app usable from the bench without reaching for the computer: the sostenuto
pedal becomes a hands-free switch **after** the app has observed that the piano sends it, the
count-in becomes a choice, a piece or a sitting becomes a link you can open on the other machine,
and the keyboard gets a way through the app.

**Architecture.** Four independent additions, each with its pure decision extracted so it is
testable under `node --test` and its wiring thin enough to be covered by the browser tier:

| Concern | Pure module (new) | Wiring |
| --- | --- | --- |
| Pedal gesture | `frontend/src/lib/pedalGesture.ts` | `midi.ts` controller stream → `state.svelte.ts` action dispatch |
| Count-in | `frontend/src/lib/countIn.ts` | `state.svelte.ts` preference → `PracticeView`/`CalibrationView` |
| Routing | `frontend/src/lib/route.ts` | `state.svelte.ts` + `App.svelte` → the three views that own a selection |
| Palette | — (a component) | `CommandPalette.svelte` over the two search endpoints that exist |

**Tech stack.** Svelte 5 (runes) + TypeScript, `node --test` for frontend units, pytest and
Playwright for the server and browser tiers.

**Baseline / authority refs.**

- `docs/ECOSYSTEM.md` § Phase 20 § 20b, and 20-D5 (the pedal is discovered, never assumed).
- `docs/TEST-STRATEGY.md` §2, §3, §8 (the standing rule) and §4 Slice 6 (frontend depth: extract
  the pure decision rather than testing through Tone).
- `docs/PLAN-PHASE20A.md` (the sibling slice: what a falsification costs, and how the tier is run).
- `AGENT-LOG.md` § *Rules*.

**Compatibility boundary.** No server route, table, column or wire format changes at all. All four
additions are client-side; `BACKUP_VERSION`, `SCHEMA_VERSION` and the API contract are untouched.
Two behaviour changes are deliberate and named: the count-in default stays one bar, and the
practice log's pedal stream keeps carrying **CC64 only**.

```text
TDD Route:
- Mode: auto
- Decision: strict
- Strict authority: docs/TEST-STRATEGY.md §8 ("a slice is not done until check.sh --full passes,
  and no assertion is trusted until it has been seen to fail"), the standing rule PLAN-SLICE1.md
  already recorded as user-approved
- Strict signals: a public behaviour change (a pedal gesture that starts a workout, a mount-time
  URL read), a shared consumer (`state.svelte.ts` is read by every view), and a new
  producer/consumer pair (the controller stream and the recogniser)
- Light eligibility: not applicable; nothing here is a single-owner edit with no behaviour change
- Test posture: strict RED first for the three pure modules; for the wiring, a break applied and
  the named browser assertion watched to fail, then restored
- Verification: ./check.sh --fast after every task; ./check.sh --full before the slice is done
```

```text
BaselineUsageDraft:
- Required baseline refs: ECOSYSTEM.md § 20b + 20-D5; TEST-STRATEGY.md §8; PLAN-PHASE20A.md
- Delivered context refs: the read-only reconnaissance of the shell, midi.ts, metronome.ts and the
  e2e harness quoted throughout this plan
- Acknowledged before plan refs: 20b's four acceptance bullets in ECOSYSTEM.md
- Cited in plan refs: ECOSYSTEM.md, TEST-STRATEGY.md, PLAN-PHASE20A.md, AGENT-LOG.md
- Missing refs: none
- Decision: continue
```

```text
Requirement Ready Check:
- Requirement source refs: docs/ECOSYSTEM.md § Phase 20 § 20b (approved with the phase)
- Goals and scope refs: the same section's Problem/Design
- User / scenario refs: the player sitting down with both hands on the keys; the LAN viewer
  opening a link to a piece on the laptop; a player who wants two bars of count-in in 6/8
- Requirement item refs: discovery, the gesture, count-in bars, click volume, URLs, palette,
  shortcuts
- Acceptance / verification criteria refs: 20b's five acceptance bullets
- Open blocker questions: none
- Decision: ready
```

```text
Change Necessity:
- User-visible need: every action in the app needs a hand that is supposed to be on the keys, and
  a piece cannot be linked to from another machine
- No-change / non-code option: insufficient — config cannot bind a controller message, cannot add
  a URL, and cannot make the count-in a choice
- Why code change is necessary: the controller path does not exist in the client at all (CC66 is
  dropped in `midi.ts` before any handler), and no hash/history code exists anywhere
- Minimum change boundary: frontend only — midi.ts, state.svelte.ts, metronome.ts, App.svelte,
  DeviceBar.svelte, PracticeView.svelte, CalibrationView.svelte, RepertoireView.svelte,
  PracticeLogView.svelte, StatsView.svelte, app.css, and four new modules
- Decision: code-change
```

```text
Existence Check:
- Proposed new surface: `onController` on MidiInput; `pedalGesture.ts`; `countIn.ts`; `route.ts`;
  `CommandPalette.svelte`; `app.seenControllers`; `app.exerciseActive`
- Existing owner / reuse candidate: `midi.ts` already owns the device stream and has
  `onPedalMonitor`; `state.svelte.ts` already owns preferences, the MIDI wiring block and
  `player`; `Metronome` already owns `countInBeats`; `App.svelte` already owns the view switch
- Why existing surface is insufficient: `onPedalMonitor` delivers CC64 **only** and feeds the
  practice log's `pedal_events`, which has no controller column — widening it would record the
  sostenuto as sustain; no component owns a URL today; `countInBeats` is derived inline in two
  components from a barrier rather than from a preference
- Creation proof: 20b's acceptance bullets cannot be met without a controller stream, a preference,
  a URL and an overlay; each is one small module with an existing owner beside it
- Entropy / retirement impact: the palette is the first overlay in the app and the only new
  component; `route.ts` keeps navigation logic out of every view; if the gesture proves annoying,
  deleting the `handleController` body leaves the discovery readout and the log untouched
- Decision: add-with-proof for the four modules; reuse-existing for the preference, the metronome
  field and the view switch
```

```text
Architecture Integrity Lens:
- Invariant: the practice log's `pedal_events` keeps meaning CC64 exactly as it does today; a
  gesture never fires during a scored attempt; typing never triggers a shortcut
- Canonical owner / contract: `midi.ts` decodes, `pedalGesture.ts` decides, `state.svelte.ts`
  acts; `route.ts` parses and serialises, the store holds the route, the view that owns a selection
  consumes it; `sceneControllers` is a report, not consent
- Responsibility overlap: none added — the new controller stream is read-only and separate from
  the pedal-log stream, and the route does not become a second source of truth for what is on
  screen (20b-D2)
- Higher-level simplification: hash routing instead of path routing removes any need for a server
  catch-all or a router dependency (20b-D1)
- Retirement / falsifier: if `CommandPalette` is never opened, it is one component and one CSS
  block to delete; if the gesture misfires, `HANDSFREE_CONTROLLERS` is one constant
- Verdict: proceed
```

```text
Complexity Budget:
- Artifact class: maintained client source; three large components gain code
- Target files / artifacts: state.svelte.ts (582 lines), App.svelte (~90), DeviceBar.svelte (296),
  PracticeView.svelte (large), RepertoireView.svelte (~1100), PracticeLogView.svelte (743)
- Current pressure: RepertoireView and PracticeLogView are the two largest components and each
  gains a small effect; state.svelte.ts is the shared store and gains the most
- Projected: state.svelte.ts +~90 lines, App.svelte +~35, DeviceBar +~30, each view +~12,
  four new modules ~60 lines each, CommandPalette ~180
- Budget result: at-risk (state.svelte.ts is the single hot spot)
- Planned governance: every pure decision goes to its own module, so the store gains dispatch and
  preferences only; the palette is one new component rather than additions to App.svelte

Plan-Time Complexity Check:
- Target files: frontend/src/lib/state.svelte.ts, frontend/src/App.svelte
- Existing size / shape signals: state.svelte.ts already mixes preferences, MIDI wiring, capture,
  workouts and playback; App.svelte is small and shell-shaped
- Owner fit: the route and the shortcut bus are shell concerns (App.svelte + the store's own
  fields); the recogniser is not
- Add-in-place risk: putting gesture recognition in the store would bury a pure decision in the
  largest file
- Better file boundary: `pedalGesture.ts`, `countIn.ts`, `route.ts`; store keeps state and dispatch
- Recommendation: extract helper, then edit-in-place
```

```text
Plan Pressure Test:
- Owner / contract / retirement: no server contract touched; the palette and the gesture both have
  a named deletion trigger; the route has one owner (`route.ts`) and one holder (the store)
- Architecture integrity / higher-level path: hash routing is the higher-level simplification
  (no server work), and the pure-module split keeps the store from absorbing four jobs
- Verification scope: three new pure modules with unit tests, four committed break scripts, one new
  browser scenario, and the full tier
- Task executability: every step names a file, complete code and an exact command
- Pressure result: proceed
```

---

## Files

**Create**

| Path | Why |
| --- | --- |
| `frontend/src/lib/pedalGesture.ts` | The gesture, as a pure decision over controller moves |
| `frontend/src/lib/pedalGesture.test.ts` | Discovery, the dedicated-pedal press, the CC64 fallback |
| `frontend/src/lib/countIn.ts` | Bars → beats, which is meter-dependent |
| `frontend/src/lib/countIn.test.ts` | The conversion, including 6/8 |
| `frontend/src/lib/route.ts` | Parse and serialise `#/…` |
| `frontend/src/lib/route.test.ts` | Total parsing, and that a round trip is stable |
| `frontend/src/components/CommandPalette.svelte` | The first overlay in the app |
| `backend/tools/falsifications/drop_handsfree_silence_gate.sh` | Break the CC64 fallback's gate |
| `backend/tools/falsifications/drop_controller_stream.sh` | Break the controller stream |
| `backend/tools/falsifications/misroute_a_piece.sh` | Break the piece URL |
| `backend/tools/falsifications/ignore_count_in_preference.sh` | Break the count-in choice |

**Modify**

| Path | Change |
| --- | --- |
| `frontend/src/lib/midi.ts` | A `MonitorController` type, `controllerHandlers`, `onController`, and one emit site |
| `frontend/src/lib/state.svelte.ts` | Route, `navigate`/`reflect`/`syncFromHash`, `seenControllers`, `exerciseActive`, `handleController`, count-in and volume preferences, `requestShortcut` |
| `frontend/src/lib/metronome.ts` | Click volume on `MetronomePlan` |
| `frontend/src/App.svelte` | `svelte:window` keydown + hashchange, the palette, `navigate` for tabs |
| `frontend/src/components/DeviceBar.svelte` | The pedal-discovery readout, count-in and click-volume controls |
| `frontend/src/components/PracticeView.svelte` | Count-in from the preference, `exerciseActive`, the shortcut request |
| `frontend/src/components/CalibrationView.svelte` | Count-in from the preference, `exerciseActive` |
| `frontend/src/components/RepertoireView.svelte` | `reflect` on open, consume a deep-linked piece |
| `frontend/src/components/PracticeLogView.svelte` | `reflect` on select, consume a deep-linked sitting |
| `frontend/src/components/StatsView.svelte` | `reflect` on open, consume a deep-linked attempt |
| `frontend/src/app.css` | The palette overlay |
| `backend/tools/e2e_browser.py` | A `scenario_bench` for pedals, count-in, URLs and the palette |
| `README.md`, `AGENT-LOG.md`, `docs/ECOSYSTEM.md` | What the player can see; the log entry; the phase index |

---

## Precondition — re-read gate

This plan was written against the tree at `df53a14`…`b37e044` (Phase 20a) plus the split/merge
correction. Before Task 1, confirm the anchors still hold:

```bash
cd /home/marco_normal/tmp/SighRTracker
grep -n "if (status === 0xb0 && first === 64)" frontend/src/lib/midi.ts
grep -n "countInBeats = barsBeats\[0\] ?? 4" frontend/src/components/*.svelte
grep -n "view = \$state<AppView>" frontend/src/lib/state.svelte.ts
git status --porcelain   # must print nothing before any falsification
```

If a line has moved, adjust the edit anchors below rather than editing around it. `falsify.sh`
refuses a dirty tree and reverts with `git checkout -- .`.

---

## Task 1 — the controller stream, and the gesture as a pure decision

**Files.** create `frontend/src/lib/pedalGesture.ts`, `frontend/src/lib/pedalGesture.test.ts`;
modify `frontend/src/lib/midi.ts`.

**Why.** The app reads CC64 and **drops every other controller** (`midi.ts:526`), so the sostenuto
pedal cannot be bound to anything today. This task adds the raw stream and the decision that reads
it, without touching what the practice log records.

**Change Necessity.** Code: there is no path from CC66 to any handler, and a gesture recogniser
cannot be expressed as configuration.

**Impact / Compatibility.** Additive on `MidiInput` (a new handler set and registration method).
The existing `sustainHandlers` and `pedalHandlers` keep receiving CC64 exactly as before — the
`pedal_events` contract is unchanged, which is deliberate: that table has no controller column, so
routing CC66 into it would record the sostenuto as sustain and corrupt `pedal_basis` and the blur
figures.

**Decision 20b-D4, stated because it is the sharp edge of this task.** `onController` is a second,
read-only stream. `onPedalMonitor` remains the only thing the practice log consumes, and it stays
CC64-only. A reviewer should check exactly that.

### Step 1.1 — write the failing units

Create `frontend/src/lib/pedalGesture.test.ts`:

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { PedalGesture, type ControllerMove } from './pedalGesture.ts';

function move(controller: number, value: number, epochMs: number): ControllerMove {
  return { controller, value, epochMs, channel: 0 };
}

test('every controller number seen is reported, whatever it is', () => {
  const gesture = new PedalGesture();
  gesture.accept(move(1, 127, 0), null);
  gesture.accept(move(66, 127, 10), null);
  gesture.accept(move(64, 0, 20), null);
  assert.deepEqual([...gesture.seen].sort((a, b) => a - b), [1, 64, 66]);
});

test('a press and release of the sostenuto is the gesture', () => {
  const gesture = new PedalGesture();
  assert.equal(gesture.accept(move(66, 127, 1_000), null), null, 'down is not the gesture');
  assert.equal(gesture.accept(move(66, 0, 1_050), null), 'toggle_workout');
});

test('the soft pedal works the same way, as the second choice', () => {
  const gesture = new PedalGesture();
  gesture.accept(move(67, 127, 1_000), null);
  assert.equal(gesture.accept(move(67, 0, 1_100), null), 'toggle_workout');
});

test('a controller nobody bound does nothing, even with a full press', () => {
  const gesture = new PedalGesture();
  gesture.accept(move(11, 127, 1_000), null);
  assert.equal(gesture.accept(move(11, 0, 1_100), null), null);
  assert.equal(gesture.seen.has(11), true, 'but it is still reported as seen');
});

test('the sustain pedal needs two taps, and only in silence', () => {
  const quiet = new PedalGesture();
  quiet.accept(move(64, 127, 10_000), 1_000);
  assert.equal(quiet.accept(move(64, 0, 10_100), 1_000), null, 'one tap is not a gesture');
  quiet.accept(move(64, 127, 10_300), 1_000);
  assert.equal(quiet.accept(move(64, 0, 10_400), 1_000), 'toggle_workout');

  const playing = new PedalGesture();
  playing.accept(move(64, 127, 10_000), 9_900);
  assert.equal(playing.accept(move(64, 0, 10_100), 10_050), null, 'not while playing');
  playing.accept(move(64, 127, 10_200), 10_150);
  assert.equal(playing.accept(move(64, 0, 10_300), 10_250), null, 'and not on the second either');
});

test('two taps far apart are two taps, not a double tap', () => {
  const gesture = new PedalGesture();
  gesture.accept(move(64, 127, 0), null);
  gesture.accept(move(64, 0, 100), null);
  gesture.accept(move(64, 127, 60_000), null);
  assert.equal(gesture.accept(move(64, 0, 60_100), null), null);
});

test('a release with no press before it is not a gesture', () => {
  const gesture = new PedalGesture();
  assert.equal(gesture.accept(move(66, 0, 500), null), null);
});
```

### Step 1.2 — verify RED

```bash
cd frontend && npm test
```

Expected: failure resolving `./pedalGesture.ts`.

### Step 1.3 — write the module

Create `frontend/src/lib/pedalGesture.ts`:

```ts
/**
 * The sostenuto pedal as a hands-free switch.
 *
 * The PX-870 has three pedals, and the middle one is barely used musically — which is
 * exactly what makes it usable as a control. Nothing here reads musical state: it is
 * handed controller moves and returns an action, so the decision is pure and can be
 * tested without a piano.
 *
 * **Discovery first.** `seen` records every controller number the piano has actually
 * sent, because a gesture bound to a message the instrument never sends is a feature
 * that silently does not exist. The device bar reports `seen`, so "the pedal does
 * nothing" can be answered by looking rather than by guessing.
 */

/** One controller move, on the wall clock like every other MIDI event here. */
export interface ControllerMove {
  /** Absolute time, ms since the Unix epoch. */
  epochMs: number;
  /** The CC number: 64 damper, 66 sostenuto, 67 soft. */
  controller: number;
  value: number;
  channel: number;
}

export type HandsfreeAction = 'toggle_workout';

/**
 * The pedals that are *not* played, in preference order.
 *
 * The damper is deliberately absent: it is used constantly, so a gesture on it would
 * fire during ordinary pedalling. It is supported as a last-resort double tap instead.
 */
export const HANDSFREE_CONTROLLERS: readonly number[] = [66, 67];

/** MIDI's own rule, shared with the sustain path rather than spelled out twice. */
const DOWN = 64;

/** Two damper taps within this window are one deliberate gesture. */
const DOUBLE_TAP_MS = 700;

/** ... and only when nothing has been played for this long. */
const SILENCE_MS = 2_000;

export class PedalGesture {
  /** Every controller number seen so far. A report, never consent. */
  readonly seen = new Set<number>();

  private readonly down = new Map<number, boolean>();
  private lastTapMs: number | null = null;

  /**
   * Feed one controller move; get an action back, or null.
   *
   * `lastNoteMs` is the wall clock of the last note heard, or null when nothing has been
   * played this session. It is consulted **only** for the damper fallback: the other two
   * pedals are not played, so a press on them is unambiguous, while a press on the
   * damper is exactly what playing looks like.
   */
  accept(move: ControllerMove, lastNoteMs: number | null): HandsfreeAction | null {
    this.seen.add(move.controller);
    const isDown = move.value >= DOWN;
    const wasDown = this.down.get(move.controller) ?? false;
    this.down.set(move.controller, isDown);

    if (HANDSFREE_CONTROLLERS.includes(move.controller)) {
      // A dedicated pedal: one deliberate press and release is the whole gesture.
      return wasDown && !isDown ? 'toggle_workout' : null;
    }

    if (move.controller === 64 && wasDown && !isDown) {
      const quiet = lastNoteMs === null || move.epochMs - lastNoteMs >= SILENCE_MS;
      if (!quiet) {
        this.lastTapMs = null;
        return null;
      }
      if (this.lastTapMs !== null && move.epochMs - this.lastTapMs <= DOUBLE_TAP_MS) {
        this.lastTapMs = null;
        return 'toggle_workout';
      }
      this.lastTapMs = move.epochMs;
    }
    return null;
  }
}
```

### Step 1.4 — verify GREEN

```bash
cd frontend && npm test
```

Expected: 83 passing (76 plus the seven new ones).

### Step 1.5 — the controller stream in `midi.ts`

Add the type beside `MonitorPedal` (`midi.ts`, after the `MonitorPedal` interface at `:60-66`):

```ts
/**
 * A controller move on **any** CC number.
 *
 * The sustain path below reads CC64 and nothing else, which is why the sostenuto pedal
 * could not be bound to anything: `handleMessage` dropped every other controller before
 * any handler saw it. This is the raw stream, for callers that decide for themselves
 * what a message means.
 *
 * It is deliberately **not** the stream the practice log consumes. `pedal_events` has no
 * controller column and is read as CC64 by `practice/pedal.py`, so widening that stream
 * would record the sostenuto as sustain and corrupt the blur and basis figures.
 */
export interface MonitorController {
  /** Absolute time, ms since the Unix epoch. */
  epochMs: number;
  /** The CC number. 64 damper, 66 sostenuto, 67 soft. */
  controller: number;
  value: number;
  channel: number;
}
```

Add the handler type beside the other handler aliases (`midi.ts:68-75`):

```ts
type ControllerHandler = (controller: MonitorController) => void;
```

Add the set beside `pedalHandlers` (`midi.ts:124-139`):

```ts
  private controllerHandlers = new Set<ControllerHandler>();
```

Add the registration method beside `onPedalMonitor` (`midi.ts:403-406`):

```ts
  onController(handler: ControllerHandler): () => void {
    this.controllerHandlers.add(handler);
    return () => this.controllerHandlers.delete(handler);
  }
```

Replace the CC64 branch in `handleMessage` (`midi.ts:526-539`) with:

```ts
    if (status === 0xb0) {
      // Every controller is reported on the raw stream first, so a caller can bind a
      // pedal the sustain path has never heard of. Then CC64 keeps its existing two
      // consumers, unchanged: the exercise path's one bit, and the practice log's value.
      const controller: MonitorController = {
        epochMs: this.epochMsFor(this.eventTimeMs(event)),
        controller: first,
        value: second,
        channel,
      };
      this.controllerHandlers.forEach((handler) => handler(controller));

      if (first === 64) {
        // The exercise path wants one bit, and gets it. The practice log wants the
        // time and the raw value too, because a pedal is only interesting as a
        // stretch of time, and a stream of booleans cannot say when it was pressed.
        // The threshold is the MIDI spec's, and is shared with the playback side
        // rather than spelled out again here.
        this.sustainHandlers.forEach((handler) => handler(second >= PEDAL_DOWN));
        const pedal: MonitorPedal = {
          epochMs: controller.epochMs,
          value: second,
          channel,
        };
        this.pedalHandlers.forEach((handler) => handler(pedal));
      }
    }
```

### Step 1.6 — verify GREEN and the typecheck

```bash
cd frontend && npm test && npm run check && npm run build
```

Expected: tests pass, `svelte-check` reports 0 errors, the build succeeds.

### Step 1.7 — falsify the silence gate

Create `backend/tools/falsifications/drop_handsfree_silence_gate.sh`:

```bash
#!/usr/bin/env bash
#
# Break: let the damper double-tap gesture fire while the player is playing.
#
# Without the silence gate, ordinary pedalling can start or finish a workout. The test
# that must catch it is 'the sustain pedal needs two taps, and only in silence' in
# frontend/src/lib/pedalGesture.test.ts.
#
#   ./falsify.sh backend/tools/falsifications/drop_handsfree_silence_gate.sh "cd frontend && npm test"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/pedalGesture.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """      const quiet = lastNoteMs === null || move.epochMs - lastNoteMs >= SILENCE_MS;
      if (!quiet) {
        this.lastTapMs = null;
        return null;
      }
"""
assert needle in text, "the gate is not where this script expects it"
path.write_text(text.replace(needle, "      const quiet = true;\n", 1))
PY
```

```bash
chmod +x backend/tools/falsifications/drop_handsfree_silence_gate.sh
backend/tools/falsify.sh backend/tools/falsifications/drop_handsfree_silence_gate.sh \
  "cd frontend && npm test"
```

Expected: `falsified: the check caught the break`.

---

## Task 2 — discovery readout and the hands-free action

**Files.** modify `frontend/src/lib/state.svelte.ts`, `frontend/src/components/DeviceBar.svelte`,
`frontend/src/components/PracticeView.svelte`, `frontend/src/components/CalibrationView.svelte`.

**Why.** The recogniser decides; something has to act, and the player has to be able to see which
pedals the piano actually sends.

**Change Necessity.** Code: the action dispatch and the discovery report do not exist.

**Impact / Compatibility.** Client-side only. `app.seenControllers` and `app.exerciseActive` are
additive store fields; the DeviceBar panel is additive.

### Step 2.1 — the store fields and dispatch

In `frontend/src/lib/state.svelte.ts`, add to the imports:

```ts
import { PedalGesture, type ControllerMove, type HandsfreeAction } from './pedalGesture';
```

Beside `workout = $state<Workout | null>(null)` (`state.svelte.ts:257`):

```ts
  /**
   * True while a scored attempt is running.
   *
   * The hands-free switch is inert then: the sostenuto pedal is not played, but it *can*
   * be pressed mid-piece, and a gesture that ends a workout in the middle of a run would
   * be worse than no gesture at all. The views that own a run set this.
   */
  exerciseActive = $state(false);

  /** Which controller numbers the connected piano has actually sent. A report. */
  seenControllers = $state<number[]>([]);

  private readonly pedalGesture = new PedalGesture();

  setExerciseActive(active: boolean): void {
    this.exerciseActive = active;
  }

  /** The last note any port has heard, or null. Only the damper fallback consults it. */
  get lastNoteMs(): number | null {
    const heard = this.ports
      .map((port) => port.lastNoteMs)
      .filter((value): value is number => value !== null);
    return heard.length > 0 ? Math.max(...heard) : null;
  }

  /** Feed one controller move to the recogniser, then act on what it decided. */
  handleController(move: ControllerMove): void {
    const action = this.pedalGesture.accept(move, this.lastNoteMs);
    this.seenControllers = [...this.pedalGesture.seen].sort((a, b) => a - b);
    if (action === null || this.exerciseActive) return;
    void this.runHandsfree(action);
  }

  /**
   * What the pedal does.
   *
   * One action today: start a workout, or finish the running one. Arming audio capture is
   * Phase 20e's, and it belongs here when it lands rather than in a second dispatch path.
   */
  async runHandsfree(action: HandsfreeAction): Promise<void> {
    if (action !== 'toggle_workout') return;
    if (this.workout?.running) {
      await this.finishWorkout();
      return;
    }
    await this.startWorkout();
  }
```

In the `connectMidi` wiring block, beside `this.midi.onDevices(...)` (`state.svelte.ts:450-459`):

```ts
      // The raw controller stream: read-only, and separate from the pedal stream the
      // practice log consumes. Registered here because this is where every other MIDI
      // handler is wired, inside the `midiWired` guard.
      this.midi.onController((move) => this.handleController(move));
```

### Step 2.2 — the views report whether a run is in progress

In `frontend/src/components/PracticeView.svelte`, in the function that begins a run (the one
containing `phase = 'countin';` at `:218`), after `phase = 'countin';`:

```ts
    app.setExerciseActive(true);
```

and in every path that ends a run — the function containing the final scoring and the `phase`
assignment for the results panel, plus the stop/abort path:

```ts
    app.setExerciseActive(false);
```

The same two calls in `frontend/src/components/CalibrationView.svelte` (its `phase = 'countin';`
is at `:136`).

Locate the end-of-run paths with:

```bash
grep -n "phase = " frontend/src/components/PracticeView.svelte frontend/src/components/CalibrationView.svelte
```

Every assignment other than `'countin'` and `'playing'` is an end of run and takes
`app.setExerciseActive(false)`. **This is the one step in this plan where the executor must read
the file rather than follow a quoted line**, because the two components have different phase
vocabularies; the rule above is exact even though the line numbers are not.

### Step 2.3 — the discovery readout

In `frontend/src/components/DeviceBar.svelte`, add beside `showPorts` (`:15`):

```ts
  let showPedals = $state(false);

  /** The three pedals a piano may send, and whether this one has. */
  const PEDALS: { cc: number; label: string }[] = [
    { cc: 64, label: 'Damper (right)' },
    { cc: 66, label: 'Sostenuto (middle)' },
    { cc: 67, label: 'Soft (left)' },
  ];

  function pedalState(cc: number): string {
    return app.seenControllers.includes(cc) ? 'sends this' : 'not seen yet';
  }
```

Add a trigger button beside the Ports button (`:90-94`):

```svelte
      {#if app.devices.length > 0}
        <button class="ghost tiny" data-pedals-trigger onclick={() => (showPedals = !showPedals)}>
          Pedals
        </button>
      {/if}
```

Add the panel after the ports list (`:217`):

```svelte
  {#if showPedals}
    <div class="row wrap latency" data-pedals>
      <span class="muted small">
        Press each pedal once. A pedal the piano does not send cannot be bound to anything,
        so this is a report rather than a promise.
      </span>
      {#each PEDALS as pedal (pedal.cc)}
        <span
          class="pill"
          class:good={app.seenControllers.includes(pedal.cc)}
          data-pedal={pedal.cc}
        >
          {pedal.label} · CC{pedal.cc} · {pedalState(pedal.cc)}
        </span>
      {/each}
      {#if app.pedalActionNote}
        <span class="muted small" data-pedal-note>{app.pedalActionNote}</span>
      {/if}
    </div>
  {/if}
```

Add `pedalActionNote` to the store beside `seenControllers`, so the gesture reports itself:

```ts
  /** What the last hands-free action did, for the device bar to show. */
  pedalActionNote = $state<string | null>(null);
```

and set it in `runHandsfree`:

```ts
    if (this.workout?.running) {
      await this.finishWorkout();
      this.pedalActionNote = 'Workout finished from the pedal';
      return;
    }
    await this.startWorkout();
    this.pedalActionNote = 'Workout started from the pedal';
```

### Step 2.4 — verify

```bash
cd frontend && npm test && npm run check && npm run build
```

### Step 2.5 — falsify the controller stream

Create `backend/tools/falsifications/drop_controller_stream.sh`:

```bash
#!/usr/bin/env bash
#
# Break: stop reporting controllers other than CC64.
#
# This is the state before Phase 20b: `handleMessage` saw only the damper, so the
# sostenuto could not be bound. The browser assertion that must catch it is
# "pressing the sostenuto is offered as a pedal the piano sends" in scenario_bench.
#
# The check builds the frontend first: the browser tier serves `frontend/dist`, so a
# source break that is not rebuilt is a break the browser never sees, and the check
# would pass for the wrong reason.
#
#   ./falsify.sh backend/tools/falsifications/drop_controller_stream.sh \
#     "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh bench"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/midi.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """      this.controllerHandlers.forEach((handler) => handler(controller));

"""
assert needle in text, "the emit is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
```

```bash
chmod +x backend/tools/falsifications/drop_controller_stream.sh
```

The falsification is run after Task 6 creates `scenario_bench`:

```bash
backend/tools/falsify.sh backend/tools/falsifications/drop_controller_stream.sh \
  "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh bench"
```

Expected: `falsified: the check caught the break`.

---

## Task 3 — count-in and click volume

**Files.** create `frontend/src/lib/countIn.ts`, `frontend/src/lib/countIn.test.ts`; modify
`frontend/src/lib/state.svelte.ts`, `frontend/src/lib/metronome.ts`,
`frontend/src/components/PracticeView.svelte`, `frontend/src/components/CalibrationView.svelte`,
`frontend/src/components/DeviceBar.svelte`.

**Why.** The count-in is hard-wired to one bar in two places (`barsBeats[0] ?? 4`), and the click
has a fixed `volume: -12` on the synth.

**Change Necessity.** Code: a preference cannot change a value that is derived inline, and the
volume is a literal in the synth constructor.

**Impact / Compatibility.** The default stays one bar, so nothing changes for a player who does
not touch it. `LatencyCalibrator` keeps its own fixed `COUNT_IN = 4` — see 20b-D5.

### Step 3.1 — write the failing units

Create `frontend/src/lib/countIn.test.ts`:

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { COUNT_IN_BARS, countInBeats } from './countIn.ts';

test('the choices are none, one bar and two bars', () => {
  assert.deepEqual([...COUNT_IN_BARS], [0, 1, 2]);
});

test('a bar is however many beats the meter puts in it', () => {
  assert.equal(countInBeats(1, [4]), 4, '4/4');
  assert.equal(countInBeats(2, [4]), 8);
  assert.equal(countInBeats(0, [4]), 0);
  assert.equal(countInBeats(1, [2]), 2, '6/8 counts two dotted-quarter beats in a bar');
  assert.equal(countInBeats(1, [3]), 3, '3/4');
});

test('nonsense reads as no count-in rather than as a negative one', () => {
  assert.equal(countInBeats(-1, [4]), 0);
  assert.equal(countInBeats(1.7, [4]), 4, 'fractional bars truncate');
  assert.equal(countInBeats(1, []), 4, 'and an empty meter falls back to four');
});
```

### Step 3.2 — verify RED

```bash
cd frontend && npm test
```

Expected: failure resolving `./countIn.ts`.

### Step 3.3 — write the module

Create `frontend/src/lib/countIn.ts`:

```ts
/**
 * How many beats of count-in to play.
 *
 * Stored as **bars**, not beats, because a bar is not a fixed number of beats: 6/8 has
 * two dotted-quarter beats and 4/4 has four quarters. Storing beats would make "two bars"
 * mean different things in different meters, which is the same mistake the metronome's
 * `secondsPerQuarter` comment records for the beat unit.
 *
 * Pure, and in its own module rather than in `metronome.ts`, because that file imports
 * Tone and cannot be loaded by `node --test`.
 */

/** The choices offered: none, one bar, two bars. */
export const COUNT_IN_BARS = [0, 1, 2] as const;
export type CountInBars = (typeof COUNT_IN_BARS)[number];

export function countInBeats(bars: number, barsBeats: number[]): number {
  const beatsPerBar = barsBeats[0] ?? 4;
  return Math.max(0, Math.trunc(bars)) * beatsPerBar;
}
```

### Step 3.4 — verify GREEN

```bash
cd frontend && npm test
```

Expected: 86 passing.

### Step 3.5 — the preference

In `frontend/src/lib/state.svelte.ts`, add the key beside the other keys (`:15-19`):

```ts
const COUNT_IN_BARS_STORAGE_KEY = 'srt.countInBars';
const CLICK_VOLUME_STORAGE_KEY = 'srt.clickVolume';
```

Add the readers beside `readBars` (`:25-32`):

```ts
function readCountInBars(): number {
  try {
    const value = Number(localStorage.getItem(COUNT_IN_BARS_STORAGE_KEY));
    return value === 0 || value === 1 || value === 2 ? value : 1;
  } catch {
    return 1;
  }
}

/** Click volume as a MIDI-style controller value, 0..127, so the app has one scale. */
function readClickVolume(): number {
  try {
    const value = Number(localStorage.getItem(CLICK_VOLUME_STORAGE_KEY));
    return Number.isFinite(value) && value >= 0 && value <= 127 ? value : 96;
  } catch {
    return 96;
  }
}
```

Add the fields beside `bars = $state(readBars())` (`:100`):

```ts
  /** Bars of count-in before beat 1: 0, 1 or 2. A preference, never part of a score. */
  countInBars = $state(readCountInBars());

  /** Metronome click volume, 0..127. */
  clickVolume = $state(readClickVolume());
```

Add the setters beside `setBars` (`:327-335`):

```ts
  setCountInBars(value: number): void {
    if (value !== 0 && value !== 1 && value !== 2) return;
    this.countInBars = value;
    try {
      localStorage.setItem(COUNT_IN_BARS_STORAGE_KEY, String(value));
    } catch {
      // Storage may be unavailable (private mode); the in-memory value still works.
    }
  }

  setClickVolume(value: number): void {
    this.clickVolume = Math.max(0, Math.min(127, Math.round(value)));
    try {
      localStorage.setItem(CLICK_VOLUME_STORAGE_KEY, String(this.clickVolume));
    } catch {
      // As above.
    }
  }
```

### Step 3.6 — the metronome's volume

In `frontend/src/lib/metronome.ts`, add to `MetronomePlan` after `countInBeats` (`:48`):

```ts
  /**
   * Click volume, 0..127.
   *
   * On the same scale as a MIDI velocity because the app already has one, and because
   * "60 is quieter than 96" needs no explanation. Absent means the historical default.
   */
  clickVolume?: number;
```

In `unlock()`, replace the literal (`metronome.ts:80`):

```ts
        volume: -12,
```

with:

```ts
        // Held on the instance so a later volume change does not need a new synth.
        volume: toneDbFor(this.plan?.clickVolume ?? DEFAULT_CLICK_VOLUME),
```

and add above the class:

```ts
/** The default click volume, where 96/127 is a comfortable practice click. */
export const DEFAULT_CLICK_VOLUME = 96;

/**
 * A 0..127 controller value as the decibels Tone expects.
 *
 * 127 maps to -6 dB rather than 0: a metronome that can clip is not a metronome. The
 * curve is the square of the fraction, which is approximately how loudness is heard.
 */
export function toneDbFor(value: number): number {
  const fraction = Math.max(0, Math.min(127, value)) / 127;
  return fraction <= 0 ? -Infinity : -6 + 20 * Math.log10(fraction * fraction);
}
```

and in `start(plan)`, before `this.buildSchedule(plan)`:

```ts
    this.plan = plan;
    if (this.synth) this.synth.volume.value = toneDbFor(plan.clickVolume ?? DEFAULT_CLICK_VOLUME);
```

**Note the ordering hazard:** `unlock()` runs on the first user gesture and may happen *after* the
first `start()`, which is why the volume is applied in both places. `this.plan` is assigned before
the volume is read, so the first start already has it.

### Step 3.7 — the call sites

In `frontend/src/components/PracticeView.svelte`, replace the derivation (`:218`) and the start call
(`:229`):

```ts
    const countInBeats = countInBeatsFor(app.countInBars, barsBeats);
```

```ts
    metronome.start({
      barsBeats,
      barBeatUnits,
      secondsPerQuarter,
      countInBeats,
      clickVolume: app.clickVolume,
    });
```

with the import at the top of the script:

```ts
  import { countInBeats as countInBeatsFor } from '../lib/countIn';
```

The same two edits in `frontend/src/components/CalibrationView.svelte` (`:136` and `:144`).

`LatencyCalibrator.svelte` is **deliberately unchanged**: it measures latency against a known
pattern, and making its count-in configurable would silently change what the measurement means.
Its `COUNT_IN = 4` stays.

### Step 3.8 — the count-in the run actually used, made visible

A preference nobody can observe is a preference nobody can verify, and the browser tier cannot
hear the metronome. So the view states the count-in it actually derived, from the same value it
hands the metronome — not from the preference, or the statement could not be wrong.

In the same function in `frontend/src/components/PracticeView.svelte`, right after the derivation
added in Step 3.7:

```ts
    countInBeatsUsed = countInBeats;
```

with the state field declared beside the component's other `$state`:

```ts
  /** The count-in this run actually uses, so the screen states it rather than implying it. */
  let countInBeatsUsed = $state(0);
```

and, in the count-in phase of the markup (the block guarded by the `phase === 'countin'` condition
that already shows the beat pulse):

```svelte
      <span class="pill mono" data-count-in-beats={countInBeatsUsed}>
        {countInBeatsUsed} beats of count-in
      </span>
```

**Why this is in the slice and not merely test scaffolding:** the count-in is invisible otherwise.
A player who set two bars and got four would have no way to notice, and the falsification below
would have nothing to fail against.

### Step 3.9 — the controls

In `frontend/src/components/DeviceBar.svelte`, add beside the Latency button (`:97-99`):

```svelte
    <span class="row sound">
      <label class="muted small" for="count-in">Count-in</label>
      <select
        id="count-in"
        value={app.countInBars}
        onchange={(event) =>
          app.setCountInBars(Number((event.currentTarget as HTMLSelectElement).value))}
      >
        <option value={0}>none</option>
        <option value={1}>1 bar</option>
        <option value={2}>2 bars</option>
      </select>
    </span>

    <span class="row sound">
      <label class="muted small" for="click-volume">Click</label>
      <input
        id="click-volume"
        type="range"
        min="0"
        max="127"
        step="1"
        value={app.clickVolume}
        aria-label="Metronome click volume"
        oninput={(event) =>
          app.setClickVolume(Number((event.currentTarget as HTMLInputElement).value))}
      />
    </span>
```

### Step 3.10 — verify

```bash
cd frontend && npm test && npm run check && npm run build
```

### Step 3.11 — falsify the preference

Create `backend/tools/falsifications/ignore_count_in_preference.sh`:

```bash
#!/usr/bin/env bash
#
# Break: derive the count-in from the meter again, ignoring the preference.
#
# This is the state before Phase 20b. The browser assertion that must catch it is
# "a two-bar count-in is what the metronome plays" in scenario_bench.
#
#   ./falsify.sh backend/tools/falsifications/ignore_count_in_preference.sh \
#     "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh bench"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/PracticeView.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    const countInBeats = countInBeatsFor(app.countInBars, barsBeats);"
assert needle in text, "the derivation is not where this script expects it"
path.write_text(
    text.replace(needle, "    const countInBeats = barsBeats[0] ?? 4;", 1)
)
PY
```

```bash
chmod +x backend/tools/falsifications/ignore_count_in_preference.sh
```

Run after Task 6, with the command above.

---

## Task 4 — hash routes and deep links

**Files.** create `frontend/src/lib/route.ts`, `frontend/src/lib/route.test.ts`; modify
`frontend/src/lib/state.svelte.ts`, `frontend/src/App.svelte`,
`frontend/src/components/RepertoireView.svelte`, `frontend/src/components/PracticeLogView.svelte`,
`frontend/src/components/StatsView.svelte`.

**Why.** Nothing in the app has a URL: every selection is local `$state` and there is no
history/hash code at all, so a piece cannot be linked to from the other machine and the Back button
leaves the app.

**Change Necessity.** Code: no URL surface exists to configure.

**Impact / Compatibility.** The URL changes from absent to describing state. Nothing server-side:
the routes are hashes, so a hard refresh still asks FastAPI for `/` (see 20b-D1).

**Decisions 20b-D1 and 20b-D2.**

- **D1 — hash routes, not path routes.** FastAPI serves the SPA at `/` plus static mounts; a path
  route such as `/piece/12` would 404 on a hard refresh unless the server grew a catch-all, and
  the LAN client pastes URLs. A hash needs zero server change and behaves identically on
  `localhost:8000` and `piano.local:8000`. The cost is cosmetic URLs and no server rendering,
  neither of which this app uses.
- **D2 — the route describes; it does not own.** Local component state stays the source of truth
  for what is displayed. A UI change calls `reflect(route)` to describe itself in the URL; the Back
  button and a pasted link call `syncFromHash()`, which sets a pending entity the owning view
  consumes. Lifting four selections into the store would be a large refactor for no visible gain,
  and `lastWrittenHash` is what stops our own hash write from being replayed as navigation.

### Step 4.1 — write the failing units

Create `frontend/src/lib/route.test.ts`:

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { parseRoute, routeHash, type Route } from './route.ts';

test('a section is a route', () => {
  assert.deepEqual(parseRoute('#/practice'), { name: 'practice' });
  assert.deepEqual(parseRoute('#/log'), { name: 'log' });
  assert.deepEqual(parseRoute('#/repertoire'), { name: 'repertoire' });
});

test('an entity is a route with an id', () => {
  assert.deepEqual(parseRoute('#/repertoire/piece/12'), {
    name: 'repertoire',
    entity: { kind: 'piece', id: 12 },
  });
  assert.deepEqual(parseRoute('#/log/sitting/34'), {
    name: 'log',
    entity: { kind: 'sitting', id: 34 },
  });
  assert.deepEqual(parseRoute('#/stats/attempt/56'), {
    name: 'stats',
    entity: { kind: 'attempt', id: 56 },
  });
});

test('parsing is total: anything unrecognised is null, never a guess', () => {
  for (const bad of ['', '#', '#/', '#/nonsense', '#/repertoire/piece', '#/repertoire/piece/x',
    '#/repertoire/piece/0', '#/log/take/3', '#/repertoire/piece/-1']) {
    assert.equal(parseRoute(bad), null, `${bad} must not parse`);
  }
});

test('an entity attached to the wrong section is refused, not silently moved', () => {
  assert.equal(parseRoute('#/log/piece/12'), null);
  assert.equal(parseRoute('#/stats/sitting/12'), null);
});

test('a round trip is stable', () => {
  const routes: Route[] = [
    { name: 'practice' },
    { name: 'calibrate' },
    { name: 'stats' },
    { name: 'log' },
    { name: 'repertoire' },
    { name: 'repertoire', entity: { kind: 'piece', id: 7 } },
    { name: 'log', entity: { kind: 'sitting', id: 8 } },
    { name: 'stats', entity: { kind: 'attempt', id: 9 } },
  ];
  for (const route of routes) {
    assert.deepEqual(parseRoute(routeHash(route)), route, `${routeHash(route)} did not round trip`);
  }
});
```

### Step 4.2 — verify RED

```bash
cd frontend && npm test
```

Expected: failure resolving `./route.ts`.

### Step 4.3 — write the module

Create `frontend/src/lib/route.ts`:

```ts
/**
 * The address of a screen.
 *
 * **Hashes, not paths.** The API serves this SPA at `/` and its own routes under `/api`;
 * a path route such as `/piece/12` would 404 on a hard refresh unless the server grew a
 * catch-all, and the whole point of this is a link that opens on the other machine —
 * `http://piano.local:8000/#/repertoire/piece/12` needs no server change at all.
 *
 * Parsing is **total**: anything unrecognised returns null so the caller can leave the
 * app where it is rather than guess. An entity that does not belong to its section is
 * refused for the same reason — `#/log/piece/12` is a typo, not a request.
 */
import type { AppView } from './types';

export type EntityKind = 'piece' | 'sitting' | 'attempt';

export interface RouteEntity {
  kind: EntityKind;
  id: number;
}

export interface Route {
  name: AppView;
  entity?: RouteEntity;
}

/** Which entities each section may own. A section that owns none has an empty list. */
const ENTITIES: Record<AppView, EntityKind[]> = {
  practice: [],
  calibrate: [],
  stats: ['attempt'],
  log: ['sitting'],
  repertoire: ['piece'],
};

export function routeHash(route: Route): string {
  const base = `#/${route.name}`;
  return route.entity ? `${base}/${route.entity.kind}/${route.entity.id}` : base;
}

export function parseRoute(hash: string): Route | null {
  if (!hash.startsWith('#/')) return null;
  const parts = hash.slice(2).split('/').filter((part) => part.length > 0);
  if (parts.length === 0) return null;

  const name = parts[0] as AppView;
  if (!(name in ENTITIES)) return null;
  if (parts.length === 1) return { name };

  if (parts.length !== 3) return null;
  const kind = parts[1] as EntityKind;
  if (!ENTITIES[name].includes(kind)) return null;
  const id = Number(parts[2]);
  if (!Number.isInteger(id) || id <= 0) return null;
  return { name, entity: { kind, id } };
}
```

### Step 4.4 — verify GREEN

```bash
cd frontend && npm test
```

Expected: 91 passing.

### Step 4.5 — the store holds the route

In `frontend/src/lib/state.svelte.ts`, add to the imports:

```ts
import { parseRoute, routeHash, type Route, type RouteEntity } from './route';
```

Beside `view = $state<AppView>('practice')` (`:70`):

```ts
  /** The address of what is on screen, and what the URL says. */
  route = $state<Route>({ name: 'practice' });

  /**
   * An entity a `syncFromHash` asked to open, waiting for the view that owns it.
   *
   * One-shot: the view takes it and it is cleared, so a later re-render cannot re-open
   * something the player has since closed.
   */
  pendingEntity = $state<RouteEntity | null>(null);

  /**
   * The last hash this app wrote itself.
   *
   * `location.hash = …` fires `hashchange` asynchronously, so without this the app would
   * treat its own write as a navigation request and re-open what it had just described.
   */
  private lastWrittenHash: string | null = null;
```

Add the methods beside `setBars`:

```ts
  /**
   * Move the app, and say so in the URL.
   *
   * A hash assignment pushes a history entry, which is exactly what makes the Back
   * button work; `replaceState` would break the thing this task exists for.
   */
  navigate(route: Route): void {
    this.route = route;
    this.view = route.name;
    this.pendingEntity = route.entity ?? null;
    if (typeof location === 'undefined') return;
    const hash = routeHash(route);
    if (location.hash === hash) return;
    this.lastWrittenHash = hash;
    location.hash = hash;
  }

  /** Describe state that has already changed, without asking any view to open anything. */
  reflect(route: Route): void {
    this.route = route;
    if (typeof location === 'undefined') return;
    const hash = routeHash(route);
    if (location.hash === hash) return;
    this.lastWrittenHash = hash;
    location.hash = hash;
  }

  /** The URL changed from outside: Back, forward, or a pasted link. */
  syncFromHash(): void {
    if (typeof location === 'undefined') return;
    if (this.lastWrittenHash === location.hash) {
      this.lastWrittenHash = null;
      return;
    }
    const parsed = parseRoute(location.hash);
    if (parsed === null) return;
    this.route = parsed;
    this.view = parsed.name;
    this.pendingEntity = parsed.entity ?? null;
  }

  /**
   * A view takes the entity it was asked to open, exactly once.
   *
   * Returns null when the pending entity belongs to another view or has already been
   * taken, so a view can call it unconditionally from an effect.
   */
  consumeEntity(kind: RouteEntity['kind']): number | null {
    if (this.pendingEntity?.kind !== kind) return null;
    const id = this.pendingEntity.id;
    this.pendingEntity = null;
    return id;
  }
```

Change the six `view` assignments so the URL follows the view. Replace
`this.view = 'repertoire';` in `writeAboutSitting` (`state.svelte.ts:291`) with:

```ts
    this.navigate({ name: 'repertoire' });
```

and the component ones (`App.svelte:50`, `StatsView.svelte:186`, `CalibrationView.svelte:229` and
`:246`, `RepertoireView.svelte:653`) with `app.navigate({ name: '…' })` for the same view.

### Step 4.6 — the shell wires the browser's navigation

In `frontend/src/App.svelte`, add the palette-adjacent state and the window listeners:

```ts
  import CommandPalette from './components/CommandPalette.svelte';
  import { type Route } from './lib/route';

  let paletteOpen = $state(false);

  function go(route: Route): void {
    app.navigate(route);
    paletteOpen = false;
  }

  function onKeydown(event: KeyboardEvent): void { /* Task 5 fills this in */ }

  onMount(() => {
    // A pasted link has to be honoured before the first paint of a view, so this runs
    // with the other boot work rather than in an effect that may fire twice.
    app.syncFromHash();
    void app.bootstrap().then(() => app.startMidi());
  });
```

replacing the existing `onMount(...)` at `App.svelte:24-26`, and add before `</div>`:

```svelte
<svelte:window
  onhashchange={() => app.syncFromHash()}
  onkeydown={onKeydown}
/>

{#if paletteOpen}
  <CommandPalette onclose={() => (paletteOpen = false)} onnavigate={go} />
{/if}
```

and change the tab button to `onclick={() => go({ name: tab.id })}`.

**Task 5 supplies `onKeydown`.** Until then, leave it as a no-op body so `svelte-check` passes.

### Step 4.7 — the three views consume their entity

In `frontend/src/components/RepertoireView.svelte`, add an effect beside the existing
`journalDraft` effect (`:70-79`), and give `open` a way to be called without toggling:

```ts
  /**
   * Open the piece a link asked for, once.
   *
   * `open()` toggles on purpose — clicking an open row closes it — and a deep link must
   * not close what it just opened, so this path says so explicitly.
   */
  $effect(() => {
    const id = app.consumeEntity('piece');
    if (id !== null) void open(id);
  });
```

`open` already returns early when the piece is already open, so calling it for an already-open
piece is idempotent rather than a toggle — check that before relying on it:

```bash
grep -n "async function open" -A 4 frontend/src/components/RepertoireView.svelte
```

If the first line is the toggle (`if (detail?.id === pieceId) { detail = null; return; }`), change
the deep-link effect to set the detail directly instead:

```ts
  $effect(() => {
    const id = app.consumeEntity('piece');
    if (id === null || detail?.id === id) return;
    detailLoading = true;
    void api.repertoire.piece(id)
      .then((next) => (detail = next))
      .finally(() => (detailLoading = false));
  });
```

And make the row click describe itself in the URL — after `onclick={() => void open(piece.id)}` at
`:563`, add the route write:

```svelte
              onclick={() => {
                app.reflect({ name: 'repertoire', entity: { kind: 'piece', id: piece.id } });
                void open(piece.id);
              }}
```

In `frontend/src/components/PracticeLogView.svelte`, the same pattern for a sitting:

```ts
  $effect(() => {
    const id = app.consumeEntity('sitting');
    if (id !== null && id !== selectedId) void select(id);
  });
```

and in `select(id)`, after `selectedId = id;` (`:128`):

```ts
    app.reflect({ name: 'log', entity: { kind: 'sitting', id } });
```

In `frontend/src/components/StatsView.svelte`, the same for an attempt:

```ts
  $effect(() => {
    const id = app.consumeEntity('attempt');
    if (id !== null && id !== attempt?.performance_id) void openAttempt(id);
  });
```

and in `openAttempt(id)`, after the fetch succeeds:

```ts
    app.reflect({ name: 'stats', entity: { kind: 'attempt', id } });
```

### Step 4.8 — verify

```bash
cd frontend && npm test && npm run check && npm run build
```

### Step 4.9 — falsify the piece URL

Create `backend/tools/falsifications/misroute_a_piece.sh`:

```bash
#!/usr/bin/env bash
#
# Break: drop the entity from a repertoire route, so a piece link lands on the tab.
#
# The browser assertion that must catch it is "a piece link opens that piece" in
# scenario_bench.
#
#   ./falsify.sh backend/tools/falsifications/misroute_a_piece.sh \
#     "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh bench"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/route.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "  return route.entity ? `${base}/${route.entity.kind}/${route.entity.id}` : base;"
assert needle in text, "the serialiser is not where this script expects it"
path.write_text(text.replace(needle, "  return base;", 1))
PY
```

```bash
chmod +x backend/tools/falsifications/misroute_a_piece.sh
```

Run after Task 6, with the command above.

---

## Task 5 — shortcuts and the command palette

**Files.** create `frontend/src/components/CommandPalette.svelte`; modify
`frontend/src/App.svelte`, `frontend/src/lib/state.svelte.ts`, `frontend/src/app.css`.

**Why.** There is no global keyboard handler at all (the only window `keydown` starts the audio
context and never reads `event.key`), and finding a piece means clicking through the library.

**Change Necessity.** Code: neither the palette nor a shortcut path exists.

**Impact / Compatibility.** The palette is the app's first overlay, so it introduces Escape,
backdrop dismissal and focus handling — all new, all additive.

### Step 5.1 — the shortcut bus

In `frontend/src/lib/state.svelte.ts`, beside `exerciseActive`:

```ts
  /**
   * A one-shot request from a keyboard shortcut to the view that owns the action.
   *
   * The keyboard and the button must go through the same code, and the store cannot start
   * an exercise itself — the score renderer, the count-in and the note capture all live in
   * the view. So the shortcut asks, and the view answers.
   */
  shortcutRequest = $state<{ name: 'start' | 'stop'; at: number } | null>(null);

  requestShortcut(name: 'start' | 'stop'): void {
    this.shortcutRequest = { name, at: Date.now() };
  }

  /** A view takes the request it handles, exactly once. */
  consumeShortcut(): 'start' | 'stop' | null {
    if (this.shortcutRequest === null) return null;
    const name = this.shortcutRequest.name;
    this.shortcutRequest = null;
    return name;
  }
```

### Step 5.2 — the palette

Create `frontend/src/components/CommandPalette.svelte`:

```svelte
<script lang="ts">
  /**
   * One box over the whole app.
   *
   * It composes searches that already exist — the library (which also matches journal
   * prose) and the journal feed — plus the recent sittings list, which has no search
   * endpoint and is therefore filtered here over the most recent fifty. That is stated
   * rather than hidden: a palette that silently searched only part of the app would be a
   * worse answer than one that says what it searched.
   *
   * It is also the first overlay in the app, so it owns the three things an overlay owes:
   * Escape closes it, a backdrop click closes it, and focus starts in the box.
   */
  import { api } from '../lib/api';
  import type { JournalEntry, PieceSummary, SittingSummary } from '../lib/types';
  import type { Route } from '../lib/route';

  interface Props {
    onclose: () => void;
    onnavigate: (route: Route) => void;
  }

  let { onclose, onnavigate }: Props = $props();

  let query = $state('');
  let pieces = $state<PieceSummary[]>([]);
  let entries = $state<JournalEntry[]>([]);
  let sittings = $state<SittingSummary[]>([]);
  let input = $state<HTMLInputElement | null>(null);
  let searching = $state(false);

  $effect(() => {
    input?.focus();
  });

  $effect(() => {
    const text = query.trim();
    // A one-frame debounce: typing "chopin" is seven requests without it, and the two
    // searches are cheap but not free.
    const handle = setTimeout(() => void search(text), 120);
    return () => clearTimeout(handle);
  });

  async function search(text: string): Promise<void> {
    searching = true;
    try {
      if (text.length === 0) {
        pieces = [];
        entries = [];
        sittings = [];
        return;
      }
      const [found, written, recent] = await Promise.all([
        api.repertoire.pieces({ search: text }),
        api.repertoire.journal({ search: text, limit: 10 }),
        api.practice.sittings(50),
      ]);
      pieces = found.slice(0, 8);
      entries = written.slice(0, 5);
      sittings = recent.filter((sitting) => sitting.local_date.includes(text)).slice(0, 5);
    } finally {
      searching = false;
    }
  }

  function onkeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      onclose();
    }
  }
</script>

<div class="backdrop" role="presentation" onclick={onclose} onkeydown={onkeydown}>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <section
    class="card palette"
    data-palette
    role="dialog"
    aria-modal="true"
    aria-label="Search the library and the log"
    onclick={(event) => event.stopPropagation()}
  >
    <input
      bind:this={input}
      bind:value={query}
      class="query"
      type="search"
      placeholder="Piece, journal word, or a date in a sitting…"
      aria-label="Search"
      onkeydown={onkeydown}
    />

    {#if searching}
      <p class="muted small">Searching…</p>
    {/if}

    {#if pieces.length > 0}
      <h4>Library</h4>
      <ul>
        {#each pieces as piece (piece.id)}
          <li>
            <button onclick={() => onnavigate({ name: 'repertoire', entity: { kind: 'piece', id: piece.id } })}>
              {piece.title}{piece.composer_name ? ` · ${piece.composer_name}` : ''}
            </button>
          </li>
        {/each}
      </ul>
    {/if}

    {#if entries.length > 0}
      <h4>Journal</h4>
      <ul>
        {#each entries as entry (entry.id)}
          <li>
            <button onclick={() => onnavigate({ name: 'repertoire', entity: { kind: 'piece', id: entry.piece_id } })}>
              {entry.entry_date} · {entry.content.slice(0, 60)}
            </button>
          </li>
        {/each}
      </ul>
    {/if}

    {#if sittings.length > 0}
      <h4>Sittings</h4>
      <ul>
        {#each sittings as sitting (sitting.id)}
          <li>
            <button onclick={() => onnavigate({ name: 'log', entity: { kind: 'sitting', id: sitting.id } })}>
              {sitting.local_date} · {Math.round(sitting.duration_s / 60)} min · {sitting.note_count} notes
            </button>
          </li>
        {/each}
      </ul>
    {/if}

    {#if query.trim().length > 0 && !searching && pieces.length + entries.length + sittings.length === 0}
      <p class="muted small">Nothing found. Sittings are searched by date over the most recent fifty.</p>
    {/if}
  </section>
</div>
```

Add to `frontend/src/app.css`:

```css
.backdrop {
  position: fixed;
  inset: 0;
  background: rgb(0 0 0 / 45%);
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding-top: 12vh;
  z-index: 50;
}

.palette {
  width: min(42rem, 92vw);
  max-height: 70vh;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.palette .query {
  width: 100%;
  font-size: 1rem;
  padding: 0.6rem 0.7rem;
}

.palette ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.palette h4 {
  margin: 0.4rem 0 0.1rem;
  font-size: 0.78rem;
  text-transform: uppercase;
  color: var(--muted);
}

.palette li button {
  width: 100%;
  text-align: left;
}
```

### Step 5.3 — the shortcuts

In `frontend/src/App.svelte`, replace the no-op `onKeydown` with:

```ts
  /**
   * Global shortcuts.
   *
   * Three rules, all of which exist because a piano app gets typed into almost never and
   * played into constantly:
   *
   * * a shortcut never fires while a field has focus, so the palette's own box and the
   *   split-position input keep working;
   * * Escape always closes, whatever has focus;
   * * space is a *request* to the view, and is inert during a scored attempt, because the
   *   one thing a stray key must not do is disturb a run.
   */
  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape' && paletteOpen) {
      event.preventDefault();
      paletteOpen = false;
      return;
    }

    const target = event.target as HTMLElement | null;
    const typing =
      target !== null &&
      (target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.tagName === 'SELECT' ||
        target.isContentEditable);
    if (typing) return;

    if (event.key === '/') {
      event.preventDefault();
      paletteOpen = true;
      return;
    }
    if (event.key === 'k' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      paletteOpen = true;
      return;
    }

    const index = Number(event.key);
    if (Number.isInteger(index) && index >= 1 && index <= tabs.length) {
      event.preventDefault();
      go({ name: tabs[index - 1].id });
      return;
    }

    if (event.key === ' ' && app.view === 'practice' && !app.exerciseActive) {
      event.preventDefault();
      app.requestShortcut('start');
    }
  }
```

In `frontend/src/components/PracticeView.svelte`, beside the existing effects:

```ts
  // The keyboard asks; the view answers. Space never reaches here during a run, because
  // the shell checks `app.exerciseActive` before asking.
  $effect(() => {
    const request = app.consumeShortcut();
    if (request === 'start' && phase === 'idle') void start();
    if (request === 'stop') stop();
  });
```

Use whatever the component's start and stop functions are actually called:

```bash
grep -n "function start\|function stop\|async function start" frontend/src/components/PracticeView.svelte
```

If the names differ, use the ones printed. The shape of the effect does not change.

### Step 5.4 — the accessibility the palette owes

The palette sets `role="dialog"`, `aria-modal` and an `aria-label`, focuses its input, and closes
on Escape and on a backdrop click. It does **not** trap focus: the app has no other overlay and a
partial trap is worse than none. That is stated here so it is a decision rather than an oversight,
and `command_palette_focus` is not claimed as a feature.

Add `aria-keyshortcuts` to the two controls that have a shortcut, so the discovery path exists:

```svelte
    <button class="ghost tiny" aria-keyshortcuts="/" onclick={() => (paletteOpen = true)}>
      Search
    </button>
```

### Step 5.5 — verify

```bash
cd frontend && npm test && npm run check && npm run build
```

---

## Task 6 — the browser proves the bench, and the docs record it

**Files.** modify `backend/tools/e2e_browser.py`, `README.md`, `AGENT-LOG.md`,
`docs/ECOSYSTEM.md`.

**Why.** All four additions are wiring, and the browser tier is the only tier that can see
`midi.ts` → store → recogniser, the URL, and the overlay.

**Change Necessity.** Test and documentation only.

### Step 6.1 — the scenario

Add `scenario_bench` to `backend/tools/e2e_browser.py`, and insert it into the tuple in `main()`
after `scenario_practice_log` (`:3153`). It uses the harness's existing `load_first_exercise(page)`
and `start_run(page)` helpers, because starting a run by clicking a button whose label depends on
the profile state is a check that drifts.

```python
def count_in_beats(page) -> int:
    """The count-in the run actually used, from the pill the view draws."""
    return int(page.get_attribute("[data-count-in-beats]", "data-count-in-beats") or "0")


def scenario_bench(browser) -> None:
    print("\n[13] The bench: pedals, count-in, links and the palette")
    clear_practice()
    if not api("/api/repertoire/pieces"):
        seed_library(2)
    pieces = api("/api/repertoire/pieces")
    target = pieces[0]

    page, errors = new_page(browser)
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("text=Sight-Reading Trainer")
    ensure_midi(page)

    # --- nothing is bound to a pedal the piano has not been seen to send ---
    click_button(page, "Pedals")
    page.wait_for_selector("[data-pedals]", timeout=10_000)
    check(
        page.inner_text("[data-pedal='66']").endswith("not seen yet"),
        "the sostenuto reads as unseen before it is pressed",
    )

    def press_sostenuto() -> None:
        # The fake device drives the real decoder: the same path the piano's bytes take.
        page.evaluate("() => window.__fakeMidi.send([0xb0, 66, 127])")
        page.evaluate("() => window.__fakeMidi.send([0xb0, 66, 0])")
        page.wait_for_timeout(700)

    press_sostenuto()
    check(
        "sends this" in page.inner_text("[data-pedal='66']"),
        "pressing the sostenuto is offered as a pedal the piano sends",
    )
    check(api("/api/workout/current") is not None, "and one press starts a workout")
    press_sostenuto()
    check(api("/api/workout/current") is None, "a second press finishes it")

    # --- the gesture is inert during a scored attempt: the failure that matters most ---
    load_first_exercise(page)
    start_run(page)
    press_sostenuto()
    check(
        api("/api/workout/current") is None,
        "and it starts nothing while a run is in progress",
    )

    # --- a link opens the thing it names, and Back comes home ---
    # Navigating abandons the run above, which is why this needs no teardown.
    page.goto(f"{BASE_URL}/#/repertoire/piece/{target['id']}", wait_until="domcontentloaded")
    page.wait_for_selector(".detail-title", timeout=20_000)
    check(
        target["title"] in page.inner_text(".detail"),
        f"a piece link opens that piece ({target['title']})",
    )
    page.go_back()
    page.wait_for_selector("nav.tabs", timeout=10_000)
    check(page.locator(".detail-title").count() == 0, "and Back leaves the piece closed")

    # --- the palette searches what the app can actually search ---
    page.keyboard.press("/")
    page.wait_for_selector("[data-palette]", timeout=5_000)
    page.keyboard.type(target["title"][:6])
    page.wait_for_selector("[data-palette] li button", timeout=10_000)
    check(
        page.locator("[data-palette] li button").count() >= 1,
        "the palette finds a piece by title",
    )
    page.keyboard.press("Escape")
    page.wait_for_selector("[data-palette]", state="detached", timeout=5_000)
    check(True, "and Escape closes it")
    check(not errors, f"no console errors on the bench page ({errors})")

    # --- count-in is a choice in bars, and it reaches the metronome ---
    # A second page, because a run is already in flight on the first and starting another
    # one on top of it is a different test.
    bench, bench_errors = new_page(browser)
    bench.goto(BASE_URL, wait_until="domcontentloaded")
    bench.wait_for_selector("text=Sight-Reading Trainer")
    ensure_midi(bench)
    bench.select_option("#count-in", "2")
    load_first_exercise(bench)
    start_run(bench)
    bench.wait_for_selector("[data-count-in-beats]", timeout=20_000)
    # A fresh profile gets level-1 material, whose meter is 4/4, so two bars is eight
    # beats. If that ever stops holding, assert the *ratio* of a one-bar run to a two-bar
    # run instead: it is meter-independent and catches the same regression.
    check(
        count_in_beats(bench) == 8,
        f"two bars of count-in is what the metronome plays ({count_in_beats(bench)} beats)",
    )
    check(not bench_errors, f"no console errors on the count-in page ({bench_errors})")
```

### Step 6.2 — run the scenario

```bash
cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh bench
```

Expected: every assertion `ok`, ending `All browser scenarios passed.` Then the three deferred
falsifications:

```bash
backend/tools/falsify.sh backend/tools/falsifications/drop_controller_stream.sh \
  "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh bench"
backend/tools/falsify.sh backend/tools/falsifications/ignore_count_in_preference.sh \
  "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh bench"
backend/tools/falsify.sh backend/tools/falsifications/misroute_a_piece.sh \
  "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh bench"
```

Each must print `falsified: the check caught the break`.

### Step 6.3 — docs

`README.md`, under the device-bar section, after the Ports paragraph:

```markdown
**Pedals.** The PX-870 has three, and the middle one (sostenuto) is barely used musically — so it
is available as a hands-free switch. Open **Pedals** in the device bar to see which controller
numbers this piano has actually sent: press each pedal once and the bar reports it. One press and
release of the sostenuto starts a workout, or finishes the running one; the soft pedal works the
same way, and if the piano sends neither, a double tap of the damper in silence does it. The
gesture is inert during a scored attempt, and nothing is ever bound to a message the piano has not
been seen to send. There is a **Count-in** choice (none, 1 bar, 2 bars) and a click volume beside
it; both are remembered.
```

and under Progress/Log, a line about links:

```markdown
**Everything is a link.** The address bar describes what you are looking at —
`#/repertoire/piece/12`, `#/log/sitting/34`, `#/stats/attempt/56` — so a piece can be opened on the
other machine by pasting it, and Back works. Press `/` (or `Ctrl`/`Cmd`+`K`) for a search box over
the library, the journal and recent sittings, and `1`–`5` to switch sections.
```

`AGENT-LOG.md` gains a landed entry following its § *Entry format*, naming: the four additions, the
one decision a reviewer must check (`onController` is read-only and the practice log still sees
CC64 only), the falsifications, and the impact on the other side (client-only; no route, table,
column or wire format changed).

`docs/ECOSYSTEM.md` § 6: change the Phase 20 row to `**20a and 20b landed; 20c–20e planned.**`, and
mark the 20b heading `— landed` with a pointer to this plan.

### Step 6.4 — the full tier and the commit

```bash
./check.sh --full
git add -A frontend/src backend/tools docs README.md AGENT-LOG.md
git commit -m "Phase 20b: the piano-side toolkit"
```

---

## Risks

| Risk | Treatment |
| --- | --- |
| The sostenuto press fires during a run | `app.exerciseActive` is checked before the action, and the browser scenario asserts that a press during a run starts no workout. This is the failure that matters most, so it is asserted rather than reasoned about |
| A piano that sends no CC66 leaves the feature invisible | The Pedals readout says `not seen yet` per number, the soft pedal is the second choice, and the damper double-tap is the third. The docs say the gesture is optional and the rest of the app is unaffected |
| The gesture annoys and the player wants it gone | `HANDSFREE_CONTROLLERS` is one constant and `runHandsfree` is one function; deleting the `handleController` body leaves discovery and the log untouched. No setting is added until somebody asks for one |
| `reflect` and `syncFromHash` fight and the app re-opens what was just closed | `lastWrittenHash` is the guard, and the route unit test plus the browser Back assertion cover the round trip. If it still misbehaves, the pending entity is one-shot by construction |
| The palette's client-side sitting filter looks like a search | The component says in its empty state that sittings are matched by date over the most recent fifty, and the plan records that no sitting search endpoint exists |
| The count-in change alters what latency calibration measures | `LatencyCalibrator` is deliberately untouched and keeps `COUNT_IN = 4`; that is 20b-D5 |

## Retirement

- **Nothing is retired.** All four additions are additive, and the six `view` assignments become
  `navigate` calls that set the same field.
- **`app.seenControllers`** is a report with no consumer but the device bar; if the gesture is
  removed, it stays useful (it is how "the piano is not sending that" is answered).
- **The palette** is one component and one CSS block. If it is never used, deleting both leaves no
  trace.

## ADR / baseline-sync signals

- **20b-D1** (hash routes rather than path routes) is a durable navigation decision with a real
  alternative that was rejected for a stated deployment reason. It is recorded in this plan and
  summarised in `ECOSYSTEM.md` § 20b.
- **20b-D4** (a second, read-only controller stream so the pedal log stays CC64-only) is a
  source-of-truth boundary. It belongs in the same decisions table as 18-D3.
- On completion the baseline-sync question is: *does the practice log still mean CC64 by
  `pedal_events`?* The answer must be yes, and `pedal_basis` unchanged is the evidence.

---

```text
Execution Readiness View:
- Intent Lock: a hands-free sostenuto switch bound only after discovery, a count-in and click
  volume choice, hash links that open the thing they name with a working Back button, and a
  keyboard path through the app
- Scope Fence: in — the four additions, their pure modules, the store fields, the device-bar
  controls, the views' route consumption, the palette, one browser scenario, docs. Out — 20c-20e,
  any change to `pedal_events`, path-based routing, a router dependency, a focus trap, and any
  search endpoint for sittings
- Baseline Lock: ECOSYSTEM.md § 20b + 20-D5; TEST-STRATEGY.md §8; the precondition re-read gate at
  the top of this plan; a clean tree before every falsification
- Approved Behavior: 20b's five acceptance bullets
- Owner / Contract Constraints: midi.ts decodes, pedalGesture.ts decides, state.svelte.ts acts;
  route.ts parses and serialises; the view owning a selection consumes it; `pedal_events` stays
  CC64-only
- Compatibility Boundary: client-only; no route, table, column, wire format, SCHEMA_VERSION or
  BACKUP_VERSION change
- Retirement Boundary: nothing retired; the palette and the gesture each have a named deletion
  trigger
- Task Batches: 1 controller stream + recogniser, 2 discovery + action, 3 count-in + volume,
  4 routes + deep links, 5 shortcuts + palette, 6 browser + docs + commit
- Test Obligations: seven gesture units, three count-in units, five route units, four committed
  break scripts plus three browser falsifications, one new browser scenario
- Review Gates: after Task 2 (the input path is complete) and after Task 6 (--full green)
- Drift / Rewind Rules: if a step needs a server change, a stored setting, or a second source of
  truth for what is on screen, stop and return to the spec
- Evidence Required Before Completion: ./check.sh --full passing; the gesture-inert-during-a-run
  assertion green; all four falsifications reported as "falsified"; the AGENT-LOG entry appended
- Advisory Boundary: method-pack execution guidance only; not GateDecision, PolicySnapshot, or
  completion authority
```

```text
Execution Route:
- Decision: inline
- Evidence: the six tasks are sequential on one file (`state.svelte.ts` is touched by 2, 3, 4 and
  5) and the frontend tier is a single fast command, so parallel writers would conflict for no gain
- Fallback: none needed
- User confirmation required: no
```

**Landed.** `PLAN-PHASE20C.md`, `PLAN-PHASE20D.md` and `PLAN-PHASE20E.md` were written and have all
landed since, completing Phase 20; see `ECOSYSTEM.md` § *Phase 20* and `AGENT-LOG.md` (2026-09-17).
The pedal mapping this plan describes is superseded — see the note above and `PLAN-PHASE23.md`.
