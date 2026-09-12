# Integration: sight-reading trainer ↔ practice-logger

Design of record for merging the two apps. Written by the sight-reading side.
Companion documents:

- `AGENT-LOG.md` (workspace root) — the shared, append-only coordination log.
- `practice-logger/docs/INTEGRATION-WITH-SIGHT-READING.md` — short brief for the
  other agent, in their own docs tree.

Status: **proposal, and its destination is superseded.**
[`ECOSYSTEM.md`](./ECOSYSTEM.md) replaces the "share `piano.db` with the Rust app"
premise with a single self-contained web app. This document is still the accurate
description of *what exists today* and of the concrete integration seam, and §5's
staging is still the right order of work — but read ECOSYSTEM.md first for where
it is all going.

Nothing here is implemented, and no table or contract in `practice-logger` has
been changed.

---

## 1. Verified facts this rests on

Everything below was read from the code and the live database, not assumed.

| Fact | Evidence |
| --- | --- |
| The three apps share one SQLite file: `~/.local/share/piano-progress/piano.db` | `practice-logger/app/config.py:60`; file exists, 98 KB |
| `piano-progress` (Rust) owns `composers`, `pieces`, `notes`, `media` | `practice-logger/app/db.py:18`; 7 / 17 / 3 / 42 rows |
| `practice-logger` owns `practice_sessions`, `note_events`, `segments`, `segment_metrics`, `identification_corrections` | `app/db.py:21-27`; all five exist and are **empty** |
| The file is in WAL mode | `app/db.py:98`, and recorded in the file header |
| `practice-logger` declares **"No runtime coupling"** to this app today | `practice-logger/docs/DESIGN.md:24` |
| `practice_sessions.source` **exists but is inert** | declared `app/db.py:37` with `DEFAULT 'web_midi'`; written with a hard-coded literal at `app/services.py:98`; never read anywhere |
| The ingest wire format has no `source` | `app/models.py:16-21` — only `client_id`, `tz_offset_minutes`, `events` |
| `client_id` is validated and then dropped | `app/models.py:17`, absent from every INSERT in `app/services.py` |
| Ingest is already idempotent | unique index `idx_events_dedupe` on `(session_id, onset_ms, pitch)`, `INSERT OR IGNORE` |
| Sessionization is absolute-time based, not "latest session" | `app/services.py:_find_session` |
| Phase 1 and 2 are complete; tree clean | 10 commits, `git status` empty, 746 lines of tests |

Two consequences worth stating plainly:

1. **The integration seam already exists and is simply not wired.** Making
   sight-reading practice visible in the practice log needs *no schema change*
   on either side — only carrying a `source` value through the wire format and
   into the INSERT that already has the column.
2. `piano.db` lives **outside my file sandbox**. I can read it and copy it, but
   a WAL connection fails because SQLite needs to create `-shm`/`-wal` beside it.
   Development and tests on my side must run against a copy via `PL_PIANO_DB`
   (which `practice-logger` already supports). The other agent evidently runs
   with access, or the user does.

---

## 2. Terminology: "session" currently means two different things

Both apps have a concept called a session, and they are not the same object.
Leaving this unresolved guarantees confused code and confused conversation.

| Term | Owner | Definition | Lifecycle |
| --- | --- | --- | --- |
| **Sitting** | practice-logger (`practice_sessions`) | A continuous stretch at the piano, inferred from silence | Emergent: opens on the first note, closes after `PL_SESSION_GAP_S` (5 min) of silence |
| **Workout** | sight-reading (new, Slice E) | A deliberate, bounded set of sight-reading exercises | Declared: the player starts it and finishes it |

Proposed vocabulary, to be used in both codebases and both docs:

- **sitting** — never "session" when the logger's object is meant.
- **workout** — never "session" when the trainer's object is meant.
- **segment** — the logger's object; one piece (or one workout) within a sitting.
- The trainer's *existing* UI may keep the word "session" for the player, but
  every schema, API and document uses **workout**.

The natural mapping that falls out of this:

```
practice_sessions (sitting)  ─┬─ segment: repertoire
                              ├─ segment: repertoire
                              └─ segment: sight-reading workouts   ← from the trainer
```

A run of sight-reading exercises has ~2-5 s gaps between exercises and 20 s is
the segment threshold, so a whole workout lands as **one** segment. That mapping
is a happy accident of the existing thresholds, not something to rely on blindly
— it is asserted in Stage 3.

---

## 3. Staged plan

Each stage is independently shippable and verifiable, in the spirit of both
projects' existing phase plans. Stages 1 and 2 are useful on their own.

### Stage 1 — The trainer reads the library (read-only)

**Value.** Generate sight-reading material that serves the repertoire you are
actually working on: exercises in the key of an active piece, at a level derived
from its difficulty. This is the single most musical thing integration buys.

**Contract.** None changed. The trainer opens `piano.db` read-only and reads
`pieces` / `composers`, exactly as `practice-logger/app/library.py` already does.
It never writes a library table.

Mapping worth noting, because the vocabularies differ:

| `pieces.difficulty` | Trainer starting level |
| --- | --- |
| `Early Intermediate` | 3-4 |
| `Intermediate` | 5-6 |
| `Late Intermediate` | 7-8 |
| `Advanced` | 9-10 |

| `pieces.key` (`"B Major"`, `"C# Minor"`, `"Db Major"`) | `skills_data.KEY_SIGNATURE_LEVELS` |
| --- | --- |
| must be normalised to the trainer's `"B"` / `"c#"` / `"Db"` spelling | level chosen so the key is legal |

**Acceptance.** With `piano.db` present, exercising in the key of an active piece
is offered; with it absent, every existing feature works unchanged and the UI
says the library is unavailable rather than erroring. **This stage must degrade
to exactly today's behaviour.**

### Stage 2 — Sight-reading practice appears in the practice log

**Value.** Today the trainer's practice is invisible to the logger, so the
calendar heatmap and "time per piece" under-report real practice. This closes
that.

**Contract change, on their side — small and additive:**

```python
# practice-logger/app/models.py
class EventBatch(BaseModel):
    client_id: str
    tz_offset_minutes: int
    source: str = "web_midi"      # NEW: validated against a known set
    events: list[WireNote]
```

```python
# practice-logger/app/services.py — replace the literal
" VALUES (?1, ?2, ?3, ?4, ?5, ?6)", (..., batch.source)
```

Default preserves today's behaviour exactly; their 25 Phase 1 API tests keep
passing unchanged. A `Literal["web_midi", "sight_reading"]` (or a small allow-list)
keeps a typo from silently creating a new category.

**Contract change, on my side:** after scoring a performance, post that
performance's note events to `PL_API_TARGET` as one batch — absolute `epoch_ms`
reconstructed from the stored `performed_at` plus each note's relative onset.

**Failure isolation.** The logger is an optional sink. If it is down or
misconfigured, the trainer queues and retries, and its own scoring, feedback and
rating updates are unaffected. The trainer must never need the logger to work.

**Acceptance.** Play a workout with the logger running: one `practice_sessions`
row appears with `source='sight_reading'`, and `note_events` counts reconcile
with the trainer's `played_notes_json`. Kill the logger mid-workout: the trainer
still scores correctly and delivers the batch when it returns. Replaying the same
batch twice adds nothing (their dedupe index, already tested).

### Stage 3 — Provenance for sight-reading segments

**Question this answers:** on the logger's timeline, a sight-reading segment is
currently indistinguishable from unidentified noodling.

**Options:**

| Option | Cost | Verdict |
| --- | --- | --- |
| Leave `segments.piece_id` NULL | none | Acceptable minimum: `practice_sessions.source` already separates sight-reading *time* from repertoire time in the analytics, which is most of the value |
| Add a nullable `segments.source` (theirs) | one additive column, their migration | **Recommended.** Lets the timeline label a segment "sight-reading" without pretending it is a library piece |
| A third owner: trainer tables in `piano.db` | needs the ADR their DESIGN.md §11 already asks for | Deferred to Stage 5 |

