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
[docs/TEST-DATA.md](TEST-DATA.md) owns — 512,010 note events, 1,151,770 pedal events, 38 sittings,
732 segments of which 443 are references. Older figures quoted inside a section were taken on an
earlier, smaller rebuild of the same library and say so in place. They are shapes, not promises:
re-measure on your own data before quoting one.

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

### 1.5 An invalidation rule wider than the thing it invalidates

**Symptom.** The first click on a sitting nobody had opened took **1,755 ms**, and the same click
afterwards took 90 ms. Reported as "it takes some time when I first click it".

**Cause.** The reference cache is keyed on `reference_state.version`, which three triggers on
`segments` bump. Two of the writes that bumped it cannot change what the cache is made of:

* `ensure_segments` inserts its new segments **unlabelled**, and `_labelled_rows` only selects
  segments with a piece on them;
* `_tag_from_workouts` rewrites `identified_by` on every segment a workout overlaps — including
  segments with no piece at all — and `identified_by` is in the UPDATE trigger's column list,
  because it decides whether a row is a `similarity` guess and therefore not training data.

So segmenting a sitting threw away the material it was about to read. Measured on the owner's
library, in one process with the cache warm, on identical fixtures:

| Invalidation rule | first click | reference rebuilds during it |
| --- | ---: | ---: |
| every write | 1,755 ms | 1 |
| only a reference change | **699–770 ms** | **0** |

That is ~985 ms — well over half the wait — spent deriving, from 49 labelled segments and a
quarter of a million notes, an answer identical to the one just discarded.

**Fix.** Each trigger asks whether the row *is or becomes* a reference:
`piece_id IS NOT NULL AND COALESCE(identified_by, '') <> 'similarity'`. The insert and delete
triggers guard on the row itself; the update trigger guards on either side of the change, because a
row entering or leaving the set is a change and a write to a row that is not a reference on either
side is not. `schema.py` drops and recreates the triggers, since `CREATE TRIGGER IF NOT EXISTS`
would leave an existing database on the old rule for ever.

**Take the shape, not the SQL.** An invalidation rule must be a function of *exactly* what the
derived material is a function of. Over-invalidating is always safe and never free, and on a path
that both writes and reads the cache it is not a rounding error — it was the dominant cost of the
whole operation. The direction of the risk is what makes this hard: over-bumping costs a rebuild,
under-bumping serves a stale answer, so narrow it against a test that walks every write path which
*does* change the set, not against one that only proves the cheap direction.

### 1.6 Work that runs on a read, when the read is not the only thing that knows the work is due

The other half of that same 1,755 ms was not a cost problem at all: the segmentation, its metrics,
the matcher's pass and the kind offers all ran inside the request that first opened the sitting,
although nothing about them depends on somebody looking. They depend on the playing having stopped,
and the server is told that far earlier — the browser closes the sitting when the piano goes away.

So the work moved to a background thread (`practice/jobs.py`), triggered by the close route, by a
sweep every twenty seconds, and once at boot; and the read, when it finds that work already
scheduled, answers `preparing` in about a millisecond instead of waiting for it. The click on a
fresh sitting is now the warm read it already was on every other one (~90 ms, §1.3).

**The rule this keeps.** The background pass calls the same `store.ensure_segments` the read still
calls when nothing is scheduled. It owns *when*, never *what*, so it is an optimisation over a path
that still works — which is also why a job that fails is survivable and why turning it off
(`SRT_BACKGROUND_JOBS=0`) is the old behaviour rather than a degraded one.

### 1.7 A limit that does not bound the work

**Symptom.** The Log dashboard's poll cost **110 ms**, and its ten-row sitting list cost the same
as a thousand-row one.

**Cause.** Two queries whose bound was decorative.

`list_sittings_conn` counted notes with a `LEFT JOIN ... GROUP BY s.id` and put the `LIMIT` on the
outside. An aggregate is not bounded by a limit: SQLite grouped every note event in the database,
sorted the result with a temp B-tree, and *then* took ten rows. The list was a function of the log
rather than of the page:

