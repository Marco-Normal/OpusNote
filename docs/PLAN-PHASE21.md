# Plan — Phase 21: the log at speed, and the blur you can find

**Parent spec:** [`ECOSYSTEM.md`](./ECOSYSTEM.md) § *Phase 21*. That section owns what and why; this
document owns the how.

**Status: landed** (2026-09-16). **The requested ordering was not followed** — 20e landed first, then
20b, 20d and 20c. See `ECOSYSTEM.md` § *Phase 21*.

**Corrected 2026-09-23: Task 3 rendered the blur one segment too late.** This document contradicted
itself and both halves were built faithfully. **Step 3.1** declares `pedal_blur_ms` *"in ms from the
start of the sitting"* — which is what the backend does, and what
[`FEATURES.md`](./FEATURES.md) § *Practice log* still says — while **Step 3.2**'s snippet renders
`(segment.start_ms + blurMs)`, adding the segment's offset to a value that already contains it. The
timeline followed the snippet, so a blur in the second segment was drawn a whole segment-length too
late: outside its own segment, and past the end of the strip when the sitting was short enough that
the doubled offset exceeded its length. The row's clock times were wrong the same way, in two more
places. Nothing caught it because every fixture put its blur in the segment at offset 0, where the
two conventions are the same number — so this is the plan's defect, not the implementation's. The
four render sites no longer add the offset; the convention is now stated in
`frontend/src/components/SegmentTimeline.svelte`, pinned by
`test_a_blur_position_is_measured_from_the_sitting_not_its_segment` and by three assertions in
`scenario_practice_log`, and the snippets below are kept as written rather than rewritten. See
`AGENT-LOG.md` 2026-09-23.

**Goal.** Two things that make the practice log hard to use on real data:

1. **The pedal blur count tells you how many and not where.** The newest sitting on the real
   installation reports 14 blur attacks across two segments — nine of them in one segment — and the
   payload carries only the number. "Nine blurs" in a 2,000-note segment is a fact you cannot act on.
2. **Every timeline edit reloads the world.** Measured against the live installation, read-only:

   | Request | Time |
   | --- | --- |
   | `/api/practice/autotag/quality` | **866 ms** |
   | `/api/practice/analytics/summary?days=30` | 96 ms |
   | `/api/practice/sittings?limit=50` | 56 ms |
   | `/api/progress/ratings?days=7` | 53 ms |
   | `/api/status/system` | 16 ms |
   | `/api/practice/sittings/{id}` | 12 ms |

   `PracticeLogView.load()` awaits five of those **in sequence** after every label, split, merge and
   kind change, and it discards the segments the mutation already returned. That is about **1.05 s of
   server time per click**, on a machine that is not the bottleneck.

**Architecture.** Two independent changes with one thing in common — both are about the log telling
you something useful at the speed you work.

* The blur positions are computed by the function that already counts them (`pedal.py`), cached in
  the same row as the count by the refresh that already runs (`segment_metrics`), and drawn on the
  strip the timeline already has.
* The edit path stops fetching what an edit cannot change: the mutation's own response updates the
  timeline, and only the cheap totals are refreshed.

**Tech stack.** Python/SQLite for the rule and the cache; Svelte 5 for the markers and the refresh
tiers; pytest and Playwright for the tiers.

**Baseline / authority refs.**

- `docs/ECOSYSTEM.md` § Phase 20 § 18b (the pedal figures and their basis), § Phase 20 § 20e (the
  payloads this must not bloat).
- `docs/PLAN-PHASE20C.md` — **its Task 2 rewrites the same `edit()` function this plan rewrites.**
  See *Impact on the queued slices* below.
- `docs/TEST-STRATEGY.md` §8 (the standing rule) and §2 (test the space).
- The live installation at `http://192.168.15.7:8000`, read-only, for the measurements above.

**Re-read gate.** Written against the tree at `3a74891` plus the correction commits after it. Before
Task 1:

```bash
cd /home/marco_normal/tmp/SighRTracker
grep -n "def blurs" -A 8 backend/app/practice/pedal.py
grep -n "pedal_blur" backend/app/practice/store.py | head
grep -n "async function load" -A 30 frontend/src/components/PracticeLogView.svelte
grep -n "async function edit" -A 14 frontend/src/components/PracticeLogView.svelte
git status --porcelain   # must print nothing before any falsification
```

**Compatibility boundary.** One additive nullable `segment_metrics` column, one new list on
`SegmentMetricsOut`, and no route, request or response *shape* change otherwise. `SCHEMA_VERSION`
2 → 3. **This moves the numbers the queued plans expect** — see *Impact on the queued slices*.
`BACKUP_VERSION` unchanged (the table list is derived; a JSON column rides along like the others).

