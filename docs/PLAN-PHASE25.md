# Plan — Phase 25: only what changed is re-derived

**Parent spec:** [`ECOSYSTEM.md`](./ECOSYSTEM.md) § *Phase 25*, which owns the *what* and the
*why*. This document owns the *how*.

**Status: landed.**

**Goal.** A label click stops paying for the whole reference set. `store.cached_references` keeps
its derivation **per labelled segment** and, when `reference_state.version` moves, re-derives only
the segments whose inputs actually moved. Measured on the local real-data fixture: the read a label
click triggers goes **1,973 ms → ~5 ms**, and the suggestions it answers with are unchanged.

**Non-goals.**

* No change to the matcher. `similarity.py`, `shingles.py`, `rank`, `identify`, the weights, the
  bands and the write policy are all untouched, and the incremental result is required to be
  *equal* to a full rebuild rather than merely close.
* No schema change, no new trigger, no migration, no route, no request or response field, no new
  tunable, no background job, no second cache. The database keeps owning invalidation exactly as
  Phase 24 left it; this phase changes what a *miss* costs, not when one happens.
* Not the frontend. An optimistic write queue was measured against this fix last session and loses:
  it moves the work off the click without making it cheaper (29,796 ms of work per 17 clicks either
  way). After this lands the click is ~167 ms, six clicks a second, and a queue would hide 167 ms.
  If that is still too slow on the notebook, it is its own decision with its own plan.
* Not the uncached helpers in §7. They become reachable only from an argument nobody passes, and
  retiring them changes a helper's contract for no part of this fix.

---

## 1. The measurements this plan rests on

Rebuilt from the backup [`TEST-DATA.md`](./TEST-DATA.md) owns — **512,010 note events, 1,151,770
pedal events, 38 sittings, 682 segments of which 443 are labelled, 7 pieces**. Shapes, not
promises: re-measure before quoting one.

**What one label click costs today**, on a sitting that still has undecided segments (17 of them) —
which is the tagging case, because `candidates_for_sitting` early-returns the moment the last one
is labelled (§1.4 of [`PERFORMANCE.md`](./PERFORMANCE.md)):

| | click waits | work the click causes |
| --- | ---: | ---: |
| **today** | `write 3.9 + detail 1,975.2` = **1,979 ms** | **1,753 ms** |
| full rebuild pushed to a worker | `2.3 + 46.4` = 49 ms | **1,753 ms** — unmoved |
| **this plan** | `3.9 + 1.1 + 162` = **167 ms** | **1.1 ms** |

Over 17 clicks: today waits 33,644 ms and does 29,796 ms of derivation work; a worker waits 828 ms
and still does 29,796 ms; this plan waits 2,841 ms and does **18 ms**. The 162 ms that remains per
click is the matcher ranking 17 undecided segments against 443 references — the useful work that
produces the suggestions, and the reason a click is not 1 ms afterwards.

**Where the 1,753 ms goes.** The derivation is two passes and a fold, and only the first is the
database:

| stage | cost |
| --- | ---: |
| `_notes_for_segments` — every labelled **sitting read whole**, then sliced per segment | ~1,010 ms |
| `fingerprint` + `shingles.features` for 443 segments (396,219 `Note` objects) | ~700 ms |
| `_pool_features` — 443 Counters folded into 7 | 16 ms |

**It grows with the library, and has been.** On the older 238,665-note backup, the same probe
measured 27 / 73 / 151 / 369 ms at 49 / 100 / 200 / 400 labelled segments — the series tracks the
labelled *notes* it reads, not the label count, because a segment's read is its whole sitting.

**The incremental path, measured on the same fixture** (one label moved between pieces):

| stage | cost |
| --- | ---: |
| `_labelled_rows` and the diff against the cached inputs | 0.33 ms |
| one **range** read: `WHERE sitting_id = ? AND onset_ms BETWEEN ? AND ?` (141 notes, not 30,000) | 0.107 ms |
| one `fingerprint` + one `shingles.features` | 0.237 ms |
| pool: subtract the old contribution, add the new | 0.381 ms |
| **total** | **1.1 ms** |

