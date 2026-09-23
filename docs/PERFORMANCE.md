# Performance — what has to stay cheap

For whoever changes the backend next, human or agent. This document owns one question: **when you
add or change code on a path somebody waits for, what is its cost a function of?**

The answer here is not "as fast as possible". It is *what the request touches*, never *how large the
library has grown*. Everything below is a record of that rule being broken, measured, and fixed —
with the numbers, because "this looks slow" is how a cost model is lost.

The backend is one user, one piano, one SQLite file, served over the LAN from a slow laptop. That
makes the cost model simple and unforgiving: there is no horizontal scaling to hide behind, the disk
spins, and every extra pass over `note_events` is paid while somebody is looking at the screen. The
failures that have actually hurt this project were never micro-optimizations. Each was a loop whose
cost grew with something that grows forever — the library, the sitting, the number of open sections
— on a path that runs on every click.

Measured numbers below are from the owner's real library, rebuilt from the local backup that
[docs/TEST-DATA.md](TEST-DATA.md) owns — 238,665 note events, 539,726 pedal events, 68 segments, 54
of them labelled. They are shapes, not promises: re-measure on your own data before quoting one.

---

## 1. The four shapes that have cost real seconds

### 1.1 A scan of one list inside a loop over another

**Symptom.** Splitting or merging a segment took **3.0–7.6 s** unprofiled (21–24 s under `cProfile`),
so editing a sitting was unusable.

**Cause.** `pedal.blur_attacks` rebuilt a set by scanning the *entire* note list for every chord
cluster inside every pedal stretch:

```python
for stretch in stretches:
    for cluster in clusters:
        held = set()
        for note in ordered:          # the whole list, again, for every cluster
            if stretch.start_ms <= note.end_ms < attack_ms:
                held.add(note.pitch % 12)
```

One split made **81,751,107** calls to `Note.end_ms`. The profile named it immediately: 12.5 s self
time in `blur_attacks`, 6.5 s in `end_ms`.

**Fix.** Sort once by onset and once by release, bisect each stretch's slice out of the onset list,
and carry a cursor over the release list. The cursor is valid because clusters are in onset order,
so their attack times are non-decreasing — the held set only ever grows. O(stretches × clusters ×
notes) became O((N + S) log N), and split/merge are **170–182 ms**.

**Take the shape, not the function.** When an inner loop walks the same list on every outer
iteration: if the outer loop moves forward in time, a monotone cursor replaces it; if it selects a
contiguous range, a sort plus `bisect` replaces it.

### 1.2 A query by parent, called once per child

**Symptom.** Every edit was slow *while a sitting still had an unlabelled section*, and snapped back
the moment the last one was labelled. This was reported as "just my impression?" and it was not.

**Cause.** `store.segment_identification` fetched a segment's notes with a query **by sitting** —
`WHERE sitting_id = ?` returns every note in the sitting — and the caller kept one segment's share.
`candidates_for_sitting` asked it once per undecided segment, and every edit re-reads the sitting, so
a sitting read its own notes *n* times per click. Measured `sitting_detail` on a 23k-note sitting:

| open sections | before | after |
| --- | --- | --- |
| 0 | 80 ms | 78 ms |
| 1 | 171 ms | 171 ms |
| 5 | 241 ms | 173 ms |
| 20 | 516 ms | 207 ms |
| 50 | **1,062 ms** | **259 ms** |

`_notes_for_segments` was called 51 times, with 734 ms of the run inside `fetchall` alone.

**Fix.** Let the per-item function accept the data it would otherwise fetch (`notes=None` meaning
"fetch it yourself"), and have each caller in the loop read once for the whole run. Fix *every*
caller with the same shape: `_autotag_rows` had it too, on the pass that runs when a sitting is
first segmented.

**The tell.** A helper named "the X for one of these" that queries by the parent returns the whole
parent every time. Called in a loop over the parent's children, that is quadratic in the parent.

### 1.3 Derived-on-read material rebuilt on every read

**Symptom.** Opening a sitting took about a second, every time.

**Cause.** `examples_from` and `_pooled_signatures` derive a fingerprint and a content feature for
every labelled segment — a pass over a quarter of a million notes — and every sitting open, page load
and accuracy report paid it to get an answer that only changes when a label or a boundary changes.

**Fix.** `store.cached_references` keeps the material per database file, validated by
`reference_state.version`, which three triggers on `segments` maintain (insert, delete, and update of
exactly `piece_id`, `identified_by`, `start_ms`, `end_ms`). `sitting_detail` went **969 ms → 2.8 ms**
warm.

