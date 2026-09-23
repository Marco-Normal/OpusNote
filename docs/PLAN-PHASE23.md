# Plan — Phase 23: the pedal as a quick-action surface

**Parent spec:** [`ECOSYSTEM.md`](./ECOSYSTEM.md) § *Phase 23*, which adopts this document as the
how. The *why* is § *The request, and what it collides with* below — the phase exists because the
request as first stated would have re-opened a defect the owner reported in use, and the design's
whole shape is the consequence of taking that seriously rather than routing around it.

**Status:** planned. The design below is approved; the implementation plan is the second half of
this document and is written separately.

**Goal.** Make the one pedal nobody plays into a small, configurable quick-action surface. Today
the sostenuto carries exactly one hard-coded action — one press and release arms take recording,
another stops it — and `HandsfreeAction` is a single-member union with a comment saying a second
action would be a type change the compiler points at. This phase spends that widening: three
*gestures* on the same pedal, each independently bound to one action from a list, chosen in Setup.

The three actions the owner asked for are a **review flag** ("flag the place I have just played, so
I can find it again"), **start/finish a workout**, and **finish the sitting**; take recording stays
on the list because it is what the pedal does today.

---

## The request, and what it collides with

The request was "bind the pedals to a list of quick actions". Read literally, that means binding the
damper and the soft pedal too. Two invariants say no, and both were paid for:

* **A played pedal must never carry a gesture.** The soft pedal was bound to the take gesture in
  20b and unbound the same day, because the owner reported *"I actually do use the soft pedal…
  tapping it will stop the recording."* The damper's double-tap was retired for the same reason: it
  fired in the middle of ordinary pedalling. The damper is the worse case of the two — it is pressed
  constantly, so *even an additive action* (a review flag) would fire throughout normal playing and
  bury the timeline in flags nobody asked for.
* **Nothing is bound to a controller the piano has not been seen to send.** `seenControllers` exists
  so "the pedal does nothing" is answerable by looking.

So the customization this phase ships is **which action each gesture on CC66 carries**, not which
pedal carries a gesture. That is not a compromise: the sostenuto is barely used musically, so
dedicating three gestures to it costs nothing, and it keeps the defect closed.

**A second collision, inside the request.** "A marker on the timeline" named no existing thing. The
only "markers" in the app are A/B loop points on a take, and the only timeline marks are the pedal
blur hairlines. The owner's clarification fixed the meaning: *"like we have pedal blurs, that marks
the moments where that blur occurred … so I hit the sostenuto and it creates a little flag on the
timeline, saying 'you should review near here'."* A review flag is therefore the blur hairline's
shape with a different glyph and a different meaning: a place a person asserted, not a place the
app measured.

---

## Architecture

### The recogniser

`frontend/src/lib/pedalGesture.ts` stays a pure module that is handed controller moves and returns
decisions, so the whole gesture logic is testable without a piano. It grows from one gesture to
three:

| Gesture | What the player does | Bound by default to |
| --- | --- | --- |
| **single** | a press and release shorter than the hold threshold | `mark_review` |
| **double** | two such taps inside the double window | `toggle_workout` |
| **hold** | a press held past the hold threshold, then released | `toggle_audio_capture` |

* `HandsfreeAction` widens from `"toggle_audio_capture"` to four members: `mark_review`,
  `toggle_workout`, `toggle_audio_capture`, `finish_sitting`.
* `PedalGestureKind` is `"single" | "double" | "hold"`; `PedalBindings` maps each kind to an action
  or to `null`.
* `accept(move)` stays pure and returns the fires a move produced; a new `tick(nowMs)` resolves the
  two things that need a clock — a hold threshold reached while the pedal is still down, and a
  single tap whose double window has expired. `tick` returns fires too, so a resolution and a hold
  can never be lost by returning one value.
* A hold is not also a tap: once the hold fires, the release is consumed.
* `HANDSFREE_CONTROLLERS` stays `[66]`. Only CC66 is read, so no played pedal can carry anything.

**One property makes the deferral harmless, and it is load-bearing.** When `single` and `double` are
both bound, a single tap cannot be recognised at the moment of release — the recogniser must wait out
the double window. That wait costs nothing because **a fire carries the press's `epochMs`, not the
time it fired**. A flag stamped at 12:03.412 appears at 12:03.412 whether it was dispatched
immediately or 300 ms later; only the on-screen confirmation is late.

### The bindings

Bindings are a client preference, stored in `localStorage` under `srt.pedal.bindings`, following the
same shape as `setCountInBars` / `setPinnedHand`: a validated read on load, a setter that writes
through. Validation matters more here than for the numeric preferences — an unknown action name or
an unknown gesture key falls back to the default rather than silently disabling a pedal.

**One action is bound to at most one gesture.** Assigning an action to a gesture clears it from any
other, so the panel is a partition and not a set of aliases. A gesture set to *nothing* is a normal,
supported state, which is why a fourth action can exist with three slots.

**Defaults follow the principle that the easiest gesture to fire gets the most benign action.**
`finish_sitting` ships unbound: it is the most destructive entry in the list and the rarest, so it
waits for a deliberate choice.

This means **take recording moves off the single press**, which is a change to the owner's daily
motor habit, and the bench scenario currently asserts the old gesture. Inverting those assertions is
part of the work, not a side effect discovered later.

### Dispatch

`state.svelte.ts` already has the seam: `handleController(move)` feeds the recogniser, publishes
`seenControllers`, and gates on `exerciseActive`. It grows one caller — the tick — and its
`runHandsfree()` becomes a switch on the action, which is exactly what the old comment predicted:

* `mark_review` → buffer a mark at the fire's press time; the capture client owns the buffer and the
  next batch carries it.
* `toggle_workout` → `startWorkout()` when nothing is running, `finishWorkout()` when something is.
* `toggle_audio_capture` → the existing `toggleAudioCapture()`, unchanged, so the pedal keeps
  inheriting its guards (the log must be running, the server must report its gap).
* `finish_sitting` → the existing `finishSitting()`, which already flushes capture first.

The store owns a short interval that calls `tick` **only while a gesture is pending**, so an idle
pedal costs nothing. Each action keeps its own error surface (`workoutError`, the capture note), and
`pedalActionNote` reports what happened, so a bound action that refuses is visible rather than
silent.

**The gesture stays inert during a scored attempt, for every action including the flag.** The
temptation is to exempt the flag because a flag is harmless; that would convert a tested invariant
into a per-action judgement about what counts as harmless, which is how the damper's double-tap got
retired in the first place. The store applies the gate at dispatch, uniformly.

### Where a review flag lives

The log's founding rule is that raw events are the gold and every figure is recomputable from them.
`pedal_events` follows it; `pedal_blur_ms` is derived from it. A review flag is a *player assertion*
rather than a measurement, so it needs a raw stream of its own:

* `CaptureClient` gains a mark buffer beside its note and pedal buffers. A mark is complete the
  moment it is pressed — nothing to wait for — so it flushes with the next batch, like a pedal move.
* `EventBatch` gains an optional `marks` list. Optional on the wire is what keeps an older client
  working unchanged, exactly as `pedals` did when it was added.
* **The client never learns the sitting id.** `capture.ts` states why in its header: a sitting is
  defined by silence, and only the server sees the whole stream. A mark therefore travels with the
  notes it happened among and the *server* assigns it, which is also what makes a late or retried
  batch land in the right place.
* `sitting_marks` stores `(sitting_id, onset_ms, epoch_ms)` with the same `INSERT OR IGNORE`
  idempotence as `pedal_events`: a retried batch must not double a flag, and two deliberate flags in
  one millisecond are not physically playable.
* A mark with no music around it is ignored, exactly as a pedal press with no practice is. The ingest
  result reports `marks_accepted` / `marks_ignored`, so "I pressed it and nothing happened" is
  answerable from the response rather than by guessing.
* `SittingDetail` gains `review_marks_ms`: positions relative to the sitting, ascending — the same
  shape and the same units as `pedal_blur_ms`.

**This stream is a decision, not a raw feed, and that is deliberate.** `pedal_events` stores every
CC64 move whether or not anything is bound to it. A mark is stored only when the flag action is
bound *and* fired. An unbound pedal must not fill a table with rows nobody asked for.

**The browser tier fails loudly until the new table is named.** `e2e_browser.reset_all` raises
`reset_all does not cover ['sitting_marks']` for any table it does not know about, so the table joins
`DATA_TABLES` in the same slice. That is the intended behaviour — a forgotten table is a scenario
that silently starts with the previous run's rows, which is the class of bug the gate exists to make
impossible — so the failure is the check catching it, not an obstacle to work around.

### Rendering

`SegmentTimeline.svelte` already draws the sitting strip, positions every segment at
`segment.start_ms / total`, and draws a blur hairline per `pedal_blur_ms` entry. The flag is one more
absolutely-positioned span inside the same `.strip`, at `markMs / total`:

* a distinct glyph and colour from the blur hairline, because "someone said review this" and "new
  harmony arrived over a held pedal" are different facts and must not look alike;
* `pointer-events: none`, like the blur hairline, so clicking a flag still seeks the transport;
* a `title` naming the time, in the same voice as the blur hairline's;
* `data-review-mark` for the browser tier to assert on.

The flag is a place in the **log**, not a live overlay on the practice view; the confirmation at the
moment of pressing is `pedalActionNote` ("Flagged — review near here"), which is what the panel and
the capture bar already read.

---

## Decisions

* **23-D1 — The sostenuto (CC66) remains the only bound controller.** Customization is which action
  each *gesture on it* carries, never which pedal carries a gesture. The played-pedal invariant is
  the design, not an obstacle to it; the damper is pressed constantly, so even an additive action
  bound to it would fire during ordinary playing.
* **23-D2 — Three gestures on one pedal: single, double, hold.** Each is independently assignable to
  any action or to nothing, and one action occupies at most one gesture. This is what "add more
  customization" buys without spending the invariant, because the pedal is unused musically and
  three gestures on it are free.
* **23-D3 — The safest action takes the easiest gesture.** single → review flag, double →
  start/finish a workout, hold → arm/stop the take; `finish_sitting` ships unbound. The destructive
  action moves behind a deliberate hold, which is a change to the owner's daily driver and is stated
  as such: the bench scenario's take assertions are inverted as part of this phase.
* **23-D4 — A review flag is a raw mark stream of its own.** A new `sitting_marks` table, an
  optional `EventBatch.marks` field, `SittingDetail.review_marks_ms`. Not a JSON column on
  `sittings` (the client cannot know the open sitting, so a retried press could land in the wrong
  one), and not a widened `pedal_events` (every CC64 reader would have to learn to filter, and
  `midi.ts` warns that routing CC66 down the sustain path records the middle pedal as sustain and
  corrupts `pedal_basis` and `pedal_blur`).
* **23-D5 — The gesture stays inert during a scored attempt, uniformly.** All four actions, with no
  exemption for the flag. `scenario_bench` already asserts that a press during a run starts nothing;
  keeping the gate uniform keeps that assertion meaningful.
* **23-D6 — A fire carries the press's timestamp, not the dispatch time.** This is what makes the
  deferred single tap free: the flag's position is exact and only its confirmation is late. It is
  also why the hold threshold can be checked by a timer without moving the mark.
* **23-D7 — A brand-new table needs no `ADDED_COLUMNS` entry and no `SCHEMA_VERSION` bump.**
  `CREATE TABLE IF NOT EXISTS` runs on every `init_db`, so the table appears on an existing database
  and an older build simply never reads it. `BACKUP_VERSION` is unchanged; `backup.table_names` reads
  `sqlite_master`. This follows the rule `ECOSYSTEM.md` § *Phase 20* states for `piece_passages`.
* **23-D8 — The discovery report survives the picker.** A gesture is bound to a message the piano may
  never send, which is why the panel must keep saying whether CC66 has actually been seen. The
  picker chooses an action; it never claims the pedal works.

---

## Slices

Three independently verifiable slices, in dependency order. 23a and 23b are independent of each
other; 23c needs both, because a flag has to be pressed before it can be stored.

| # | Slice | Delivers | Verifiable alone by |
| --- | --- | --- | --- |
| **23a** | **The recogniser learns three gestures** | `single`/`double`/`hold` on CC66, the hold threshold, the double window, `tick` for the two clock-dependent resolutions, and press-time stamping | Unit tests: a tap, a double, a hold, a hold that is not also a tap, an unbound gesture, a release with no press, only CC66 |
| **23b** | **The binding is the player's choice** | `PedalBindings`, the validated `localStorage` preference, one-action-one-gesture, the four-way dispatch, and the Setup panel's per-gesture pickers | The panel shows the chosen binding per gesture; changing it takes effect without a reload; an unknown stored action falls back |
| **23c** | **A flag on the timeline** | The mark buffer, the optional wire field, `sitting_marks`, ingest placement and idempotence, `review_marks_ms`, and the strip's flag layer | Backend ingest tests plus the browser assertion that a pressed flag appears at the pressed position |

---

## Acceptance criteria

1. A press-and-release of the sostenuto shorter than the hold threshold drops a review flag, and the
   flag's position on the strip is the **press** time — a single tap that waits out the double
   window is stamped where it was pressed, not where it fired.
2. Two taps inside the double window start a workout when none is running and finish the running one;
   a hold past the threshold arms and then stops take recording; a hold never also registers as a
   tap.
3. Any gesture can be rebound in Setup to any action or to nothing, and the change takes effect
   without a page reload. An action assigned to a second gesture is cleared from the first.
4. Nothing fires during a scored attempt — every action, the flag included — and `scenario_bench`'s
   existing "arms nothing while a run is in progress" assertion still passes.
5. Only CC66 is read. No CC64 or CC67 value reaches the recogniser, and no CC66 value reaches
   `pedal_events`; a sitting full of flags leaves `pedal_blur`, `pedal_blur_ms` and `pedal_basis`
   exactly as they were.
6. A mark with no music around it is ignored and counted in `marks_ignored`; a retried batch does
   not double a flag; `review_marks_ms` is sitting-relative and ascending.
7. An older client that sends no `marks` is unaffected, and every existing route, `streak_days`,
   `resegment`'s contract and the `identification_outcomes` shape are unchanged.
8. `./check.sh --full` green.

## Risks

| Risk | Treatment |
| --- | --- |
| Moving take recording to a hold breaks the owner's habit | The panel prints the live binding beside each gesture, and the bench scenario asserts the new gesture in both directions, so it cannot silently regress to the old one |
| The deferred single costs responsiveness | The only cost is the confirmation note, because the mark is stamped at press time; acceptance 1 measures exactly that and would catch a dispatch-time stamp |
| A brushed pedal leaves a flag that cannot be deleted | Accepted and stated as a non-goal: a mis-fired flag is inert, costs one hairline on a strip that already carries hundreds, and the fix if it becomes noise is a click-to-remove on the flag rather than a delete mode |
| Binding more actions multiplies the ways a pedal can surprise the player | The default partition is the mitigation — the benign action takes the easy gesture, the destructive one takes the hold, and the rarest ships unbound — and each action reuses the store method the button already uses, so it inherits that method's guards rather than bypassing them |
| A new raw stream that only records deliberate acts is not a raw controller log | Deliberate: unlike `pedal_events`, this stream is a player's decision, so an unbound pedal writes nothing. Stated in the module rather than left for a reader to notice the asymmetry |
| The flag layer and the blur layer drift into looking alike | Different glyph and colour, asserted in the browser tier, because the two facts are not the same fact |
| A mark assigned to the wrong sitting by a late batch | The server assigns it, using the same placement the notes and pedals use; a mark with no music around it is ignored rather than attached to whatever sitting is nearest |
| The store has no unit harness, so its dispatch is only covered by the browser tier | Every decision that can be pure was made pure (`pedalGesture.ts`, `pedalBindings.ts`), and the dispatch is one `switch` whose branches each call a method the button already uses; the bench assertion is watched red before it is trusted |
| The existing bench assertions encode the old mapping | They are inverted in the same task that changes the mapping, and the inversion is itself falsified by `let_a_single_press_stop_the_take.sh` |
| The 40 ms tick leaks a timer | It is started only while `pending` and clears itself when nothing is pending; an idle pedal runs no timer at all |
| A mark arrives for a sitting that is already closed | `_find_sitting` is the same function the pedals use, so a mark is placed by the same rule as a pedal move and dropped when there is nothing to attach it to |
| Orphan mark rows survive `clear_practice` | `clear_practice` does not enable foreign keys, so `sitting_marks` must be in its delete list as well as in `DATA_TABLES`; Task 3.8 does both |

## Retirement

* **The single press retires as the take-recording gesture.** `PLAN-PHASE20B.md`'s module snippet,
  its gesture test and its Status line all describe the one-gesture mapping and must be marked
  superseded rather than left to mislead a reader, exactly as 20b's own status line was corrected
  when the two gestures swapped.
* **`SetupPanel.svelte`'s hard-coded `PEDALS` binding strings retire** in favour of the live config.
  The per-pedal *seen* report stays: that is the discovery invariant and it is not what is changing.
* **`HandsfreeAction`'s single-member union retires.** This is the change the type was shaped for;
  the compiler names every caller, which is why the dispatch had no branch to add before now.
* **Nothing else retires.** `pedal_events`, `pedal_blur` / `pedal_blur_ms`, `pedal_basis`, the `.blur`
  hairline, `toggleAudioCapture`'s guards and the inert-during-a-run rule all keep their meanings.
  The phase adds a stream and a picker; it does not migrate, replace or re-derive anything.

## ADR / baseline-sync signals

* **Durable decisions, recorded here and not in a second authority.** The pedal as a configurable
  action surface bound to one discovered controller (23-D1, 23-D2, 23-D8), the review flag as a new
  persisted raw stream (23-D4), and the reaffirmation that the gesture is inert during a run for
  every action (23-D5) all extend the runtime and trust boundaries that 20-D5 opened. This project's
  decision record is `ECOSYSTEM.md` plus its decisions tables, and no ADR directory is created.
* **Baseline-sync work for completion:** `ECOSYSTEM.md`'s phase table and the Phase 23 section carry
  the decisions; `docs/FEATURES.md` § *Pedal control* carries the user-facing behaviour and must stop
  saying "one press and release arms take recording"; `PLAN-PHASE20B.md`'s superseded mapping is
  flagged; `AGENT-LOG.md` records what was built and what was measured.
* **No `SCHEMA_VERSION` bump, no `BACKUP_VERSION` change, no new route** — the wire field is additive
  and the new table is created by `init_db` (23-D7).

## What this does not do

* **No binding to the damper or the soft pedal, and no silence gate that would make it safe.** The
  invariant is the design; a gate would be a second thing to keep true, and the soft-pedal defect
  already showed what binding a played pedal costs.
* **No new controller.** No CC67, no aftertouch, no note-based or velocity-based gestures, and no
  timer-only gesture with no pedal at all.
* **No deletion or editing of a review flag.** Named as a non-goal with its trigger in the risk table.
* **No per-segment flag count and no `segment_metrics` column.** A flag is a place in a sitting;
  deriving "this attempt carries two flags" on read is a follow-up if it is ever asked for.
* **No live flag overlay on the practice view.** The flag is a place in the log; the live feedback is
  the existing action note.
* **No change to the blur rule, the pedal figures, or the notes payload**, and no retention policy
  for anything.

---

# Implementation plan

**Goal.** Three gestures on the sostenuto, each bound in Setup to one of four actions; the review
flag travels as its own raw mark stream and is drawn on the sitting strip beside the blur hairlines.

**Architecture.** A pure recogniser (`pedalGesture.ts`) decides; a pure binding table
(`pedalBindings.ts`) owns the mapping and its one-action-one-gesture rule; the store holds the
`localStorage` preference, the tick timer, and the dispatch; the panel renders the pickers. On the
server, a mark is a raw event placed by the same code that places a pedal move, and the sitting
detail carries its positions.

**Tech stack.** Svelte 5 runes + TypeScript (`node --test` for pure modules, `svelte-check`, Vite);
Python 3.11 / FastAPI / SQLite / pytest; Playwright driven by `backend/tools/e2e_browser.py`.

**Baseline / authority refs.** `ECOSYSTEM.md` § *Phase 23* and its decisions table (adopted by this
document); `FEATURES.md` § 2; `PLAN-PHASE20B.md` (the superseded one-gesture mapping);
`backend/app/practice/{models,schema,store,api}.py`; `frontend/src/lib/{pedalGesture,capture,state.svelte}.ts`;
`frontend/src/components/{SetupPanel,SegmentTimeline}.svelte`; `docs/TEST-STRATEGY.md` § 8.

**Compatibility boundary.** `HANDSFREE_CONTROLLERS` stays `[66]`; `pedal_events` and every CC64
reader are untouched; `EventBatch.marks` is optional so an older client is unaffected;
`SittingDetail.review_marks_ms` is optional on the client type; `SCHEMA_VERSION` stays **5**,
`BACKUP_VERSION` unchanged, no new route.

**TDD Route:**

```text
TDD Route:
- Mode: auto
- Decision: strict
- Strict authority: recorded auto decision — behaviour, contract, persistence and
  producer/consumer signals all apply
- Strict signals: new public wire field; new persisted table; a changed default that alters
  existing user-visible behaviour; a producer (CaptureClient) and a consumer (ingest) that
  must agree; the bench scenario's existing assertions are inverted
- Light eligibility: not applicable
- TDD-fit exception: none
- Test posture: strict RED test, except where the only honest harness is the browser tier —
  there the assertion is added and watched to fail before the wiring is made to satisfy it
- Reason: the store and the panel have no unit harness, so their obligation is discharged by a
  browser assertion that has been seen red; every decision that can be a pure function is made
  one, so most of this phase is unit-testable
- Verification: ./check.sh --full, plus ./check.sh --falsify
```

**Verification.** `cd frontend && npm test` · `cd frontend && npm run check` · `cd frontend && npm run build` ·
`cd backend && .venv/bin/python -m pytest -q` · `backend/tools/run_e2e.sh bench` · `./check.sh --fast` ·
`./check.sh --full` · `./check.sh --falsify`.

## Basis

```text
BaselineUsageDraft:
- Required baseline refs: ECOSYSTEM.md § Phase 23; PLAN-PHASE20B.md; FEATURES.md § 2;
  frontend/src/lib/pedalGesture.ts; backend/app/practice/{models,schema,store}.py
- Acknowledged before plan refs: all of the above were read during design
- Cited in plan refs: ECOSYSTEM.md § Phase 23 (23-D1…23-D8); AGENT-LOG.md 2026-09-17 (the
  soft-pedal defect and the retired damper double-tap)
- Missing refs: none
- Decision: continue
```

```text
Requirement Ready Check:
- Requirement source refs: the owner's request, then four answered design questions
- Goals and scope refs: PLAN-PHASE23.md § Goal, § What this does not do
- User / scenario refs: at the piano, hands on the keys, using the middle pedal
- Requirement item refs: 23-D1…23-D8
- Acceptance / verification criteria refs: § Acceptance criteria 1–8
- Open blocker questions: none
- Decision: ready
```

```text
Change Necessity:
- User-visible need: the middle pedal should carry more than one action, chosen by the player,
  and a press should leave a place in the log to come back to
- No-change / non-code option: the panel could keep printing one hard-coded binding — which is
  today's behaviour and answers none of the request
- Why code change is necessary: a second action needs a recogniser that can tell gestures apart,
  a stored preference, and a place to put a mark; none of the three exists
- Minimum change boundary: pedalGesture.ts, pedalBindings.ts (new), state.svelte.ts,
  SetupPanel.svelte, capture.ts, api.ts, types.ts, SegmentTimeline.svelte,
  backend/app/practice/{models,schema,store}.py
- Decision: code-change
```

```text
Existence Check:
- Proposed new surface: sitting_marks table; EventBatch.marks; review_marks_ms;
  frontend/src/lib/pedalBindings.ts
- Existing owner / reuse candidate: pedal_events (raw stream), segment_metrics.pedal_blur_ms
  (derived positions), state.svelte.ts (preferences)
- Why existing surface is insufficient: pedal_events is CC64 by contract and midi.ts warns that
  routing CC66 into it records the middle pedal as sustain; pedal_blur_ms is derived from the
  pedal stream and a mark is not derived from anything; the bindings are a validated mapping with
  an invariant, which is more than a scalar preference and needs a test
- Creation proof: the table is the only place a mark can be stored raw so the server assigns the
  sitting and a retry stays idempotent; a mark cannot be recomputed from notes, because nothing
  in the notes records that a person asked to come back
- Entropy / retirement impact: one table mirroring pedal_events, one additive wire field, one
  small pure module; nothing is replaced
- Decision: add-with-proof
```

```text
Complexity Budget:
- Artifact class: maintained owner files, one new pure module, one new table
- Target files / artifacts: pedalGesture.ts, pedalBindings.ts, state.svelte.ts (~960 lines),
  SetupPanel.svelte (~376), SegmentTimeline.svelte, models/schema/store.py
- Current pressure: state.svelte.ts is the app's single store and is already large;
  SegmentTimeline.svelte already draws two overlay layers
- Projected post-change pressure: state.svelte.ts +~45 lines; SegmentTimeline +~15; store.py
  +~25; the new logic lives in two pure modules rather than in the store
- Budget result: within-budget
- Planned governance: the binding rules and the recogniser are pure modules with their own tests;
  the store keeps only state, storage and dispatch

Plan-Time Complexity Check:
- Target files: as above
- Existing size / shape signals: SegmentTimeline already places `.block`, `.blur`, `.sounding`
  and `.playhead`; the flag is the fifth, not a new mechanism
- Owner fit: the recogniser owns gestures, the binding module owns the mapping, capture.ts owns
  the outbound buffer — each already owns its kind of thing
- Add-in-place risk: putting the binding rules in the store would make them untestable, which is
  why they are a separate pure module
- Better file boundary: pedalBindings.ts (new)
- Recommendation: add owner file for the bindings; edit-in-place everywhere else
```

## Files

| Path | Change |
| --- | --- |
| `frontend/src/lib/pedalGesture.ts` | Rewrite: four actions, three gestures, `tick`, press-time stamping |
| `frontend/src/lib/pedalGesture.test.ts` | Rewrite: the gesture table, deferral, hold-is-not-a-tap, only CC66 |
| `frontend/src/lib/pedalBindings.ts` | **New.** The action list, the defaults, assign/parse/serialise |
| `frontend/src/lib/pedalBindings.test.ts` | **New.** The one-action-one-gesture rule and the validated load |
| `frontend/src/lib/state.svelte.ts` | `pedalBindings` state, the tick timer, the four-way dispatch |
| `frontend/src/lib/capture.ts` | The mark buffer, `mark()`, the batch field, the status count |
| `frontend/src/lib/api.ts` | `PracticeBatch.marks` |
| `frontend/src/lib/types.ts` | `SittingDetail.review_marks_ms` |
| `frontend/src/components/SetupPanel.svelte` | The live binding per pedal and the three pickers |
| `frontend/src/components/SegmentTimeline.svelte` | The `.review` flag layer and its styles |
| `backend/app/practice/models.py` | `WireMark`, `EventBatch.marks`, `IngestResult` counts, `review_marks_ms` |
| `backend/app/practice/schema.py` | The `sitting_marks` table and its indexes |
| `backend/app/practice/store.py` | Mark placement in `ingest`, marks in `sitting_detail` |
| `backend/tests/test_practice_store.py` | Ingest, idempotence, orphan marks, resegment survival |
| `backend/tests/test_practice_api.py` | The additive field on the detail payload |
| `backend/tools/e2e_browser.py` | `sitting_marks` in `DATA_TABLES` and `clear_practice`; bench assertions |
| `backend/tools/falsifications/*.sh` | Three new break scripts (below) |
| `README.md`, `docs/{ECOSYSTEM,FEATURES}.md`, `AGENT-LOG.md`, `docs/PLAN-PHASE20B.md` | Status, behaviour, supersession, the log entry |

---

## Task 1 — the recogniser learns three gestures (23a)

**Files.** Modify `frontend/src/lib/pedalGesture.ts`; rewrite `frontend/src/lib/pedalGesture.test.ts`.

**Why.** Everything else depends on the recogniser being able to tell a tap, a double tap and a hold
apart, and on a fire carrying the press time. It is pure, so it is fully unit-testable.

**Change necessity.** The current module returns one action from one press-and-release; there is no
input shape it could be given that would produce a second action.

**Step 1.1 — write the failing tests.** Replace the whole of
`frontend/src/lib/pedalGesture.test.ts`:

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  PedalGesture,
  HOLD_MS,
  DOUBLE_MS,
  type ControllerMove,
  type PedalBindings,
  type PedalFire,
} from './pedalGesture.ts';