Re-pooling all 443 segments instead of adjusting one costs 16.25 ms of that 16.9 ms total — which
is why the pool is adjusted in O(1) rather than rebuilt, even though rebuilding it would already be
a 100× improvement.

**Why the range read is the whole trick.** `_notes_for_segments` fetches a sitting's entire note
list and binary-searches each segment's slice out of it (14.1 ms for one segment); a range query on
`idx_events_sitting(sitting_id, onset_ms)` returns only the segment's notes (0.107 ms). Nothing is
cached to get that — it is `R9` in `PERFORMANCE.md` applied honestly.

---

## 2. Change necessity — why code

No configuration, documentation or data change can make this cheaper. The cost is a Python loop over
every labelled segment's notes, executed whenever the database's own version counter moves, and the
counter is *supposed* to move on a label click — that is the invalidation working. Nothing here is a
threshold that can be tuned, an index that is missing, or a cap that could be raised:

* **Bounding it by discarding references is forbidden** (`R5`, and Phase 22b's measured reason): a
  newest-N window evicted pieces outright and answered with the wrong piece.
* **Narrowing the trigger further is impossible**: Phase 24 already reduced it to exactly the
  columns the derivation is a function of. What is left is the legitimate case — a label moved.
* **Storing the result is not the answer either**: the design deliberately computes suggestions
  from the labels you have *now* (`PERFORMANCE.md` §1.3, "derived-on-read is a correctness virtue").
  The cache is already the compromise, and it is the right one.

So the only remaining lever is the one this phase takes: **when the inputs move, re-derive the
inputs that moved instead of all of them.** Minimum code boundary: `store.py`'s reference-cache
section — the `_REFERENCES` entry shape and the miss path of `cached_references`, plus one new
private read helper. `cached_references` keeps returning the same 3-tuple; no caller changes.

---

## 3. The design

### 3.1 What the cache entry holds

Today: `(version, examples, local, pooled)`. The version says *that* something moved and nothing
about *what*, which is why a miss can only start over. The entry gains the inputs it was built from:

```python
#: {segment_id: (sitting_id, start_ms, end_ms, piece_id)} — the four facts the per-segment
#: derivation is a function of, and the diff is taken against this.
_REFERENCES: dict[str, tuple[int, dict[int, tuple[int, int, int, int | None]],
                              list[Example],
                              dict[int, collections.Counter],
                              dict[int, collections.Counter]]]
```

`piece_id` belongs in the key because it decides which pooled signature a segment's features are
added to; `start_ms`/`end_ms`/`sitting_id` because together they decide which notes are read.

**`identified_by` deliberately does not.** It decides *membership*, and `_labelled_rows` has already
applied that filter by the time the diff runs — but it is not an input to a fingerprint or a content
feature, so a row that changes between two reference states (`manual` → `workout`) does not need
re-deriving. That is the same reasoning Phase 24 used to narrow the trigger, applied one level
further down; the trigger must still fire, because the membership transition is real.

### 3.2 The diff

On a version miss, with an entry for the same database file present:

```python
rows = _labelled_rows(conn)                     # 0.33 ms
current = {int(r["id"]): _reference_inputs(r) for r in rows}
removed = cached_inputs.keys() - current.keys()
added   = current.keys() - cached_inputs.keys()
changed = [i for i in current.keys() & cached_inputs.keys()
           if current[i] != cached_inputs[i]]
```

`removed` needs no read: the contribution is subtracted from the pool and the entry dropped.
`added | changed` is exactly the set that must be read and derived.

### 3.3 The update

For each segment in `added | changed`, read its own notes and derive one fingerprint and one feature
Counter. Then, **copy-on-write**:

* `local` — a new `dict` sharing the unchanged segments' `Counter` objects (they are never mutated,
  so sharing them is safe), with the removed keys dropped and the changed/added ones replaced.
* `pooled` — a new `dict` whose affected pieces' `Counter`s are **copies**, because
  `Counter.subtract` mutates its target. For each moved segment: subtract its old features from its
  old piece, add its new features to its new piece.