| the join form | work |
| --- | ---: |
| `LIMIT` 1 | 65.3 ms |
| `LIMIT` 1000 | 65.4 ms |

`calendar` was the same defect with the bound applied in Python instead: it grouped **every** sitting
and joined **every** note event, and `_fill_days` kept the requested days at the end. A one-day
calendar cost 20.3 ms and a thirty-day calendar cost 20.3 ms.

**The fix is to choose the rows first and count them second.** A correlated subquery per *returned*
row is answered from `idx_events_sitting` — but only once the limited set is materialised:

```sql
WITH recent AS MATERIALIZED (
    SELECT id, started_at, ended_at, local_date, source, started_ms, ended_ms
    FROM sittings ORDER BY started_ms DESC LIMIT ?
)
SELECT r.id, (SELECT COUNT(*) FROM note_events e WHERE e.sitting_id = r.id) AS note_count, ...
FROM recent r ORDER BY r.started_ms DESC
```

`calendar` got the window filter `sources` and `by_piece` already had.

| | before | after |
| --- | ---: | ---: |
| `list_sittings_conn(10)` | 65.2 ms | **2.9 ms** |
| … at `LIMIT` 1 / 10 / 1000 | 65.3 / 65.2 / 65.4 | **0.2 / 3.0 / 10.1** |
| `calendar(1)` | 20.3 ms | **0.0 ms** |
| `calendar(30)` | 20.3 ms | 20.2 ms |
| `summary(days=30)` | 110.1 ms | **47.1 ms** |

**The shape, and the trap inside it.** "Bound the query" is not the same as "add a `LIMIT`", and the
obvious correction is not sufficient on its own. Plain correlated subqueries — no CTE — look right,
return identical rows, and measure 10 ms on the real library, and they are *still* a function of the
log: a subquery in the result list is evaluated for every row the scan visits, including the ones
the limit throws away. The work test caught exactly that, at 400 notes added to a sitting the list
does not return: 660 → 1,857 VM steps. Materialised first, it is 686 → 686.

### 1.8 A cache key borrowed from a narrower rule

**Symptom.** Opening the largest sitting took **165 ms**, 130 ms of it deriving the sitting's
passages, and every open, every edit's re-read and every poll paid it again.

**Cause.** `_passage_rows` derived a content feature for each segment, in a pass over the sitting's
notes, on every read. The obvious key was the one the reference cache already uses,
`reference_state.version`. It would have been wrong in the dangerous direction: that counter moves
only when a *reference* changes (§1.5), and a re-segment which deletes segments nobody had labelled
leaves it still — while changing exactly the rows the passages are a function of. A cache keyed on
it would have served the boundaries from before the edit.

**Fix.** Key it on the inputs: the sitting's segment rows (ids, boundaries, pieces) and the sitting's
note count. Notes are only ever appended, so the count is exact rather than a proxy. A key that *is*
the inputs cannot be forgotten by a write path that does not exist yet — the property that made the
trigger-owned reference cache correct — and a piece's *name* is deliberately in neither the key nor
the value, so renaming a piece is answered rather than remembered.

| | before | after |
| --- | ---: | ---: |
| `_passage_rows`, largest sitting (33k notes, 60 segments) | 130.2 ms | **0.7 ms** |
| `sitting_detail`, that sitting | 165.0 ms | **37.9 ms** |
| `sitting_detail`, median sitting | 52.8 ms | **1.1 ms** |

**The shape.** R4 says to let the database own the invalidation, which is the right instinct and an
incomplete instruction: a database can only own a counter it maintains, and a counter maintained for
a *different* question is narrower than yours. When the derived value is a function of rows rather
than of a labelled set, key it on those rows.