/** The mapping these tests exercise. The shipped defaults live in `pedalBindings.ts`. */
const BINDINGS: PedalBindings = {
  single: 'mark_review',
  double: 'toggle_workout',
  hold: 'toggle_audio_capture',
};

function move(controller: number, value: number, epochMs: number): ControllerMove {
  return { controller, value, epochMs, channel: 0 };
}

/** Feed a press and a release, and return everything the recogniser produced. */
function tap(gesture: PedalGesture, atMs: number, heldMs = 0): PedalFire[] {
  const fires = [...gesture.accept(move(66, 127, atMs))];
  fires.push(...gesture.accept(move(66, 0, atMs + heldMs)));
  return fires;
}

const actions = (fires: PedalFire[]) => fires.map((fire) => fire.action);

test('every controller number seen is reported, whatever it is', () => {
  const gesture = new PedalGesture(BINDINGS);
  gesture.accept(move(1, 127, 0));
  gesture.accept(move(66, 127, 10));
  gesture.accept(move(64, 0, 20));
  assert.deepEqual([...gesture.seen].sort((a, b) => a - b), [1, 64, 66]);
});

test('a single tap on the sostenuto fires the single action, stamped when it was pressed', () => {
  const gesture = new PedalGesture(BINDINGS);
  const fires = tap(gesture, 1_000);
  assert.deepEqual(fires, [], 'a tap is held back: it may be the first of two');
  // The window expires and the single fires, still stamped at the press.
  const resolved = gesture.tick(1_000 + DOUBLE_MS);
  assert.deepEqual(actions(resolved), ['mark_review']);
  assert.equal(resolved[0].atMs, 1_000, 'the press time, not the resolution time');
});

