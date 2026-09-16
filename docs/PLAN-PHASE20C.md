# Plan — Phase 20c: log trust and habit

**Parent spec:** [`ECOSYSTEM.md`](./ECOSYSTEM.md) § *Phase 20* § *20c — log trust and habit (F1,
B3)*, with decisions 20-D3 and 20-D6. That section owns what and why; this document owns the how.

**Status:** planned.

**Goal.** Make the log safe to edit and the streak fit a real week. Undo for the three reversible
boundary edits, built from the routes that already exist; a `resegment` that says plainly that it
cannot be undone; and a streak that tolerates one rest day in seven and reports it.

**Architecture.** The interesting half of undo is *deciding what the inverse is*, and that decision
is a pure function of two segment lists — so it lives in `frontend/src/lib/segmentUndo.ts` and is
unit-tested, while `PracticeLogView` only maps a descriptor to an API call. The streak is a server
read: one function, one new summary field.

**Tech stack.** TypeScript + Svelte 5, `node --test` for the pure module; Python/SQLite for the
streak; Playwright for the browser tier.

**Baseline / authority refs.**

- `docs/ECOSYSTEM.md` § Phase 20 § 20c, plus 20-D3 (no persisted undo record) and 20-D6 (one grace
  day per rolling seven).
- `docs/TEST-STRATEGY.md` §8 (the standing rule).
- `docs/PLAN-PHASE20B.md` (the sibling slice; the same tier and falsification mechanics).
- `AGENT-LOG.md` § *Rules*.

**Re-read gate.** This plan was written against the tree at `2708ebb`. Before Task 1:

```bash
cd /home/marco_normal/tmp/SighRTracker
grep -n "async function edit" -A 12 frontend/src/components/PracticeLogView.svelte
grep -n "def streak_days" backend/app/practice/store.py
grep -n "resegment" -A 6 frontend/src/components/SegmentTimeline.svelte
git status --porcelain   # must print nothing before any falsification
```

**Compatibility boundary.** One additive summary field (`streak_grace_used`) and no schema change at
all — undo needs no table (20-D3). `streak_days` keeps its name and its meaning for a week with no
missed days, so every existing assertion about it still holds; that is asserted rather than assumed
(Task 3, Step 3.1). `resegment` is unchanged in behaviour and only gains a sentence.

```text
TDD Route:
- Mode: auto
- Decision: strict
- Strict authority: docs/TEST-STRATEGY.md §8, the standing rule
- Strict signals: a public behaviour change (a streak that no longer breaks on one missed day), a
  shared pure decision consumed by a view, and an additive response field
- Light eligibility: not applicable
- Test posture: strict RED first for `segmentUndo.ts` and for the streak; for the wiring, the
  browser assertion is watched to fail with a break applied
- Verification: ./check.sh --fast after every task; ./check.sh --full before the slice is done
```

```text
Change Necessity:
- User-visible need: an accidental merge or split is currently permanent, and a single missed day
  erases months of streak
- No-change / non-code option: insufficient — the inverse of an edit is not configuration, and the
  streak rule is arithmetic in one function
- Why code change is necessary: no undo exists anywhere, and `streak_days` breaks on the first gap
- Minimum change boundary: one new frontend module, PracticeLogView, SegmentTimeline's confirm
  copy, `store.streak`, two models fields, tests, one browser assertion, docs
- Decision: code-change
```

```text
Existence Check:
- Proposed new surface: `frontend/src/lib/segmentUndo.ts`; `app.…`-free — undo state stays in the
  view; `AnalyticsSummary.streak_grace_used`; `store.streak()` replacing `store.streak_days()`
- Existing owner / reuse candidate: the merge/split/assign routes already exist and are exactly
  invertible; `PracticeLogView.edit()` is already the single funnel every timeline edit goes
  through; `streak_days` already owns the streak
- Why existing surface is insufficient: `edit()` discards what changed, so nothing can compute an
  inverse; the streak function has no notion of a tolerated day
- Creation proof: 20c's acceptance bullets require a reversible edit and an explained grace day
- Entropy / retirement impact: no new table, no persisted undo record (20-D3) — the stack is one
  field in a component, so it dies with the page and that is stated in the UI rather than implied;
  `segmentUndo.ts` is pure and deletable in one file
- Decision: add-with-proof for the pure inverse function; reuse-existing for the routes, the edit
  funnel and the streak owner
```

```text
Plan-Time Complexity Check:
- Target files: frontend/src/components/PracticeLogView.svelte (743 lines), backend/app/practice/store.py (1941)
- Existing size / shape signals: PracticeLogView already owns load/edit/select/busy/error; store.py
  already owns every practice read and write
- Owner fit: `edit()` is where every mutation already funnels, so undo belongs there and nowhere else
- Add-in-place risk: computing the inverse inline in the view would put a testable decision in a
  component that `node --test` cannot load
- Better file boundary: `segmentUndo.ts`; the view keeps one field and one button
- Recommendation: extract helper (segmentUndo.ts), then edit-in-place
```