**Why the triggers matter more than the cache.** Invalidation owned by a list of call sites is a bug
waiting for the call site somebody adds later. Making the database maintain it means no write path
can forget — including an older build's, or the second machine writing the same file over the LAN.
The version is stored *beside* the material and checked on every read, so an out-of-order write
cannot paper over a relabel.

**Derived-on-read is a correctness virtue, not a cost one.** A suggestion must reflect the labels you
have *now*; that is an argument for computing it rather than storing it, and no argument at all for
computing it once per request. Cache it, and make the invalidation something you cannot forget.

### 1.4 Work gated on a pending state

`candidates_for_sitting` begins `if not undecided: return {}`. That single line is why the symptom in
1.2 had such a sharp boundary: the cost was zero once the last label landed, and grew with every open
section before that.

**Know when you have built one.** An early return keyed on a state a person can clear creates a
switch, and the switch is usually the explanation for a bug report that says "it depends". When you
write one, say so in the docstring — and when a read sits on the *edit* path, remember its cost is
multiplied by how often somebody clicks.

---

## 2. The rules

**R1 — Cost is a function of the request, not of the library.** If a click's cost grows with the
number of sittings, labels or notes in the database, it is a bug with a delay fuse. Bound it, cache
it, or say plainly in the docstring that it is O(library) and why that is acceptable.

**R2 — One query per parent, not per child.** Hoist the query out of the child loop and pass the
rows down (1.2). Check every caller of the helper, not just the one you found.

**R3 — Sort once, then bisect or carry a cursor.** Never rescan a list you have already walked (1.1).

**R4 — Cache derived material; let the database own the invalidation.** A version the writes maintain
(triggers) beats a list of call sites to remember (1.3).

**R5 — Never bound cost by discarding data.** A newest-N cap on the matcher's references is a
*correctness* change wearing a performance fix's clothes: measured on the owner's library, a newest-10
cap evicted a piece outright and a newest-5 cap answered with a different piece. That window is the
defect Phase 22b retired; see [docs/PLAN-PHASE22.md](PLAN-PHASE22.md) and the guard in
`tests/test_autotag.py` that pins it.

**R6 — Count work in tests, never seconds.** A timing assertion passes on a quiet machine and fails
in CI. Assert that the number of reads does not grow with the input (see §5).

**R7 — Fixed per-request costs matter on a slow disk.** A connection that sets a PRAGMA, a payload
that is not compressed, a query with no index: small each, paid on every click. `PRAGMA
journal_mode = WAL` is a property of the file and does not need re-issuing per connection.

**R8 — Measure before optimizing.** The piano roll's per-frame note filter looked like an obvious
win. Measured, one pass over 23,482 notes is **0.140 ms**, about 0.8% of a 60 fps frame — the
windowed binary search it implied would have bought a seventh of a millisecond for a sorted-order
contract. It is not in the code, and that is the right answer.

**R9 — A schema index is part of the cost model.** Every hot `WHERE`/`ORDER BY` should be able to use
one. `note_events(sitting_id, onset_ms)` and `segments(sitting_id, start_ms)` are why the per-sitting
reads are cheap; check the query plan before assuming.

---

## 3. The map — what must stay cheap

If you touch one of these, you own its complexity.

| Function or path | Its cost may scale with | Guarded by |
| --- | --- | --- |
| `pedal.blur_attacks` | the segment's notes and stretches, O((N+S) log N) | `tests/test_pedal.py`, `falsifications/drop_blur_positions.sh` |
| `store._notes_for_segments` | one query per sitting; the notes in the group's range | `test_reading_a_sitting_does_not_read_its_notes_once_per_open_section` |
| `store.cached_references` | nothing on a hit; the labelled set only when the version moves | the invalidation tests in `tests/test_autotag.py` |
| `store.segment_identification` | what the caller hands it; accept `examples`, `signatures`, `notes` rather than re-deriving | — |
| `store.candidates_for_sitting` | the sitting's own segments, and its notes **once** | the note-read guard above |
| `store._refresh_metrics` | the sitting's notes and its pedal stream, once each | metric equivalence in `tests/test_practice_metrics.py` |
| `store._labelled_rows` | the labelled set — **uncapped on purpose** | `test_every_label_is_a_reference_however_lopsided_the_library` |
| `db.connect` | per request; keep the fixed part small (R7) | — |
| `db.init_db` | startup only; it may run migrations | `tests/test_migration_upgrade.py` |
| `practice/api.py` responses | the events in the sitting; gzip is on for ≥1 KB | — |

---

## 4. How to measure

Do not guess, and do not profile first — profile tells you *where*, not *how much*, and it inflates
wall time by 3–4×.