test('two taps inside the window are one double, and no single escapes', () => {
  const gesture = new PedalGesture(BINDINGS);
  assert.deepEqual(tap(gesture, 1_000), []);
  const second = tap(gesture, 1_000 + DOUBLE_MS - 50);
  assert.deepEqual(actions(second), ['toggle_workout']);
  assert.equal(second[0].atMs, 1_000 + DOUBLE_MS - 50, 'the press that completed the gesture');
  assert.deepEqual(gesture.tick(10_000), [], 'the first tap was claimed by the double');
});

test('a press held past the threshold is a hold, and fires while the pedal is still down', () => {
  const gesture = new PedalGesture(BINDINGS);
  gesture.accept(move(66, 127, 2_000));
  assert.deepEqual(gesture.tick(2_000 + HOLD_MS - 1), [], 'not yet');
  const fires = gesture.tick(2_000 + HOLD_MS);
  assert.deepEqual(actions(fires), ['toggle_audio_capture']);
  assert.equal(fires[0].atMs, 2_000, 'stamped at the press');
});

test('a hold is not also a tap, and its release fires nothing', () => {
  const gesture = new PedalGesture(BINDINGS);
  gesture.accept(move(66, 127, 2_000));
  gesture.tick(2_000 + HOLD_MS);
  const release = gesture.accept(move(66, 0, 2_000 + HOLD_MS + 100));
  assert.deepEqual(release, [], 'the release of a hold is consumed');
  assert.deepEqual(gesture.tick(9_000), [], 'and it leaves no single behind');
});