**Also verify:** a sight-reading run really does become one segment at
`PL_SEGMENT_GAP_S = 20`; if a workout contains a long pause it will split, and
the timeline should say so rather than looking broken.

### Stage 4 — The logger informs the trainer

**Value.** The trainer currently knows only about its own exercises, so its
"streak" and its sense of "have you practised today" are half-blind. Reading
`practice_sessions` lets it:

- count a day as practised when *any* practice happened, not only sight-reading;
- size a workout to the time already spent (a 3-minute top-up, not a 10-minute
  block, after an hour at the piano);
- surface "you have not touched Polonaise in 12 days" and offer sight-reading in
  its key.

Read-only, so no ownership question. Degrades to today's behaviour without the DB.

### Stage 5 — The merge

One process, one frontend, one database. This is what "practice-logger is
integrating into the sight-reading" eventually means, and it is the only stage
that needs real architectural decisions:

1. Do the trainer's tables (`users`, `skills`, `user_skills`, `exercises`,
   `exercise_skills`, `performances`, `workouts`) **move into `piano.db`**, making
   a third owner in one file?
2. Or does the merged app keep `sightreading.sqlite3` beside `piano.db` and
   correlate by timestamp?

**Recommendation: move them in.** The trainer's tables are additive and invisible
to both existing owners — the same argument `practice-logger` used for itself,
and which `piano-progress` was verified to tolerate. It buys real foreign keys
(`workouts.practice_session_id → practice_sessions.id`), one dashboard, and one
backup to think about. It costs a one-time migration and an ADR.

Until Stage 5, cross-database references are plain integers with no FK, and must
be documented as such.

---

## 4. The double-capture hazard

**This is the most likely way integration goes wrong, and it is not obvious.**

Web MIDI delivers events to *every* listening tab. If the trainer is posting
attempts *and* the logger's own capture tab is open, the same physical notes are
logged twice: once as `source='web_midi'` from the logger's tab, once as
`source='sight_reading'` from the trainer. Practice time then double-counts, and
because the two clients anchor differently the duplicate notes are not identical
rows, so the dedupe index does **not** catch them.

Mitigations, in order of preference:

1. **One capture owner at a time (documented operational rule).** Close the
   logger's capture tab while working out, or vice versa. Zero code, relies on
   discipline.
2. **Make it visible.** With `source` wired, the analytics can show the split, so
   double counting is at least diagnosable rather than silent.
3. **A handshake (later).** The logger exposes capture state; the trainer checks
   it before posting. Real work, deferred.

I would take (1) and (2) now, and note (3) as the eventual fix. This belongs in
the user-facing README of whichever app is running, and it is a genuine argument
for Stage 5: two capture clients is one too many.

---

## 5. Decisions needed

| ID | Question | My recommendation |
| --- | --- | --- |
| I1 | Adopt *sitting* / *workout* / *segment* as the shared vocabulary? | Yes — the collision is already real |
| I2 | Does the trainer post to the logger's existing `POST /api/events`, or get its own endpoint? | Reuse the existing endpoint; wire the inert `source` column |
| I3 | Is the logger an optional sink the trainer degrades without? | Yes, absolutely — the trainer must never need it |
| I4 | Stage 3: label sight-reading segments with a new nullable column, or leave them NULL? | Add the nullable column |
| I5 | Stage 5: do the trainer's tables move into `piano.db`? | Yes, with an ADR |
| I6 | Who owns the double-capture rule, and where is it documented? | Both READMEs; revisit at Stage 5 |

---

## 6. Change log (what the sight-reading side has done)

| Date | Change | Files |
| --- | --- | --- |
| this session | Read-only reconnaissance of `practice-logger` and `piano.db`; no code changed in either sibling | — |
| this session | Wrote this design | `docs/INTEGRATION-practice-logger.md` |
| this session | Created the shared coordination log | `AGENT-LOG.md` |
| this session | Corrected a misleading `.gitignore` comment that described `practice-logger` as unrelated, when it is a planned merge | `.gitignore` |

Nothing in `practice-logger/` was modified except the added brief in its `docs/`.