```bash
cd backend
mkdir -p .scratch            # gitignored; fixtures belong here, not /tmp
```

1. **Build a fixture that has the right row counts.** `.scratch/` is gitignored, and code paths that
   run against the real library must be exercised against something the right size.
   [docs/TEST-DATA.md](TEST-DATA.md) owns where the real backup is and what is in it; rebuild a
   working database from it by running `db.init_db` for the schema and then inserting each table's
   rows. Row counts are what matter; byte size is a symptom.
2. **Time the real functions unprofiled.** Call `store.split_segment`, `store.sitting_detail`,
   `store.candidates_for_sitting` and so on against a copy, and record milliseconds.
3. **Then profile for attribution only.** `cProfile` + `pstats.sort_stats("tottime")` names the hot
   function; the numbers you report come from step 2.
4. **Scale the input and watch the growth.** Double the labels, the notes, or the open sections. Time
   that roughly doubles is linear and probably fine; quadrupling is quadratic and is a bug.
5. **For the matcher, use the existing tools.** `backend/tools/measure_real.py` and
   `backend/tools/measure_autotag.py` run the shipped `rank`/`identify` rather than a reimplementation.

---

## 5. How to guard it

**Count work, not seconds.** A test that says "this took under 200 ms" is a test that fails on a
loaded CI runner for no reason, and passes on a fast laptop while the bug is present. Assert the
*shape* instead — that the number of reads does not grow with the input:

```python
calls = {"n": 0}
original = store._notes_for_segments

def counted(conn, rows):
    calls["n"] += 1
    return original(conn, rows)

monkeypatch.setattr(store, "_notes_for_segments", counted)
store.sitting_detail(small)          # 2 open sections
after_small = calls["n"]
store.sitting_detail(large)          # 8 open sections
assert calls["n"] - after_small == after_small
```

Two traps in that idiom, both hit while writing it: **warm any cache before you start counting** (the
first read legitimately costs an extra build, which looks like scaling), and count the *helper you
changed*, not the wall clock.

**Prove equivalence when the change is meant to be invisible.** For a pure refactor, copy the old
implementation into a scratch harness as the reference and compare: thousands of randomized cases
plus every real row. That is stronger evidence than the suite passing, because the suite only covers
the cases somebody thought of.

**Every new assertion gets a break script.** The standing rule in
[docs/TEST-STRATEGY.md](TEST-STRATEGY.md) §8 is that an assertion is not trusted until it has been
seen to fail:

```bash
backend/tools/falsify.sh backend/tools/falsifications/<your_break>.sh
```

It runs the check on the clean tree first, applies your break, rebuilds, and requires the check to
fail *and* to name the assertion you meant. A check that passes with the break applied is not a
check.

**And the tier that must stay green:** `./check.sh --fast`.

---

## 6. What not to optimize

- **Anything you have not measured.** See R8. The repo has one measured non-optimization already.
- **A cache without a checkable version.** If you cannot say what invalidates it, you cannot say it
  is correct.
- **A cap that discards data** to bound work (R5). Bound the caller instead — for the accuracy report
  that is `settings.autotag_quality_limit`, which caps how many segments are evaluated and says so in
  the report rather than sampling silently.
- **A read that a write makes unnecessary.** The deepest remaining cost here is that every edit
  re-reads the whole sitting detail so the derived passages stay honest; returning the passages with
  the edit's own response would remove the re-read. That is a contract change, not a fix, and it
  belongs in a plan rather than in a quick patch.

---

## 7. The checklist

Before you commit backend work that touches a hot path:

- [ ] What is this cost a function of? Does it grow with the library, the sitting, or the labels?
- [ ] Is there a query inside a loop that is by *parent* rather than by the item? (R2)
- [ ] Is there a list rescanned on every outer iteration? (R3)
- [ ] Am I deriving something on every read that only changes on a write? (R4)
- [ ] If I cached it, what invalidates it — and can a write path forget? (R4)
- [ ] Did I measure it, before and after, unprofiled? (R8)
- [ ] Does the guard count work rather than time, and does it have a break script? (§5)
- [ ] If behaviour is meant to be unchanged, did I prove equivalence? (§5)

---

## 8. Where the record lives

The case studies are in `AGENT-LOG.md`, with the commits that fixed them. The four that produced this
document: `a63e991` (1.1 and 1.2-part), `b9e0be5` (1.3), `8b775c3` (1.2), `94590af` (R5). The
non-optimization in R8 is `f7decad`.

[docs/TEST-STRATEGY.md](TEST-STRATEGY.md) owns how a change is known not to have broken something;
[docs/ENGINEERING.md](ENGINEERING.md) owns what the code is. This document owns what it costs.