test('a tap followed by a hold is the hold alone', () => {
  // The second press claims the pair, so the first tap is not also a single: an accidental
  // tap before a deliberate hold must not fire two actions.
  const gesture = new PedalGesture(BINDINGS);
  tap(gesture, 1_000);
  gesture.accept(move(66, 127, 1_100));
  const held = gesture.tick(1_100 + HOLD_MS);
  assert.deepEqual(actions(held), ['toggle_audio_capture']);
  assert.deepEqual(gesture.tick(1_100 + HOLD_MS + DOUBLE_MS + 1), []);
});

test('a second tap arriving after the window is its own tap, and the first still fires', () => {
  const gesture = new PedalGesture(BINDINGS);
  tap(gesture, 1_000);
  // Expire the first, then tap again well outside the window.
  assert.deepEqual(actions(gesture.tick(1_000 + DOUBLE_MS)), ['mark_review']);
  assert.deepEqual(tap(gesture, 3_000), []);
  assert.deepEqual(actions(gesture.tick(3_000 + DOUBLE_MS)), ['mark_review']);
});

test('a release with no press before it is not a gesture', () => {
  const gesture = new PedalGesture(BINDINGS);
  assert.deepEqual(gesture.accept(move(66, 0, 500)), []);
  assert.deepEqual(gesture.tick(9_000), []);
});

test('a gesture bound to nothing fires nothing, and the pedal is still reported', () => {
  const gesture = new PedalGesture({ single: null, double: null, hold: null });
  assert.deepEqual(tap(gesture, 1_000), []);
  assert.deepEqual(gesture.tick(1_000 + DOUBLE_MS), []);
  assert.equal(gesture.seen.has(66), true);
});

test('only the sostenuto is read: the damper and the soft pedal carry nothing', () => {
  // The invariant this phase exists to keep. The damper is played constantly and the soft pedal
  // mid-phrase, so neither may reach an action however it is pressed.
  const gesture = new PedalGesture(BINDINGS);
  for (const controller of [64, 67]) {
    gesture.accept(move(controller, 127, 1_000));
    assert.deepEqual(gesture.accept(move(controller, 0, 1_010)), []);
    gesture.accept(move(controller, 127, 1_020));
    gesture.accept(move(controller, 0, 1_030));
  }
  assert.deepEqual(gesture.tick(9_000), []);
  assert.equal(gesture.seen.has(64), true, 'but both are still reported as seen');
  assert.equal(gesture.seen.has(67), true);
});

test('a binding can be changed while the pedal is idle and takes effect at once', () => {
  const gesture = new PedalGesture(BINDINGS);
  gesture.setBindings({ single: 'finish_sitting', double: null, hold: null });
  tap(gesture, 1_000);
  assert.deepEqual(actions(gesture.tick(1_000 + DOUBLE_MS)), ['finish_sitting']);
});

test('the recogniser reports whether anything is still waiting on the clock', () => {
  const gesture = new PedalGesture(BINDINGS);
  assert.equal(gesture.pending, false);
  gesture.accept(move(66, 127, 1_000));
  assert.equal(gesture.pending, true, 'a press is waiting for a hold or a release');
  gesture.accept(move(66, 0, 1_010));
  assert.equal(gesture.pending, true, 'a tap is waiting for a possible second');
  gesture.tick(1_010 + DOUBLE_MS);
  assert.equal(gesture.pending, false);
});
```

**Step 1.2 — verify RED.**

```bash
cd frontend && npm test
```

Expected: `pedalGesture.test.ts` fails to import — `BINDINGS` and `PedalFire` do not
exist and `PedalGesture` takes no argument. Every other file must still pass.

**Step 1.3 — the recogniser.** Replace the whole of `frontend/src/lib/pedalGesture.ts`:

```ts
/**
 * The pedals as hands-free switches.
 *
 * The PX-870 has three pedals, and the middle one is barely used musically — which is
 * exactly what makes it usable as a control. Nothing here reads musical state: it is
 * handed controller moves and returns actions, so the decision is pure and can be
 * tested without a piano.
 *
 * **Discovery first.** `seen` records every controller number the piano has actually
 * sent, because a gesture bound to a message the instrument never sends is a feature
 * that silently does not exist. The panel reports `seen`, so "the pedal does nothing"
 * can be answered by looking rather than by guessing.
 *
 * **One pedal, three gestures.** The sostenuto carries a single press, a double press and
 * a press-and-hold; each is bound to one action from the list, or to nothing. The damper
 * and the soft pedal carry nothing at all, because both are *played*: binding a tap on
 * either means an ordinary press fires a command mid-phrase. That was learned twice — the
 * soft pedal ended a take mid-phrase, and the damper's double tap started a workout during
 * ordinary pedalling — so the invariant is the design rather than an obstacle to it.
 *
 * **A fire carries the press's time.** A single tap cannot be told from the first half of a
 * double until the double window expires, so it is resolved late. Stamping it at the press
 * means the lateness costs only the on-screen confirmation, never the accuracy of the place
 * it records.
 *
 * **Nothing here owns the clock.** `accept` is driven by the move's own timestamp and `tick`
 * by whatever calls it, so the whole state machine is deterministic under test.
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

/** Every action a gesture can carry. */
export type HandsfreeAction =
  | 'mark_review'
  | 'toggle_workout'
  | 'toggle_audio_capture'
  | 'finish_sitting';

/** The three gestures one pedal can carry. */
export type PedalGestureKind = 'single' | 'double' | 'hold';

/** One gesture's binding: an action, or nothing at all. */
export type PedalBindings = Record<PedalGestureKind, HandsfreeAction | null>;

/** A gesture that fired, and *when the pedal was pressed* — never when it was resolved. */
export interface PedalFire {
  action: HandsfreeAction;
  /** Absolute time of the press that completed the gesture, ms since the Unix epoch. */
  atMs: number;
}

/**
 * The one pedal that is *not* played.
 *
 * The damper is used constantly and the soft pedal is used while playing, so neither can carry
 * a gesture a musician will fire by accident: the soft pedal especially, where a press
 * mid-phrase would stop the take being recorded. The sostenuto is the middle pedal almost
 * nobody touches, so it is the only one bound to anything — and the only one read.
 */
export const HANDSFREE_CONTROLLERS: readonly number[] = [66];

/** A press held at least this long is a hold rather than a tap. */
export const HOLD_MS = 500;

/**
 * How long a tap waits for a second one.
 *
 * Measured from the release, not the press: a deliberately slow tap is still a tap, and
 * timing the window from the press would expire it before the finger came off.
 */
export const DOUBLE_MS = 300;

/** MIDI's own rule, shared with the sustain path rather than spelled out twice. */
const DOWN = 64;

export class PedalGesture {
  /** Every controller number seen so far. A report, never consent. */
  readonly seen = new Set<number>();

  private readonly down = new Map<number, boolean>();
  private bindings: PedalBindings;