**A key is only as good as the writes it can see, though.** Keying on the inputs is immune to a
write path forgetting to invalidate *within* one database, and blind to a wholesale rewrite of that
database's contents: `import_document` replaces every row and restarts nothing, and a `replace`
restore reproduces a sitting's segment rows and note count *exactly* while the notes are whatever
the document carried. So the import drops both caches itself — the same `forget_references()` that
`init_db` calls, for the same reason. Guarded by
`test_a_restore_drops_the_caches_derived_from_the_rows_it_replaced`.

### 1.9 An export assembled in memory, to be written to a file

**Symptom.** The nightly backup peaked at **2,539 MB** on the owner's 4 GB notebook to produce a
160 MB document — an out-of-memory kill waiting for the night the library grew, with no cgroup limit
to catch it. The Download button had the same shape, at 948 MB.

**Cause.** Two costs, multiplied. `export_document` built every row of every table as a list of
dicts, and `json.dumps(..., indent=1)` then built the document's *text* as a second object on top of
it. `indent` is the expensive half on CPython: it assembles nested lists of strings before joining,
which is why the indented form peaked at 1,369 MB where the compact one managed 442 MB on the same
data. The fix could not be a faster `json.dumps` — the document itself was the problem.

**Fix.** Write the document instead of building it: walk the tables a row at a time, emit JSON
pieces, flush every 64 KiB. One serializer serves both writers, and the file is staged as `.part`
and renamed into place, so an interrupted run cannot leave a half-document for the rotation to keep
or for the status panel to report as the newest good backup.

| | before | after |
| --- | ---: | ---: |
| `write_backup`, process peak | 2,539 MB | **81 MB** |
| `GET /api/backup/export`, server peak RSS | not measured on the old code | **94 MB** |
| `iter_export_json`, serializer peak | — | 81 MB, in 2,447 pieces |
| `write_backup`, wall | 8,736 ms | **5,148 ms** |
| backup file | 206.3 MB | **160.5 MB** |

All of it on the rebuilt local fixture — **512,010 note events, 1,151,770 pedal events, 89 MB**
([TEST-DATA.md](TEST-DATA.md)) — and the server figure is from a real `uvicorn` process's `VmHWM`
after a 160.5 MB download, not from `TestClient`, which buffers the body and so reports the *client's*
peak. That is why the old server-side figure is left unmeasured rather than quoted: the 948 MB was
that confounded number, and the serializer's actual requirement was measured separately at **425 MB
in-process on half this library**. An honest gap beats a number that flatters the fix.

**The shape.** A stream that is serialised to one string and then written is not a stream, and
neither is one whose flush threshold is the document. The guard counts pieces rather than seconds,
because a timing assertion passes on a fast laptop with the defect present. See R11.

---

### 1.10 A whole derivation rebuilt for one changed input

**Symptom.** Re-tagging one segment — from one piece to another — took **1,808 ms** on the owner's
library, 1,010 ms of it reading notes and 1,700 ms deriving from them, to apply a one-row change. The
view writes a label and then reads the sitting back, so it landed *inside* the click, and only while
that sitting still had an undecided segment to suggest for (§1.4's switch).

**Cause.** Invalidation was exact and the rebuild was not. Phase 24 had already narrowed the trigger
to the columns the derivation is a function of, so the version moved for the right reason — and the
miss path then answered it by starting over: `_notes_for_segments` read **every** labelled sitting
whole, `fingerprints`/`shingles.features` ran over all 443 references (396,219 `Note` objects), and
`_pool_features` re-pooled all seven pieces. A version counter can say *that* something moved. It
cannot say *what*, and the cache entry was not recording the difference.

**Fix.** Keep the inputs. The entry gained a `{segment_id: (sitting_id, start_ms, end_ms, piece_id)}`
map — the four facts a segment's derivation is a function of — and a version miss is diffed against
it instead of obeyed. Three things follow, and each is load-bearing:

* Only the segments whose inputs moved are read, from their **own range** on
  `idx_events_sitting(sitting_id, onset_ms)` rather than from the sitting's whole list (R9 applied
  honestly): **606 notes in 1.0 ms** where the sitting-wide read is 14 ms for one segment.
