# Plan — Phase 22: hearing the piece

**Parent spec:** [`ECOSYSTEM.md`](./ECOSYSTEM.md) § *Phase 22*, which adopts this document as the
how. The *why* — the measurement that made this a phase at all — is § *The measured case* below,
and it is the reason the phase exists rather than the identification work being a tuning change.

**Status:** planned.

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

**Next step:** user review of this spec, then `writing-plans` for the task decomposition. No
implementation before that.