  /** When the current press began, or null when nothing is down. */
  private pressedAt: number | null = null;
  /** Whether the hold has already fired for the current press, so its release is consumed. */
  private holdFired = false;
  /** Whether the current press is the second tap of a pair. */
  private awaitingSecond = false;
  /** A tap waiting to find out whether a second one follows. */
  private pending: { atMs: number; expiresAt: number } | null = null;

  constructor(bindings: PedalBindings) {
    this.bindings = bindings;
  }

  /** A gesture can be rebound while the pedal is idle; the next move uses the new map. */
  setBindings(bindings: PedalBindings): void {
    this.bindings = bindings;
  }

  /** True while a press or a tap is still waiting on the clock. */
  get pending(): boolean {
    return this.pressedAt !== null || this.pending !== null;
  }

  private fire(kind: PedalGestureKind, atMs: number): PedalFire[] {
    const action = this.bindings[kind];
    return action === null ? [] : [{ action, atMs }];
  }

  /** Feed one controller move; get the gestures it completed, in order. */
  accept(move: ControllerMove): PedalFire[] {
    this.seen.add(move.controller);
    if (!HANDSFREE_CONTROLLERS.includes(move.controller)) return [];

    const isDown = move.value >= DOWN;
    const wasDown = this.down.get(move.controller) ?? false;
    this.down.set(move.controller, isDown);
    if (isDown === wasDown) return [];

    if (isDown) {
      this.pressedAt = move.epochMs;
      this.holdFired = false;
      // A second press inside the window claims the pair, so the first tap will not also
      // resolve as a single: an accidental tap before a deliberate hold fires one action.
      this.awaitingSecond = this.pending !== null && move.epochMs <= this.pending.expiresAt;
      if (this.awaitingSecond) this.pending = null;
      return [];
    }

    const pressTime = this.pressedAt;
    this.pressedAt = null;
    if (pressTime === null) return [];
    if (this.holdFired) {
      this.holdFired = false;
      this.awaitingSecond = false;
      return [];
    }
    if (this.awaitingSecond) {
      this.awaitingSecond = false;
      return this.fire('double', pressTime);
    }
    // A plain tap. It may be the first of a double, so it is held back — unless an earlier
    // tap is still pending, which the clock has not yet expired.
    const late = this.pending;
    this.pending = { atMs: pressTime, expiresAt: move.epochMs + DOUBLE_MS };
    return late === null ? [] : this.fire('single', late.atMs);
  }

  /**
   * Resolve whatever the clock has decided: a hold that has reached its threshold, and a
   * single tap whose double window has run out.
   *
   * Separate from `accept` because both need time to pass with no event arriving, and keeping
   * them here rather than in a timer is what makes the state machine testable.
   */
  tick(nowMs: number): PedalFire[] {
    const fires: PedalFire[] = [];
    if (this.pressedAt !== null && !this.holdFired && nowMs - this.pressedAt >= HOLD_MS) {
      this.holdFired = true;
      fires.push(...this.fire('hold', this.pressedAt));
    }
    if (this.pending !== null && nowMs >= this.pending.expiresAt) {
      const atMs = this.pending.atMs;
      this.pending = null;
      fires.push(...this.fire('single', atMs));
    }
    return fires;
  }
}
```

**Step 1.4 — verify GREEN, and check types.**

```bash
cd frontend && npm test && npm run check
```

Expected: all tests pass; `svelte-check` reports `state.svelte.ts` errors because `runHandsfree`
still takes no argument and `new PedalGesture()` has no argument. Those are Task 2's; note them and
carry on — do not silence them.

---

## Task 2 — the binding is the player's choice (23b)

**Files.** Create `frontend/src/lib/pedalBindings.ts` and `pedalBindings.test.ts`; modify
`state.svelte.ts` and `SetupPanel.svelte`.

**Why.** The action list, its defaults, and the one-action-one-gesture rule are decisions a player
makes, so they need a shape that can be validated and tested rather than three strings in the store.

**Step 2.1 — write the failing tests.** Create `frontend/src/lib/pedalBindings.test.ts`:

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  DEFAULT_BINDINGS,
  HANDSFREE_ACTIONS,
  assignBinding,
  parseBindings,
  serialiseBindings,
} from './pedalBindings.ts';

test('the default puts the benign action on the easiest gesture', () => {
  // A tapped pedal is the easiest to fire by accident, so it gets the action that costs
  // nothing; stopping a take is the one action that can destroy work, so it needs a hold.
  assert.equal(DEFAULT_BINDINGS.single, 'mark_review');
  assert.equal(DEFAULT_BINDINGS.double, 'toggle_workout');
  assert.equal(DEFAULT_BINDINGS.hold, 'toggle_audio_capture');
  assert.equal(
    HANDSFREE_ACTIONS.includes('finish_sitting') && DEFAULT_BINDINGS.single !== 'finish_sitting',
    true,
  );
});

test('assigning an action takes it from whatever gesture held it', () => {
  // One action, one gesture: two gestures firing the same action is a pedal that does the
  // same thing twice, and the panel would be showing a partition it does not have.
  const before = { single: 'mark_review', double: 'toggle_workout', hold: null } as const;
  const after = assignBinding({ ...before }, 'hold', 'mark_review');
  assert.deepEqual(after, { single: null, double: 'toggle_workout', hold: 'mark_review' });
});

test('clearing a gesture touches no other', () => {
  const after = assignBinding({ ...DEFAULT_BINDINGS }, 'double', null);
  assert.deepEqual(after, {
    single: 'mark_review',
    double: null,
    hold: 'toggle_audio_capture',
  });
});

test('an unreadable preference falls back to the defaults', () => {
  assert.deepEqual(parseBindings(null), DEFAULT_BINDINGS);
  assert.deepEqual(parseBindings('not json'), DEFAULT_BINDINGS);
  assert.deepEqual(parseBindings('[]'), DEFAULT_BINDINGS);
});

test('an unknown action name falls back for that gesture only', () => {
  const parsed = parseBindings('{"single":"play_a_tune","double":null}');
  assert.equal(parsed.single, 'mark_review', 'the unknown name does not disable the pedal');
  assert.equal(parsed.double, null, 'an explicit null is honoured');
  assert.equal(parsed.hold, 'toggle_audio_capture');
});

test('a stored partition with a duplicate keeps the first and clears the rest', () => {
  // Hand-edited storage, or a build that wrote two slots. Keeping both would make one press
  // fire one action and the other gesture the same action, which the panel cannot show.
  const parsed = parseBindings(
    '{"single":"mark_review","double":"mark_review","hold":"mark_review"}',
  );
  assert.deepEqual(parsed, { single: 'mark_review', double: null, hold: null });
});

test('a round trip through storage is lossless', () => {
  const cleared = assignBinding({ ...DEFAULT_BINDINGS }, 'hold', null);
  assert.deepEqual(parseBindings(serialiseBindings(cleared)), cleared);
});
```

**Step 2.2 — verify RED.**

```bash
cd frontend && npm test
```

Expected: `pedalBindings.test.ts` fails — the module does not exist.

**Step 2.3 — the module.** Create `frontend/src/lib/pedalBindings.ts`:

```ts
/**
 * Which action each gesture on the sostenuto carries.
 *
 * A pure module rather than three fields in the store, because it owns a rule the store cannot
 * test: **one action occupies one gesture**. Two gestures bound to the same action would be a
 * pedal that does the same thing twice, which no picker can show and no player can reason about,
 * so assigning an action clears it from wherever it was.
 *
 * The stored form is a small JSON object under one `localStorage` key. A value this build does
 * not recognise falls back **per gesture** rather than discarding the whole preference: a
 * hand-edited or forward-written key must not silently disable a pedal, because a pedal that does
 * nothing is exactly what the discovery report exists to distinguish from a feature that is
 * broken.
 */

import type { HandsfreeAction, PedalBindings, PedalGestureKind } from './pedalGesture';

/** The list, in the order the picker offers it. */
export const HANDSFREE_ACTIONS: readonly HandsfreeAction[] = [
  'mark_review',
  'toggle_workout',
  'toggle_audio_capture',
  'finish_sitting',
];

export const PEDAL_GESTURE_KINDS: readonly PedalGestureKind[] = ['single', 'double', 'hold'];

/** What each action does, in the panel's words. */
export const ACTION_LABELS: Record<HandsfreeAction, string> = {
  mark_review: 'flag this place for review',
  toggle_workout: 'start or finish a workout',
  toggle_audio_capture: 'arm or stop take recording',
  finish_sitting: 'finish the sitting',
};

/**
 * The same actions in two or three words, for the pedal pill.
 *
 * The full label is a select option, where there is room; the pill has to say what the pedal does
 * beside the discovery report without becoming the widest thing in the panel.
 */
export const ACTION_SHORT: Record<HandsfreeAction, string> = {
  mark_review: 'flag',
  toggle_workout: 'workout',
  toggle_audio_capture: 'take recording',
  finish_sitting: 'finish sitting',
};

/** What each gesture is, in the panel's words. */
export const GESTURE_LABELS: Record<PedalGestureKind, string> = {
  single: 'press',
  double: 'double press',
  hold: 'press and hold',
};

/**
 * The shipped partition: the benign action takes the gesture that is easiest to fire by
 * accident, and the one action that can destroy work takes the gesture that cannot be.
 *
 * `finish_sitting` is deliberately absent: it is the most destructive entry and the rarest, so it
 * waits to be chosen rather than arriving pre-bound.
 */
export const DEFAULT_BINDINGS: PedalBindings = {
  single: 'mark_review',
  double: 'toggle_workout',
  hold: 'toggle_audio_capture',
};

export const PEDAL_BINDINGS_STORAGE_KEY = 'srt.pedal.bindings';

/** Assign an action to a gesture, or clear one with null. One action, one gesture. */
export function assignBinding(
  bindings: PedalBindings,
  kind: PedalGestureKind,
  action: HandsfreeAction | null,
): PedalBindings {
  const next: PedalBindings = { ...bindings, [kind]: action };
  if (action !== null) {
    for (const other of PEDAL_GESTURE_KINDS) {
      if (other !== kind && next[other] === action) next[other] = null;
    }
  }
  return next;
}

/** The stored preference, or the defaults. Unrecognised values fall back per gesture. */
export function parseBindings(raw: string | null): PedalBindings {
  const next: PedalBindings = { ...DEFAULT_BINDINGS };
  if (raw === null) return next;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return next;
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return next;

  const record = parsed as Record<string, unknown>;
  for (const kind of PEDAL_GESTURE_KINDS) {
    if (!(kind in record)) continue; // absent keeps the default
    const value = record[kind];
    if (value === null) {
      next[kind] = null;
      continue;
    }
    if (typeof value === 'string' && (HANDSFREE_ACTIONS as readonly string[]).includes(value)) {
      next[kind] = value as HandsfreeAction;
    }
  }

  // A stored duplicate keeps the first gesture and clears the rest, so the partition the panel
  // shows is the partition the recogniser uses.
  const claimed = new Set<HandsfreeAction>();
  for (const kind of PEDAL_GESTURE_KINDS) {
    const value = next[kind];
    if (value === null) continue;
    if (claimed.has(value)) next[kind] = null;
    else claimed.add(value);
  }
  return next;
}

export function serialiseBindings(bindings: PedalBindings): string {
  return JSON.stringify(bindings);
}

/** The stored preference, or the defaults. Storage being unavailable is not an error. */
export function loadBindings(): PedalBindings {
  try {
    return parseBindings(localStorage.getItem(PEDAL_BINDINGS_STORAGE_KEY));
  } catch {
    return { ...DEFAULT_BINDINGS };
  }
}

export function saveBindings(bindings: PedalBindings): void {
  try {
    localStorage.setItem(PEDAL_BINDINGS_STORAGE_KEY, serialiseBindings(bindings));
  } catch {
    // A preference that cannot be written is a preference that resets on reload. Saying so
    // would be noise in a panel about pedals.
  }
}
```

