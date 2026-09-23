# Plan — Phase 22: hearing the piece

**Parent spec:** [`ECOSYSTEM.md`](./ECOSYSTEM.md) § *Phase 22*, which adopts this document as the
how. The *why* — the measurement that made this a phase at all — is § *The measured case* below,
and it is the reason the phase exists rather than the identification work being a tuning change.

**Status: landed 22a–22c** (2026-09-21). Task 5 (22d) was settled by measurement rather than code —
see `ECOSYSTEM.md` § *Phase 22*.

**Goal.** Make the log tell the truth about what was practised. Two failures, one cause:

* **The boundaries are not where the playing turns over.** One fixed 8-second silence gap is the
  whole segmenter, and on the owner's own ten hours it fires **60 times in 238,648 note
  transitions**. A 54-minute sitting becomes three segments. The player compensates by hand — 42% of
  the stored boundaries sit on no silence at all, and twelve segments contain an internal silence
  longer than the rule that supposedly made them.
* **The matcher declines to act, and would decline harder as the library grows.** Across the whole
  library, `identified_by` is `manual 54, workout 10, none 4, **similarity 0**` — the automatic band
  has never once fired. Measured leave-one-out it is **98.1% correct** and still writes nothing,
  because the comparison it wants does not exist inside its own neighbour window.

Both are the same defect: **the app compares whole-segment averages.** An average is a different
thing depending on where the cut fell, and it stops being discriminative when the library is large.
The fix is a representation, not a parameter.

---

## Architecture

### The four units

| Unit | Stored? | What it is |
| --- | --- | --- |
| **attempt** | **yes** (`segments`) | one uninterrupted stretch of playing; the raw fact |
| **passage** | derived | adjacent attempts that are the same musical material, with *n* attempts |
| **piece-session** | derived | adjacent passages sharing a piece — "what this sitting was about" |
| **sitting** | yes | the session |

The primary row in the log becomes the **passage**, with its attempts as the detail. The
piece-session is the heading above it. This is the shape that matches how the owner practises —
drill a section for a while, run it through occasionally — and it is what turns 54 labelling
decisions into about 15.

`segments` keeps every current meaning and every current consumer. Passages and piece-sessions are
**derived on read** from the attempts and their labels, so there is **no table and no migration**.

### The representation: global plus local

**Local content shingles.** From a note stream, extract many small tempo-invariant features:

* (`hand`, pitch class) for every note;
* the pitch-class set of every chord;
* melodic bigrams (`hand`, pitch class → pitch class, interval) between adjacent events.

Pooled **per piece**, not per segment. Scored by **IDF-weighted containment**
(`|A∩B| / min(|A|,|B|)`), not cosine — because a drill is a *snippet* of a piece, and cosine
punishes the query for everything the piece has that the query lacks.

**Two details that mattered more than the model choice**, both measured:

* **Rhythm does not go in the key.** Putting the inter-onset bin into the shingle cost 7–15 points,
  because a slower repeat of the same passage hashes to different keys. Tempo is carried as its own
  term instead.
* **Pool per piece, never per segment.** Matching becomes O(pieces) rather than O(labels); the
  600-segment reference window and its "oldest fall out" cliff disappear; a piece learned a year ago
  is exactly as strong as yesterday's; and one heavily-drilled piece can no longer fill the
  neighbour window.

**The score** is a mix: `0.75 × global + 0.25 × containment`, where "global" is the existing
fingerprint. The global term wins on whole material; the local term wins on fragments.

### Segmentation

Four rules replacing one:

1. **Adaptive gap, 2-second floor.** A boundary when `gap > max(2 s, k × local median
   inter-onset interval)`. The floor stops fast passages being chopped; the adaptive term stops
   slow ones being merged.
2. **Minimum size** — absorb a segment under ~8 notes into its neighbour, so a stray touch is not a
   segment.
3. **Maximum size** — split anything over ~2 minutes at its largest internal gaps.
4. **Never truncate a phrase.** Splitting at a real pause yields a complete unit; the existing
   measurement of how short a *unit* may be still governs.

The floor (2 s), the minimum (8 notes), the maximum (2 minutes) and the adaptive multiplier `k` are
**starting values taken from the measurements above, not constants to defend** — all four are
re-chosen by the same sweep that produces acceptance 1's curve.

---

## The measured case

All of it on the owner's own backup (17 sittings, 238,665 notes, 68 segments) and on the app's own
generator corpus, using the app's own `fingerprint`, `compare`, `identify` and `measure_autotag.py`.

**The segmenter is inert.** 238,648 transitions; only **60 gaps exceed 8 s** (0.03%). Median stored
segment **3,385 notes / 5 minutes**; 36 of 68 over five minutes. Of 53 internal boundaries, only 31
sit on a silence — **22 were made by hand**. And **12 of 68 segments contain an internal silence
longer than 8 s** (up to 76.7 s inside a 90 s segment), which `sessionize` cannot produce, so they
were merged by hand. The player is correcting the rule in both directions.

**There is signal to cut on.** Of the 36 segments over five minutes, **34 contain an internal break
longer than 2 s**, median largest 4.6 s.

**Re-cutting the real sittings at other thresholds** (labels inherited from the stored segments,
leave-one-out top-1):

| gap | segments | median notes | current | hybrid |
| ---: | ---: | ---: | ---: | ---: |
| **2 s** | **354** | **314** | 94.1% | **94.6%** |
| 4 s | 98 | 1,363 | 86.7% | 88.8% |
| 8 s *(shipped)* | 50 | 3,385 | 88.0% | 90.0% |
| 16 s | 33 | 5,284 | 87.9% | 93.9% |
| 32 s | 20 | 13,951 | 90.0% | 90.0% |

2 s is best **and** puts the median segment at 314 notes — drill scale, which is the shape the
weights were measured on.

**The automatic band never fires, and the reason is not the threshold.** Leave-one-out over the 54
real labelled segments: **top-1 98.1%**, median best score **0.990**, 53 of 54 above the 0.85 auto
threshold. Yet only 6 auto-write, and **46 of 54 are downgraded for one reason: "nothing else to
compare it with"** — `runner_up is None`. Cause: four labelled pieces, so the top-6 neighbour window
holds a single piece for **47 of 54** queries. The margin was never the problem (median margin where
a runner-up exists: 0.354 against a 0.10 threshold). Taking the best neighbour **per piece** lifts
auto coverage **11.1% → 68.5% at unchanged 100% precision**.

**But that fix does not scale, which is why this phase is a representation change.** On the
generator corpus, top-1 at whole length → quarter length:

| pieces | current | hybrid |
| ---: | --- | --- |
| 8 | 90.3% → 63.9% | 88.9% → 72.2% |
| 16 | 74.3% → 40.3% | 77.1% → 54.2% |
| 32 | 61.8% → 26.4% | 66.0% → 39.2% |

The per-piece window fix is worth **exactly zero** at 16 and 32 pieces. The hybrid beats the current
method at 16 and 32 **even at full length**, and roughly halves boundary sensitivity.

**One honest calibration.** The generator corpus is harsher than this library — 86.1% at four pieces
where the real data gives 98.1%. And the 94.6% is *partly flattered*: at a 2 s cut the inherited
labels create several near-identical sub-segments of one piece, which flatters leave-one-out. Both
caveats must travel with the number.

**Housekeeping found on the way.** 20 of 68 segments (29%) have **no `segment_metrics` row** — the
metrics wipe Phase 20a fixed but never backfilled. `identification_outcomes` holds six rows and is
read by nothing, including one rejection at **0.9664** confidence, which is the only real-world
accuracy evidence the app has.

---

## Decisions

* **22-D1 — The four units, and the passage as the row.** Attempts are stored; passages and
  piece-sessions are derived on read. Fixes the "54 rows for six attempts" problem without a table.
* **22-D2 — Labels stay on segments.** Confirming a passage writes `piece_id` to its member
  segments, exactly where labels live today. The group is a view; its label is durable. **No
  migration, no new table, no `SCHEMA_VERSION` change.**
* **22-D3 — Hybrid score**, `0.75 × global + 0.25 × IDF-containment`, with tempo-invariant local
  features. The weight is a starting point to be re-chosen by `measure_autotag.py`, not a constant
  to defend.
* **22-D4 — Per-piece pooled signatures** replace the 600-segment reference window. Retires
  `SRT_AUTOTAG_TRAINING_LIMIT` as a correctness boundary (it becomes a performance bound at most).
* **22-D5 — Adaptive gap with a 2 s floor**, plus minimum-size merge and maximum-size split. The
  finer cut is the **default**, accepted by the owner knowing the stored segment count rises about
  7× (50 → 354 on current data).