```text
TDD Route:
- Mode: auto
- Decision: strict
- Strict authority: docs/TEST-STRATEGY.md §8, the standing rule
- Strict signals: persistence (a column and a frozen-shape tripwire), a public contract (a new field
  on an existing response), and a behaviour change (an edit no longer refetches three panels)
- Light eligibility: not applicable
- Test posture: strict RED first for the rule, the cache invariant and the refresh tiers; the browser
  assertions are watched to fail with a break applied
- Verification: ./check.sh --fast after every task; ./check.sh --full before the phase is called done
```

```text
Change Necessity:
- User-visible need: "saying that it found 4 spots blurry, on a 1 hour sitting, is kinda useless if it
  don't tell me where"; and label/split/merge stalls of one to two seconds
- No-change / non-code option: insufficient — a count cannot be turned into positions by reading it
  differently, and no configuration removes a request from the edit path
- Why code change is necessary: the positions are not computed anywhere, and `load()` is called by
  `edit()` by construction
- Minimum change boundary: pedal.py, one segment_metrics column, _refresh_metrics, one models field,
  SegmentTimeline, PracticeLogView's load/edit split, tests, falsifications, docs
- Decision: code-change
```

```text
Existence Check:
- Proposed new surface: `PedalMetrics.blur_at_ms`; `segment_metrics.pedal_blur_ms`;
  `SegmentMetricsOut.pedal_blur_ms`; two functions in `PracticeLogView`
- Existing owner / reuse candidate: `pedal.blurs` owns the rule and `segment_pedal` already calls it
  per segment; `_refresh_metrics` already computes and stores `pedal_blur` for that segment;
  `SegmentMetricsOut` already carries the count to the client; `SegmentTimeline` already has the strip
- Why existing surface is insufficient: the count has no positions to give; recomputing them on the
  detail read would put a pass over `note_events` on the read the timeline uses constantly, which is
  the opposite of what this phase is for
- Creation proof: the positions are the same computation the count already performs, so caching them
  adds no arithmetic and one JSON encode; the acceptance below cannot be met otherwise
- Entropy / retirement impact: one column whose value is derivable from the notes, like every other
  `segment_metrics` column — the table stays "a cache of a pure function", and dropping the column
  loses nothing that `_refresh_metrics` cannot rebuild
- Decision: add-with-proof for the column and the field; reuse-existing for the rule and the strip
```

```text
Plan-Time Complexity Check:
- Target files: backend/app/practice/{pedal,store,models}.py, backend/app/practice/schema.py,
  frontend/src/components/{SegmentTimeline,PracticeLogView}.svelte, frontend/src/lib/types.ts
- Existing size / shape signals: `PracticeLogView.load()` is one function doing two jobs (totals and
  panels); `_refresh_metrics` already computes the blur; `SegmentTimeline` already renders per-segment
  facts and a positioned strip
- Owner fit: the rule belongs in `pedal.py`; the cache write belongs in `_refresh_metrics`; the tier
  split belongs in `PracticeLogView`
- Add-in-place risk: adding markers without the column would mean recomputing on every detail read
- Better file boundary: none needed; this is four small edits and two new functions
- Recommendation: edit-in-place
```

---

## Files

**Create**

| Path | Why |
| --- | --- |
| `backend/tools/falsifications/drop_blur_positions.sh` | Break the count/positions invariant |
| `backend/tools/falsifications/reload_everything_after_an_edit.sh` | Restore the stall |

**Modify**

| Path | Change |
| --- | --- |
| `backend/app/practice/pedal.py` | `blur_attacks()` returns the onsets; `PedalMetrics.blur_at_ms`; `blurs()` delegates |
| `backend/app/practice/schema.py` | `segment_metrics.pedal_blur_ms` in the CREATE and in `ADDED_COLUMNS` |
| `backend/app/db.py` | `SCHEMA_VERSION` 2 → 3 |
| `backend/app/practice/store.py` | `_refresh_metrics` stores the positions; `_segment_rows` reads them |
| `backend/app/practice/models.py` | `SegmentMetricsOut.pedal_blur_ms` |
| `backend/tests/test_pedal.py`, `test_practice_store.py`, `test_migration_upgrade.py` | The rule, the invariant, the frozen shape |
| `frontend/src/lib/types.ts` | `SegmentMetrics.pedal_blur_ms` |
| `frontend/src/components/SegmentTimeline.svelte` | Blur markers on the strip, and the times in the row |
| `frontend/src/components/PracticeLogView.svelte` | `refreshTotals()` split out of `load()`; `edit()` applies the response |
| `backend/tools/e2e_browser.py` | Two assertions in `scenario_practice_log` |
| `README.md`, `AGENT-LOG.md`, `docs/ECOSYSTEM.md` | docs |

---

## Task 1 — the rule says where, not just how many