* The pool is adjusted in O(1): subtract the moved segment's features from the piece it left, add
  them to the piece it joined, copying only those pieces' `Counter`s because `subtract` mutates.
* `examples` is rebuilt from `_labelled_rows`' own order rather than patched in place, because the
  matcher sees a *list* and a tie broken differently is a different answer.

`identified_by` is deliberately **not** among the four inputs. It decides membership, which
`_labelled_rows` has already applied, and it is not an input to a fingerprint or a content feature —
the same reasoning Phase 24 used one level up.

| | before | after |
| --- | ---: | ---: |
| the derivation a label click causes | 1,808 ms | **3.4 ms** |
| a click, end to end | 80.7 ms | **79.0 ms** |
| derivation work over 17 tag clicks | 30,736 ms | **58 ms** |

Measured on the rebuilt local fixture — **512,010 note events, 1,151,770 pedal events, 38 sittings,
682 segments of which 443 are references, 7 pooled pieces** ([TEST-DATA.md](TEST-DATA.md)) — with the
miss instrumented rather than modelled. The cold rebuild is unchanged at ~1,800 ms; what changed is
that a label click no longer pays it. **The click is 79 ms rather than the ~5 ms the derivation alone
would suggest** because the reference derivation was never the whole click: `sitting_detail` is ~73 ms
of it, and that is a different cost this phase did not touch.

**The shape.** R4's inversion has a second half, and this is it: *the rebuild must be proportional to
what changed*. A trigger that says "something moved" is a correct instruction to expire and a useless
instruction to rebuild — the entry has to record which inputs it was built from, or a miss can only
start over. R4 is extended below rather than duplicated.

**Two traps, both found by the tests rather than by reading.** A segment that *moves* between pieces
must be subtracted from the piece it left and not only a segment that is deleted, or its features are
counted under both pieces and the old piece keeps a signature it no longer owns. And
`Counter.subtract` leaves the keys it zeroed in place — a Counter whose values are all zero is still
*truthy*, so the obvious `if counts` keeps a piece that has just lost its last label. That piece is
not inert: `shingles.idf` counts `max(1, len(signatures))` documents, so one extra empty "document"
shifts every IDF weight and therefore every score, silently and library-wide, with no crash and no
visible symptom. The prune tests the values, and the equivalence guard compares **key sets**, because
a comparison that normalised empty signatures away could not see it.

**The worst case was measured, not assumed.** "Always incremental" is only justified if nothing is
lost at high churn, so every labelled segment was changed at once: **1,530 ms incremental against
1,985 ms rebuild at all 682**, and incremental won at every size from 10 up. There is no crossover, so
there is deliberately no threshold — deciding that by feel is what R8 exists to prevent. The margin
does narrow (≈500× at one changed segment, ≈1.3× at full churn), and if a future workload is ever
found where incremental loses, that is the measurement to revisit rather than a number to guess now.

**No lock, deliberately.** The background worker and request threads both reach this, and copy-on-write
makes it safe without one: a published entry is never mutated, so a reader sees the old entry or the
new one and never a torn one, and the version check is conservative in the right direction — an entry
is served only while the database still reports the version it was filed under, and versions never move
backwards while `note_events` is append-only. If a future change makes the derivation depend on
something that can *decrease*, that argument stops holding and a lock becomes necessary; that is the
trigger to revisit, recorded here so it is not rediscovered.

## 2. The rules

**R1 — Cost is a function of the request, not of the library.** If a click's cost grows with the
number of sittings, labels or notes in the database, it is a bug with a delay fuse. Bound it, cache
it, or say plainly in the docstring that it is O(library) and why that is acceptable.

**R2 — One query per parent, not per child.** Hoist the query out of the child loop and pass the
rows down (1.2). Check every caller of the helper, not just the one you found.