```text
Plan Pressure Test:
- Owner / contract / retirement: no schema change, no new route; the summary gains one field; the
  undo stack is deliberately not persisted and that limitation is shown to the player
- Architecture integrity / higher-level path: the inverse is derived from what changed, so the view
  never has to know what each action did — one function covers all three edits
- Verification scope: eight pure units, three streak units, one contract assertion, one browser
  assertion, three committed break scripts
- Task executability: every step names a file, complete code and an exact command
- Pressure result: proceed
```

---

## Files

**Create**

| Path | Why |
| --- | --- |
| `frontend/src/lib/segmentUndo.ts` | The inverse of an edit, as a pure function of two lists |
| `frontend/src/lib/segmentUndo.test.ts` | Split, merge, assign, and the two cases with no inverse |
| `backend/tools/falsifications/drop_undo_split_inverse.sh` | Break the split's inverse |
| `backend/tools/falsifications/break_streak_on_one_miss.sh` | Break the grace day |

**Modify**

| Path | Change |
| --- | --- |
| `frontend/src/components/PracticeLogView.svelte` | Snapshot before each edit, compute the inverse, an Undo control, the streak sentence, the weekly target |
| `frontend/src/components/SegmentTimeline.svelte` | The resegment confirm says it cannot be undone |
| `frontend/src/lib/state.svelte.ts` | The weekly-target preference |
| `backend/app/practice/store.py` | `streak()` with the grace day, replacing `streak_days()` |
| `backend/app/practice/models.py` | `AnalyticsSummary.streak_grace_used` |
| `backend/tests/test_practice_api.py` | The grace-day behaviour, and that an unbroken week is unchanged |
| `backend/tools/e2e_browser.py` | One assertion in `scenario_practice_log` |
| `README.md`, `AGENT-LOG.md`, `docs/ECOSYSTEM.md` | docs |

---

## Task 1 — the inverse of an edit, as a pure function

**Files.** create `frontend/src/lib/segmentUndo.ts`, `frontend/src/lib/segmentUndo.test.ts`.

**Why.** Merge, split and assign are each exactly invertible through the routes that already exist,
but *which* inverse applies is a decision, and a decision hidden inside a component is a decision
nobody tests. This is the whole of F1's logic in one file.

**Change Necessity.** Code: nothing computes an inverse today; `edit()` throws away what changed.

**Impact / Compatibility.** A new module and a new type. No existing behaviour changes.

**Decision 20c-D1, and the one thing a reviewer must check.** `merge` and `split` are exact
inverses *for the rows the app owns*: `split` keeps the left half in the original row and inserts a
new one, and `merge` keeps the lower-start row and deletes the other, so `split` then `merge`
restores both ids and both boundaries — and, since the 20a follow-up, the practice kind as well.
The one asymmetry is `identification_outcomes`: a merge nulls the absorbed segment's `segment_id`
(`ON DELETE SET NULL`), so undoing a merge restores the segments but **not** the matcher's record of
one of them. The undo control therefore says only what it does ("Undo merge") and never claims the
matcher's history came back. `resegment` and `identify` have no inverse at all and must return
`null` — that is what keeps the Undo control off the screen after them.

### Step 1.1 — write the failing units

Create `frontend/src/lib/segmentUndo.test.ts`:

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { inverseOf } from './segmentUndo.ts';
import type { SegmentSummary } from './types';

/** A segment with only the fields the inverse reads; the rest are noise for these tests. */
function seg(id: number, startMs: number, endMs: number, pieceId: number | null = null): SegmentSummary {
  return {
    id,
    sitting_id: 1,
    start_ms: startMs,
    end_ms: endMs,
    piece_id: pieceId,
    piece_title: null,
    composer_name: null,
    source: null,
    workout_id: null,
    confidence: null,
    identified_by: null,
    practice_kind: null,
    practice_kind_basis: null,
    note_count: 1,
    metrics: null,
    candidates: [],
  };
}

test('a split is undone by merging the two halves back', () => {
  const before = [seg(1, 0, 8_000)];
  const after = [seg(1, 0, 3_000), seg(2, 4_000, 8_000)];
  assert.deepEqual(inverseOf(before, after), {
    kind: 'merge',
    segmentId: 1,
    otherId: 2,
    label: 'Undo split',
  });
});

test('a merge is undone by splitting at the boundary that was absorbed', () => {
  const before = [seg(1, 0, 3_000), seg(2, 4_000, 8_000)];
  const after = [seg(1, 0, 8_000)];
  assert.deepEqual(inverseOf(before, after), {
    kind: 'split',
    segmentId: 1,
    atMs: 4_000,
    label: 'Undo merge',
  });
});