**Files.** modify `backend/app/practice/pedal.py`, `backend/tests/test_pedal.py`.

**Why.** The count is computed by a loop that already knows the answer; it throws the position away.

**Change Necessity.** Code: nothing computes positions.

**Impact / Compatibility.** `PedalMetrics` gains a field with a default, so every existing
constructor and test keeps working.

### Step 1.1 — write the failing test

Append to `backend/tests/test_pedal.py`, beside the blur tests (`:81-137`):

```python
def test_the_blur_positions_are_where_the_blurs_are() -> None:
    """Two blurs, and the onsets they happened at — the count alone cannot be acted on."""
    notes = [
        note(0, 60, 200),     # ringing on the pedal from 200 ms
        note(500, 65, 200),   # a triad that does not contain C: blur at 500
        note(500, 67, 200),
        note(500, 69, 200),
        note(1_500, 71, 200),  # a chord sharing only one class with what is ringing: blur at 1500
        note(1_500, 73, 200),
        note(1_500, 76, 200),
    ]
    stretches = intervals([(0, 127), (3_000, 0)])
    assert blur_attacks(notes, stretches) == [500, 1_500]
    assert blurs(notes, stretches) == 2, "and the count is their length"


def test_the_count_and_the_positions_can_never_disagree() -> None:
    """One owner: `blurs` is defined as the length of `blur_attacks`, not a second loop."""
    notes = [
        note(0, 60, 200),
        note(500, 65, 200),
        note(500, 67, 200),
        note(500, 69, 200),
    ]
    stretches = intervals([(0, 127), (2_000, 0)])
    assert blurs(notes, stretches) == len(blur_attacks(notes, stretches))


def test_no_pedal_means_no_positions_either() -> None:
    assert blur_attacks([note(0, 60, 200)], []) == []
    assert blur_attacks([], intervals([(0, 127), (1_000, 0)])) == []
```

with `blur_attacks` added to that module's import list.

### Step 1.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_pedal.py -k blur_positions
```

Expected: `ImportError: cannot import name 'blur_attacks'`.

### Step 1.3 — the function

In `backend/app/practice/pedal.py`, add to `PedalMetrics`:

```python
    #: Where the blur attacks were, in ms relative to the sitting, ascending. `blur` is
    #: `len(blur_at_ms)` and is never computed separately, so the number and the places can
    #: not disagree — which is exactly the failure a second loop would eventually produce.
    blur_at_ms: tuple[int, ...] = ()
```

Rename the existing `blurs` body to `blur_attacks` and return the onsets:

```python
def blur_attacks(notes: list[Note], stretches: list[PedalInterval]) -> list[int]:
    """The attacks that count as blur, with their onsets.

    The rule is :func:`blurs`' rule — read that docstring, which is the one that explains why
    "the pedal is holding something" and "the attack brings new pitch classes" are both
    required. It lives here rather than there because a count with no positions cannot be
    acted on: "nine blurs" in a two-thousand-note segment says nothing about where to look,
    and the onsets cost nothing extra to produce.
    """
    if not notes or not stretches:
        return []

    ordered = sorted(notes, key=lambda note: (note.epoch_ms, note.pitch))
    found: list[int] = []
    for stretch in stretches:
        inside = [
            note
            for note in ordered
            if stretch.start_ms <= note.epoch_ms <= stretch.end_ms
        ]
        clusters: list[list[Note]] = []
        for note in inside:
            if clusters and note.epoch_ms - clusters[-1][0].epoch_ms <= 50:
                clusters[-1].append(note)
            else:
                clusters.append([note])
        for cluster in clusters:
            attack_ms = cluster[0].epoch_ms
            held: set[int] = set()
            for note in ordered:
                if stretch.start_ms <= note.end_ms < attack_ms:
                    held.add(note.pitch % 12)
            if not held:
                continue
            arriving = {note.pitch % 12 for note in cluster}
            if len(arriving - held) >= PEDAL_BLUR_MIN_NEW:
                found.append(attack_ms)
    return found


def blurs(notes: list[Note], stretches: list[PedalInterval]) -> int:
    """How many blur attacks there were. The positions are in :func:`blur_attacks`.

    <the existing docstring, unchanged>
    """
    return len(blur_attacks(notes, stretches))
```

and in `segment_pedal`:

```python
    stretches = intervals(pedals, span)
    found = blur_attacks(notes, stretches)
    return PedalMetrics(
        recorded=True,
        changes=changes(pedals),
        down_ratio=down_ratio(pedals, span),
        blur=len(found),
        blur_at_ms=tuple(found),
    )
```

### Step 1.4 — verify GREEN and falsify

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_pedal.py
```

Create `backend/tools/falsifications/drop_blur_positions.sh`:

```bash
#!/usr/bin/env bash
#
# Break: report only the first blur position, so the places stop matching the count.
#
# The test that must catch it is the count/positions agreement in test_pedal.py — and, through
# the cache, the invariant in test_practice_store.py.
#
#   ./falsify.sh backend/tools/falsifications/drop_blur_positions.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_pedal.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/pedal.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "    return found\n"
assert text.count(needle) == 1, "the return is not where this script expects it"
path.write_text(text.replace(needle, "    return found[:1]\n", 1))
PY
```

---

## Task 2 — the positions are cached beside the count

**Files.** modify `backend/app/practice/schema.py`, `backend/app/db.py`,
`backend/app/practice/store.py`, `backend/app/practice/models.py`,
`backend/tests/test_migration_upgrade.py`, `backend/tests/test_practice_store.py`.

**Why.** The detail read is the one the timeline uses constantly (12 ms on the real box) and it must
not gain a pass over `note_events`. `_refresh_metrics` already computes the blur with the notes and
the pedal stream in hand, so storing the positions costs one JSON encode and nothing else.

**Change Necessity.** Code: the positions have nowhere to live.

**Impact / Compatibility.** One additive nullable column; `SegmentMetricsOut` gains a list that
defaults to empty, so an older client is unaffected.

### Step 2.1 — the failing invariant test

Append to `backend/tests/test_practice_store.py`:

```python
def test_the_stored_blur_positions_are_where_the_stored_count_says(client, conn) -> None:
    """The invariant the cache exists to keep: one number, and the places it is made of.

    Both come from the same `_refresh_metrics` pass over the same notes and the same pedal
    stream, so a disagreement means the two were computed by different code.
    """
    sitting = recent_sitting(client, [0, 500, 1_000, 4_000, 4_500])
    sitting_id = sitting["sitting_id"]
    segment_id = segment_of(client, sitting)["id"]

    with db.transaction(settings.db_path) as conn:
        # A chord released under the pedal, then a triad arriving over it: one blur at 4,000.
        conn.execute(
            "INSERT INTO pedal_events (sitting_id, onset_ms, value, channel)"
            " VALUES (?1, 100, 127, 0), (?1, 5_000, 0, 0)",
            (sitting_id,),
        )
    store._refresh_metrics(conn, sitting_id)
    conn.commit()

    metrics = store._segment_rows(conn, sitting_id)[0].metrics
    assert metrics is not None
    assert metrics.pedal_blur == len(metrics.pedal_blur_ms), (
        f"the count and the places must agree ({metrics.pedal_blur} vs {metrics.pedal_blur_ms})"
    )
```

**Adjust the note offsets to whatever actually produces a blur** — the fixture above is the shape,
and the pedal rule needs a released note under the pedal plus three new pitch classes at the attack.
Run it, look at what `pedal_blur` comes back as, and if it is 0 either change the offsets or assert
the invariant only over a sitting built for it. **An invariant test that passes on zeros proves
nothing**, so it must assert `metrics.pedal_blur >= 1` as well.

### Step 2.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_store.py -k blur_positions
```

Expected: `AttributeError: 'SegmentMetricsOut' object has no attribute 'pedal_blur_ms'`.

### Step 2.3 — the column

`backend/app/practice/schema.py`, in `segment_metrics`' CREATE after `pedal_basis`:

```sql
    -- Where the blur attacks were, as a JSON array of ms relative to the sitting, ascending.
    -- `pedal_blur` above is its length. Stored together because `_refresh_metrics` has the
    -- notes and the pedal stream in hand when it computes both, so a position costs nothing
    -- to keep — while re-deriving it on the detail read would put a pass over `note_events`
    -- on the read the timeline uses most.
    pedal_blur_ms   TEXT,
```

and to `ADDED_COLUMNS`:

```python
    ("segment_metrics", "pedal_blur_ms", "TEXT"),