* `examples` — rebuilt from the current rows in `_labelled_rows`' own order
  (`ORDER BY g.sitting_id, g.start_ms`), taking each `Fingerprint` from the derived-or-cached map.
  This is O(labels) over ~443 tiny objects, and it is what makes the list *identical* to a full
  rebuild rather than merely equivalent as a set.

### 3.4 Two traps this design has to close deliberately

**A piece that loses its last label must leave `pooled` entirely.** `Counter.subtract` leaves
zero-valued keys, and a piece left behind as an *empty* Counter is not inert: `shingles.idf` counts
it as a document (`count = max(1, len(signatures))`), which shifts every IDF weight and therefore
every score — a silent, library-wide change in the suggestions. (It does not crash:
`containment` guards its zero denominator.) So the affected pieces are pruned after subtraction and
a piece whose Counter is empty is **removed from the dict**, so the key set is exactly what a full
rebuild would produce. The equivalence test compares key sets, not just the counters — the probe
that justified this design normalised empty counters away before comparing and would not have
caught this.

**The example list must keep a full rebuild's order.** `rank`/`identify` see a list, not a set.
Rebuilding it from the row order closes any tie-breaking difference before it can exist.

### 3.5 Why this needs no lock

`practice/jobs.py`'s daemon thread and request threads both call `cached_references`. The update is
still safe without a mutex, and the argument is worth writing down rather than relying on:

* **Copy-on-write** means a published entry is never mutated, so a concurrent reader sees either the
  old entry or the new one, never a torn one.
* **The version check is conservative in the right direction.** An entry is filed under the version
  read at the top of the call and is served only while the database still reports that version. Its
  content is derived from rows read at or after that version; versions never move backwards and
  `note_events` is append-only, so a mismatched entry is never served — the worst case is a wasted
  entry and one extra rebuild. The existing full-rebuild path has exactly the same property.

If a future change makes the derivation depend on something that can *decrease*, this argument stops
holding and a lock becomes necessary. That is the trigger to revisit, and it is recorded here rather
than discovered later.

---

## 4. Tasks

TDD route: **strict** (repository convention; `store.py` is shared core, the change is a cache
contract, and the failure mode is silently wrong suggestions). Each task writes the failing test
first and watches it fail for the stated reason.

### T1 — the range read, and the entry that knows its inputs

* **Files:** `backend/app/practice/store.py`.
* **Change:** add `_reference_inputs(row)` and `_notes_in_range(conn, sitting_id, start_ms,
  end_ms)`; widen the `_REFERENCES` entry to carry the inputs. The miss path still does a full
  rebuild — this task is the plumbing only, so the work-count test can fail first.
* **Test (RED first):** `test_one_label_change_re_derives_only_that_segment` — count calls to
  `_notes_in_range` and to `_notes_for_segments` across a relabel; assert the range read ran once
  and the whole-sitting read did not run at all. Fails today because neither helper's count moves
  (the whole set is re-read instead).
* **Compatibility:** none observable; `cached_references` still returns a 3-tuple.

### T2 — the incremental derivation and the O(1) pool

* **Files:** `backend/app/practice/store.py`.
* **Change:** on a miss with a usable base entry, diff, derive only `added | changed`, copy-on-write
  `local`/`pooled`, adjust the affected pieces' Counters, rebuild `examples` in row order, prune
  empty pieces (§3.4), and file the entry under the version read at the top.
* **Test (RED first),** in `backend/tests/test_autotag.py` beside the existing invalidation tests:
  * `test_the_incremental_references_equal_a_full_rebuild` — after each of *add a label*, *relabel to
    another piece*, *change a boundary*, *delete a labelled segment*: compare the incremental triple
    against `forget_references()` + a full rebuild, **including the `pooled` key set**, the `local`
    key set, and the `examples` list element for element in order.
  * `test_moving_a_label_between_pieces_moves_its_contribution_only` — the old piece's signature
    lost exactly that segment's features and the new one gained them, by Counter equality.
  * `test_a_piece_that_loses_its_last_label_leaves_the_pooled_signatures` — the trap in §3.4: after
    moving a piece's only label away, the piece is gone from `pooled` and `shingles.idf` sees the
    same document count a full rebuild would give it.
  * `test_a_cold_cache_still_builds_from_scratch` — `forget_references()` then a read still produces
    the full answer (no base entry is not an error).