test('a piece label is undone by putting the old one back, including a cleared one', () => {
  const before = [seg(1, 0, 8_000, 7)];
  const after = [seg(1, 0, 8_000, null)];
  assert.deepEqual(inverseOf(before, after), {
    kind: 'assign',
    segmentId: 1,
    pieceId: 7,
    label: 'Undo label',
  });

  const wasClear = [seg(1, 0, 8_000, null)];
  const nowLabelled = [seg(1, 0, 8_000, 7)];
  assert.deepEqual(inverseOf(wasClear, nowLabelled), {
    kind: 'assign',
    segmentId: 1,
    pieceId: null,
    label: 'Undo label',
  });
});

test('a re-segment has no inverse, and says so by returning null', () => {
  const before = [seg(1, 0, 3_000), seg(2, 4_000, 8_000)];
  const after = [seg(9, 0, 8_000)];
  assert.equal(inverseOf(before, after), null);
});

test('answering the matcher has no inverse', () => {
  const before = [seg(1, 0, 8_000, null)];
  const after = [seg(1, 0, 8_000, 7)];
  // The id and the label both moved, which is an assign as far as the *rows* are concerned;
  // what makes `identify` different is that the route, not the rows, records the outcome. The
  // view therefore never offers undo for it, and this test pins the reasoning rather than the
  // behaviour: `inverseOf` reports what it can see, and nothing more.
  assert.deepEqual(inverseOf(before, after), {
    kind: 'assign',
    segmentId: 1,
    pieceId: null,
    label: 'Undo label',
  });
});

test('nothing changed means nothing to undo', () => {
  const same = [seg(1, 0, 8_000, 3)];
  assert.equal(inverseOf(same, [seg(1, 0, 8_000, 3)]), null);
});

test('an empty before has no inverse, so the first load cannot offer one', () => {
  assert.equal(inverseOf([], [seg(1, 0, 8_000)]), null);
});
```

### Step 1.2 — verify RED

```bash
cd frontend && npm test
```

Expected: failure resolving `./segmentUndo.ts`.

### Step 1.3 — write the module

Create `frontend/src/lib/segmentUndo.ts`:

```ts
/**
 * The inverse of a timeline edit.
 *
 * Merge, split and assign are exactly invertible through the routes that already exist, and
 * working out *which* inverse applies is a pure function of the segment list before and after —
 * so it lives here, where `node --test` can reach it, rather than inside the view that happens to
 * know which button was pressed.
 *
 * Two edits deliberately have no inverse and return null:
 *
 * * `resegment` throws every boundary and label away and rebuilds them, so the rows that were
 *   destroyed are not recoverable from the rows that exist;
 * * answering the matcher (`identify`) writes an `identification_outcomes` row, which the segments
 *   do not carry. The rows may look invertible — the label did change — but the record of the guess
 *   would not come back, so the view does not offer undo for it.
 *
 * **The one thing this cannot restore.** A merge sets the absorbed segment's
 * `identification_outcomes.segment_id` to NULL (`ON DELETE SET NULL`), so undoing a merge restores
 * the segments and their labels but not the matcher's record of one of them. The control says
 * "Undo merge" and claims nothing more.
 */
import type { SegmentSummary } from './types';

export type UndoAction =
  | { kind: 'assign'; segmentId: number; pieceId: number | null; label: string }
  | { kind: 'merge'; segmentId: number; otherId: number; label: string }
  | { kind: 'split'; segmentId: number; atMs: number; label: string };

export function inverseOf(before: SegmentSummary[], after: SegmentSummary[]): UndoAction | null {
  if (before.length === 0) return null;

  const beforeIds = new Set(before.map((segment) => segment.id));
  const afterIds = new Set(after.map((segment) => segment.id));
  const added = after.filter((segment) => !beforeIds.has(segment.id));
  const removed = before.filter((segment) => !afterIds.has(segment.id));

  // A split: one new row appeared and none went away. The original row kept the left half,
  // so merging the two adjacent halves restores both boundaries exactly.
  if (added.length === 1 && removed.length === 0) {
    const [left, right] = [before[0], added[0]].sort((a, b) => a.start_ms - b.start_ms);
    if (left === undefined || right === undefined) return null;
    return { kind: 'merge', segmentId: left.id, otherId: right.id, label: 'Undo split' };
  }

  // A merge: one row went away and none appeared. The survivor is the row whose id is in
  // both lists; the absorbed row's start was the boundary the split has to cut at.
  if (removed.length === 1 && added.length === 0) {
    const absorbed = removed[0];
    const survivor = after.find((segment) => beforeIds.has(segment.id));
    if (absorbed === undefined || survivor === undefined) return null;
    return {
      kind: 'split',
      segmentId: survivor.id,
      atMs: absorbed.start_ms,
      label: 'Undo merge',
    };
  }

  // Neither: the id set is unchanged, so this was a label edit. Whoever moved, moves back.
  if (added.length === 0 && removed.length === 0) {
    const changed = before.find((segment) => {
      const now = after.find((candidate) => candidate.id === segment.id);
      return now !== undefined && now.piece_id !== segment.piece_id;
    });
    if (changed === undefined) return null;
    return {
      kind: 'assign',
      segmentId: changed.id,
      pieceId: changed.piece_id,
      label: 'Undo label',
    };
  }

  return null;
}
```

### Step 1.4 — verify GREEN

```bash
cd frontend && npm test
```

Expected: 98 passing (91 after 20b, plus the seven here).

### Step 1.5 — falsify the split inverse

Create `backend/tools/falsifications/drop_undo_split_inverse.sh`:

```bash
#!/usr/bin/env bash
#
# Break: stop recognising a split, so the Undo control would offer a label edit instead.
#
# The test that must catch it is 'a split is undone by merging the two halves back' in
# frontend/src/lib/segmentUndo.test.ts.
#
#   ./falsify.sh backend/tools/falsifications/drop_undo_split_inverse.sh "cd frontend && npm test"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/segmentUndo.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "  if (added.length === 1 && removed.length === 0) {"
assert needle in text, "the branch is not where this script expects it"
path.write_text(text.replace(needle, "  if (false) {", 1))
PY
```

```bash
chmod +x backend/tools/falsifications/drop_undo_split_inverse.sh
backend/tools/falsify.sh backend/tools/falsifications/drop_undo_split_inverse.sh "cd frontend && npm test"
```

Expected: `falsified: the check caught the break`.

---

## Task 2 — the Undo control

**Files.** modify `frontend/src/components/PracticeLogView.svelte`,
`frontend/src/components/SegmentTimeline.svelte`.

**Why.** The inverse is useless until a person can reach it.

**Change Necessity.** Code: there is no control and no state to drive one.

**Impact / Compatibility.** Additive UI. `edit()` keeps its signature and gains an optional second
argument.

### Step 2.1 — the wiring

In `frontend/src/components/PracticeLogView.svelte`, add to the imports:

```ts
  import { inverseOf, type UndoAction } from '../lib/segmentUndo';