```

`backend/app/db.py`: `SCHEMA_VERSION = 3`.

### Step 2.4 — the write

In `store.py`'s `_refresh_metrics`, add the column to the INSERT and to the conflict update:

```python
        conn.execute(
            "INSERT INTO segment_metrics"
            " (segment_id, duration_s, note_count, median_tempo, mean_velocity,"
            "  velocity_stddev, restarts, pedal_changes, pedal_down_ratio, pedal_blur,"
            "  pedal_blur_ms, pedal_basis, median_velocity, velocity_range,"
            "  mean_velocity_low, mean_velocity_high)"
            " VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16)"
            " ON CONFLICT (segment_id) DO UPDATE SET"
            ...
            "  pedal_blur = excluded.pedal_blur,"
            "  pedal_blur_ms = excluded.pedal_blur_ms,"
            ...
```

with `db.json_dump(list(pedalling.blur_at_ms))` in the matching parameter position. **`json_dump`,
not `json.dumps`** — the project's own compact encoder, and the one `json_load` is paired with.

### Step 2.5 — the read

`_segment_rows`' SELECT gains `m.pedal_blur_ms`, and the `SegmentMetricsOut(...)` it builds gains:

```python
                pedal_blur=data["pedal_blur"],
                pedal_blur_ms=db.json_load(data["pedal_blur_ms"], []),
```

and `backend/app/practice/models.py`:

```python
    #: Where the blurs were, in ms relative to the sitting, ascending. `pedal_blur` is its
    #: length: the count tells you whether to look, these tell you where.
    pedal_blur_ms: list[int] = Field(default_factory=list)
```

### Step 2.6 — the frozen shape

In `backend/tests/test_migration_upgrade.py`:

```python
    "segment_metrics": {
        "segment_id", "duration_s", "note_count", "median_tempo", "mean_velocity",
        "velocity_stddev", "restarts", "pedal_changes", "pedal_down_ratio",
        "pedal_blur", "pedal_blur_ms", "pedal_basis", "median_velocity", "velocity_range",
        "mean_velocity_low", "mean_velocity_high",
    },
```

and add a migration test:

```python
def test_the_upgraded_database_gains_the_blur_positions() -> None:
    """Phase 21: where the blurs were, on a database that predates the column."""
    path = _build_fixture_db("blur-columns.sqlite3")
    db.init_db(path)
    conn = db.connect(path)
    try:
        assert "pedal_blur_ms" in _columns(conn, "segment_metrics")
    finally:
        conn.close()
```

### Step 2.7 — verify GREEN and falsify

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_pedal.py tests/test_practice_store.py \
  tests/test_migration_upgrade.py tests/test_backup.py
backend/tools/falsify.sh backend/tools/falsifications/drop_blur_positions.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_practice_store.py"
```

---

## Task 3 — the timeline shows them

**Files.** modify `frontend/src/lib/types.ts`,
`frontend/src/components/SegmentTimeline.svelte`, `backend/tools/e2e_browser.py`.

**Why.** The positions are useless until they are on the picture you are already looking at.

**Change Necessity.** Code.

**Impact / Compatibility.** Additive UI.

### Step 3.1 — the type

`frontend/src/lib/types.ts`, `SegmentMetrics`:

```ts
  /** Attacks that brought new harmony over notes the pedal was already holding. */
  pedal_blur: number | null;
  /**
   * Where those attacks were, in ms from the start of the sitting, ascending.
   * `pedal_blur` is this array's length: the count says whether to look, these say where.
   */
  pedal_blur_ms: number[];
```

### Step 3.2 — markers on the strip

In `SegmentTimeline.svelte`, after the segment blocks inside `.strip` (`:377-389`), add:

```svelte
      {#each detail.segments as segment (segment.id)}
        {#each segment.metrics?.pedal_blur_ms ?? [] as blurMs (blurMs)}
          <span
            class="blur"
            data-blur={blurMs}
            style="left: {((segment.start_ms + blurMs) / total) * 100}%"
            title="Pedal blur at {formatClock((segment.start_ms + blurMs) / 1000)} — new harmony
              arrived while the pedal was holding notes from before"
          ></span>
        {/each}
      {/each}
```

and in the component's `<style>`:

```css
  /* A blur marker is a hairline: it has to be findable on a long sitting without becoming
     the loudest thing on the strip. */
  .strip .blur {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    margin-left: -1px;
    background: var(--warn, #b45309);
    opacity: 0.85;
    pointer-events: none;
  }
```

**Check the variable first** — `grep -n "\-\-warn" frontend/src/app.css`. If the token has another
name, use that one; a hardcoded colour that ignores the theme is the kind of thing this project
notices.

### Step 3.3 — the times in the row

The existing blur pill (`:414-421`) gains the places, because the strip marker tells you where to
look and the row tells you what you are looking at:

```svelte
              {#if segment.metrics.pedal_blur}
                <span
                  class="pill warn"
                  data-pedal-blur={segment.metrics.pedal_blur}
                  title="Attacks that brought new harmony over notes the pedal was already holding.
                    Observed from the pitches, not from a score — it reports, it does not judge.
                    At {segment.metrics.pedal_blur_ms
                      .map((ms) => formatClock((segment.start_ms + ms) / 1000))
                      .join(', ')}"
                >
                  {segment.metrics.pedal_blur} pedal blur
                </span>
                <span class="muted small" data-blur-where={segment.id}>
                  at {segment.metrics.pedal_blur_ms
                    .slice(0, 4)
                    .map((ms) => formatClock((segment.start_ms + ms) / 1000))
                    .join(', ')}{segment.metrics.pedal_blur_ms.length > 4 ? ' …' : ''}
                </span>
              {/if}
```

The readout is capped at four and the full list is in the tooltip: a segment can hold nine of them,
and nine clock times in a row is a wall of digits rather than a hint about where to look.

### Step 3.4 — the browser assertion

In `scenario_practice_log`, where the pedal figures are asserted (`:2065-2080`), add:

```python
    check(
        page.locator("[data-blur-where]").count() >= 1
        or page.evaluate("() => document.querySelectorAll('[data-pedal-blur]').length") == 0,
        "a blur count comes with the places it happened",
    )
```

and, when the scenario's seeded sitting does carry blurs, a positive form:

```python
    where = page.inner_text("[data-blur-where]")
    check(where.startswith("at "), f"the blur row names the times ({where!r})")
```

**The seeded sitting must actually produce a blur**, or the second assertion is skipped and the first
is vacuous. The scenario's `seed_closed_sitting` currently plays four notes with no pedal; extend it
with a pedalled chord change (a note released under CC64, then a triad over it), the same shape the
unit test uses. That is the same lesson as the invariant test above: an assertion over zeros is not
an assertion.

---

## Task 4 — an edit refreshes what an edit changed

**Files.** modify `frontend/src/components/PracticeLogView.svelte`, `backend/tools/e2e_browser.py`.

**Why.** The measured 1.05 s per click, entirely in requests an edit cannot invalidate.

**Change Necessity.** Code: `load()` is called by `edit()` by construction, and it awaits the panels
in series.

**Impact / Compatibility.** Panels now refresh on mount, on the Refresh button, and after a
`resegment` (which *can* change the matcher's record). Nothing they report becomes stale in a way a
person would notice, and the two independent reads become parallel rather than sequential.

### Step 4.1 — split the refresh into tiers

Replace `load()` in `PracticeLogView.svelte` (`:99-124`) with:

```ts
  /**
   * What an edit can change: the totals and the sitting list.
   *
   * Cheap — 96 ms and 56 ms on the real library, and they go together — and it is the half of
   * `load` that a label genuinely invalidates.
   */
  async function refreshTotals(): Promise<void> {
    const [nextSummary, nextSittings] = await Promise.all([
      api.practice.summary(days),
      api.practice.sittings(50),
    ]);
    summary = nextSummary;
    sittings = nextSittings;
  }

  /**
   * The whole dashboard: once on mount, and from Refresh.
   *
   * The three panels below are reads about the *library* and the *machine*, and they are the
   * expensive ones — the matcher's leave-one-out accuracy measured 866 ms on the real library,
   * against 96 ms for the totals. They used to be refetched after every label, split and merge,
   * which is where a one-second stall per click came from.
   *
   * `allSettled` rather than `all`: none of the three may take the log down, and in series they
   * cost the sum of their times rather than the longest.
   */
  async function load(): Promise<void> {
    try {
      await refreshTotals();
      const [nextWeek, nextSystem, nextQuality] = await Promise.allSettled([
        api.progressRatings(7),
        api.systemStatus(),
        api.practice.identificationQuality(),
      ]);
      week = nextWeek.status === 'fulfilled' ? nextWeek.value : null;
      system = nextSystem.status === 'fulfilled' ? nextSystem.value : null;
      quality = nextQuality.status === 'fulfilled' ? nextQuality.value : null;
      await openSelectedSitting();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  /** Keep the timeline pointed at the same sitting across a refresh. */
  async function openSelectedSitting(): Promise<void> {
    if (selectedId !== null && sittings.some((row) => row.id === selectedId)) {
      await select(selectedId);
    } else if (sittings.length > 0 && selectedId === null) {
      await select(sittings[0].id);
    } else if (selectedId !== null) {
      selectedId = null;
      detail = null;
    }
  }
```

### Step 4.2 — the edit applies what the server returned

Every segment mutation already answers with the sitting's segments — `assignSegment`,
`setSegmentKind`, `splitSegment`, `mergeSegments`, `resegment` and `identify` all return
`SegmentSummary[]` — and `edit()` threw that away and refetched the same rows. Replace `edit()`
(`:136-148`):

```ts
  /**
   * Every edit applies the server's own answer, then refreshes only the totals.
   *
   * The response *is* what the timeline draws, so the edit is on screen the moment it lands, with
   * no second read of the rows that were just written and no reload of panels an edit cannot
   * have changed. `SittingDetail` carries more than its segments, but nothing an edit moves lives
   * outside them: a split changes boundaries, not the sitting's duration or its note count.
   */
  async function edit(action: () => Promise<unknown>): Promise<void> {
    busy = true;
    error = null;
    try {
      const result = await action();
      if (detail !== null && Array.isArray(result)) {
        detail = { ...detail, segments: result as SegmentSummary[] };
      }
      await refreshTotals();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = false;
    }
  }
```

`resegment` is the one edit whose *metadata* the matcher's panel depends on, so it keeps the full
load:

```svelte
      onresegment={async (confirm) => {
        await edit(() => api.practice.resegment(detail!.id, confirm));
        // Re-segmenting rebuilds the rows the matcher was measured against, so its panel is
        // the one thing here that a refresh can legitimately move.
        quality = await api.practice.identificationQuality().catch(() => quality);
      }}
```

### Step 4.3 — verify

```bash
cd frontend && npm test && npm run check && npm run build
```

### Step 4.4 — the browser assertion, and the measurement

In `scenario_practice_log`, around the tagging assertions, watch the network for the edit:

```python
    # --- an edit refreshes what an edit changed, and nothing else ---
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url))
    with page.expect_response(lambda r: "/api/practice/segments/" in r.url and r.request.method == "PATCH"):
        page.select_option('select[aria-label="Piece for this segment"] >> nth=0', str(target["id"]))
    page.wait_for_timeout(800)
    check(
        any("analytics/summary" in url for url in requested),
        "the totals are refreshed after an edit",
    )
    check(
        not any("/autotag/quality" in url for url in requested),
        "and the matcher's accuracy is not, because a label cannot change it",
    )
    check(
        not any("/api/status/system" in url for url in requested),
        "nor the machine's health",
    )
```

**This is the assertion that pins the fix**, and it is falsifiable in the strongest sense: restore
`await load()` in `edit()` and all three move the wrong way.

Create `backend/tools/falsifications/reload_everything_after_an_edit.sh`:

```bash
#!/usr/bin/env bash
#
# Break: put the full reload back on the edit path, restoring the stall.
#
# The browser assertion that must catch it is the pair in scenario_practice_log —
# "the matcher's accuracy is not [fetched]" and "nor the machine's health".
#
# The check rebuilds the frontend first: the browser tier serves `frontend/dist`, so a source
# break that is not rebuilt is a break the browser never sees.
#
#   ./falsify.sh backend/tools/falsifications/reload_everything_after_an_edit.sh \
#     "cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh practice_log"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/components/PracticeLogView.svelte"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """      await refreshTotals();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = false;
    }"""
assert needle in text, "the edit body is not where this script expects it"
path.write_text(text.replace(needle, """      await refreshTotals();
      await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = false;
    }""", 1))
PY
```

### Step 4.5 — measure it, and write the number into the log

```bash
cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh practice_log
```

Then, against a running server and with the same read-only discipline the plan opened with, time the
two paths so the improvement is a number rather than a claim:

```bash
for path in "/api/practice/analytics/summary?days=30" "/api/practice/autotag/quality" "/api/status/system"; do
  printf '%-46s ' "$path"
  curl -s -o /dev/null -w '%{time_total}s\n' "http://127.0.0.1:8000$path"
done
```

The edit path's server time is the first line; it used to be the sum of all three.

---

## Task 5 — docs and the commit

**Files.** modify `README.md`, `AGENT-LOG.md`, `docs/ECOSYSTEM.md`.

**Why.** The project's own rule: the owning document, not a sibling, and the shared log for anything
another agent must know.

### Step 5.1 — README

In the practice-log bullets, after the pedal paragraph:

```markdown
- **The pedal blur tells you where.** A blur is an attack that brought new harmony over notes the
  pedal was already holding, and the count now comes with its clock times: the sitting strip carries
  a hairline at each one, and the segment row reads *"9 pedal blur — at 1:23, 2:04, 4:11, 6:38 …"*.
  The rule is unchanged and still observed from the pitches rather than from a score; what is new is
  that "nine" is now something you can find.
- **Editing is immediate.** Labelling, splitting, merging and re-tagging apply the server's own answer
  as it arrives and refresh only the totals. The matcher's measured accuracy, the machine's health
  and the week's ratings are reads about the library, not about the edit, and they now load when the
  tab opens rather than after every click.
```

### Step 5.2 — ECOSYSTEM.md

Add the Phase 21 row to § 6 and the section this plan's parent reference points at, marked
`— landed` when it is; and put a line in `PLAN-PHASE20C.md`'s and `PLAN-PHASE20D.md`'s *Precondition*
sections noting that the `SCHEMA_VERSION` they expect has moved (see below).

### Step 5.3 — the log entry, and the commit

```bash
./check.sh --full
git add -A backend frontend docs README.md AGENT-LOG.md
git commit -m "Phase 21: blur positions you can find, and an edit path that stops reloading the world"
```

---

## Impact on the queued slices

This phase is executed **before** 20b–20e, so it moves two things those plans read as fixed:

1. **`SCHEMA_VERSION` becomes 3, not 2.** `PLAN-PHASE20D.md` Step 1.4 says "2 → 3" and
   `PLAN-PHASE20E.md` Step 2.4 says "3 → 4". After this phase they become **3 → 4** and **4 → 5**.
   Both plans carry a re-read gate that prints the current version before editing, which is what that
   gate is for, but the numbers should be corrected in the plans when this lands rather than
   discovered during execution.
2. **`PracticeLogView.edit()` is rewritten here, and `PLAN-PHASE20C.md` Task 2 rewrites it again** to
   add the undo stack. 20c's plan quotes the current body as its anchor, and its Step 2.1 will not
   match after this phase. The behaviour 20c needs is intact — `edit()` still takes the action, still
   has `before`/`after` segment lists available, and this phase's version keeps the `catch`/`finally`
   shape 20c's replacement expects — but the anchor text must be re-read at execution time. 20c's
   precondition already does exactly that (`grep -n "async function edit" -A 14`).

Neither is a defect; both are the cost of doing a fix out of order, and both are recorded here so
they are not discovered as surprises.

## Risks

| Risk | Treatment |
| --- | --- |
| An invariant test that passes on zeros | Both Task 2's invariant and Task 3's browser assertion are written to require a real blur, and the plan says so in both places; the seeded sitting has to be extended to produce one |
| A stale panel after an edit | Only `resegment` can move the matcher's panel, and it refetches it explicitly. The totals — the numbers a person watches while editing — are refreshed on every edit |
| The strip becomes unreadable on a long sitting | Blur markers are 2 px hairlines at 85% opacity and `pointer-events: none`; the count is unchanged, so the picture gains marks only where a blur actually happened |
| The JSON column drifts from the count | Impossible by construction: `blur` is `len(blur_at_ms)`, from one function, in one pass. That is what `drop_blur_positions.sh` exists to prove |
| A corrupt JSON column reads as "no positions" | It goes through `db.json_load`, which raises rather than degrading — Slice 1's T9 decision, the same path the tag arrays use |

## Retirement

- **Nothing is retired.** `blurs()` keeps its name and its meaning and becomes a length; the edit path
  keeps its shape and stops doing two extra reads.
- **The column** is a cache of a pure function like every other column in `segment_metrics`: dropping
  it and re-segmenting rebuilds it, which is the same guarantee the table already makes.

## ADR / baseline-sync signals

- **The blur count and its positions have one owner** (`blur_attacks`), and the count is defined as
  its length. That is a small but durable contract, and it belongs in the same decisions table as
  18-D3 (where the pedal numbers live).
- **The refresh tiers** encode a judgement worth recording: a panel that reads the library is not
  invalidated by an edit to one sitting. It is the kind of thing that gets quietly undone by a later
  "just refresh everything" fix, so the browser assertion exists to keep it undone-proof.

---

```text
Execution Readiness View:
- Intent Lock: blur counts that say where, and an edit path that refreshes only what an edit changed
- Scope Fence: in — the rule's positions, one cached column, the strip markers and row times, the
  load/edit split, two browser assertions and the docs. Out — any new endpoint, any change to the
  blur rule itself, any change to the notes payload, and anything in 20b-20e
- Baseline Lock: the read-only measurements from the live installation (866 ms / 96 ms / 56 ms /
  53 ms / 16 ms / 12 ms); TEST-STRATEGY.md §8; the re-read gate; a clean tree before falsification
- Approved Behavior: the two asks, verbatim — where the blurs were, and no one-to-two-second stall
  per edit
- Owner / Contract Constraints: `pedal.py` owns the rule; `_refresh_metrics` writes the cache;
  `_segment_rows` reads it; `PracticeLogView` owns the refresh tiers
- Compatibility Boundary: one additive nullable column, one additive response field; SCHEMA_VERSION
  2 -> 3; BACKUP_VERSION unchanged; the queued plans' version numbers shift by one, recorded above
- Retirement Boundary: nothing retired
- Task Batches: 1 the rule, 2 the cache, 3 the timeline, 4 the edit path, 5 docs and commit
- Test Obligations: three pedal units, one cache invariant with a non-zero requirement, one migration
  test, two browser assertions with a real blur, three browser assertions on the request log, two
  committed break scripts
- Review Gates: after Task 2 (the data is on the wire) and after Task 5 (--full green)
- Drift / Rewind Rules: if a step needs the positions recomputed on the detail read, a new endpoint,
  or the notes payload to grow, stop and return to this plan
- Evidence Required Before Completion: ./check.sh --full passing; both falsifications reported as
  "falsified"; the blur readout visible on a sitting that has one; the measured edit-path time
  recorded in AGENT-LOG.md
- Advisory Boundary: method-pack execution guidance only; not GateDecision, PolicySnapshot, or
  completion authority
```

```text
Execution Route:
- Decision: inline
- Evidence: five tasks, sequential on two backend files and one component, ending in a browser run;
  nothing here parallelises usefully
- Fallback: none needed
- User confirmation required: no
```