* **Compatibility:** none. Same return shape, same invalidation owner.

### T3 — the head-to-head measurement, recorded

* **Files:** `backend/.scratch/` (gitignored) — extend the existing probe.
* **Change:** measure one label click three ways on the current fixture (today / a full rebuild moved
  off the click / this plan) and the nine-stage breakdown of the incremental path, so the numbers in
  §1 and in `PERFORMANCE.md` §1.10 have a re-runnable source.
* **Also measure, and record honestly:** the *worst* case — every labelled segment changed at once —
  because "always incremental" is only justified if there is no volume at which starting over wins.
  If the worst case turns out worse than a full rebuild, add the threshold then, with the measured
  crossover in the docstring; do not add one on speculation.
* **No test.** This is evidence, not an assertion.

### T4 — three falsifiers, committed and proven

* **Files:** `backend/tools/falsifications/`.
* **Change:** one break script per assertion this phase adds, each naming its test in `# EXPECT`:
  * `rebuild_every_reference_for_one_label.sh` — makes the miss path start over, so the work-count
    test in T1 fails;
  * `forget_the_old_piece_when_a_label_moves.sh` — skips the subtraction, so the equivalence test in
    T2 fails;
  * `keep_an_empty_piece_in_the_pooled_signatures.sh` — prunes to `>= 0` instead of `> 0`, so the
    key-set test in T2 fails.
* **Sequence:** commit first — `falsify.sh` refuses a dirty tree — then
  `./check.sh --falsify <filter>` and record that each one was caught.

### T5 — the documents this invalidates, in the same commit

* **`docs/PERFORMANCE.md`** — a new **§1.10 _A whole derivation rebuilt for one changed input_**
  (symptom → cause → fix → numbers, and the §3.4 trap, because a silently-shifted IDF is exactly the
  kind of thing the next reader must not rediscover); extend **R4** with the second half it is
  missing — *caching is not enough; the rebuild must be proportional to what changed* — rather than
  adding a rule that repeats it; and add the guard names to the `store.cached_references` row of the
  §3 map.
* **`docs/ECOSYSTEM.md`** — the status line, the phase-table row and the § *Phase 25* heading, and
  the phase's decisions.
* **`README.md`** — the phase-25 plan moves from **Open work** to the record table.
* **This document** — `**Status: landed.**`, plus the execution record of any deviation.
* **`AGENT-LOG.md`** — the entry.
* Nothing else: no route, tunable, schema, table, column or player-visible behaviour changes, so
  `ENGINEERING.md`, `FEATURES.md` and `DEPLOYMENT.md` are not touched. `check.sh --fast` runs
  `check_docs.py`, so a stale phase status or an unreachable document fails the tier rather than
  being noticed later.

### T6 — the sweep

* `./check.sh --fast` after each task; `./check.sh --full` on the frozen tree before handing over.

---

## 5. Verification

* **The equivalence tests are the guard, and they are the right kind**: they assert a *property*
  (incremental == full rebuild, key sets included), not a duration. `R6` is explicit that a timing
  assertion passes on a fast machine with the bug present.
* **The work-count test is the performance guard**: one changed input reads one segment's notes, and
  the whole-sitting read does not run. This is what a falsifier can break and a timing test cannot.
* **Existing tests must stay green unmodified** — in particular the invalidation contract in
  `test_autotag.py` (`test_reading_the_references_twice_rebuilds_them_once`,
  `test_relabelling_a_segment_invalidates_the_cached_references`,
  `test_answering_a_practice_kind_keeps_the_cached_references`,
  `test_segmenting_a_sitting_does_not_rebuild_the_references`,
  `test_every_reference_change_still_invalidates`, `test_init_db_forgets_the_cached_references`).
  If one of them has to change, that is a finding about this design, not a test to adjust: report it
  before touching it.