**Step 2.4 — verify GREEN.**

```bash
cd frontend && npm test
```

**Step 2.5 — the store.** In `frontend/src/lib/state.svelte.ts`:

1. Extend the import:

```ts
import {
  PedalGesture,
  type ControllerMove,
  type HandsfreeAction,
  type PedalBindings,
  type PedalFire,
  type PedalGestureKind,
} from './pedalGesture';
import { assignBinding, loadBindings, saveBindings } from './pedalBindings';
```

2. Add the tick period beside the other constants:

```ts
/**
 * How often a pending gesture is asked whether its clock has run out.
 *
 * Short enough that a hold feels immediate and a single tap is not perceptibly late; it runs
 * only while something is pending, so an idle pedal costs nothing.
 */
const GESTURE_TICK_MS = 40;
```

3. Replace the field declaration and the recogniser with:

```ts
  /** Which action each gesture on the sostenuto carries. A preference, not a discovery. */
  pedalBindings = $state<PedalBindings>(loadBindings());

  private readonly pedalGesture = new PedalGesture(loadBindings());

  /** The timer that resolves a hold or an expired double window, or null when idle. */
  private gestureTimer: ReturnType<typeof setInterval> | null = null;

  /** Rebind one gesture. One action occupies one gesture, so an action moves rather than copies. */
  setPedalBinding(kind: PedalGestureKind, action: HandsfreeAction | null): void {
    this.pedalBindings = assignBinding(this.pedalBindings, kind, action);
    saveBindings(this.pedalBindings);
    this.pedalGesture.setBindings(this.pedalBindings);
  }
```

4. Replace `handleController` and `runHandsfree` with:

```ts
  /** Feed one controller move to the recogniser, then act on what it decided. */
  handleController(move: ControllerMove): void {
    const fires = this.pedalGesture.accept(move);
    this.seenControllers = [...this.pedalGesture.seen].sort((a, b) => a - b);
    if (this.pedalGesture.pending) this.startGestureClock();
    for (const fire of fires) this.dispatchHandsfree(fire);
  }

  /**
   * Ask the recogniser whether the clock has decided anything.
   *
   * A single tap cannot be told from the first half of a double until the window closes, and a
   * hold fires while the pedal is still down, so both need time to pass with no event arriving.
   * The timer runs only while something is pending and stops itself when nothing is.
   */
  private startGestureClock(): void {
    if (this.gestureTimer !== null) return;
    this.gestureTimer = setInterval(() => {
      for (const fire of this.pedalGesture.tick(Date.now())) this.dispatchHandsfree(fire);
      if (!this.pedalGesture.pending && this.gestureTimer !== null) {
        clearInterval(this.gestureTimer);
        this.gestureTimer = null;
      }
    }, GESTURE_TICK_MS);
  }

  /**
   * The one place a hands-free action is allowed to happen.
   *
   * The gate is here rather than in the recogniser so every action is covered by one rule: the
   * gesture is inert during a scored attempt, the flag included. Exempting the flag because it is
   * harmless would turn a tested invariant into a per-action judgement about what counts as
   * harmless, which is how the damper's double tap got retired.
   */
  private dispatchHandsfree(fire: PedalFire): void {
    if (this.exerciseActive) return;
    void this.runHandsfree(fire);
  }

  /**
   * What the pedals do.
   *
   * Every branch goes through the same method the button uses, so a pedal inherits that method's
   * guards — the log must be running, the server must report its gap — rather than bypassing them.
   * The note is set here rather than in each action so a bound action that refuses is visible
   * instead of silent.
   */
  async runHandsfree(fire: PedalFire): Promise<void> {
    switch (fire.action) {
      case 'mark_review':
        // Stamped at the press, not at the dispatch: a tap resolved 300 ms late still records
        // where the player actually was.
        this.capture.mark(fire.atMs);
        this.pedalActionNote = 'Flagged — review near here';
        return;
      case 'toggle_workout':
        if (this.workout?.running) {
          await this.finishWorkout();
          this.pedalActionNote = 'Workout finished from the pedal';
        } else {
          await this.startWorkout();
          this.pedalActionNote = 'Workout started from the pedal';
        }
        return;
      case 'finish_sitting':
        await this.finishSitting();
        this.pedalActionNote = 'Sitting finished from the pedal';
        return;
      case 'toggle_audio_capture':
        await this.toggleAudioCapture();
        this.pedalActionNote = this.audioArmed
          ? 'Recording takes from the pedal'
          : 'Take recording stopped from the pedal';
        return;
    }
  }
```

Delete the old `runHandsfree()` body and the old `private readonly pedalGesture = new
PedalGesture();` line, and the old dispatch comment above `runHandsfree`.

**Step 2.6 — the panel.** In `frontend/src/components/SetupPanel.svelte`, import the binding module:

```ts
  import {
    ACTION_LABELS,
    ACTION_SHORT,
    GESTURE_LABELS,
    HANDSFREE_ACTIONS,
    PEDAL_GESTURE_KINDS,
  } from '../lib/pedalBindings';
  import type { HandsfreeAction, PedalGestureKind } from '../lib/pedalGesture';
```

Replace the `PEDALS` array with a map whose CC66 entry is derived from the live binding:

```ts
  /**
   * The three pedals a piano may send, and whether this one has.
   *
   * The binding is printed beside the discovery for one reason: two of the three pedals are
   * deliberately bound to nothing, because they are played — and a pedal that silently does
   * nothing is indistinguishable from a broken feature unless the panel says which it is.
   * CC66's line is read from the live preference, so what it prints is what the pedal does.
   */
  function bindingSummary(cc: number): string {
    if (cc !== 66) return 'deliberately not bound';
    const parts: string[] = [];
    for (const kind of PEDAL_GESTURE_KINDS) {
      const action = app.pedalBindings[kind];
      if (action !== null) parts.push(`${GESTURE_LABELS[kind]}: ${ACTION_SHORT[action]}`);
    }
    // A pedal with nothing bound must say so rather than read as broken: this is the sentence
    // that makes "the pedal does nothing" answerable by looking.
    return parts.length === 0 ? 'nothing bound' : parts.join(' · ');
  }

  const PEDALS: { cc: number; label: string }[] = [
    { cc: 64, label: 'Damper (right)' },
    { cc: 66, label: 'Sostenuto (middle)' },
    { cc: 67, label: 'Soft (left)' },
  ];
```

Update the pill to use it:

```svelte
        <span
          class="pill"
          class:good={app.seenControllers.includes(pedal.cc)}
          data-pedal={pedal.cc}
        >
          {pedal.label} · CC{pedal.cc} · {bindingSummary(pedal.cc)} · {pedalState(pedal.cc)}
        </span>
```

Replace the group's prose paragraph with text that explains the gestures, and add the pickers after
the pill row:

```svelte
    <p class="muted small">
      Press each pedal once. A pedal the piano does not send cannot be bound to anything, so this
      is a report rather than a promise. The sostenuto carries three gestures; each is bound to one
      action or to nothing. A single press flags the place for review, a double press starts or
      finishes a workout, and a press and hold arms or stops take recording — so stopping a take
      needs a deliberate hold rather than a tap. The damper and the soft pedal are bound to nothing
      at all: both are played, and a press mid-phrase must never end a take.
    </p>
    <div class="row wrap" data-pedal-bindings>
      {#each PEDAL_GESTURE_KINDS as kind (kind)}
        <label class="muted small" for="pedal-{kind}">{GESTURE_LABELS[kind]}</label>
        <select
          id="pedal-{kind}"
          data-pedal-binding={kind}
          value={app.pedalBindings[kind] ?? ''}
          onchange={(event) => {
            const raw = (event.currentTarget as HTMLSelectElement).value;
            app.setPedalBinding(kind, raw === '' ? null : (raw as HandsfreeAction));
          }}
        >
          <option value="">nothing</option>
          {#each HANDSFREE_ACTIONS as action (action)}
            <option value={action}>{ACTION_LABELS[action]}</option>
          {/each}
        </select>
      {/each}
    </div>
```