```

Add the state beside `busy` (`:44`):

```ts
  /**
   * What the last edit could be taken back with, and the segments it would restore.
   *
   * Deliberately **not** persisted: it describes one action in this page's history, and a
   * remembered undo across a reload would silently apply to a different list of segments
   * (20-D3). Reloading the page is how you lose the offer, and the card says so.
   */
  let undo = $state<{ action: UndoAction } | null>(null);
```

Replace `edit()` (`:136-148`) with:

```ts
  /**
   * Every edit re-reads both the sitting and the totals, then works out whether it can be
   * taken back. `undoable: false` is for the undo itself, so pressing it twice cannot
   * ping-pong between two states for ever.
   */
  async function edit(
    action: () => Promise<unknown>,
    options: { undoable?: boolean } = {},
  ): Promise<void> {
    busy = true;
    error = null;
    const before = detail?.segments ?? [];
    try {
      await action();
      await load();
      const next =
        options.undoable === false || detail === null ? null : inverseOf(before, detail.segments);
      undo = next === null ? null : { action: next };
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
      undo = null;
    } finally {
      busy = false;
    }
  }

  function applyUndo(action: UndoAction): Promise<unknown> {
    if (action.kind === 'assign') {
      return api.practice.assignSegment(action.segmentId, action.pieceId);
    }
    if (action.kind === 'merge') {
      return api.practice.mergeSegments(action.segmentId, action.otherId);
    }
    return api.practice.splitSegment(action.segmentId, action.atMs);
  }

  async function undoLast(): Promise<void> {
    if (undo === null) return;
    const action = undo.action;
    await edit(() => applyUndo(action), { undoable: false });
  }