* **A before/after on the real fixture**, quoted in the landing report with the fixture's own row
  counts, for the one number the phase exists to move.

---

## 6. Risks

| Risk | Why it is not the plan's problem, or what catches it |
| --- | --- |
| The incremental answer drifts from a full rebuild | The four equivalence tests, on all four write shapes, with the key sets compared. Drift is a test failure, not a slow leak. |
| A silently shifted IDF from an empty pooled piece | `test_a_piece_that_loses_its_last_label_leaves_the_pooled_signatures`, plus the `keep_an_empty_piece…` falsifier. This is the risk the probe did *not* cover; §3.4 records that. |
| Memory: the entry now also holds one small tuple per label | 443 tuples against 396,219 `Note` objects that the same call already builds. Not a measurable change; if the labelled set ever reaches six figures, the entry shape is the thing to look at. |
| Concurrency with the background worker | §3.5 argues the copy-on-write + conservative-version property; the trigger for revisiting it is written down. No new lock, because one is not needed and would be the kind of guard that outlives its reason. |
| "Always incremental" being slower at some volume | Measured in T3, with the crossover recorded if it exists. Deciding it by feel is the thing this repository's `R8` exists to prevent. |

---

## 7. Retained paths and retirement

**Retained on purpose.** `examples_from`, `_segment_features`, `_pooled_signatures` and
`references_from` stay. `segment_identification` accepts `examples`, `signatures` and `notes` as
optional arguments and falls back to building them; `_pooled_signatures` is reached only through
that fallback, and **no caller in `app/` passes nothing** — both call sites
(`candidates_for_sitting`, `_autotag_rows`) pass what `cached_references` returned. So they are
reachable-but-unused, and this phase does not make them more or less used.

An earlier reading of this session's measurements said `_pooled_signatures` was a second live cost
on the tagging path. It is not: nothing on that path reaches it. Recorded here so the claim is not
inherited.

**Retirement candidate, deliberately not taken.** Those four helpers are dead weight reachable only
from an argument nobody passes. Retiring them means changing `segment_identification`'s contract
(dropping its optional arguments) and the leave-one-out shape the quality report would use — a real
change with real test surface, and no part of this phase's problem. Classified here, scheduled
nowhere.

**No fallback is added.** There is one code path for a miss, not two: with a base entry it updates
incrementally, without one it builds from scratch. The second is not a compatibility branch — it is
the cold case, and it is the behaviour every read had before this phase.

---

## 8. Execution route

Inline. The tasks share one file (`store.py`), one test file and one narrative; delegation would
serialise on the same lines and lose the equivalence reasoning. Each task is committed only after it
is verified on its own, and T4's falsifiers follow the commit they certify.

```
Execution Route:
- Decision: inline
- Evidence: T1/T2/T3 all edit store.py's reference-cache section and test_autotag.py; T4/T5/T6
  depend on the committed state of T2.
- Fallback: none needed — no independent slice.
- User confirmation required: no — the scope was approved ("implement A"), and this document is
  the plan that approval asked for.
```

---

## 9. Execution record

Landed as three commits: `d44360a` (the incremental cache), `390f787` (three falsifiers), `df1819b`
(a precise rewrite of the first one).

**Every task landed with the tests it named, and the RED was watched for each.** T1's
`test_one_label_change_re_derives_only_that_segment` failed first with `AttributeError` (the helper
did not exist), then with `['sitting']` (the plumbing was in but the miss path still rebuilt
everything) — which is the sequence this plan's T1/T2 split predicted, and the reason the two were
committed as one verified unit rather than a deliberately red tree.