**Step 2.7 — verify.**

```bash
cd frontend && npm test && npm run check && npm run build
```

Expected: tests pass, `svelte-check` clean, build clean. The store and the panel have no unit
harness, so their real obligation is the browser assertion in Task 5 — it must be seen red against
this code before it is trusted.

---

## Task 3 — a flag on the timeline, the server side (23c)

**Files.** Modify `backend/app/practice/models.py`, `schema.py`, `store.py`; add tests to
`backend/tests/test_practice_store.py` and `test_practice_api.py`.

**Why.** A mark must survive a retried batch, land in the sitting the notes establish, and be read
back with its positions. That is the whole server-side contract.

**Step 3.1 — write the failing tests.** In `backend/tests/test_practice_store.py`, add `WireMark` to
the existing model import line:

```python
from app.practice.models import EventBatch, WireMark, WireNote, WirePedal
```

and append these four tests. They use the module's existing `BASE_MS`, `LATER_MS` and `fresh_db`
fixture; a sitting at `BASE_MS` is already closed by `LATER_MS`, so nothing has to wait:

```python
def test_a_mark_is_stored_relative_to_its_sitting(fresh_db) -> None:
    payload = EventBatch(
        tz_offset_minutes=0,
        events=[
            WireNote(epoch_ms=BASE_MS, pitch=60, velocity=70, duration_ms=300, channel=0),
            WireNote(epoch_ms=BASE_MS + 4_000, pitch=62, velocity=70, duration_ms=300, channel=0),
        ],
        marks=[WireMark(epoch_ms=BASE_MS + 1_500, channel=0)],
    )
    result = store.ingest(payload)

    assert (result.marks_accepted, result.marks_ignored) == (1, 0)
    detail = store.sitting_detail(result.sitting_id, now_ms=LATER_MS)
    assert detail.review_marks_ms == [1_500], "relative to the sitting, not absolute"


def test_reposting_a_batch_does_not_double_a_mark(fresh_db) -> None:
    payload = EventBatch(
        tz_offset_minutes=0,
        events=[WireNote(epoch_ms=BASE_MS, pitch=60, velocity=70, duration_ms=300, channel=0)],
        marks=[WireMark(epoch_ms=BASE_MS + 500, channel=0)],
    )
    first = store.ingest(payload)
    second = store.ingest(payload)

    assert first.marks_accepted == 1
    assert second.marks_accepted == 0, "the second pass is a duplicate, not a second flag"
    assert store.sitting_detail(first.sitting_id, now_ms=LATER_MS).review_marks_ms == [500]


def test_a_mark_with_no_music_around_it_is_ignored(fresh_db) -> None:
    # The rule a pedal press already follows: a foot on a pedal is not practice, so a flag must
    # not invent a sitting or extend one.
    result = store.ingest(
        EventBatch(tz_offset_minutes=0, marks=[WireMark(epoch_ms=BASE_MS, channel=0)])
    )

    assert result.sitting_id is None
    assert (result.marks_accepted, result.marks_ignored) == (0, 1)


def test_marks_survive_a_resegment(fresh_db) -> None:
    # A mark is a fact about the sitting, not about a boundary, so rebuilding the segments must
    # not touch it.
    payload = EventBatch(
        tz_offset_minutes=0,
        events=[
            WireNote(
                epoch_ms=BASE_MS + offset,
                pitch=pitch,
                velocity=70,
                duration_ms=300,
                channel=0,
            )
            for offset, pitch in ((0, 60), (1_000, 62), (20_000, 64), (21_000, 65))
        ],
        marks=[WireMark(epoch_ms=BASE_MS + 1_500, channel=0)],
    )
    sitting_id = store.ingest(payload).sitting_id
    store.resegment_sitting(sitting_id, confirm=True)

    assert store.sitting_detail(sitting_id, now_ms=LATER_MS).review_marks_ms == [1_500]
```

Append to `backend/tests/test_practice_api.py`, which already has the `client` fixture and
`batch_payload` helper:

```python
def test_the_detail_payload_carries_the_review_marks(client) -> None:
    # Additive, so every reader written before Phase 23 still holds; asserted here because the
    # field is the whole user-visible point of the mark stream.
    payload = batch_payload([0, 500, 1_000])
    payload["marks"] = [{"epoch_ms": BASE_MS + 800, "channel": 0}]
    sitting_id = client.post("/api/practice/events", json=payload).json()["sitting_id"]

    body = client.get(f"/api/practice/sittings/{sitting_id}").json()
    assert body["review_marks_ms"] == [800]
```

**Step 3.2 — verify RED.**

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_store.py tests/test_practice_api.py
```

Expected: `ImportError` for `WireMark`, and no `marks_accepted` on the result.

**Step 3.3 — the models.** In `backend/app/practice/models.py`, add beside `WirePedal`:

```python
class WireMark(BaseModel):
    """A place the player asked to come back to.

    A deliberate act rather than a measurement, which is why it travels as its own stream: nothing
    in the notes records that a person pressed a pedal to say "review this". It carries no value
    because there is nothing to carry — the fact is the instant.
    """

    epoch_ms: int = Field(description="Absolute event time, ms since the Unix epoch")
    channel: int | None = Field(default=None, ge=0, le=15)
```

Add to `EventBatch`:

```python
    marks: list[WireMark] = Field(default_factory=list)
```

and extend its docstring with one line: *"``marks`` is optional on the wire for the same reason
``pedals`` is: a client that predates it keeps working unchanged."*

Add to `IngestResult`:

```python
    #: Marks stored in this batch, and those dropped because no sitting was open. A flag pressed
    #: with no music around it is not practice, so it is dropped rather than allowed to open one.
    marks_accepted: int = 0
    marks_ignored: int = 0
```

Add to `SittingDetail`:

```python
    #: Where the player asked to come back to, in ms relative to the sitting, ascending. Additive
    #: with a default, so every pre-existing reader of a sitting still holds.
    review_marks_ms: list[int] = Field(default_factory=list)
```

**Step 3.4 — the table.** In `backend/app/practice/schema.py`, after the `pedal_events` indexes:

```sql
-- Places the player asked to come back to, pressed on the sostenuto.
--
-- Its own stream rather than a column on `pedal_events`: that table is CC64 by contract, and
-- routing CC66 into it would record the middle pedal as sustain and corrupt `pedal_blur` and
-- `pedal_basis`. Raw like the pedal stream rather than derived, because nothing in the notes
-- records that a person asked to come back — but *only* deliberate marks, so an unbound pedal
-- writes nothing here.
CREATE TABLE IF NOT EXISTS sitting_marks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sitting_id   INTEGER NOT NULL REFERENCES sittings(id) ON DELETE CASCADE,
    onset_ms     INTEGER NOT NULL,       -- ms since the sitting start
    epoch_ms     INTEGER NOT NULL        -- what the piano's clock said, for debugging
);
-- The same idempotence as note_events and pedal_events: a retried batch must not double a mark,
-- and two deliberate marks in one millisecond are not physically playable.
CREATE UNIQUE INDEX IF NOT EXISTS idx_marks_dedupe ON sitting_marks(sitting_id, onset_ms);
CREATE INDEX IF NOT EXISTS idx_marks_sitting ON sitting_marks(sitting_id, onset_ms);
```

**Step 3.5 — ingest.** In `backend/app/practice/store.py`, in `ingest`:

```python
    pedals = sorted(batch.pedals, key=lambda pedal: pedal.epoch_ms)
    marks = sorted(batch.marks, key=lambda mark: mark.epoch_ms)
    if not notes and not pedals and not marks:
        raise InvalidRequest("cannot ingest an empty batch")
```

```python
    marks_accepted = 0
    marks_ignored = 0
```

After the pedals loop, before `final`:

```python
        # Marks last, for the same reason the pedals are second: a batch that opens a sitting must
        # attach its mark to that sitting. Nothing here opens or extends one either — a flag with
        # no music around it is not practice, so it is counted and dropped.
        for mark in marks:
            row = _find_sitting(conn, mark.epoch_ms, gap_ms)
            if row is None:
                marks_ignored += 1
                continue
            mark_sitting = int(row["id"])
            cursor = conn.execute(
                "INSERT OR IGNORE INTO sitting_marks"
                " (sitting_id, onset_ms, epoch_ms) VALUES (?1, ?2, ?3)",
                (
                    mark_sitting,
                    mark.epoch_ms - int(row["started_ms"]),
                    mark.epoch_ms,
                ),
            )
            if cursor.rowcount:
                marks_accepted += 1
                sitting_id = mark_sitting
```

and add to the returned `IngestResult`:

```python
        marks_accepted=marks_accepted,
        marks_ignored=marks_ignored,
```

**Step 3.6 — read.** In `sitting_detail`, after `note_count`:

```python
        review_marks_ms = [
            int(mark["onset_ms"])
            for mark in conn.execute(
                "SELECT onset_ms FROM sitting_marks WHERE sitting_id = ? ORDER BY onset_ms",
                (sitting_id,),
            )
        ]
```

and pass it to the constructor:

```python
            review_marks_ms=review_marks_ms,
```

**Step 3.7 — verify GREEN.**

```bash
cd backend && .venv/bin/python -m pytest -q
```

**Step 3.8 — the browser tier's table gate.** In `backend/tools/e2e_browser.py`, add
`"sitting_marks"` to `DATA_TABLES` **and** to the tuple `clear_practice()` deletes. Both, because
`clear_practice` uses its own list and — as its own comment says — does not set
`PRAGMA foreign_keys = ON`, so the `ON DELETE CASCADE` will not fire and orphan rows would survive
into the next scenario.

---

## Task 4 — a flag on the timeline, the client (23c)

**Files.** Modify `frontend/src/lib/capture.ts`, `api.ts`, `types.ts`,
`frontend/src/components/SegmentTimeline.svelte`.

**Why.** The press has to reach the server, and the place has to be visible where the blur hairlines
are.

**Step 4.1 — the buffer.** In `frontend/src/lib/capture.ts`, beside `CapturedPedal`:

```ts
/**
 * A place the player asked to come back to.
 *
 * Kept apart from the notes and the pedals because it has neither a duration to wait for nor a
 * value: it is complete the moment it is pressed, and there is exactly one per deliberate press.
 */