```

### Step 2.2 — the control

Immediately above `<SegmentTimeline …>` (`:375`), inside the same `{#if detail}`:

```svelte
    {#if undo}
      <div class="row wrap" data-undo>
        <span class="muted small">
          Changed the timeline. This offer lasts until the page is reloaded.
        </span>
        <button class="ghost tiny" disabled={busy} onclick={() => void undoLast()}>
          {undo.action.label}
        </button>
      </div>
    {/if}
```

### Step 2.3 — resegment says what it cannot do

Find the confirm text and add the sentence:

```bash
grep -n "resegment" -A 8 frontend/src/components/SegmentTimeline.svelte
```

The confirm already exists and asks when segments carry labels. Add this sentence to it, verbatim:

> Re-segmenting cannot be undone: the boundaries and labels it replaces are rebuilt from the notes.

and keep the existing behaviour (only the `confirm: true` variant is loopback-restricted, and that
is unchanged).

### Step 2.4 — verify

```bash
cd frontend && npm test && npm run check && npm run build
```

---

## Task 3 — a streak that tolerates one rest day in seven

**Files.** modify `backend/app/practice/store.py`, `backend/app/practice/models.py`,
`backend/tests/test_practice_api.py`.

**Why.** One missed day currently erases months.

**Change Necessity.** Code: the rule is arithmetic inside one function.

**Impact / Compatibility.** `AnalyticsSummary` gains `streak_grace_used` (additive). `streak_days`
keeps its name and its value for any week without a missed day, which is what the existing
assertions cover.

**Decision 20c-D2.** The reported number is the **length of the unbroken run in calendar days,
including the tolerated rest day**, because the run is the thing the number means — and the field
`streak_grace_used` lets the UI say that one of those days was a rest day, so the number is never
mistaken for days played. The alternative (counting only days played) makes the number go *down*
on a day you are still in the streak, which is worse.

**Decision 20c-D3.** A second missed day inside the same rolling week **ends the run**, and the run
keeps the length it had reached up to and including the first forgiven day. It does not zero the
number, because the days already practised were practised; what it does is stop the run reaching
back past the gap. The case where the number *is* zero is the one the spec calls a reset — today
and yesterday both empty, which is the Monday after a weekend away — and that is what
`test_a_streak_never_opens_on_a_rest_day` covers.

**Two consequences of the rule that are asserted rather than assumed:** an unbroken week must report
exactly the days it contains (a naive implementation forgives a rest day at the *end* of every run
and reports one too many — the look-ahead in the loop exists for that), and a forgiven rest day must
join two stretches of practice rather than sit at the edge of one.

### Step 3.1 — write the failing tests

Append to `backend/tests/test_practice_api.py`:

```python
def _record_on(client, day: str, offsets: list[int]) -> None:
    """A closed sitting filed on one calendar day."""
    import time

    stamp = f"{day}T12:00:00+00:00"
    base = int(datetime.fromisoformat(stamp).timestamp() * 1000)
    body = client.post(
        "/api/practice/events",
        json={
            "tz_offset_minutes": 0,
            "events": [
                {
                    "epoch_ms": base + offset,
                    "pitch": 60 + index,
                    "velocity": 70,
                    "duration_ms": 300,
                    "channel": 0,
                }
                for index, offset in enumerate(offsets)
            ],
        },
    ).json()
    assert body["sitting_id"] is not None
    client.post("/api/practice/sittings/close")


def _days_ago(count: int) -> str:
    from datetime import date, timedelta

    return (date.today() - timedelta(days=count)).isoformat()


def test_an_unbroken_week_is_unchanged_by_the_grace_rule(client) -> None:
    """The rule must not move the number for anybody who never missed a day."""
    for offset in (2, 1, 0):
        _record_on(client, _days_ago(offset), [0, 500])
    body = client.get("/api/practice/analytics/summary?days=30").json()
    assert body["streak_days"] == 3
    assert body["streak_grace_used"] == 0


def test_one_missed_day_keeps_the_streak_and_is_reported(client) -> None:
    for offset in (3, 1, 0):
        _record_on(client, _days_ago(offset), [0, 500])
    body = client.get("/api/practice/analytics/summary?days=30").json()
    assert body["streak_days"] == 4, "the run covers four calendar days"
    assert body["streak_grace_used"] == 1, "and one of them was a rest day"


def test_two_missed_days_in_a_row_end_the_run(client) -> None:
    """One rest day is forgiven; the second ends the run rather than extending it.

    The run is "today plus one forgiven rest day", not "everything back to the practice four
    days ago": the second consecutive miss is where the run stops, which is the whole point
    of allowing only one rest day per rolling week.
    """
    for offset in (4, 0):
        _record_on(client, _days_ago(offset), [0, 500])
    body = client.get("/api/practice/analytics/summary?days=30").json()
    assert body["streak_days"] == 2, "today plus the one forgiven rest day"
    assert body["streak_grace_used"] == 1
    assert body["streak_days"] < 4, "and the practice before the gap is not in this run"


def test_a_streak_never_opens_on_a_rest_day(client) -> None:
    """A week away must not report a one-day streak on return."""
    _record_on(client, _days_ago(10), [0, 500])
    body = client.get("/api/practice/analytics/summary?days=30").json()
    assert body["streak_days"] == 0
    assert body["streak_grace_used"] == 0


def test_today_not_yet_played_does_not_count_against_you(client) -> None:
    for offset in (2, 1):
        _record_on(client, _days_ago(offset), [0, 500])
    body = client.get("/api/practice/analytics/summary?days=30").json()
    assert body["streak_days"] == 2
    assert body["streak_grace_used"] == 0, "an empty today is not a rest day, it is not over"
```

`datetime` must be imported in that test module; add `from datetime import datetime` at the top if
it is not there.

### Step 3.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py -k streak
```

Expected: failures on `streak_grace_used` (a `KeyError`) and on the grace cases.

### Step 3.3 — the model field

In `backend/app/practice/models.py`, in `AnalyticsSummary` after `streak_days`:

```python
    #: How many of the streak's days were tolerated rest days, 0 or 1 under the current rule.
    #: Reported so the UI can say the run includes a rest day rather than implying it was played.
    streak_grace_used: int = 0
```

### Step 3.4 — the rule

In `backend/app/practice/store.py`, add above `streak_days`:

```python
@dataclass(frozen=True)
class Streak:
    """A run of days at the piano, with at most one rest day forgiven per rolling week."""

    days: int
    grace_used: int


#: How many calendar days a forgiven rest day stays forgiven for. One rest day per week is the
#: rule a pianist can actually keep; two inside a week is a break.
GRACE_WINDOW_DAYS = 7

#: How far back to look. A streak longer than ten years is not a thing this app needs to prove.
STREAK_LOOKBACK_DAYS = 3_660
```

and replace `streak_days` (`store.py:1350-1375`) with:

```python
def streak(conn: sqlite3.Connection) -> Streak:
    """The run of days ending today or yesterday, forgiving one rest day per rolling week.

    Three rules, each of which exists because the obvious version got it wrong:

    * **Today not yet played does not break it.** The day is not over, and a streak that resets
      every midnight until you play is a nag, not a measurement.
    * **One missed day in seven is forgiven**, and the run continues from the day before it. A
      second miss within the same seven days ends the run, which is why the check is against the
      previous forgiven day rather than a count.
    * **A run never opens on a rest day.** Otherwise coming back after a fortnight would report a
      one-day streak, which is worse than reporting nothing.

    ``days`` is the length of the run in calendar days, so it includes a forgiven rest day; the
    caller reports ``grace_used`` beside it so the number is never read as days played.
    """
    rows = [
        row["local_date"]
        for row in conn.execute("SELECT DISTINCT local_date FROM sittings")
    ]
    dates = {datetime.fromisoformat(value).date() for value in rows}
    today = _today()

    cursor = today if today in dates else today - timedelta(days=1)
    if cursor not in dates:
        return Streak(days=0, grace_used=0)

    days = 0
    grace_used = 0
    last_forgiven: date | None = None
    while (today - cursor).days <= STREAK_LOOKBACK_DAYS:
        if cursor in dates:
            days += 1
        else:
            # A rest day is only forgiven when it is joining two stretches of practice. A
            # gap at the *end* of a run is simply the end of the run — without this check
            # every streak would be one longer than the days it is made of, which is
            # exactly what `test_an_unbroken_week_is_unchanged_by_the_grace_rule` pins.
            ahead = range(1, GRACE_WINDOW_DAYS + 1)
            if not any((cursor - timedelta(days=step)) in dates for step in ahead):
                break
            if last_forgiven is not None and (last_forgiven - cursor).days < GRACE_WINDOW_DAYS:
                break
            last_forgiven = cursor
            grace_used += 1
            days += 1
        cursor -= timedelta(days=1)
    return Streak(days=days, grace_used=grace_used)
```

Update the caller in `summary()` (`store.py:1399`):

```python
        streak_days=streak(conn).days,
        streak_grace_used=streak(conn).grace_used,
```

Call it once, not twice:

```python
    run = streak(conn)
    return AnalyticsSummary(
        ...
        streak_days=run.days,
        streak_grace_used=run.grace_used,
```

`dataclass` is already imported in `store.py` (`:24`) and `date` needs adding to the datetime import
(`:25` currently imports `datetime, timedelta, timezone`).

### Step 3.5 — verify GREEN

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py tests/test_api.py
```

Expected: all pass, including the three pre-existing `streak_days` assertions.

### Step 3.6 — falsify the grace day

Create `backend/tools/falsifications/break_streak_on_one_miss.sh`:

```bash
#!/usr/bin/env bash
#
# Break: go back to breaking the streak on the first missed day.
#
# The test that must catch it is test_one_missed_day_keeps_the_streak_and_is_reported.
#
#   ./falsify.sh backend/tools/falsifications/break_streak_on_one_miss.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """            if last_forgiven is not None and (last_forgiven - cursor).days < GRACE_WINDOW_DAYS:
                break
"""
assert needle in text, "the grace check is not where this script expects it"
path.write_text(text.replace(needle, "            break\n", 1))
PY
```

```bash
chmod +x backend/tools/falsifications/break_streak_on_one_miss.sh
backend/tools/falsify.sh backend/tools/falsifications/break_streak_on_one_miss.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py"
```

### Step 3.7 — the UI says which days were played

In `frontend/src/components/PracticeLogView.svelte`, the streak stat (`:277-281`):

```svelte
    <div class="stat" data-streak={summary.streak_days}>
      <span class="muted small">Streak</span>
      <strong>{summary.streak_days} {summary.streak_days === 1 ? 'day' : 'days'}</strong>
      <span class="muted small">
        {summary.streak_grace_used > 0
          ? 'counting 1 rest day'
          : 'consecutive days played'}
      </span>
    </div>
```

and the `Sight-reading` cell in the week review (`:411`):

```svelte
        <span class="muted small">
          {summary.streak_days}-day streak{summary.streak_grace_used > 0 ? ' · 1 rest day' : ''}
        </span>
```

Add `streak_grace_used: number;` to `AnalyticsSummary` in `frontend/src/lib/types.ts`, after
`streak_days`.

---

## Task 4 — the weekly target

**Files.** modify `frontend/src/lib/state.svelte.ts`,
`frontend/src/components/PracticeLogView.svelte`, `frontend/src/lib/types.ts` (nothing new).

**Why.** The grace day makes a missed day survivable; a weekly target is what replaces the daily
nag with a habit the player can actually hit.

**Change Necessity.** Code: a preference and one rendered comparison.

**Impact / Compatibility.** Additive. The target is a client preference with no server field, so an
older server is unaffected.

### Step 4.1 — the preference

In `frontend/src/lib/state.svelte.ts`, add the key beside the others:

```ts
const WEEKLY_TARGET_STORAGE_KEY = 'srt.weeklyTargetDays';
```

the reader:

```ts
function readWeeklyTarget(): number {
  try {
    const value = Number(localStorage.getItem(WEEKLY_TARGET_STORAGE_KEY));
    return Number.isInteger(value) && value >= 1 && value <= 7 ? value : 4;
  } catch {
    return 4;
  }
}
```

the field beside `countInBars` (or `bars` when 20b has not landed):

```ts
  /** Days a week the player is aiming for. A preference, never a score or a streak input. */
  weeklyTargetDays = $state(readWeeklyTarget());
```

and the setter beside `setBars`:

```ts
  setWeeklyTargetDays(value: number): void {
    if (!Number.isInteger(value) || value < 1 || value > 7) return;
    this.weeklyTargetDays = value;
    try {
      localStorage.setItem(WEEKLY_TARGET_STORAGE_KEY, String(value));
    } catch {
      // Storage may be unavailable (private mode); the in-memory value still works.
    }
  }
```

### Step 4.2 — the card

In `frontend/src/components/PracticeLogView.svelte`, the `Practised` cell (`:401-407`) already counts
days played; make the target explicit:

```svelte
      <div data-week-target={app.weeklyTargetDays}>
        <span class="muted small">Practised</span>
        <strong>{formatMinutes(summary.calendar.slice(-7).reduce((sum, day) => sum + day.minutes, 0))}</strong>
        <span class="muted small">
          on {summary.calendar.slice(-7).filter((day) => day.minutes > 0).length} of
          {app.weeklyTargetDays} target days
        </span>
      </div>
```

and the control, beside the window selector at the top of the card (`:239-247`):

```svelte
        <label class="muted small" for="weekly-target">Target</label>
        <select
          id="weekly-target"
          value={app.weeklyTargetDays}
          onchange={(event) =>
            app.setWeeklyTargetDays(Number((event.currentTarget as HTMLSelectElement).value))}
        >
          {#each [1, 2, 3, 4, 5, 6, 7] as days (days)}
            <option value={days}>{days} days/week</option>
          {/each}
        </select>
```

### Step 4.3 — verify

```bash
cd frontend && npm test && npm run check && npm run build
```

---

## Task 5 — the browser proves it, and the docs record it

**Files.** modify `backend/tools/e2e_browser.py`, `README.md`, `AGENT-LOG.md`,
`docs/ECOSYSTEM.md`.

### Step 5.1 — the browser assertions

In `scenario_practice_log`, after the split/merge assertions (the block around
`"a segment can be split at a chosen point"` and `"and merged back with its neighbour"`, `:2150-2170`),
add:

```python
    # --- an edit can be taken back, and a re-segment cannot ---
    page.wait_for_selector("[data-undo]", timeout=10_000)
    before = page.locator(".segment").count()
    with page.expect_response(lambda r: "/api/practice/segments/" in r.url and "/merge" in r.url):
        click_button(page, "Undo merge")
    page.wait_for_timeout(600)
    check(
        page.locator(".segment").count() == before + 1,
        "Undo merge puts the boundary back",
    )
    check(
        page.locator("[data-undo]").count() == 0,
        "and the offer is gone, because there is nothing further to reverse",
    )
    check(
        page.locator("[data-streak]").count() == 1,
        "the dashboard reports the streak and whether a rest day is counted",
    )
    check(
        page.locator("[data-week-target]").count() == 1,
        "and the week review names the target",
    )
```

### Step 5.2 — run the scenario

```bash
cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh practice_log
```

Expected: every assertion `ok`, ending `All browser scenarios passed.`

### Step 5.3 — docs

`README.md`, in the practice-log bullets, after the segment-tagging bullet:

```markdown
- **An edit can be taken back.** Splitting, merging and re-tagging a segment are reversible: after
  any of them the timeline offers *Undo split*, *Undo merge* or *Undo label*, and it works by
  reversing that one change exactly. The offer lasts until the page is reloaded, and re-segmenting
  is the exception — it throws every boundary away and rebuilds them, so it says so before it runs.
- **The streak forgives one rest day a week.** A single missed day does not end it, the dashboard
  says when a rest day is being counted, and two missed days inside the same week do. Today not
  being played yet never counts against you. The week review also names your target —
  *"on 3 of 4 target days"* — which is a preference rather than a score.
```

`AGENT-LOG.md` gains a landed entry naming: the pure inverse module, that no table or persisted undo
record was added (20-D3), that `streak_days` keeps its meaning for an unbroken week, the one thing
undo cannot restore (the absorbed segment's `identification_outcomes` row), and the falsifications.

`docs/ECOSYSTEM.md`: the Phase 20 row becomes `**20a–20c landed; 20d–20e planned.**`, and the 20c
heading is marked `— landed` with a pointer to this plan.

### Step 5.4 — the full tier and the commit

```bash
./check.sh --full
git add -A frontend/src backend/app backend/tests backend/tools docs README.md AGENT-LOG.md
git commit -m "Phase 20c: log trust and habit"
```

---

## Risks

| Risk | Treatment |
| --- | --- |
| Undo restores the wrong thing and makes the log worse | The inverse is derived by *diffing the rows*, not by remembering which button was pressed, so it cannot disagree with what actually happened. Eight unit tests cover the three reversible shapes and the two that must return null |
| A player expects undo to survive a reload | The card says "this offer lasts until the page is reloaded", which is 20-D3's honest limitation rather than a hidden one |
| The grace day becomes a way to report a streak that was not earned | `streak_grace_used` is a separate field the UI renders, so the run length and the days played are never conflated; the value for an unbroken week is asserted to be 0 |
| The new streak rule silently changes an existing number | `test_an_unbroken_week_is_unchanged_by_the_grace_rule` and the three pre-existing `streak_days` assertions pin it. Nothing changes for a week with no missed day |
| A run opens on a rest day and reports a bogus streak | `test_a_streak_never_opens_on_a_rest_day` covers the fortnight-away case, which is the one the naive implementation gets wrong |

**A falsification deliberately not written.** The tempting extra break — "a segment's practice_kind
must not affect the streak" — has no assertion to fail, because the streak counts sittings and never
reads kinds. It is named here so the absence is visible rather than forgotten.

## Retirement

- **Nothing is retired.** `streak_days` is renamed to `streak` internally and keeps its meaning; the
  three existing assertions that read it through the API are untouched.
- **The undo stack is not persisted**, so there is no table to retire and nothing to migrate. If a
  persisted history is ever wanted, that is a new decision with a new owner, not an extension of
  this field (20-D3).
- **`segmentUndo.ts`** is one file with no consumer but `PracticeLogView`; deleting both the file and
  the `[data-undo]` block removes the feature with no residue.

## ADR / baseline-sync signals

- **20-D3** is implemented as written: no persisted undo record, `resegment` irreversible. The
  sequence that would make it a durable record — a `practice_edits` table with a backup-table-list
  entry — is explicitly *not* taken, and the reason (a remembered undo across a reload would apply
  to a different list) is in the code comment.
- **20-D6** is implemented with the run-length reading of "streak" and `streak_grace_used` as the
  explanation field. If the player later prefers the days-played reading, it is one function.
- On completion the baseline-sync question is: *does `streak_days` still mean the same thing for a
  week without a missed day?* The answer must be yes, and Step 3.1 is the evidence.

---

```text
Execution Readiness View:
- Intent Lock: reversible timeline edits with no persisted history, a re-segment that says it is
  not reversible, and a streak that forgives one rest day in seven and says so
- Scope Fence: in — segmentUndo.ts, the Undo control, the confirm copy, the streak rule and its
  field, the weekly target, one browser assertion, docs. Out — a persisted undo table, undo for
  re-segment or for answering the matcher, per-piece streaks, a server-side weekly target
- Baseline Lock: ECOSYSTEM.md § 20c + 20-D3/20-D6; TEST-STRATEGY.md §8; the re-read gate at the top
- Approved Behavior: 20c's four acceptance bullets
- Owner / Contract Constraints: `edit()` is the single funnel for an undo offer; the inverse is a
  pure function of the two segment lists; the streak owns the rule and the field reports the grace
- Compatibility Boundary: one additive summary field; no schema change; `streak_days` unchanged for
  an unbroken week; `resegment` behaviour unchanged
- Retirement Boundary: nothing retired; no persisted state added
- Task Batches: 1 the pure inverse, 2 the control, 3 the streak, 4 the weekly target, 5 browser +
  docs + commit
- Test Obligations: eight inverse units, five streak tests, one browser assertion, two committed
  break scripts, one documented temporary break for the resegment copy
- Review Gates: after Task 2 (undo works end to end in the unit tier) and after Task 5 (--full green)
- Drift / Rewind Rules: if a step needs a table, an extra route, or the inverse to know which button
  was pressed, stop and return to the spec
- Evidence Required Before Completion: ./check.sh --full passing; both falsifications reported as
  "falsified"; the pre-existing streak assertions still green; the AGENT-LOG entry appended
- Advisory Boundary: method-pack execution guidance only; not GateDecision, PolicySnapshot, or
  completion authority
```

```text
Execution Route:
- Decision: inline
- Evidence: five tasks, sequential on two files, with a fast pure tier for the substantive half
- Fallback: none needed
- User confirmation required: no
```

**Next step:** after 20c, write `PLAN-PHASE20D.md` (journal and library depth) and
`PLAN-PHASE20E.md` (audio takes) against the tree as it then stands.