* **22-D6 — A run-through is the anchor.** The owner runs a piece through when it is finished; that
  is the best reference the piece will ever have. Detect it (a long attempt whose content is
  contained in, or defines, the piece's material) and treat it as the piece's canonical signature,
  which drills then match into.
* **22-D7 — The auto band is calibrated, not asserted.** Chosen by `measure_autotag.py` extended
  with a fragment-length axis and a segmentation-threshold axis, with the per-piece neighbour fix
  and the containment term in place.

---

## Slices

This is too large for one plan, so it ships in four independently verifiable slices, in the order
that lets each be measured before the next depends on it — the same shape Phase 20 used.

| # | Slice | Delivers | Verifiable alone by |
| --- | --- | --- | --- |
| **22a** | **Where the playing turns over** | The adaptive gap with its 2 s floor, the minimum-size merge and the maximum-size split | The re-cut table: top-1 across gap thresholds, re-measured |
| **22b** | **Hearing it in pieces** | Tempo-invariant local shingles, per-piece pooling, IDF containment, the hybrid score, and the retirement of the 600-segment window's correctness role | The 32-piece corpus table, whole and quarter length, against the current fingerprint |
| **22c** | **Passages and piece-sessions** | The derived layer, the additive `passages` field, the passage row and the piece-session heading | Acceptance 5's round-trip, and the browser scenario |
| **22d** | **The band, and the run-through** | The auto band chosen by measurement, the run-through anchor, and the quality report's stale window note deleted | Auto precision and coverage on both corpora; the anchor's effect on a run-through query |

22a and 22b are independent of each other and can be measured in either order; 22c depends on 22a's
boundaries being settled, and 22d depends on both 22b's score and 22c's passages existing.

---

## Acceptance criteria

1. Re-cutting a sitting at the chosen gap and at twice and half that gap changes top-1 by **no more
   than 3 points** (the "segments impact the least possible" requirement, stated as a number).
2. On the generator corpus at **32 pieces**, hybrid top-1 at whole length is **at least 5 points
   above** the current fingerprint, and at quarter length **at least 10 points above**.
3. On the owner's real library, leave-one-out top-1 at the chosen segmentation is **at least 94%**.
4. Auto-labelled passages are **at least 95% precise** on both corpora, measured, and auto coverage
   on the real library is **at least 50%**.
5. A passage confirmation writes every member attempt's `piece_id`, and re-running the derivation
   after a split/merge/resegment produces the same passages from the same labels.
6. `streak_days`, `resegment`'s contract, `identification_outcomes`'s shape and every existing route
   are unchanged; no `SCHEMA_VERSION` change.
7. `./check.sh --full` green.

## Risks

| Risk | Treatment |
| --- | --- |
| The hybrid is worse than what it replaces | It already measured better at 16 and 32 pieces and at every real-data threshold; the weights table re-measures it, and acceptance 2 is a gate rather than a hope |
| Local features are brittle to tempo after all | The tempo-in-key variant was measured 7–15 points worse and is excluded by construction; the "repeat, slower" bucket is asserted separately |
| The 2 s cut bloats the log | 354 segments over ten hours is a few thousand rows a year; accepted explicitly in 22-D5, and the passage grouping is what keeps the view readable |
| Passage grouping merges different passages of one piece | Grouping uses containment, not the piece label alone — a *differing* label is a hard boundary, and a containing one is not sufficient evidence on its own |
| Derived passages shift when a neighbouring label changes | Accepted: the label is durable on the segments, so nothing is lost by regrouping. Stated in the UI rather than hidden |
| Precision is unproven beyond ~32 pieces | Named as unresolved. The next lever, if acceptance 2 fails at 64, is sequence-aware verification (ordered interval n-grams as a subsequence rather than a bag) |

## Retirement

* **`SRT_AUTOTAG_TRAINING_LIMIT`'s correctness role retires** with 22-D4; the field may remain as a
  performance bound, and if it does, the quality report's "older segments are beyond the reference
  window" note must be deleted with it rather than left describing behaviour that no longer exists.
* **Nothing else is retired.** `fingerprint`, `compare` and `identify` keep their names and their
  meanings; `_labelled_rows` keeps its manual-labels-only rule (auto-written labels are still not
  training data, or a matcher's mistake becomes its own evidence).
* The derived layer is one module. Deleting it and the two view blocks removes the phase with no
  residue and no migration to reverse.

## ADR / baseline-sync signals

* **Durable decisions, recorded here and not in a second authority.** This project's decision record
  is `ECOSYSTEM.md` plus its decisions tables; `ECOSYSTEM.md` § *Non-goals* states that no ADR
  directory exists and that inventing one would create a second authority for the same facts. So
  these live here and are summarised in the Phase 22 row.
* **Baseline-sync question on completion:** *does an existing labelled segment still mean what it
  meant?* The answer must be yes — the same rows, the same `piece_id`, the same `identified_by`.
  Acceptance 6 is the evidence.
* **Second baseline-sync question:** *does `segment_gap_s = 8` appear anywhere as a decision?* If it
  does, that text is superseded by 22-D5 and must be updated in place, not left to contradict.

## What this does not do

No score alignment, so a passage remains *inferred from sound* rather than known to be bars 40–48.
No section-generation or looping (that stays the deferred "section practice" feature — this phase
makes the section work you already do **visible**, it does not create it). No per-hand inference. No
audio. No reversal of the "one app, one database" boundary.

**No new endpoint at all.** Passages arrive as an additive field on the existing sitting detail,
because the derivation needs the notes and `SittingDetail` today carries only its segments — so the
derivation has to be server-side, but it does not need a route of its own.

---

```text
Execution Readiness View:
- Intent Lock: attempts are the raw fact; passages and piece-sessions are derived and carry the
  labels; identification is robust to where the cut falls and does not degrade as the library grows
- Scope Fence: in — the segmentation rules, the passing/passage derivation, the hybrid scorer, the
  per-piece signatures, the run-through anchor, the passage row and the piece-session heading, the
  extended measurement. Out — score alignment, section generation/looping, per-hand inference,
  audio, a persisted group table, any schema change
- Baseline Lock: ECOSYSTEM.md § Phase 22 and the Phase 20 row; TEST-STRATEGY.md §8; the measurements
  in this document, reproducible with backend/tools/measure_autotag.py
- Compatibility Boundary: no schema change; segments keep every field and meaning; `resegment`,
  `identify`, `metrics` and the media/practice seam are unchanged; **one additive `passages` field on
  `SittingDetail`** and no new route
- Retirement Boundary: SRT_AUTOTAG_TRAINING_LIMIT's correctness role, and its stale report note
- Test Obligations: the re-cut stability assertion (acceptance 1), the 32-piece corpus gate
  (acceptance 2), the real-library accuracy floor (acceptance 3), auto-band precision on both
  corpora (acceptance 4), the passage round-trip (acceptance 5), and a falsification per claim —
  the tempo-invariance one being "put the rhythm bin back and watch 'repeat, slower' fail"
- Review Gates: after the segmentation rules (the re-cut curve, re-measured); after the scorer (the
  32-piece table); after the derivation (the passage round-trip)
- Drift / Rewind Rules: if the hybrid cannot beat the current fingerprint at 32 pieces, stop and
  return to this document rather than shipping the representation
- Evidence Required Before Completion: ./check.sh --full green; the extended measure_autotag.py
  table; every falsification reported "falsified"; acceptance 1-7 individually evidenced
- Advisory Boundary: method-pack execution guidance only; not GateDecision or completion authority
```

---

# Implementation plan

```text
TDD Route:
- Mode: auto
- Decision: strict
- Strict authority: project instruction — docs/TEST-STRATEGY.md §8, "no assertion is trusted until
  it has been seen to fail", the same standing rule Phase 20c executed under; plus this phase's own
  acceptance criteria, which are numbers rather than adjectives
- Strict signals: persistent stored data changes shape (the segmentation of `segments`), a core
  shared owner is replaced (`similarity.rank`/`identify`), a response contract gains a field
  (`SittingDetail`), and a truth claim (precision) is being made about a growing corpus
- Light eligibility: not applicable — no slice here is tiny, single-owner, or behaviour-free
- TDD-fit exception: none
- Test posture: strict RED first for `segment.py`, `shingles.py` and `passages.py`; for the wiring,
  the measurement tables are the assertion and each is watched to fail with a break applied
- Verification: ./check.sh --fast after every task; ./check.sh --full before the phase is done
```

```text
BaselineUsageDraft:
- Required baseline refs: docs/PLAN-PHASE22.md § The measured case; docs/TEST-STRATEGY.md §8;
  backend/tools/measure_autotag.py (the weights/bands table); backend/app/practice/sessionize.py;
  similarity.py; store.py:1596-1640 (`_labelled_rows`) and :1842-1884 (`_autotag_rows`)
- Delivered context refs: the five probe scripts under .scratch/probe/ (gitignored)
- Acknowledged before plan refs: ECOSYSTEM.md § Phase 22; the Phase 20 row
- Cited in plan refs: all of the above, with file:line
- Missing refs: none
- Decision: continue
```

```text
Requirement Ready Check:
- Requirement source refs: the owner's request ("robust... very good precision... future proof with
  many new pieces, segments impact the least possible... do not forget segmentization") plus the
  approved spec's acceptance criteria 1-7
- Goals and scope refs: PLAN-PHASE22.md § Goal, § Decisions 22-D1..22-D7, § Scope Fence
- User / scenario refs: the owner's stated practice — drill a section for a while, run it through
  when the piece is done
- Requirement item refs: 22-D1..D7
- Acceptance / verification criteria refs: PLAN-PHASE22.md § Acceptance criteria 1-7
- Open blocker questions: none — the two user-owned decisions (fine cut as default; one phase) were
  answered before this plan was written
- Decision: ready
```

```text
Change Necessity:
- User-visible need: the log's boundaries are not where the playing turns over, and the matcher has
  never written a single label despite being 98% accurate
- No-change / non-code option: insufficient — 42% of stored boundaries are already hand-corrections,
  which is the owner paying for the missing rule; and no threshold change fixes a representation
  that is compared as a whole-segment average
- Why code change is necessary: the segmentation rule, the scoring representation and the reference
  window are all code; the measurements in § The measured case are of the current code
- Minimum change boundary: practice/segment.py (new), practice/shingles.py (new),
  practice/passages.py (new), practice/similarity.py, practice/store.py, practice/models.py,
  lib/types.ts, components/PracticeLogView.svelte, the measurement tool, tests, docs
- Decision: code-change
```

```text
Existence Check:
- Proposed new surface: three new modules — segment.py, shingles.py, passages.py
- Existing owner / reuse candidate: sessionize.py owns cutting; similarity.py owns scoring;
  SegmentSummary owns the segment view
- Why existing surface is insufficient: sessionize.py is a pure gap rule with one number and is
  ported byte-for-byte from practice-logger, so widening it would break the property that the live
  and rebuild paths cannot drift; similarity.py has no notion of a local feature or of pooling; no
  module derives a group above a segment
- Creation proof: acceptance 1 (segment.py), 2 (shingles.py), 5 (passages.py)
- Entropy / retirement impact: sessionize.py is kept and still used for sittings, so the ported
  contract survives; each new module is pure and deletable in one file; nothing is persisted
- Decision: add-with-proof for segment.py, shingles.py and passages.py; reuse-existing for the
  sessionize contract, the similarity owner and the SegmentSummary shape
```

```text
Architecture Integrity Lens:
- Invariant: an attempt is the raw stored fact; passages and piece-sessions are derived and never
  stored; a label lives on segments and nowhere else
- Canonical owner / contract: practice/ owns the practice domain; similarity.py is the one scorer;
  SittingDetail is the one read that carries a sitting's shape
- Responsibility overlap: none introduced — segment.py decides boundaries, shingles.py decides
  content features, passages.py decides grouping; each has one question
- Higher-level simplification: the 600-segment reference window is retired as a correctness
  boundary rather than tuned, and the per-piece pooling removes a whole class of "which examples
  happened to be inside the window" bugs
- Retirement / falsifier: SRT_AUTOTAG_TRAINING_LIMIT's correctness role, with the stale quality
  report note; falsified by a 32-piece corpus if the hybrid does not beat the current score
- Verdict: proceed
```

```text
Plan Pressure Test:
- Owner / contract / retirement: one additive response field, no schema change, one retirement with
  its stale text named
- Architecture integrity / higher-level path: per-piece pooling removes a scaling cliff rather than
  adding a fallback to live with it
- Verification scope: five tasks, each with a measurement table or a unit suite as its gate, plus
  one falsification per substantive claim
- Task executability: every step names a file, complete code and an exact command
- Pressure result: proceed
```

```text
Complexity Budget:
- Artifact class: domain module (pure) / scoring module (pure) / derivation module (pure) / one
  response model / one view
- Target files / artifacts: store.py is 2082 lines and already over budget, so it gets wiring only
- Current pressure: store.py already owns every practice read and write; PracticeLogView is 866 lines
- Projected post-change pressure: store.py +~15 lines of wiring; PracticeLogView +~40 lines
- Budget result: at-risk for store.py, within-budget elsewhere
- Planned governance: no new logic in store.py — it calls segment.cut, shingles.pooled and
  passages.derive; the grouping decision and the scoring arithmetic live in their own modules

Plan-Time Complexity Check:
- Target files: backend/app/practice/store.py
- Existing size / shape signals: 2082 lines, mixed-purpose (reads, writes, matcher, analytics)
- Owner fit: store.py is the transaction owner, not the algorithm owner
- Add-in-place risk: putting the adaptive rule or the containment arithmetic in store.py would put
  testable decisions where `pytest` cannot reach them without a database
- Better file boundary: three pure modules; store.py only calls them
- Recommendation: add owner file(s), then edit-in-place for the wiring
```

## Files

**Create**

| Path | Why |
| --- | --- |
| `backend/app/practice/segment.py` | Where a stretch of playing turns over: adaptive gap, min size, max size |
| `backend/tests/test_segment.py` | The three rules, the adaptive floor and ceiling, and the degenerate inputs |
| `backend/app/practice/shingles.py` | Tempo-invariant local content features, and containment over them |
| `backend/tests/test_shingles.py` | Subset behaviour, tempo-invariance, pooling, containment |
| `backend/app/practice/passages.py` | Grouping attempts into passages and passages into piece-sessions |
| `backend/tests/test_passages.py` | Grouping, the hard label boundary, and the round trip |
| `backend/tools/measure_real.py` | The re-cut harness: reads a backup document if present, skips cleanly if not |
| `backend/tools/falsifications/drop_tempo_invariance.sh` | Put the rhythm bin back into the shingle key |
| `backend/tools/falsifications/drop_adaptive_gap.sh` | Replace the adaptive threshold with a fixed one |

**Modify**

| Path | Change |
| --- | --- |
| `backend/app/practice/similarity.py` | Per-piece pooling, the containment term, the hybrid score |
| `backend/app/practice/store.py` | Call `segment.cut`; pool per piece; retire the window's correctness role |
| `backend/app/practice/models.py` | `PassageOut`, and `passages` on `SittingDetail` |
| `backend/app/config.py` | The segmentation settings; `SRT_SEGMENT_GAP_S` becomes a floor |
| `frontend/src/lib/types.ts` | `Passage` and the field |
| `frontend/src/components/PracticeLogView.svelte` | The passage row and the piece-session heading |
| `backend/tools/measure_autotag.py` | A piece-count axis and a fragment-length axis |
| `README.md`, `AGENT-LOG.md`, `docs/ECOSYSTEM.md`, `docs/TEST-DATA.md` | Docs, and the real corpus's role |

---

## Task 1 — the measurement gains its axes

**Files.** modify `backend/tools/measure_autotag.py`.

**Why.** Every acceptance gate in this phase is a table, and today the tool sweeps one axis at eight
pieces. Without this task, 22a and 22b cannot be judged and the phase would be argued rather than
measured. This is the first task on purpose.

**Change Necessity.** Code: the tool hard-codes `PIECES` at eight and has no fragment or
piece-count axis.

**Impact / Compatibility.** A tool, not production. It reads no database and writes nothing.

### Step 1.1 — a piece-count axis

Add above `PIECES`:

```python
#: Keys cycled to synthesise a larger library than the eight hand-written pieces. Two
#: pieces sharing a key is the matcher's documented failure mode, so repetition is the
#: point rather than a compromise.
KEYS = ("C", "G", "D", "A", "E", "B", "F#", "Db", "Ab", "Eb", "Bb", "F",
        "a", "e", "b", "f#", "d", "g", "c", "bb")


def pieces_for(count: int) -> tuple[tuple[str, str, dict[str, int]], ...]:
    """``count`` distinct pieces, cycling keys and varying the character."""
    return tuple(
        (f"piece-{index:02d}", KEYS[index % len(KEYS)], {
            "hand_position": 3 + (index % 6),
            "intervals": 3 + ((index * 2) % 6),
            "rhythm": 3 + ((index * 3) % 6),
            "texture": 3 + ((index * 5) % 6),
            "key_signature": 1 + (index % 5),
        })
        for index in range(count)
    )
```

and make `build_corpus` read the module global (it already does), adding a parameter:

```python
def build_corpus(seed: int = 20260913, pieces=None) -> list[Drill]:
    global PIECES
    if pieces is not None:
        PIECES = tuple(pieces)
    ...
```

### Step 1.2 — a fragment axis

Add `first_notes`'s sibling:

```python
def middle_notes(drill: Drill, fraction: float, rng: random.Random) -> Drill:
    """A contiguous middle chunk — a legitimate sub-snippet.

    This is the axis the existing truncation table does not cover: ``first_notes`` asks
    what a *shorter* drill would need, and this asks what a drill looks like when the
    boundary fell somewhere else. Acceptance 1 is about the second question.
    """
    if fraction >= 1.0:
        return drill
    count = len(drill.notes)
    keep = max(1, int(count * fraction))
    start = rng.randrange(0, max(1, count - keep + 1))
    return Drill(drill.piece_id, drill.label, drill.notes[start:start + keep], drill.transform)
```

### Step 1.3 — verify

```bash
cd backend && .venv/bin/python tools/measure_autotag.py --verbose | head -20
```

Expected: unchanged output for the default eight pieces — this task adds axes without moving the
existing numbers, and that is the check.

```bash
cd backend && .venv/bin/python -c "
import sys; sys.path.insert(0,'tools'); sys.path.insert(0,'.')
import measure_autotag as M
for k in (2,8,32):
    d = M.build_corpus(pieces=M.pieces_for(k))
    print(k, len(d), len({x.piece_id for x in d}))
"
```

Expected: `2 18 2`, `8 72 8`, `32 288 32`.

---

## Task 2 — 22a: where the playing turns over

**Files.** create `backend/app/practice/segment.py`, `backend/tests/test_segment.py`; modify
`backend/app/practice/store.py`, `backend/app/config.py`.

**Why.** A 54-minute sitting is three segments today and 42% of boundaries are the owner's own
corrections. This is the half of the phase the owner can feel immediately.

**Change Necessity.** Code: the rule is one number in `sessionize.py`, which is ported byte-for-byte
and whose whole value is that the live and rebuild paths cannot drift.

**Impact / Compatibility.** `segments` changes shape for new sittings only. Existing rows are never
recomputed (that is `resegment`'s job and the owner's decision), so this is additive in practice.

### Step 2.1 — write the failing units

Create `backend/tests/test_segment.py`:

```python
"""Where a stretch of playing turns over."""

from __future__ import annotations

from app.practice.segment import Config, cut
from app.practice.sessionize import Note


def play(*onsets_ms: int, duration_ms: int = 100) -> list[Note]:
    return [Note(onset, 60 + index, 70, duration_ms, 0) for index, onset in enumerate(onsets_ms)]


def steady(count: int, every_ms: int, *, start_ms: int = 0, duration_ms: int = 100) -> list[Note]:
    return play(*[start_ms + index * every_ms for index in range(count)], duration_ms=duration_ms)


def test_a_pause_longer_than_the_floor_cuts() -> None:
    notes = steady(20, 200) + [Note(20 * 200 + 5_000, 60, 70, 100, 0)]
    assert len(cut(notes, config=Config())) == 2


def test_a_pause_shorter_than_the_floor_does_not() -> None:
    notes = steady(20, 200) + [Note(20 * 200 + 900, 60, 70, 100, 0)]
    assert len(cut(notes, config=Config())) == 1


def test_a_slow_passage_tolerates_a_pause_a_fast_one_would_not() -> None:
    """The whole point of the adaptive term: the same 3 s is a breath at 60 bpm and a stop at 240."""
    slow = steady(40, 1_000) + [Note(40 * 1_000 + 3_000, 60, 70, 100, 0)]
    fast = steady(40, 150) + [Note(40 * 150 + 3_000, 60, 70, 100, 0)]
    assert len(cut(slow, config=Config())) == 1, "3 s inside a 1 s pulse is not a break"
    assert len(cut(fast, config=Config())) == 2, "3 s inside a 150 ms pulse is"


def test_an_undersized_group_is_absorbed_into_its_neighbour() -> None:
    """A five-note stray is a segment today, and should not be."""
    notes = steady(40, 200) + [Note(40 * 200 + 5_000, 60, 70, 100, 0)]
    notes += [Note(40 * 200 + 5_000 + 10_000, 60, 70, 100, 0)]
    windows = cut(notes, config=Config())
    assert len(windows) == 1, "the one-note group between the two pauses is absorbed"


def test_a_long_group_is_split_at_its_largest_internal_gap() -> None:
    notes = steady(60, 100)
    notes += [Note(60 * 100 + 6_000 + index * 100, 60, 70, 100, 0) for index in range(60)]
    notes += [Note(60 * 100 + 12_000 + index * 100, 60, 70, 100, 0) for index in range(60)]
    windows = cut(notes, config=Config(max_ms=4_000))
    assert len(windows) >= 3
    assert all(w.end_ms - w.start_ms <= 4_000 for w in windows)


def test_nothing_at_all_cuts_to_nothing() -> None:
    assert cut([], config=Config()) == []


def test_one_note_is_one_window() -> None:
    single = play(1_000)
    assert len(cut(single, config=Config())) == 1
```

### Step 2.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_segment.py
```

Expected: `ModuleNotFoundError: No module named 'app.practice.segment'`.

### Step 2.3 — the module

Create `backend/app/practice/segment.py`:

```python
"""Where a stretch of playing turns over.

The rule this replaces was one fixed silence gap, and on the owner's own ten hours it fired
**60 times in 238,648 note transitions**: a 54-minute sitting became three segments, 42% of the
stored boundaries sat on no silence at all because they had been made by hand, and twelve segments
contained an internal silence longer than the rule that supposedly made them. One number cannot
describe both "I stopped to think for three seconds" and "I have not touched the piano since
Tuesday".

Three rules, each answering a different question:

* **The adaptive gap** asks whether this pause is long *for this passage*. A slow phrase breathes
  for a second between notes; a fast one does not. The floor stops a fast passage being chopped,
  and the multiplier stops a slow one being welded into a session.
* **The minimum size** asks whether the result is worth keeping. A one-note stray is a segment
  today; it should be part of its neighbour.
* **The maximum size** asks whether the result is usable. A 42-minute blob holds many passages, and
  splitting it at its largest internal gaps is what makes them visible.

Pure: no database, no clock, no configuration import. ``store.ensure_segments`` applies it; this
module decides. ``sessionize.py`` is left alone and still cuts sittings, because its whole value is
that the live and rebuild paths cannot drift and it is ported byte-for-byte.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence

from .sessionize import Note, Window


@dataclass(frozen=True)
class Config:
    """The four numbers, all of them chosen by ``tools/measure_real.py`` rather than by taste."""

    #: The shortest pause that can ever be a boundary. Measured: 2 s is the best of the
    #: thresholds tried, and it puts the median segment at drill scale (~314 notes).
    floor_ms: int = 2_000
    #: How many times the passage's own pulse a pause must be to count.
    multiplier: float = 2.5
    #: Past this, a pause is a break whatever the pulse says.
    ceiling_ms: int = 30_000
    #: Below this, a group is not worth being a segment.
    min_notes: int = 8
    #: Above this, a group is too coarse to be useful and gets split at its largest gaps.
    max_ms: int = 120_000
    #: How many recent inter-onset intervals define "this passage's pulse".
    window: int = 32


def cut(notes: Sequence[Note], *, config: Config = Config()) -> list[Window]:
    """The boundaries for one sitting's notes, oldest first."""
    ordered = sorted(notes, key=lambda note: (note.epoch_ms, note.pitch))
    if not ordered:
        return []
    groups = _by_adaptive_gap(ordered, config)
    groups = _merge_small(groups, config)
    groups = _split_large(groups, config)
    return [
        Window(group[0].epoch_ms, max(note.end_ms for note in group)) for group in groups
    ]


def _limit(config: Config, pulse_ms: float) -> float:
    if pulse_ms <= 0:
        return float(config.floor_ms)
    return min(float(config.ceiling_ms), max(float(config.floor_ms), config.multiplier * pulse_ms))


def _limits(ordered: Sequence[Note], config: Config) -> dict[int, float]:
    """A gap limit per distinct onset, from the pulse immediately before it."""
    onsets = sorted({note.epoch_ms for note in ordered})
    intervals = [second - first for first, second in zip(onsets, onsets[1:])]
    out: dict[int, float] = {}
    for index, onset in enumerate(onsets):
        recent = intervals[max(0, index - config.window) : index]
        out[onset] = _limit(config, statistics.median(recent) if recent else 0.0)
    return out


def _by_adaptive_gap(ordered: Sequence[Note], config: Config) -> list[list[Note]]:
    limits = _limits(ordered, config)
    groups: list[list[Note]] = [[ordered[0]]]
    end = ordered[0].end_ms
    for note in ordered[1:]:
        if note.epoch_ms - end > limits[note.epoch_ms]:
            groups.append([note])
        else:
            groups[-1].append(note)
        end = max(end, note.end_ms)
    return groups


def _merge_small(groups: list[list[Note]], config: Config) -> list[list[Note]]:
    """An undersized group joins the one before it, which is the simpler promise to keep."""
    out: list[list[Note]] = []
    for group in groups:
        if out and len(out[-1]) < config.min_notes:
            out[-1].extend(group)
        else:
            out.append(list(group))
    while len(out) > 1 and len(out[-1]) < config.min_notes:
        out[-2].extend(out.pop())
    return out


def _split_large(groups: list[list[Note]], config: Config) -> list[list[Note]]:
    out: list[list[Note]] = []
    for group in groups:
        out.extend(_split_one(group, config))
    return out


def _split_one(group: list[Note], config: Config) -> list[list[Note]]:
    span = max(note.end_ms for note in group) - group[0].epoch_ms
    if span <= config.max_ms or len(group) < 2:
        return [group]
    best_index, best_gap, end = 1, -1, group[0].end_ms
    for index, note in enumerate(group[1:], start=1):
        gap = note.epoch_ms - end
        if gap > best_gap:
            best_index, best_gap = index, gap
        end = max(end, note.end_ms)
    if best_gap <= 0:
        return [group]
    return _split_one(group[:best_index], config) + _split_one(group[best_index:], config)
```

### Step 2.4 — verify GREEN

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_segment.py
```

Expected: 7 passed.

### Step 2.5 — the settings

In `backend/app/config.py`, beside `segment_gap_s`:

```python
    #: Phase 22a: the shortest pause that can be a segment boundary, and how many times the
    #: passage's own pulse a pause must be. `segment_gap_s` is superseded for segmenting and
    #: kept for the take-cutter and anything else that still asks for "the segment gap".
    segment_floor_ms: int = _env_int("SRT_SEGMENT_FLOOR_MS", 2_000)
    segment_pulse_multiplier: float = _env_float("SRT_SEGMENT_PULSE_MULTIPLIER", 2.5)
    segment_ceiling_ms: int = _env_int("SRT_SEGMENT_CEILING_MS", 30_000)
    segment_min_notes: int = _env_int("SRT_SEGMENT_MIN_NOTES", 8)
    segment_max_ms: int = _env_int("SRT_SEGMENT_MAX_MS", 120_000)
```

### Step 2.6 — the wiring

In `backend/app/practice/store.py`, replace the `sessionize(...)` call site inside `ensure_segments`
(currently line ~750):

```python
        for window in segment.cut(notes, config=_segment_config()):
```

and add beside `ensure_segments`:

```python
def _segment_config() -> segment.Config:
    """The tunables, from settings, so the measurement tool and the app share one shape."""
    return segment.Config(
        floor_ms=settings.segment_floor_ms,
        multiplier=settings.segment_pulse_multiplier,
        ceiling_ms=settings.segment_ceiling_ms,
        min_notes=settings.segment_min_notes,
        max_ms=settings.segment_max_ms,
    )
```

with `from . import segment` added to the imports. `sessionize` is still imported — sittings still
use it.

### Step 2.7 — verify GREEN and the re-cut gate

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py tests/test_api.py
cd .. && ./check.sh --fast
```

Expected: green.

### Step 2.8 — the re-cut harness and the acceptance-1 gate

Create `backend/tools/measure_real.py`:

```python
#!/usr/bin/env python
"""Measure the matcher on the real library, and how much segmentation moves it.

Reads a backup document **if it is there** and prints one line and exits 0 if it is not, because
the fixture is local-only (`docs/TEST-DATA.md`) and a tool that fails on a clean checkout is worse
than no tool.

The axis that matters is acceptance 1. Re-cut every sitting at other gap floors, inherit each new
window's piece from the stored segment its midpoint falls inside, and report top-1. A
representation is only "robust to segmentation" if that curve is flat.

Nothing is written and no database is read: it is a measurement.

Usage::

    backend/.venv/bin/python backend/tools/measure_real.py [--path PATH] [--alpha 0.75]
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.practice import segment, shingles
from app.practice.sessionize import Note
from app.practice import similarity as S

DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "piano-ecosystem-backup(3).json"

#: The floors to re-cut at. The chosen one should sit in the flat part of the curve.
FLOORS_MS = (1_000, 2_000, 4_000, 8_000, 16_000)


def load(path: Path):
    document = json.loads(path.read_text())
    tables = document["tables"]
    notes: dict[int, list[Note]] = collections.defaultdict(list)
    for row in tables["note_events"]:
        notes[row["sitting_id"]].append(
            Note(row["onset_ms"], row["pitch"], row["velocity"], row["duration_ms"], row["channel"])
        )
    return tables, notes


def recut(notes, stored, config: segment.Config):
    """Re-cut one sitting, inheriting the piece of the stored segment each window lands in."""
    ordered = sorted(notes, key=lambda note: (note.epoch_ms, note.pitch))
    out: list[tuple[list[Note], int]] = []
    for window in segment.cut(ordered, config=config):
        middle = (window.start_ms + window.end_ms) // 2
        owner = next(
            (row["piece_id"] for row in stored if row["start_ms"] <= middle < row["end_ms"]), None
        )
        inside = [n for n in ordered if window.start_ms <= n.epoch_ms < window.end_ms]
        if owner is not None and inside:
            out.append((inside, owner))
    return out


def _weights(signatures):
    return shingles.idf(signatures)


def evaluate(items, *, alpha: float):
    """Leave-one-out top-1 for the current fingerprint and for the hybrid."""
    prints = [S.fingerprint(notes, attack_window_ms=settings.attack_window_ms) for notes, _ in items]
    local = [shingles.features(notes) for notes, _ in items]
    current = hybrid = 0
    for index, (_, piece) in enumerate(items):
        global_scores: collections.Counter = collections.Counter()
        for other, (_, other_piece) in enumerate(items):
            if other == index:
                continue
            total = S.compare(prints[index], prints[other], weights=S.DEFAULT_WEIGHTS)[0]
            if total > global_scores[other_piece]:
                global_scores[other_piece] = total
        signatures: dict[int, collections.Counter] = {}
        for other, (_, other_piece) in enumerate(items):
            if other == index:
                continue
            signatures.setdefault(other_piece, collections.Counter()).update(local[other])
        weights = _weights(signatures)
        shares = {p: shingles.containment(local[index], sig, weights) for p, sig in signatures.items()}
        mixed = {p: alpha * global_scores.get(p, 0.0) + (1 - alpha) * shares.get(p, 0.0)
                 for p in set(global_scores) | set(shares)}
        best_global = max(global_scores.items(), key=lambda item: item[1])[0] if global_scores else None
        best_hybrid = max(mixed.items(), key=lambda item: item[1])[0] if mixed else None
        current += (best_global == piece)
        hybrid += (best_hybrid == piece)
    count = max(1, len(items))
    return current / count, hybrid / count, len(items)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--alpha", type=float, default=0.75,
                        help="weight on the global term; the rest goes to containment")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"no real corpus at {args.path}; skipping (see docs/TEST-DATA.md)")
        return 0

    tables, notes = load(args.path)
    stored: dict[int, list[dict]] = collections.defaultdict(list)
    for row in tables["segments"]:
        stored[row["sitting_id"]].append(row)

    print(f"REAL library: {len(notes)} sittings, {len(tables['segments'])} stored segments")
    print(f"alpha={args.alpha} (weight on the global term)\n")
    print(f"{'floor':>7} {'segments':>9} {'median notes':>13} | {'current':>8} {'hybrid':>8}")
    for floor in FLOORS_MS:
        items: list[tuple[list[Note], int]] = []
        for sitting_id, sitting_notes in notes.items():
            items.extend(recut(sitting_notes, stored.get(sitting_id, []),
                               segment.Config(floor_ms=floor)))
        if len(items) < 5:
            continue
        sizes = sorted(len(ns) for ns, _ in items)
        current, hybrid, count = evaluate(items, alpha=args.alpha)
        print(f"{floor:>6}ms {count:>9} {sizes[len(sizes) // 2]:>13} | "
              f"{current:>8.1%} {hybrid:>8.1%}")
    print("\nacceptance 1: the chosen floor must sit within 3 points of half and twice itself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```bash
cd backend && .venv/bin/python tools/measure_real.py
```

Expected on the owner's machine: the re-cut table, with the cut at the chosen floor within 3
points of half and twice that floor (acceptance 1), and the real-library top-1 at the chosen floor
at or above 94% (acceptance 3).

### Step 2.9 — falsify the adaptive term

Create `backend/tools/falsifications/drop_adaptive_gap.sh`:

```bash
#!/usr/bin/env bash
#
# Break: replace the adaptive threshold with the fixed floor, so a slow passage is
# chopped by a pause that is a breath in it.
#
# The test that must catch it is test_a_slow_passage_tolerates_a_pause_a_fast_one_would_not.
#
#   ./falsify.sh backend/tools/falsifications/drop_adaptive_gap.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_segment.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/segment.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    if pulse_ms <= 0:
        return float(config.floor_ms)
    return min(float(config.ceiling_ms), max(float(config.floor_ms), config.multiplier * pulse_ms))"""
assert needle in text, "the threshold is not where this script expects it"
path.write_text(text.replace(needle, "    return float(config.floor_ms)", 1))
PY
```

```bash
cd .. && chmod +x backend/tools/falsifications/drop_adaptive_gap.sh
git add -A && git commit -q -m "Phase 22a: cut where the playing turns over"
backend/tools/falsify.sh backend/tools/falsifications/drop_adaptive_gap.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_segment.py"
```

Expected: `falsified: the check caught the break`.

---

## Task 3 — 22b: hearing it in pieces

**Files.** create `backend/app/practice/shingles.py`, `backend/tests/test_shingles.py`; modify
`backend/app/practice/similarity.py`, `backend/app/practice/store.py`.

**Why.** The matcher is 98.1% correct and writes nothing, and it would fall to 62% at 32 pieces. This
is the half that decides whether the phase is worth anything in five years.

**Change Necessity.** Code: the representation is a whole-segment average; no threshold repairs it.

**Impact / Compatibility.** `fingerprint`, `compare` and `identify` keep their names and meanings;
the hybrid is added around them. One retirement, named below.

### Step 3.1 — write the failing units

Create `backend/tests/test_shingles.py`:

```python
"""Tempo-invariant local content features, and containment over them."""

from __future__ import annotations

from app.practice.shingles import containment, features, idf, pooled
from app.practice.sessionize import Note


def line(onsets_ms, pitches, *, duration_ms: int = 100) -> list[Note]:
    return [Note(onset, pitch, 70, duration_ms, 0) for onset, pitch in zip(onsets_ms, pitches)]


PHRASE = [0, 200, 400, 600, 800, 1000, 1200, 1400]
PITCHES = [60, 62, 64, 65, 67, 69, 71, 72]


def test_a_fragment_is_a_subset_of_the_whole() -> None:
    """This is the property that makes the score survive re-cutting."""
    whole = features(line(PHRASE, PITCHES))
    fragment = features(line(PHRASE[:5], PITCHES[:5]))
    assert set(fragment) <= set(whole)


def test_the_same_passage_at_half_speed_is_the_same_features() -> None:
    """Tempo must not be in the key. Putting the inter-onset bin back in cost 7-15 points."""
    fast = features(line(PHRASE, PITCHES))
    slow = features(line([onset * 2 for onset in PHRASE], PITCHES))
    assert fast == slow


def test_a_transposed_passage_is_a_different_piece() -> None:
    """Register and pitch class both carry information; only rhythm is normalised away."""
    assert features(line(PHRASE, PITCHES)) != features(line(PHRASE, [p + 1 for p in PITCHES]))


def test_pooling_adds_the_segments_of_one_piece() -> None:
    one = features(line(PHRASE, PITCHES))
    two = features(line(PHRASE, PITCHES))
    assert pooled([one, two])["n", "R", 0] == one["n", "R", 0] * 2


def test_containment_of_a_subset_is_one() -> None:
    whole = features(line(PHRASE, PITCHES))
    fragment = features(line(PHRASE[:5], PITCHES[:5]))
    weights = idf({1: whole, 2: features(line(PHRASE, [p + 7 for p in PITCHES]))})
    assert containment(fragment, whole, weights) == 1.0


def test_containment_of_unrelated_material_is_low() -> None:
    weights = idf({1: features(line(PHRASE, PITCHES))})
    other = features(line(PHRASE, [p + 6 for p in PITCHES]))
    assert containment(other, features(line(PHRASE, PITCHES)), weights) < 0.5


def test_an_empty_query_contains_nothing() -> None:
    weights = idf({1: features(line(PHRASE, PITCHES))})
    assert containment({}, features(line(PHRASE, PITCHES)), weights) == 0.0
```

### Step 3.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_shingles.py
```

Expected: `ModuleNotFoundError: No module named 'app.practice.shingles'`.

### Step 3.3 — the module

Create `backend/app/practice/shingles.py`:

```python
"""Tempo-invariant local content features, and containment over them.

A whole-segment average is a different vector depending on where the cut fell, and it stops
discriminating once the library is large. Measured on this app's own corpus, cutting a query to a
quarter of its length dropped top-1 from 90.3% to 63.9% at eight pieces and from 61.8% to 26.4% at
thirty-two. A bag of local features does not have that problem, because a fragment's features are a
*subset* of the whole's rather than an average of it.

Two details are load-bearing and both were measured:

* **Rhythm is not in the key.** Putting the inter-onset bin into the feature identity cost 7-15
  points, because a slower repeat of the same passage hashed to different keys. Tempo is carried by
  ``similarity.compare`` as its own term instead.
* **Features are pooled per piece, not per segment.** Matching then costs O(pieces) rather than
  O(labels), which is what lets the 600-segment reference window be retired.

Pure: no database, no clock, no configuration import.
"""

from __future__ import annotations

import collections
import math
from typing import Iterable, Mapping, Sequence

from .sessionize import Note

#: Notes this close together are one chord rather than a melody.
CHORD_MS = 60

PITCH_CLASSES = 12

#: Middle C. Below it is the left hand, which is what tells a right-hand drill from a
#: left-hand drill of the same passage.
HAND_SPLIT = 60


def _events(notes: Sequence[Note]) -> list[list]:
    """``[onset, pitches]``, with notes within ``CHORD_MS`` of each other merged."""
    events: list[list] = []
    for note in sorted(notes, key=lambda item: (item.epoch_ms, item.pitch)):
        if events and note.epoch_ms - events[-1][0] <= CHORD_MS:
            events[-1][1].append(note.pitch)
        else:
            events.append([note.epoch_ms, [note.pitch]])
    return events


def _hand(pitch: int) -> str:
    return "L" if pitch < HAND_SPLIT else "R"


def features(notes: Sequence[Note]) -> collections.Counter:
    """The multiset of local content features. Tempo-invariant by construction."""
    events = _events(notes)
    out: collections.Counter = collections.Counter()
    for index, (_, pitches) in enumerate(events):
        for pitch in pitches:
            out[("n", _hand(pitch), pitch % PITCH_CLASSES)] += 1
        if len(pitches) > 1:
            out[("c", frozenset(pitch % PITCH_CLASSES for pitch in pitches))] += 1
        if index + 1 < len(events):
            for first in pitches:
                for second in events[index + 1][1]:
                    if _hand(first) != _hand(second):
                        continue
                    step = max(-12, min(12, second - first))
                    out[("m", _hand(first), first % PITCH_CLASSES,
                         second % PITCH_CLASSES, step)] += 1
    return out


def pooled(parts: Iterable[collections.Counter]) -> collections.Counter:
    """One signature from every part of one piece."""
    total: collections.Counter = collections.Counter()
    for part in parts:
        total.update(part)
    return total


def idf(signatures: Mapping[int, collections.Counter]) -> dict:
    """How much each feature tells pieces apart, over the pieces that exist right now.

    A feature in every piece carries almost nothing; one in a single piece is close to a
    name. This is why the representation gets *better* as the library grows rather than
    worse, and it is the mechanism behind the future-proofing claim.
    """
    document_frequency: collections.Counter = collections.Counter()
    for signature in signatures.values():
        for key in signature:
            document_frequency[key] += 1
    count = max(1, len(signatures))
    return {
        key: math.log((count + 1) / (frequency + 1)) + 0.05
        for key, frequency in document_frequency.items()
    }


def _mass(counter: collections.Counter, weights: Mapping) -> float:
    return sum(weights.get(key, 0.0) * value for key, value in counter.items())


def containment(query: collections.Counter, reference: collections.Counter,
                weights: Mapping) -> float:
    """What share of the *smaller* side's information the two explain.

    Containment rather than cosine, because a drill is a snippet of a piece: cosine would
    punish the query for every feature the piece has that the query does not, which is
    almost all of them.
    """
    numerator = 0.0
    for key, value in query.items():
        weight = weights.get(key, 0.0)
        if weight:
            numerator += weight * min(value, reference.get(key, 0))
    denominator = min(_mass(query, weights), _mass(reference, weights))
    return numerator / denominator if denominator > 0 else 0.0
```

### Step 3.4 — verify GREEN

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_shingles.py
```

Expected: 7 passed.

### Step 3.5 — the hybrid, and per-piece pooling

The DB read belongs to `store.py` (the transaction owner); the arithmetic belongs to
`similarity.py` (the scorer). `Candidate` is `frozen=True`, so the blend uses
`dataclasses.replace` rather than mutating.

In `backend/app/practice/similarity.py`, add at the end:

```python
def blend(
    candidates: Sequence[Candidate],
    shares: Mapping[int, float],
    *,
    weight: float,
) -> list[Candidate]:
    """Mix each piece's content share into its score, and re-rank.

    ``weight`` is how much of the score comes from the global fingerprint; the rest comes from
    containment over the local features. Measured on this app's corpus at 32 pieces, the mix
    beats either term alone at whole length *and* at a quarter length — the global term wins on
    whole material and the local term wins on fragments, so neither is dropped.
    """
    mixed = [
        replace(
            candidate,
            score=(1.0 - weight) * candidate.score
            + weight * float(shares.get(candidate.piece_id, 0.0)),
        )
        for candidate in candidates
    ]
    mixed.sort(key=lambda candidate: (-candidate.score, candidate.piece_id))
    return mixed
```

with `from dataclasses import dataclass, replace` and `Mapping` added to the typing import.

In `backend/app/practice/store.py`, add beside `_labelled_rows`:

```python
def _pooled_signatures(
    conn: sqlite3.Connection, *, exclude_segment_id: int | None = None
) -> dict[int, collections.Counter]:
    """One content signature per piece, from every segment a person labelled.

    Per piece and not per segment, which is what retires the reference window: matching costs
    O(pieces) rather than O(labels), a piece learned a year ago is exactly as strong as
    yesterday's, and one heavily-drilled piece can no longer fill the neighbour window and
    leave the runner-up undefined.
    """
    started: dict[int, int] = {}
    cache: dict[int, list] = {}
    signatures: dict[int, collections.Counter] = {}
    for row in _labelled_rows(conn, exclude_segment_id=exclude_segment_id):
        sitting_id = int(row["sitting_id"])
        if sitting_id not in started:
            found = conn.execute(
                "SELECT started_ms FROM sittings WHERE id = ?", (sitting_id,)
            ).fetchone()
            started[sitting_id] = int(found["started_ms"])
            cache[sitting_id] = _sitting_notes(conn, sitting_id, started[sitting_id])
        base = started[sitting_id]
        low, high = base + int(row["start_ms"]), base + int(row["end_ms"])
        notes = [note for note in cache[sitting_id] if low <= note.epoch_ms < high]
        if notes:
            signatures.setdefault(int(row["piece_id"]), collections.Counter()).update(
                shingles.features(notes)
            )
    return signatures
```

with `import collections` and `from . import shingles` added to the imports.

Then in `segment_identification`, blend before returning:

```python
    pooled = _pooled_signatures(conn, exclude_segment_id=segment_id)
    if pooled:
        weights_by_feature = shingles.idf(pooled)
        shares = {
            piece_id: shingles.containment(segment_signature, signature, weights_by_feature)
            for piece_id, signature in pooled.items()
        }
        candidates = blend(
            candidates, shares, weight=settings.autotag_containment_weight
        )
```

where `segment_signature` is `shingles.features(<the segment's notes>)`, computed once beside
`segment_print`. Add `autotag_containment_weight: float = _env_float(
"SRT_AUTOTAG_CONTAINMENT_WEIGHT", 0.25)` to `config.py`, and add the
`autotag_containment_weight` row to the weights table in `measure_autotag.py` so the value is
*chosen* rather than asserted (22-D7).

### Step 3.6 — the retiring change

In `backend/app/practice/store.py`, `_labelled_rows(limit=settings.autotag_training_limit)` is no
longer the reference set — pooled signatures are. Change the two live call sites (lines ~1783 and
~1851) to build pooled signatures, and delete the block in `identification_quality` that appends
the "older N are beyond the matcher's reference window" note, because that sentence will describe
behaviour that no longer exists. This is the retirement named in § Retirement and it must land in
the same commit as the change that causes it.

### Step 3.7 — verify GREEN and the 32-piece gate

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py tests/test_api.py
cd .. && ./check.sh --fast
cd backend && .venv/bin/python -c "
import sys; sys.path.insert(0,'tools'); sys.path.insert(0,'.')
import measure_autotag as M
for k in (8,16,32):
    M.PIECES = M.pieces_for(k)
    d = M.build_corpus()
    M.report(f'{k} pieces', M.evaluate(d, weights=M.DEFAULT_WEIGHTS))
"
```

Expected: at 32 pieces the hybrid is at least 5 points above the current fingerprint at whole
length and at least 10 points above at quarter length (acceptance 2). **If it is not, stop** — the
drift rule in the Execution Readiness View says return to the spec rather than ship the
representation.

### Step 3.8 — falsify tempo-invariance

Create `backend/tools/falsifications/drop_tempo_invariance.sh`, replacing
`max(-12, min(12, b - a))` with `(max(-12, min(12, b - a)), ioi_bin)` in the melodic key, and verify
it is caught by `test_the_same_passage_at_half_speed_is_the_same_features`:

```bash
cd .. && chmod +x backend/tools/falsifications/drop_tempo_invariance.sh
git add -A && git commit -q -m "Phase 22b: hear the piece in pieces"
backend/tools/falsify.sh backend/tools/falsifications/drop_tempo_invariance.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_shingles.py"
```

Expected: `falsified: the check caught the break`.

---

## Task 4 — 22c: passages and piece-sessions

**Files.** create `backend/app/practice/passages.py`, `backend/tests/test_passages.py`; modify
`backend/app/practice/models.py`, `backend/app/practice/store.py`, `frontend/src/lib/types.ts`,
`frontend/src/components/PracticeLogView.svelte`.

**Why.** Six attempts at one passage are six unrelated rows today. This is what makes the log say
what the owner actually did, and it is where 54 labelling decisions become about 15.

**Change Necessity.** Code: nothing derives a group above a segment.

**Impact / Compatibility.** One additive field on `SittingDetail`. No schema change, no new route.

### Step 4.1 — write the failing units

Create `backend/tests/test_passages.py`:

```python
"""Grouping attempts into passages, and passages into piece-sessions."""

from __future__ import annotations

from app.practice.passages import Attempt, derive, piece_sessions

#: Uniform weights, and signatures as plain counters, so these units are about the grouping
#: decision rather than about feature extraction (which has its own suite).
WEIGHTS = {"a": 1.0, "z": 1.0}
SAME = {"a": 10}
DIFFERENT = {"z": 10}


def attempt(id: int, start_ms: int, end_ms: int, piece_id: int | None = None) -> Attempt:
    return Attempt(id=id, start_ms=start_ms, end_ms=end_ms, piece_id=piece_id)


def test_adjacent_attempts_of_one_passage_group() -> None:
    attempts = [attempt(1, 0, 1_000), attempt(2, 5_000, 6_000), attempt(3, 9_000, 10_000)]
    signals = {1: SAME, 2: SAME, 3: SAME}
    out = derive(attempts, signals, WEIGHTS)
    assert len(out) == 1
    assert out[0].attempts == 3
    assert out[0].attempt_ids == (1, 2, 3)
    assert (out[0].start_ms, out[0].end_ms) == (0, 10_000)


def test_different_material_makes_a_new_passage() -> None:
    attempts = [attempt(1, 0, 1_000), attempt(2, 5_000, 6_000)]
    signals = {1: SAME, 2: DIFFERENT}
    out = derive(attempts, signals, WEIGHTS)
    assert len(out) == 2


def test_a_differing_label_is_always_a_boundary() -> None:
    """Two pieces are two passages however alike they sound."""
    attempts = [attempt(1, 0, 1_000, 7), attempt(2, 5_000, 6_000, 8)]
    signals = {1: SAME, 2: SAME}
    assert len(derive(attempts, signals, WEIGHTS)) == 2


def test_a_matching_label_is_not_enough_on_its_own() -> None:
    """Bars 1-16 and bars 40-60 of one piece are two passages, not one."""
    attempts = [attempt(1, 0, 1_000, 7), attempt(2, 5_000, 6_000, 7)]
    signals = {1: SAME, 2: DIFFERENT}
    assert len(derive(attempts, signals, WEIGHTS)) == 2


def test_a_passage_takes_the_label_any_of_its_attempts_carries() -> None:
    attempts = [attempt(1, 0, 1_000), attempt(2, 5_000, 6_000, 7)]
    signals = {1: SAME, 2: SAME}
    out = derive(attempts, signals, WEIGHTS)
    assert len(out) == 1 and out[0].piece_id == 7


def test_an_attempt_with_no_signature_is_its_own_passage() -> None:
    """A segment with no notes cannot be shown to belong with anything."""
    attempts = [attempt(1, 0, 1_000), attempt(2, 5_000, 6_000)]
    signals = {1: SAME}
    assert len(derive(attempts, signals, WEIGHTS)) == 2


def test_nothing_is_no_passages() -> None:
    assert derive([], {}, WEIGHTS) == []


def test_the_round_trip_is_stable() -> None:
    """The same labels always produce the same groups, which is what makes deriving safe."""
    attempts = [attempt(1, 0, 1_000, 7), attempt(2, 5_000, 6_000, 7), attempt(3, 9_000, 10_000, 8)]
    signals = {1: SAME, 2: SAME, 3: SAME}
    first = derive(attempts, signals, WEIGHTS)
    second = derive(attempts, signals, WEIGHTS)
    assert [(p.piece_id, p.attempt_ids) for p in first] == \
           [(p.piece_id, p.attempt_ids) for p in second]
    assert len(first) == 2


def test_piece_sessions_group_adjacent_passages_of_one_piece() -> None:
    """Two attempts of piece 7, then one of piece 8, then two more of piece 7."""
    attempts = [attempt(1, 0, 1_000, 7), attempt(2, 5_000, 6_000, 7),
                attempt(3, 9_000, 10_000, 8),
                attempt(4, 12_000, 13_000, 7), attempt(5, 15_000, 16_000, 7)]
    signals = {1: SAME, 2: SAME, 3: DIFFERENT, 4: SAME, 5: SAME}
    passages = derive(attempts, signals, WEIGHTS)
    assert [(p.piece_id, p.attempts) for p in passages] == [(7, 2), (8, 1), (7, 2)]
    assert piece_sessions(passages) == [(7, (0,)), (8, (1,)), (7, (2,))]
```

### Step 4.2 — verify RED, then the module

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_passages.py
```

Expected: `ModuleNotFoundError: No module named 'app.practice.passages'`.

Create `backend/app/practice/passages.py`:

```python
"""Groups above a segment: the passage, and the piece-session.

Six attempts at one passage are six unrelated rows today, and the owner's own library shows the
pattern plainly: of nineteen consecutive same-piece segment pairs, the musical material is
essentially identical in every one.

The row the musician wants is the **passage**, with its attempts as the detail; the heading is the
**piece-session**. Both are derived and never stored (22-D1), and the label stays on the segments
(22-D2), so regrouping after an edit loses nothing — the same labels always produce the same groups.

Grouping uses content, not the label. A *differing* label is a hard boundary, because two pieces
are two passages whatever they sound like; a *matching* label is not sufficient on its own, or bars
1-16 and bars 40-60 of one piece would be welded together.

Pure: no database, no clock, no configuration import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .shingles import containment

#: Measured on this library: same-piece adjacent pairs score a median of 0.957 and
#: different-piece pairs a median of 0.647, so 0.90 separates them with room to spare.
PASSAGE_SIMILARITY = 0.90


@dataclass(frozen=True)
class Attempt:
    """One stored segment, as the grouping sees it."""

    id: int
    start_ms: int
    end_ms: int
    piece_id: int | None


@dataclass(frozen=True)
class Passage:
    """Adjacent attempts that are the same musical material, and how many there were."""

    start_ms: int
    end_ms: int
    piece_id: int | None
    attempt_ids: tuple[int, ...]

    @property
    def attempts(self) -> int:
        return len(self.attempt_ids)


def derive(
    attempts: Sequence[Attempt],
    signatures: Mapping[int, Mapping],
    weights: Mapping,
    *,
    threshold: float = PASSAGE_SIMILARITY,
) -> list[Passage]:
    """The passages of one sitting, oldest first."""
    if not attempts:
        return []
    groups: list[list[Attempt]] = [[attempts[0]]]
    for previous, attempt in zip(attempts, attempts[1:]):
        if _continues(previous, attempt, signatures, weights, threshold):
            groups[-1].append(attempt)
        else:
            groups.append([attempt])
    return [_passage(group) for group in groups]


def _continues(
    previous: Attempt,
    attempt: Attempt,
    signatures: Mapping[int, Mapping],
    weights: Mapping,
    threshold: float,
) -> bool:
    if previous.piece_id is not None and attempt.piece_id is not None:
        if previous.piece_id != attempt.piece_id:
            return False
        # Same piece is necessary but not sufficient — see the module docstring.
    first, second = signatures.get(previous.id), signatures.get(attempt.id)
    if not first or not second:
        return False
    return containment(second, first, weights) >= threshold


def _passage(group: list[Attempt]) -> Passage:
    return Passage(
        start_ms=group[0].start_ms,
        end_ms=max(attempt.end_ms for attempt in group),
        piece_id=next((a.piece_id for a in group if a.piece_id is not None), None),
        attempt_ids=tuple(attempt.id for attempt in group),
    )


def piece_sessions(passages: Sequence[Passage]) -> list[tuple[int | None, tuple[int, ...]]]:
    """Adjacent passages sharing a piece, as ``(piece_id, passage indices)``."""
    if not passages:
        return []
    out: list[tuple[int | None, list[int]]] = [(passages[0].piece_id, [0])]
    for index, passage in enumerate(passages[1:], start=1):
        if passage.piece_id is not None and passage.piece_id == out[-1][0]:
            out[-1][1].append(index)
        else:
            out.append((passage.piece_id, [index]))
    return [(piece, tuple(members)) for piece, members in out]
```

### Step 4.3 — verify GREEN

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_passages.py
```

### Step 4.4 — the additive field

In `backend/app/practice/models.py`, add `class PassageOut(BaseModel)` and
`passages: list[PassageOut] = Field(default_factory=list)` to `SittingDetail`. Additive with a
default, so every existing assertion about `SittingDetail` still holds. Populate it in
`store.sitting_detail` from `passages.derive(...)`.

Mirror `Passage` and the field in `frontend/src/lib/types.ts`.

### Step 4.5 — the view, and the confirmation

In `PracticeLogView.svelte`, render a passage as the row and its attempts beneath it, with a
piece-session heading above a run of passages sharing a piece. Keep `data-segments` and every
existing test hook intact — the browser scenario counts `.segment`, so the attempts must remain the
`.segment` elements rather than being replaced by passages.

**The confirmation writes the member attempts (22-D2, acceptance 5).** The label stays on segments,
so labelling a passage is the per-segment route that already exists, sent once per member. That is
what keeps durability where it already lives and needs no group table and no new endpoint. Add
beside `applyUndo` in `PracticeLogView.svelte`:

```ts
  /**
   * Label a whole passage at once.
   *
   * The label lives on the segments (22-D2), so this is the route that already exists, sent
   * once per member rather than a new one: nothing about where a label is stored changes, and
   * there is no group to keep in step with the segments. `undoable` is off because the inverse
   * of a many-segment write is not one action, and offering one would be a lie.
   */
  async function labelPassage(attemptIds: number[], pieceId: number | null): Promise<void> {
    await edit(
      async () => {
        let last: unknown = [];
        for (const id of attemptIds) last = await api.practice.assignSegment(id, pieceId);
        return last;
      },
      { undoable: false },
    );
  }
```

The passage row calls it with `passage.attempt_ids`.

### Step 4.6 — verify

```bash
cd frontend && npm test && npm run check && npm run build
cd .. && ./check.sh --fast
backend/tools/run_e2e.sh practice_log
```

Expected: green, and the browser scenario still counts segments as it did.

Then the two acceptance checks this task owns. **Write this test before the wiring**, per the TDD
route:

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py -k "passage or segment"
```

Expected: a test asserting that after labelling a passage every member attempt carries the
`piece_id`, that re-deriving produces the same passages from the same labels, and that the
`passages` field is additive with a default — so every pre-existing `SittingDetail` assertion still
passes unchanged (acceptance 5 and 6).

---

## Task 5 — 22d: the band, and the run-through

**Files.** modify `backend/app/config.py`, `backend/app/practice/store.py`,
`backend/app/practice/similarity.py`, `backend/tools/measure_autotag.py`, docs.

**Why.** The auto band has never fired once. With the representation fixed it can be **chosen**
rather than asserted, and the run-through the owner plays when a piece is finished becomes the
piece's best possible reference.

### Step 5.1 — choose the band

Extend the band table in `measure_autotag.py` to print coverage and precision per band on the
32-piece corpus, run it, and set `autotag_score_auto`, `autotag_score_prompt` and
`autotag_min_margin` from the table so auto precision is at least 95% (acceptance 4). Record the
chosen row in the commit message.

### Step 5.2 — the run-through anchor

The owner runs a piece through when it is finished; that is the best reference the piece will ever
have (22-D6). Add to `backend/app/practice/shingles.py`:

```python
#: A run-through is at least this many times the piece's median attempt length. The owner plays
#: one when a piece is done; it is the best reference the piece will ever have, and length is the
#: only signal the notes carry on their own.
RUN_THROUGH_RATIO = 2.5


def anchor_weights(lengths_ms: Sequence[float]) -> list[float]:
    """How much each of one piece's attempts counts towards its signature, in order.

    A first approximation on purpose. Length alone cannot tell a run-through from a long section,
    so this is kept only if it moves a run-through query — measured by ``tools/measure_real.py``
    with a run-through held out. If it does not move it, the rule is deleted rather than kept and
    tuned, because a rule that does not pay for itself is entropy.
    """
    if not lengths_ms:
        return []
    ordered = sorted(lengths_ms)
    median = ordered[len(ordered) // 2]
    if median <= 0:
        return [1.0] * len(lengths_ms)
    return [
        RUN_THROUGH_RATIO if length >= RUN_THROUGH_RATIO * median else 1.0
        for length in lengths_ms
    ]
```

and in the units:

```python
def test_a_run_through_weighs_more_than_a_drill() -> None:
    lengths = [60_000.0, 55_000.0, 70_000.0, 600_000.0]
    weights = anchor_weights(lengths)
    assert weights[:3] == [1.0, 1.0, 1.0]
    assert weights[3] == RUN_THROUGH_RATIO


def test_all_attempts_alike_are_all_weighted_alike() -> None:
    assert anchor_weights([60_000.0, 61_000.0, 59_000.0]) == [1.0, 1.0, 1.0]


def test_no_attempts_weigh_nothing() -> None:
    assert anchor_weights([]) == []
```

Then `store._pooled_signatures` multiplies each segment's features by its anchor weight, computed
per piece from the labelled rows it already has, and the acceptance check is that a held-out
run-through identifies at least as well with the anchor as without it — if it does not, delete
`anchor_weights` and the call, and record that it was measured and did not pay.

### Step 5.3 — verify the whole phase

```bash
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm test && npm run check
cd .. && ./check.sh --full
```

Expected: `check.sh --full passed`.

### Step 5.4 — docs, and the commit

`README.md` (what the log now shows), `AGENT-LOG.md` (the landed entry, naming the retired window
and the measured tables), `docs/ECOSYSTEM.md` (the Phase 22 row to landed, per slice),
`docs/TEST-DATA.md` (the backup is now the re-cut corpus, with `measure_real.py` named as its
reader).

```bash
git add -A backend frontend docs README.md AGENT-LOG.md
git commit -m "Phase 22: hear the piece"
```

---

## Execution Route

```text
Execution Route:
- Decision: inline
- Evidence: five tasks, sequential on store.py and similarity.py, with the substantive halves in
  new pure modules that have a fast pytest tier; task 2 and task 3 are independent enough to be
  reordered, but both touch store.py so they are not parallel-safe in one workspace
- Fallback: none needed
- User confirmation required: no
```