interface CapturedMark {
  epoch_ms: number;
  channel: number | null;
}
```

Add `marks: number;` to `CaptureStatus` beside `pedals`, and the field:

```ts
  /** Deliberate marks ready to send. Nothing is ever held back here either. */
  private marks: CapturedMark[] = [];
```

Add the public method:

```ts
  /**
   * Record a place to come back to.
   *
   * Deliberately not a subscription to CC66 like the pedal listener: a mark is recorded only
   * when the flag action is bound *and* fired, so an unbound pedal writes nothing. The stream is
   * a player's decision, not a raw controller log.
   */
  mark(epochMs: number): void {
    this.marks.push({ epoch_ms: epochMs, channel: null });
    this.publish();
  }
```

In `flush()`: change the empty check to include marks, sort and cap them like the pedals, slice
them out of the buffer, and add them to the body:

```ts
    if (this.buffer.length === 0 && this.pedals.length === 0 && this.marks.length === 0) {
```
```ts
    this.marks.sort((a, b) => a.epoch_ms - b.epoch_ms);
    if (this.marks.length > MAX_BUFFERED) this.marks = this.marks.slice(-MAX_BUFFERED);
```
```ts
    const batch = this.buffer.slice();
    const pedals = this.pedals.slice();
    const marks = this.marks.slice();
```
```ts
      await api.practice.ingest({
        source: this.source(),
        events: batch,
        pedals,
        marks,
      });
      this.buffer = this.buffer.slice(batch.length);
      this.pedals = this.pedals.slice(pedals.length);
      this.marks = this.marks.slice(marks.length);
```

Apply the same three changes to `flushOnHide`'s body construction and buffer trimming, and add
`marks: this.marks.length` to `publish()`.

**Step 4.2 — the wire.** In `frontend/src/lib/api.ts`, add to `PracticeBatch`:

```ts
  /**
   * Deliberate "review this" marks. Optional on the wire, like `pedals`: a server that predates
   * the field ignores it, and a batch with none is the ordinary case.
   */
  marks?: { epoch_ms: number; channel: number | null }[];
```

**Step 4.3 — the type.** In `frontend/src/lib/types.ts`, add to `SittingDetail`:

```ts
  /**
   * Where the player asked to come back to, in ms relative to the sitting, ascending.
   * Optional with a default for the same reason `passages` is: a server that predates Phase 23
   * still satisfies this type, and every reader can treat it as an empty list.
   */
  review_marks_ms?: number[];
```

**Step 4.4 — the strip.** In `frontend/src/components/SegmentTimeline.svelte`, inside `.strip`,
after the `{#each detail.segments …}{/each}` block and before the `soundingRange` block:

```svelte
      {#each detail.review_marks_ms ?? [] as markMs (markMs)}
        <!-- A flag you put there yourself, as against the blur hairline the app measured: the
             same layer, a different fact, so it must not look like one. -->
        <span
          class="review"
          data-review-mark={markMs}
          style="left: {(markMs / total) * 100}%"
          title="You flagged this for review at {formatClock(markMs / 1000)}"
        ></span>
      {/each}
```

and in `<style>`, beside `.strip .blur`:

```css
  /* A review flag is a hairline with a pennant: findable on a long sitting, and unmistakably not
     the warn-coloured blur hairline beside it. It takes no pointer events, so clicking it still
     seeks. */
  .strip .review {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    margin-left: -1px;
    background: var(--good);
    pointer-events: none;
  }

  .strip .review::before {
    content: '';
    position: absolute;
    top: 0;
    left: 2px;
    width: 7px;
    height: 7px;
    background: var(--good);
    clip-path: polygon(0 0, 100% 50%, 0 100%);
  }
```

**Step 4.5 — verify.**

```bash
cd frontend && npm run check && npm run build
```

---

## Task 5 — the browser assertions, the falsifications, and the docs

**Files.** Modify `backend/tools/e2e_browser.py`; add three scripts under
`backend/tools/falsifications/`; modify `README.md`, `docs/FEATURES.md`,
`docs/PLAN-PHASE20B.md`, `AGENT-LOG.md`.

**Step 5.1 — invert the take assertions and add the new gestures.** In `scenario_bench`, the
existing `press_sostenuto()` is a tap, which now flags rather than arms. Replace it with three
helpers and rework the assertions:

```python
    def tap_sostenuto() -> None:
        # One press and release: the flag. Short enough not to trip the hold threshold.
        page.evaluate("() => window.__fakeMidi.send([0xb0, 66, 127])")
        page.wait_for_timeout(60)
        page.evaluate("() => window.__fakeMidi.send([0xb0, 66, 0])")
        page.wait_for_timeout(700)

    def hold_sostenuto() -> None:
        # Past the hold threshold: take recording.
        page.evaluate("() => window.__fakeMidi.send([0xb0, 66, 127])")
        page.wait_for_timeout(900)
        page.evaluate("() => window.__fakeMidi.send([0xb0, 66, 0])")
        page.wait_for_timeout(400)

    def double_tap_sostenuto() -> None:
        # Two taps inside the double window: the workout.
        for _ in range(2):
            page.evaluate("() => window.__fakeMidi.send([0xb0, 66, 127])")
            page.wait_for_timeout(60)
            page.evaluate("() => window.__fakeMidi.send([0xb0, 66, 0])")
            page.wait_for_timeout(120)
        page.wait_for_timeout(700)
```

The assertions become, in order:

* the untouched `data-pedal='66'` read (`not seen yet`, then `sends this`) stays exactly as it is —
  the discovery report is 23-D8 and must not change;
* `hold_sostenuto()` arms the take (`[data-audio-capture="armed"]`), and a second hold stops it;
* `tap_sostenuto()` does **not** change the capture state — this is the assertion that proves the
  destructive action moved off the easy gesture — and after a note has been played into the sitting
  it adds one entry to `review_marks_ms` on the newest sitting, read back over `api()`;
* `double_tap_sostenuto()` starts a workout (`api("/api/workout/current")` is not None) and a second
  double finishes it;
* the soft-pedal and damper assertions are unchanged: both must still leave the take and the workout
  alone;
* the inert-during-a-run assertion uses `tap_sostenuto()` and additionally asserts that the run's
  mark count did not move.

**Step 5.2 — verify the browser tier.**

```bash
cd frontend && npm run build && cd .. && backend/tools/run_e2e.sh bench
```

Then watch each new assertion fail before trusting it — apply the break by hand once (for example,
restore `single: 'toggle_audio_capture'` in `DEFAULT_BINDINGS`), rebuild, re-run, confirm the
matching assertion goes red, then revert.

**Step 5.3 — the falsifications.** Add three scripts in the shape of
`let_the_soft_pedal_stop_the_take.sh`, each with its `CHECK:` line:

| Script | The break | What must catch it |
| --- | --- | --- |
| `stamp_the_flag_when_it_fires.sh` | In `pedalGesture.ts`, fire the single with the tick's `nowMs` instead of `pending.atMs` | `npm test` — the press-time assertions, and through them the bench's "the flag lands where it was pressed" |
| `let_a_single_press_stop_the_take.sh` | Set `DEFAULT_BINDINGS.single = 'toggle_audio_capture'` | `npm test` (the default partition) and the bench (a tap must not change the capture state) |
| `drop_the_mark_stream.sh` | Remove `marks` from the `capture.ts` ingest body | The bench's mark assertion, after `npm run build` |

Run each:

```bash
./falsify.sh backend/tools/falsifications/stamp_the_flag_when_it_fires.sh "cd frontend && npm test"
./falsify.sh backend/tools/falsifications/let_a_single_press_stop_the_take.sh "cd frontend && npm test"
./falsify.sh backend/tools/falsifications/drop_the_mark_stream.sh \
  "(cd frontend && npm run build) && backend/tools/run_e2e.sh bench"
```

**Step 5.4 — the docs, in the commit that lands the code.**

* `docs/FEATURES.md` § 2: replace "one press and release arms take recording, and another stops it"
  with the gesture table and the binding rule; keep the two invariants and the discovery paragraph,
  and add that a played pedal remains unbound by design.
* `docs/PLAN-PHASE20B.md`: mark the one-gesture mapping superseded, naming this document — its own
  test and module snippets would otherwise mislead a reader.
* `docs/ECOSYSTEM.md`: flip the phase-table row and the Phase 23 heading from **Planned** to
  **Landed**, and record the measured verification numbers in the section.
* `README.md`: if the selected-capabilities list mentions the pedal gesture, update the sentence.
* `AGENT-LOG.md`: the dated entry — what changed, what the falsifications caught, and the exact
  verification numbers.

**Step 5.5 — the full gate.**

```bash
./check.sh --full
```

## Execution Route

```text
Execution Route:
- Decision: inline
- Evidence: five tasks, strictly ordered — the recogniser is a dependency of the dispatch, which is
  a dependency of the flag — all in one repository with one working tree, and each task leaves the
  tree green
- Fallback: none needed
- User confirmation required: no
```

The route is `inline` rather than `subagent-driven` because the tasks are not independent: Task 2
cannot type-check until Task 1's signatures exist, and Task 5's assertions cannot be written until
Tasks 2–4 have given them something to assert. The only genuinely independent pair is Task 3 (server)
and Task 1 (recogniser), and splitting the context between them would cost more than it saves.