**R3 — Sort once, then bisect or carry a cursor.** Never rescan a list you have already walked (1.1).

**R4 — Cache derived material; let the database own the invalidation.** A version the writes maintain
(triggers) beats a list of call sites to remember (1.3) — and the trigger must count *only* what the
cached material is a function of, or it is the database throwing the cache away on the cache's own
read path (1.5). **And caching is not enough: the rebuild must be proportional to what changed.** A
counter can say *that* something moved; it cannot say *what*, so the entry must record the inputs each
part of the derivation came from and a miss must re-derive only those (1.10). Where the derived value
is one row per input, the read is that row's own range on its index (R9), not its parent's whole list.

**R5 — Never bound cost by discarding data.** A newest-N cap on the matcher's references is a
*correctness* change wearing a performance fix's clothes: measured on the owner's library, a newest-10
cap evicted a piece outright and a newest-5 cap answered with a different piece. That window is the
defect Phase 22b retired; see [docs/PLAN-PHASE22.md](PLAN-PHASE22.md) and the guard in
`tests/test_autotag.py` that pins it.

**R6 — Count work in tests, never seconds.** A timing assertion passes on a quiet machine and fails
in CI. Assert that the number of reads does not grow with the input (see §5).

**R7 — Fixed per-request costs matter on a slow disk.** A connection that sets a PRAGMA, a payload
that is not compressed, a query with no index: small each, paid on every click. `PRAGMA
journal_mode = WAL` is a property of the file and does not need re-issuing per connection. The
write side pays one too: at SQLite's default `synchronous = FULL` every COMMIT fsyncs the
write-ahead log — **1.165 ms against 0.012 ms** measured on the 512,010-note library, and a plain
piece *read* commits twice. Connections therefore ship `synchronous = NORMAL`; the durability that
gives up is stated once, in [DEPLOYMENT.md](DEPLOYMENT.md) § *Backup*.

**R8 — Measure before optimizing.** The piano roll's per-frame note filter looked like an obvious
win. Measured, one pass over 23,482 notes is **0.140 ms**, about 0.8% of a 60 fps frame — the
windowed binary search it implied would have bought a seventh of a millisecond for a sorted-order
contract. It is not in the code, and that is the right answer.

**R9 — A schema index is part of the cost model.** Every hot `WHERE`/`ORDER BY` should be able to use
one. `note_events(sitting_id, onset_ms)` and `segments(sitting_id, start_ms)` are why the per-sitting
reads are cheap; check the query plan before assuming.

**R10 — A `LIMIT` bounds a result, not the work that produced it.** An aggregate, a sort, or a
correlated subquery in the result list is evaluated *before* the limit applies, so "cheap, it only
returns ten rows" is a claim to measure rather than to assume (1.7). Bound the input: choose the
rows first, then compute over them.

**R11 — An export is written, not assembled.** A backup's cost is the size of the whole database, and
building the document *and* its text in memory multiplies that by two or three (1.9). Stream it to
the destination, flush in bounded pieces, and stage-then-rename so a run that dies half way leaves
nothing where a good backup belongs. The same shape applies to any response whose body is the whole
library.

---

## 3. The map — what must stay cheap

If you touch one of these, you own its complexity.