**One deviation from this plan's test list, recorded rather than smoothed over.** §T2 predicted the
four equivalence tests would be RED. Three of them cannot be: an equivalence guard ("incremental ==
full rebuild") is satisfied trivially while a full rebuild is still the implementation, so they passed
before the incremental path existed and then **failed against my first implementation** — which is
where they earned their keep, catching two real defects (below). Because they cannot be the RED
driver, a fifth test was added to pin the property the whole design rests on and which *can* fail:
`test_the_range_read_returns_the_slice_a_whole_sitting_read_would`, asserting the range query returns
exactly the notes, in the same order, that the binary-searched slice returns. The work-count test from
T1 is the RED-anchored performance guard, as the plan intended.

**Two real defects the equivalence tests caught, both in my first implementation:**

1. A segment that **moves** between pieces was not subtracted from the piece it left — I subtracted
   only `removed`, so a moved segment's features were counted under both pieces. This is exactly the
   defect `forget_the_old_piece_when_a_label_moves.sh` breaks deliberately.
2. The pool prune used `if counts`, and `Counter.subtract` leaves the keys it zeroed in place — an
   all-zero Counter is still *truthy*, so a piece that had lost its last label stayed in the pooled
   map and would have shifted every IDF weight (§3.4). The prune is now `any(counts.values())`.

A third gap the tests caught was structural rather than arithmetic: a base entry built when the library
had **no labels** holds no examples, so the first label after that could not be looked up in the
fingerprint map. The moved set is now driven off `cached_inputs`, not off `examples`.

**§T3's numbers were re-measured on the current fixture and differ from §1's projections, which were
taken on an earlier build.** The measured series, on **512,010 note events, 1,151,770 pedal events, 38
sittings, 682 segments of which 443 are references, 7 pooled pieces**:

| | this plan's projection | measured |
| --- | ---: | ---: |
| derivation per label click | 1.1 ms | **3.4 ms** |
| the click itself | 167 ms | **79.0 ms** |
| today's click, for comparison | 1,979 ms | 80.7 ms |

The derivation target is met in substance (1,808 ms → 3.4 ms). The click figure is *better* than
projected and for a different reason than the plan assumed: `sitting_detail` now reads in ~73 ms on
this fixture rather than the ~1,975 ms §1 recorded, so the reference derivation was never the whole
click and the click was already fast before this phase. The honest statement of the value — recorded
in `ECOSYSTEM.md` and `PERFORMANCE.md` rather than only here — is that the derivation stops growing
with the library and a ~1.8 s stall disappears, not that a click improves from 1,979 ms to 167 ms.

**The worst case was measured as §T3 required.** Every one of the 682 labels moved at once: **1,530 ms
incremental against 1,985 ms rebuild**, with incremental ahead at every size from 10 up. There is no
crossover, so no threshold was added — per §T3's own instruction not to add one on speculation. The
margin narrowing from ~500× to ~1.3× is recorded as the measurement to revisit.

**The measurement probe** is `backend/.scratch/probe_phase25_incremental.py` (gitignored, as §T3
specifies), re-runnable against the fixture; it calls the shipped implementation and instruments the
real miss rather than modelling it.

**Falsifiers, all three proven to catch their break:**

| Script | Test it must catch |
| --- | --- |
| `rebuild_every_reference_for_one_label.sh` | `test_one_label_change_re_derives_only_that_segment` — **1 failed, 44 passed** |
| `forget_the_old_piece_when_a_label_moves.sh` | `test_moving_a_label_between_pieces_moves_its_contribution_only` (3 failed, 42 passed) |
| `keep_an_empty_piece_in_the_pooled_signatures.sh` | `test_a_piece_that_loses_its_last_label_leaves_the_pooled_signatures` — **1 failed, 44 passed** |

The first falsifier was **rewritten** after its first version inverted the input diff: that broke 43
tests, so it certified the work-count assertion without isolating it. It now restores the exact
pre-Phase-25 miss path — correct answers, every equivalence test still green, and only the
read-counting test able to tell the difference.

**No lock was added**, on §3.5's argument (copy-on-write plus a conservative version check), and the
revisit trigger is recorded in this plan and in `ECOSYSTEM.md` 25-D4: if the derivation ever comes to
depend on something that can *decrease*, that argument stops holding.

**Existing tests stayed green unmodified**, including all six invalidation-contract tests §5 named.

<!-- historical-record -->
This plan is a record of work that has landed, not a specification. Current behaviour is in docs/FEATURES.md; current status is the status line in ECOSYSTEM.md. See docs/archive/README.md.