| Function or path | Its cost may scale with | Guarded by |
| --- | --- | --- |
| `pedal.blur_attacks` | the segment's notes and stretches, O((N+S) log N) | `tests/test_pedal.py`, `falsifications/drop_blur_positions.sh` |
| `store._notes_for_segments` | one query per sitting; the notes in the group's range | `test_reading_a_sitting_does_not_read_its_notes_once_per_open_section` |
| `store._notes_in_range` | one segment's notes on `idx_events_sitting` — never its sitting's | `test_the_range_read_returns_the_slice_a_whole_sitting_read_would` |
| `store.cached_references` | nothing on a hit; **only the inputs that moved** when the version moves (1.10) | `test_one_label_change_re_derives_only_that_segment`, `test_the_incremental_references_equal_a_full_rebuild`, `forget_the_old_piece_when_a_label_moves.sh`, `keep_an_empty_piece_in_the_pooled_signatures.sh` |
| `store._passages_derived` | nothing on a hit; one sitting's segments and notes when they move | `test_reading_a_sitting_again_does_not_derive_its_passages_again`, `test_a_label_written_after_a_read_is_answered_not_remembered` |
| `store.list_sittings_conn` | the returned rows and *their* notes — never the log | `test_listing_the_newest_sittings_does_not_read_the_older_ones` |
| `store.calendar` | the days in the requested window | `test_the_calendar_only_reads_its_own_window`, `test_the_calendar_still_answers_exactly_its_window` |
| `store.awaiting_segments` | one indexed probe per sitting, on a **tick** (Phase 24) — never a click | `tests/test_jobs.py` |
| `practice/jobs.py` | the work `ensure_segments` already costs, once per sitting, and only while it is queued or running | `tests/test_jobs.py` |
| `store.segment_identification` | what the caller hands it; accept `examples`, `signatures`, `notes` rather than re-deriving | — |
| `store.candidates_for_sitting` | the sitting's own segments, and its notes **once** | the note-read guard above |
| `store._refresh_metrics` | the sitting's notes and its pedal stream, once each | metric equivalence in `tests/test_practice_metrics.py` |
| `store._labelled_rows` | the labelled set — **uncapped on purpose** | `test_every_label_is_a_reference_however_lopsided_the_library` |
| `db.connect` | per request, and per COMMIT (R7) | `test_a_commit_does_not_fsync_the_write_ahead_log` |
| `backup.iter_export_json` | one row and one 64 KiB buffer — never the document (R11) | `test_the_export_is_written_in_bounded_pieces`, `test_the_nightly_backup_does_not_build_the_whole_document`, `test_the_download_route_does_not_build_the_whole_document` |
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

**SQLite has a work counter built in.** `set_progress_handler` is called every N virtual-machine
instructions, so a callback that counts its own calls measures work performed rather than time spent
— the same number on a laptop and on the piano machine:

```python
def work(conn, call, *, step: int = 200) -> int:
    ticks = 0

    def tick() -> int:
        nonlocal ticks
        ticks += 1
        return 0

    conn.set_progress_handler(tick, step)
    try:
        call()
    finally:
        conn.set_progress_handler(None, 0)
    return ticks
```

Use it when the cost is inside a *statement* rather than inside a Python helper, which the
monkeypatch idiom cannot see at all. It is what caught the half-fix in §1.7: "identical rows, six
times faster" was still a function of the log, and only a count of VM steps showed it. Warm the
statement cache first, and warm away the WAL re-read a previous write causes — neither is the cost
being measured.

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
- **A read that a write makes unnecessary.** Every edit re-reads the whole sitting detail so the
  derived passages stay honest; returning the passages with the edit's own response would remove the
  re-read. That is a contract change, not a fix, and it belongs in a plan rather than in a quick
  patch. Its *cost* is no longer the reason to want it — §1.8 cached the derivation, so what is left
  is the read itself, a couple of milliseconds. The deepest remaining cost on that path is now the
  matcher's pass in `candidates_for_sitting`, about 36 ms of the 38 ms `sitting_detail` still takes
  on the largest sitting. That is a separate question with its own owner, and it has not been
  measured to a conclusion yet.

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
non-optimization in R8 is `f7decad`. Phase 24 added 1.5 and 1.6: `692c132` (the invalidation rule),
`a93899a` (the runner) and `671d4fd` (the read that answers instead of waiting).

[docs/TEST-STRATEGY.md](TEST-STRATEGY.md) owns how a change is known not to have broken something;
[docs/ENGINEERING.md](ENGINEERING.md) owns what the code is. This document owns what it costs.
