# Plan — Phase 20a: practice kinds

**Parent spec:** [`ECOSYSTEM.md`](./ECOSYSTEM.md) § *Phase 20* § *20a — practice kinds (A1, A3)*,
with decisions 20-D1 and 20-D2. That section owns what and why; this document owns the how and
must not be edited to match drift in it.

**Status:** planned.

**Goal.** A segment records what was played and for how long, never *how*. Add one deliberate
axis — `run_through / slow / section / hands_separate / memory / warm_up / other` — that a person
sets in one click, that the app may *offer* but never write, and that the Log dashboard splits
logged time by. Nothing about the sight-reading loop changes.

**Architecture.** The taxonomy is a `Literal` in `practice/models.py` beside the existing
`PracticeSource`; the offer rule is pure functions in a new `practice/kinds.py` beside
`metrics.py` and `pedal.py`; `practice/store.py` owns every write and the SQL aggregate;
`practice/api.py` exposes one new route. The client keeps a single display-label module
(`frontend/src/lib/kinds.ts`) so the timeline and the dashboard cannot disagree about words.

**Tech stack.** Python 3.11 / FastAPI / Pydantic / SQLite (no ORM), Svelte 5 (runes) + TypeScript,
`node --test` for frontend units, pytest for backend, Playwright for the browser tier.

**Baseline / authority refs.**

- `docs/ECOSYSTEM.md` § Phase 20 (approved spec), § *Risks*, § *Non-goals*.
- `docs/TEST-STRATEGY.md` §2 (test the space, grade the suite), §3 (two tiers), §8 (standing rule).
- `docs/PLAN-SLICE1.md` (the schema-migration mechanism and the falsification tooling this plan reuses).
- `AGENT-LOG.md` § *Rules* (append, never rewrite; shared-contract changes stated explicitly).

**Compatibility boundary.**

- Two nullable `segments` columns, additive, no backfill. `BACKUP_VERSION` is **not** bumped:
  `test_backup.py::test_a_v1_document_in_the_old_shape_still_imports` records that the guarantee is
  one-directional and that additive columns need no version change.
- No existing route changes shape. `SegmentSummary` and `AnalyticsSummary` gain fields only.
- `SCHEMA_VERSION` goes 1 → 2, so an older build refuses a database that has the columns. That is
  the intended tripwire, and it is why `test_migration_upgrade.py`'s frozen shape must be edited
  deliberately rather than derived.
- `resegment` continues to discard labels, including kinds — it already asks first when labels exist.

---

```text
TDD Route:
- Mode: auto
- Decision: strict
- Strict authority: docs/TEST-STRATEGY.md §8, the standing rule ("a slice is not done until
  check.sh --full passes, and no assertion is trusted until it has been seen to fail"), which
  PLAN-SLICE1.md already recorded as the user-approved strict authority for this repo
- Strict signals: persistence (two columns plus a frozen-shape tripwire), a public contract (a new
  PATCH route and a new summary field), a behaviour change (a taxonomy that is written, offered
  and aggregated), and a producer/consumer pair (the offer writer and the split reader)
- Light eligibility: not applicable — no part of this slice is a single-owner edit with no
  behaviour change
- Test posture: strict RED first for the schema and the store behaviour; for assertions added over
  behaviour that is already correct by construction (the read path), apply a break, watch it fail,
  restore
- Verification: ./check.sh --fast after every task; ./check.sh --full before the slice is called
  done; every new assertion falsified
```

```text
BaselineUsageDraft:
- Required baseline refs: docs/ECOSYSTEM.md § Phase 20 § 20a + decisions 20-D1, 20-D2;
  docs/TEST-STRATEGY.md §2, §3, §8; docs/PLAN-SLICE1.md § Slice 1
- Delivered context refs: ECOSYSTEM.md Phase 20 rendered above in this conversation
- Acknowledged before plan refs: ECOSYSTEM.md 20a acceptance bullets; TEST-STRATEGY §8 standing rule
- Cited in plan refs: ECOSYSTEM.md (parent spec), TEST-STRATEGY.md §8 (TDD authority),
  PLAN-SLICE1.md (migration + falsification mechanism), AGENT-LOG.md (log rules)
- Missing refs: none
- Decision: continue
```

```text
Requirement Ready Check:
- Requirement source refs: docs/ECOSYSTEM.md § Phase 20 § 20a (approved by the user, commit bacf049)
- Goals and scope refs: the same section's Problem/Design
- User / scenario refs: the player tagging a logged segment at the piano; the player reading
  "how the time was spent" a week later
- Requirement item refs: two segments columns, one offer rule, one route, one split, one refusal
- Acceptance / verification criteria refs: 20a's five acceptance bullets
- Open blocker questions: none
- Decision: ready
```

```text
Change Necessity:
- User-visible need: the log cannot say how a segment was practised, so a run-through and a slow
  pass over the same bars are one row; 20a's acceptance bullets require a stored how-axis
- No-change / non-code option: insufficient — config cannot store a per-segment decision, and the
  split is a SQL aggregate over rows that do not exist yet
- Why code change is necessary: a column, a write path, an offer rule and an aggregate are all code
- Minimum change boundary: practice/schema.py, db.py, practice/models.py, practice/kinds.py (new),
  practice/store.py, practice/api.py, frontend types/api/kinds.ts/SegmentTimeline/PracticeLogView,
  tests, falsifications, README, AGENT-LOG
- Decision: code-change
```

```text
Existence Check:
- Proposed new surface: `segments.practice_kind` + `segments.practice_kind_basis`;
  `practice/kinds.py`; `PATCH /api/practice/segments/{id}/kind`; `AnalyticsSummary.kinds`;
  `frontend/src/lib/kinds.ts`
- Existing owner / reuse candidate: `segments` already owns per-segment facts; `practice/pedal.py`
  and `practice/metrics.py` are the pure-module precedent; `PATCH /segments/{id}` owns the piece
  label; `sources()` is the aggregate precedent
- Why existing surface is insufficient: `source` is provenance (a workout produced this) and
  cannot carry "how" without owning one fact twice — refused by 20-D1; overloading
  `PATCH /segments/{id}` would make one body carry two decisions with different rules, since the
  piece label overrules a matcher and the kind overrules nothing
- Creation proof: 20a's acceptance bullets cannot be satisfied by configuration or by an existing
  column; the kind must persist per segment to survive a reload and to aggregate
- Entropy / retirement impact: no new table, so no backup or version change; the offer path is one
  function (`offer_practice_kinds`) that can be deleted without touching stored labels if it proves
  noisy, and `kinds.py` follows `pedal.py`'s shape rather than inventing a new one
- Decision: add-with-proof for the module and the route; reuse-existing for the column owner
```

```text
Architecture Integrity Lens:
- Invariant: sight-reading stays owned by `segments.source`/`workout_id` alone; a stored kind is
  never overwritten by an inference pass, and an unaccepted offer never counts in an aggregate
- Canonical owner / contract: `practice/store.py` writes segments; `practice/kinds.py` owns the
  taxonomy rules; `practice/models.py` owns the wire vocabulary; `frontend/src/lib/kinds.ts` owns
  display labels only
- Responsibility overlap: none added — the piece label and the practice kind are different columns
  written by different routes, and the split reads only what a person confirmed
- Higher-level simplification: a `kind` column on `segments` is the whole feature; no tag table,
  no per-piece baseline table, no config keys
- Retirement / falsifier: if `offer_practice_kinds` produces noise in real use, delete the call in
  `ensure_segments` and the function; offers are `practice_kind_basis = 'offered'` rows and are
  cleared by a single UPDATE
- Verdict: proceed
```

```text
Complexity Budget:
- Artifact class: maintained source; core store and two large Svelte components
- Target files / artifacts: practice/store.py (1757 lines), practice/models.py (~450),
  practice/api.py (289), practice/schema.py (239), SegmentTimeline.svelte (681),
  PracticeLogView.svelte (~600)
- Current pressure: store.py and SegmentTimeline.svelte already carry the most behaviour in their
  domains
- Projected post-change pressure: store.py +~95 lines in its existing role; models +~30;
  api +~12; schema +~6; SegmentTimeline +~45; PracticeLogView +~12
- Budget result: at-risk (store.py and SegmentTimeline are the pressure points)
- Planned governance: the taxonomy rules go to a new `practice/kinds.py`, not into store.py; the
  aggregate copies `sources()`'s existing shape instead of starting an analytics module; the
  timeline gains one select and one pill, not a new panel

Plan-Time Complexity Check:
- Target files: practice/store.py, frontend/src/components/SegmentTimeline.svelte
- Existing size / shape signals: store.py is the single owner of practice SQL and already mixes
  reads, writes, metrics and analytics; SegmentTimeline already renders per-segment controls
- Owner fit: the new write and aggregate belong to store.py; the new rules do not
- Add-in-place risk: putting the offer rule in store.py would bury a pure decision inside SQL code
- Better file boundary: `practice/kinds.py` for the rules; store.py keeps only persistence
- Recommendation: extract helper (kinds.py), then edit-in-place in store.py and the components
```

```text
Plan Pressure Test:
- Owner / contract / retirement: one new route on an existing owner; the offer path has a named
  deletion trigger; no new table
- Architecture integrity / higher-level path: the taxonomy is a column, not a subsystem; nothing
  higher-level was skipped
- Verification scope: migration test, pure-module units, store + contract tests, a reconciliation
  invariant, frontend unit tests, one browser assertion, three falsifications
- Task executability: every step names a file, complete code and an exact command
- Pressure result: proceed
```

---

## Files

**Create**

| Path | Why |
| --- | --- |
| `backend/app/practice/kinds.py` | The taxonomy and the offer rule, as pure functions |
| `backend/tests/test_practice_kinds.py` | The units: what may be offered, and what may never be |
| `backend/tools/falsifications/drop_practice_kind_added_column.sh` | Break the migration parity |
| `backend/tools/falsifications/drop_kind_basis_guard.sh` | Break the "an offer does not count" rule |
| `backend/tools/falsifications/let_inference_overwrite_manual.sh` | Break the "manual wins" rule |
| `frontend/src/lib/kinds.ts` | Display labels, one owner for both components |
| `frontend/src/lib/kinds.test.ts` | The label and counting rules |

**Modify**

| Path | Change |
| --- | --- |
| `backend/app/practice/schema.py` | Two columns in `segments`' CREATE and in `ADDED_COLUMNS` |
| `backend/app/db.py` | `SCHEMA_VERSION` 1 → 2 |
| `backend/app/practice/models.py` | `PracticeKind`, `PracticeKindBasis`, `PracticeKindSplit`, `PracticeKindRequest`, `AnalyticsSummary.kinds` |
| `backend/app/practice/store.py` | Read the columns; `offer_practice_kinds`; `set_practice_kind`; `kinds_breakdown`; `summary()` |
| `backend/app/practice/api.py` | `PATCH /segments/{id}/kind` |
| `backend/tests/test_migration_upgrade.py` | The frozen `segments` shape, and one explicit upgrade test |
| `backend/tests/test_practice_api.py` | The route contract and the reconciliation invariant |
| `backend/tools/e2e_browser.py` | One assertion in `scenario_practice_log` |
| `frontend/src/lib/types.ts` | `PracticeKind`, `PracticeKindBasis`, `PracticeKindSplit`, two `SegmentSummary` fields, `AnalyticsSummary.kinds` |
| `frontend/src/lib/api.ts` | `practice.setSegmentKind` |
| `frontend/src/components/SegmentTimeline.svelte` | Kind pill, offer row, kind select |
| `frontend/src/components/PracticeLogView.svelte` | The kind split in *How the time was spent* |
| `README.md`, `AGENT-LOG.md` | What a player can see; the shared-log entry |

---

## Precondition — the working tree must be clean before any falsification

`backend/tools/falsify.sh` refuses to run when `git status --porcelain` is non-empty, because it
reverts a break with `git checkout -- .` and must not be able to take anything else with it.

When this plan was written the tree carried another slice's uncommitted work; that work is now
committed as `d0aba27` ("Slice-1"), so the tree is clean and every falsification below can run as
written. The precondition is therefore an assertion rather than a cleanup task — but it is the
first thing to check, and if the tree *is* dirty the fix is to commit or stash before Task 1, never
to run the break scripts anyway.

```bash
git status --porcelain   # must print nothing before running falsify.sh
```

---

## Task 1 — the schema carries how a segment was practised

**Files.** modify `backend/app/practice/schema.py`, `backend/app/db.py`,
`backend/tests/test_migration_upgrade.py`; create
`backend/tools/falsifications/drop_practice_kind_added_column.sh`.

**Why.** Without the column there is nowhere to store the answer, and the app's own honesty rules
require the *basis* to travel with the value — the same reason `segment_metrics.pedal_basis` exists.

**Change Necessity.** Code, not config: SQLite cannot gain a column a reader can select without a
migration, and the frozen-shape test is deliberately a literal so this edit is an act rather than a
side effect.

**Impact / Compatibility.** Additive and nullable. A fresh database gains the columns from the
CREATE; an existing one gains them from `ADDED_COLUMNS`. `SCHEMA_VERSION` 1 → 2 makes an older build
refuse the file, which is the intended tripwire.

### Step 1.1 — write the failing migration test

Append to `backend/tests/test_migration_upgrade.py`:

```python
def test_the_upgraded_database_gains_the_practice_kind_columns() -> None:
    """20a: how a segment was practised arrives on a database that predates it.

    The parity test above compares a fresh database against an upgraded one, so it
    already catches a missing `ADDED_COLUMNS` entry. This asserts the specific
    columns the slice is about, so a rename cannot pass by moving the drift
    somewhere parity happens to agree on.
    """
    path = _build_fixture_db("kind-columns.sqlite3")
    db.init_db(path)
    conn = db.connect(path)
    try:
        assert {"practice_kind", "practice_kind_basis"} <= _columns(conn, "segments")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    finally:
        conn.close()
```

### Step 1.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py::test_the_upgraded_database_gains_the_practice_kind_columns
```

Expected: **1 failed**, `AssertionError` on the column set. If it passes, stop — the test is not
testing what it claims.

### Step 1.3 — add the columns

In `backend/app/practice/schema.py`, in the `segments` CREATE, after the `identified_by` line:

```sql
    identified_by   TEXT,                -- 'similarity' | 'workout' | 'manual'
    -- How it was practised, as opposed to what it was. `source` above is
    -- *provenance* — a workout produced this segment — which is a different fact and
    -- must not be overloaded to carry this one. Sight-reading is deliberately not a
    -- kind for the same reason: `source`/`workout_id` already own it.
    practice_kind       TEXT,            -- 'run_through' | 'slow' | ... | NULL
    -- Where the value came from. 'offered' is a proposal the player has not answered:
    -- it is drawn as a question and excluded from every aggregate. Stored rather than
    -- re-derived, which is the same rule `pedal_basis` and `identified_by` follow.
    practice_kind_basis TEXT             -- 'offered' | 'manual' | 'accepted' | NULL
```

and append to `ADDED_COLUMNS`, after the Phase 18b block:

```python
    # Phase 20a — how a segment was practised, as a second axis from `source`, which
    # owns *what produced* the segment rather than how it went.
    ("segments", "practice_kind", "TEXT"),
    ("segments", "practice_kind_basis", "TEXT"),
```

### Step 1.4 — bump the schema version

In `backend/app/db.py`:

```python
SCHEMA_VERSION = 2
```

### Step 1.5 — update the frozen shape literal

In `backend/tests/test_migration_upgrade.py`, in `EXPECTED_COLUMNS["segments"]`:

```python
    "segments": {
        "id", "sitting_id", "start_ms", "end_ms", "piece_id", "source", "workout_id",
        "confidence", "identified_by", "practice_kind", "practice_kind_basis",
    },
```

In the same file, extend the frozen fixture's own guard in
`test_the_fixture_is_the_pre_phase18_shape`, so a future "fix the fixture" cannot quietly hand the
migration test a database that already has the columns:

```python
        assert {"source", "workout_id", "practice_kind", "practice_kind_basis"}.isdisjoint(
            _columns(conn, "segments")
        ), "the fixture predates every ADDED_COLUMNS entry for segments"
```

(This replaces the existing `assert {"source", "workout_id"}.isdisjoint(...)` line at
`test_migration_upgrade.py:229`.)

### Step 1.6 — verify GREEN

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py tests/test_backup.py
```

Expected: all pass. `test_a_fresh_database_has_exactly_the_frozen_shape` passing is the proof the
literal and the CREATE agree.

### Step 1.7 — write the break script and falsify

Create `backend/tools/falsifications/drop_practice_kind_added_column.sh`:

```bash
#!/usr/bin/env bash
#
# Break: delete the 20a ADDED_COLUMNS entry for segments.practice_kind.
#
# Without it the ALTER never runs on a database that predates Phase 20a, so the upgraded
# schema is missing a column a fresh one has. The parity test in test_migration_upgrade.py
# is what must catch it — an assertion derived from ADDED_COLUMNS itself could not, because
# the deleted entry leaves the loop.
#
#   ./falsify.sh backend/tools/falsifications/drop_practice_kind_added_column.sh "./check.sh --fast"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '    ("segments", "practice_kind", "TEXT"),\n'
assert needle in text, "the line to break is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
```

```bash
chmod +x backend/tools/falsifications/drop_practice_kind_added_column.sh
backend/tools/falsify.sh backend/tools/falsifications/drop_practice_kind_added_column.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py"
```

Expected: `falsified: the check caught the break`. If it reports `FALSIFICATION FAILED`, the
migration test is not guarding the column.

---

## Task 2 — the taxonomy, and what may never be offered

**Files.** create `backend/app/practice/kinds.py`, `backend/tests/test_practice_kinds.py`; modify
`backend/app/practice/models.py` (the two `Literal`s only).

**Why.** The offer rule is a pure decision — inputs in, one kind or nothing out — and it carries the
slice's most important refusal. Keeping it out of `store.py` makes it reachable from
`node`-free, SQL-free unit tests and keeps store.py from growing a second responsibility.

**Change Necessity.** Code: the rule does not exist anywhere, and it is the difference between a
taxonomy the player trusts and a form they ignore.

**Impact / Compatibility.** A new module and two new type aliases; nothing existing changes.

### Step 2.1 — write the failing units

Create `backend/tests/test_practice_kinds.py`:

```python
"""The deliberate-practice taxonomy: what may be offered, and what may not."""

from __future__ import annotations

import typing

import pytest

from app.practice import kinds
from app.practice.models import PracticeKind


def test_the_tuple_and_the_wire_literal_are_one_list() -> None:
    """Two spellings of one vocabulary; drift between them is a silent 422."""
    assert kinds.KINDS == typing.get_args(PracticeKind)


def test_sight_reading_is_not_a_kind() -> None:
    """It is already owned by `segments.source`/`workout_id`, so it is not offered here."""
    assert "sight_reading" not in kinds.KINDS


def test_only_slow_and_section_may_ever_be_inferred() -> None:
    """The offer path is a closed set, asserted over its whole input space.

    Hands-separate is the one that matters: `mean_velocity_low`/`high` is a register
    balance and not a measurement of the hands — the piano sends both on one channel —
    so Phase 18b refused that claim in the UI and inference must not make it here.
    """
    offered: set[str | None] = set()
    for note_count in (0, 3, 4, 40):
        for median_tempo in (None, 20.0, 60.0, 120.0, 240.0):
            for typical in (None, 40.0, 80.0, 160.0):
                for baseline in (0, 1, 3, 30):
                    for restarts in (None, 0, 2, 3, 12):
                        offered.add(
                            kinds.offer_for(
                                note_count=note_count,
                                is_sight_reading=False,
                                median_tempo=median_tempo,
                                piece_typical_tempo=typical,
                                piece_baseline_segments=baseline,
                                restarts=restarts,
                            )
                        )
    assert offered <= {"slow", "section", None}


def test_a_slow_pass_is_offered_slow() -> None:
    assert (
        kinds.offer_for(
            note_count=30,
            is_sight_reading=False,
            median_tempo=40.0,
            piece_typical_tempo=80.0,
            piece_baseline_segments=5,
            restarts=0,
        )
        == "slow"
    )


@pytest.mark.parametrize("baseline", [0, 1, 2])
def test_slow_needs_a_piece_to_be_slow_against(baseline: int) -> None:
    """Two segments are a difference; three are a habit."""
    assert (
        kinds.offer_for(
            note_count=30,
            is_sight_reading=False,
            median_tempo=40.0,
            piece_typical_tempo=80.0,
            piece_baseline_segments=baseline,
            restarts=0,
        )
        is None
    )


def test_slow_never_fires_without_a_tempo_on_both_sides() -> None:
    for median_tempo, typical in ((None, 80.0), (40.0, None)):
        assert (
            kinds.offer_for(
                note_count=30,
                is_sight_reading=False,
                median_tempo=median_tempo,
                piece_typical_tempo=typical,
                piece_baseline_segments=9,
                restarts=0,
            )
            is None
        )


def test_repeated_starts_are_offered_as_section_work() -> None:
    assert (
        kinds.offer_for(
            note_count=30,
            is_sight_reading=False,
            median_tempo=None,
            piece_typical_tempo=None,
            piece_baseline_segments=0,
            restarts=kinds.RESTARTS_FOR_SECTION,
        )
        == "section"
    )


def test_a_slow_pass_outranks_repeated_starts() -> None:
    """One offer, deterministically chosen, so the timeline never shows two questions."""
    assert (
        kinds.offer_for(
            note_count=30,
            is_sight_reading=False,
            median_tempo=30.0,
            piece_typical_tempo=80.0,
            piece_baseline_segments=6,
            restarts=9,
        )
        == "slow"
    )


def test_a_sight_reading_segment_and_a_scrap_are_never_offered() -> None:
    common = dict(
        median_tempo=30.0,
        piece_typical_tempo=80.0,
        piece_baseline_segments=6,
        restarts=9,
    )
    assert (
        kinds.offer_for(
            note_count=30, is_sight_reading=True, **common
        )
        is None
    )
    assert (
        kinds.offer_for(
            note_count=kinds.MIN_NOTES_FOR_OFFER - 1, is_sight_reading=False, **common
        )
        is None
    )


def test_an_offer_is_a_question_and_only_a_confirmed_basis_counts() -> None:
    assert kinds.counted("manual") is True
    assert kinds.counted("accepted") is True
    assert kinds.counted("offered") is False
    assert kinds.counted(None) is False
```

### Step 2.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_kinds.py
```

Expected: collection error or failures — `app.practice.kinds` does not exist yet.

### Step 2.3 — add the wire vocabulary to models.py

In `backend/app/practice/models.py`, immediately after the existing `PracticeSource` alias:

```python
#: How a segment was practised — the axis the log was missing. Deliberately **not**
#: including sight-reading: that is owned by `source`/`workout_id`, and a second owner
#: for one fact is how the two drift apart.
PracticeKind = Literal[
    "run_through",
    "slow",
    "section",
    "hands_separate",
    "memory",
    "warm_up",
    "other",
]

#: Where a stored kind came from. 'offered' is a proposal the player has not answered, so
#: it is displayed as a question and excluded from every aggregate — which is the same
#: restraint the autotag bands and `pedal_basis` follow.
PracticeKindBasis = Literal["offered", "manual", "accepted"]
```

### Step 2.4 — write the module

Create `backend/app/practice/kinds.py`:

```python
"""The deliberate-practice taxonomy, and what the log can honestly infer.

A segment already records *what* was played and for how long. This module owns the axis
it was missing — *how* it was practised — and the one rule that keeps it trustworthy:
an inference produces an **offer**, never a label. The autotag bands follow the same
restraint, and for the same reason: a guess written silently is a guess the player
cannot disagree with.

Nothing here persists anything. `store.offer_practice_kinds` calls :func:`offer_for` when
a sitting is segmented and stores the result with ``practice_kind_basis = 'offered'``,
which every aggregate ignores until a person accepts it.
"""

from __future__ import annotations

from .models import PracticeKind

KINDS: tuple[PracticeKind, ...] = (
    "run_through",
    "slow",
    "section",
    "hands_separate",
    "memory",
    "warm_up",
    "other",
)

#: Bases that count as a label. `offered` is a question, so it counts in nothing.
COUNTED_BASES: frozenset[str] = frozenset({"manual", "accepted"})

#: A segment at or below this fraction of the piece's own typical note rate reads as
#: slower-than-usual practice. Relative to the piece, never to a metronome mark: the log
#: has no score, so there is no target tempo to be slower *than*.
SLOW_RATIO = 0.7

#: How many *other* segments of the piece are needed before "slower than usual" means
#: anything. Two segments are a difference, not a habit.
MIN_BASELINE_SEGMENTS = 3

#: Mid-segment silences that read as section work rather than phrasing.
RESTARTS_FOR_SECTION = 3

#: Below this many notes a segment is too short to characterise at all.
MIN_NOTES_FOR_OFFER = 4


def counted(basis: str | None) -> bool:
    """Is a stored kind a label, or still a question?"""
    return basis in COUNTED_BASES


def offer_for(
    *,
    note_count: int,
    is_sight_reading: bool,
    median_tempo: float | None,
    piece_typical_tempo: float | None,
    piece_baseline_segments: int,
    restarts: int | None,
) -> PracticeKind | None:
    """The one offer this app is willing to make about how a segment went.

    Two rules, both derived from numbers the log already stores:

    * ``slow`` — the segment is at or below :data:`SLOW_RATIO` of the piece's own
      typical note rate, with at least :data:`MIN_BASELINE_SEGMENTS` other segments to
      compare against.
    * ``section`` — the player stopped and started again at least
      :data:`RESTARTS_FOR_SECTION` times, which is what section work looks like from
      the outside.

    ``slow`` is decided first so there is exactly one answer, and **hands-separate is
    never decided at all**: ``mean_velocity_low``/``high`` is a register balance, not a
    measurement of the hands — the piano sends both hands on one channel — and Phase 18b
    refused that claim in the UI. Making it here would break the same promise from the
    other side. Sight-reading is refused for a different reason: ``source`` owns it.

    Register inputs are not parameters at all, which is the strongest form the refusal
    can take.
    """
    if is_sight_reading or note_count < MIN_NOTES_FOR_OFFER:
        return None
    if (
        median_tempo is not None
        and piece_typical_tempo is not None
        and piece_baseline_segments >= MIN_BASELINE_SEGMENTS
        and median_tempo <= piece_typical_tempo * SLOW_RATIO
    ):
        return "slow"
    if restarts is not None and restarts >= RESTARTS_FOR_SECTION:
        return "section"
    return None
```

### Step 2.5 — verify GREEN

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_kinds.py
```

Expected: 12 passed (one parametrised into three).

### Step 2.6 — falsify the refusal

Temporarily insert exactly `    return "hands_separate"` as the last line of `offer_for`, replacing
`    return None` (the function's final statement), then:

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_kinds.py
```

Expected: `test_only_slow_and_section_may_ever_be_inferred` fails. Restore the file
(`git checkout -- backend/app/practice/kinds.py`) and confirm green again. No break script is
committed for this one: the temporary edit is a single line and has no stable needle.

---

## Task 3 — the store owns the kind, the offer and the split

**Files.** modify `backend/app/practice/models.py`, `backend/app/practice/store.py`,
`backend/app/practice/api.py`, `backend/tests/test_practice_api.py`; create
`backend/tools/falsifications/drop_kind_basis_guard.sh`,
`backend/tools/falsifications/let_inference_overwrite_manual.sh`.

**Why.** Persistence is where a taxonomy either stays honest or quietly becomes a guess, and the
split is the payoff that makes the tags worth setting.

**Change Necessity.** Code: the write path and the aggregate do not exist; the reconciliation
invariant cannot be asserted without them.

**Impact / Compatibility.** `SegmentSummary` gains two nullable fields and `AnalyticsSummary` gains
`kinds` — additive on both. One new route. No existing route's shape changes.

### Step 3.1 — write the failing contract and invariant tests

Append to `backend/tests/test_practice_api.py`:

```python
def recent_sitting(client, offsets: list[int]) -> dict:
    """A sitting played a minute ago and closed, so it has segments *and* is in the window.

    Two constraints meet here. Stored segments are never recomputed implicitly, so a
    sitting still inside its own silence gap has none until it is closed. And every
    windowed analytics query starts from today, so the 2023 fixtures the store tests use
    would be asserted as correctly *excluded* rather than counted.
    """
    import time

    base = int(time.time() * 1000) - 60_000
    body = client.post(
        "/api/practice/events",
        json={
            "tz_offset_minutes": server_offset_minutes(),
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
    closed = client.post("/api/practice/sittings/close")
    assert closed.status_code == 200, closed.text
    detail = client.get(f"/api/practice/sittings/{body['sitting_id']}").json()
    return {"sitting_id": body["sitting_id"], "segments": detail["segments"]}


def seed_piece(conn, title: str = "Etude") -> int:
    piece_id = conn.execute(
        "INSERT INTO pieces (title, status) VALUES (?, 'active')", (title,)
    ).lastrowid
    conn.commit()
    return int(piece_id)


def segment_of(client, sitting: dict, index: int = 0) -> dict:
    """Re-read one segment through the API, which is the thing under test."""
    detail = client.get(f"/api/practice/sittings/{sitting['sitting_id']}").json()
    return detail["segments"][index]


#: Attacks every 500 ms - 120 BPM, a piece's ordinary rate in the offer tests.
FAST_OFFSETS = [0, 500, 1_000, 1_500]
#: Attacks every 1500 ms - 40 BPM, a third of the ordinary rate.
SLOW_OFFSETS = [0, 1_500, 3_000, 4_500]


def a_piece_with_a_slow_offer(client, conn) -> tuple[dict, int]:
    """Three ordinary segments give the piece a baseline; a slow one earns an offer.

    The offer arrives from *labelling the piece*, not from a button: "slower than usual"
    cannot mean anything until the app knows what usual is for that piece. That is also
    why `offer_practice_kinds` runs when a label is written, not only at segmentation.
    """
    piece_id = seed_piece(conn)
    for _ in range(3):
        sitting = recent_sitting(client, FAST_OFFSETS)
        client.patch(
            f"/api/practice/segments/{segment_of(client, sitting)['id']}",
            json={"piece_id": piece_id},
        )
    slow = recent_sitting(client, SLOW_OFFSETS)
    segment_id = segment_of(client, slow)["id"]
    response = client.patch(
        f"/api/practice/segments/{segment_id}", json={"piece_id": piece_id}
    )
    assert response.status_code == 200, response.text
    return slow, segment_id


def test_labelling_a_piece_offers_slow_against_that_pieces_own_tempo(client, conn) -> None:
    slow, segment_id = a_piece_with_a_slow_offer(client, conn)
    segment = segment_of(client, slow)
    assert segment["id"] == segment_id
    assert (segment["practice_kind"], segment["practice_kind_basis"]) == ("slow", "offered")


def test_an_offer_is_a_question_until_it_is_answered(client, conn) -> None:
    """The rule the whole feature rests on, over a real offer rather than a planted one."""
    _slow, segment_id = a_piece_with_a_slow_offer(client, conn)

    offered = client.get("/api/practice/analytics/summary?days=365").json()["kinds"]
    assert all(entry["kind"] is None for entry in offered), (
        f"an unanswered offer must not appear as a kind ({offered})"
    )

    accepted = client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "accept"}
    )
    assert accepted.status_code == 200, accepted.text
    segment = next(s for s in accepted.json() if s["id"] == segment_id)
    assert (segment["practice_kind"], segment["practice_kind_basis"]) == ("slow", "accepted")

    counted = client.get("/api/practice/analytics/summary?days=365").json()["kinds"]
    assert "slow" in {entry["kind"] for entry in counted}


def test_declining_clears_the_offer_so_it_cannot_linger(client, conn) -> None:
    slow, segment_id = a_piece_with_a_slow_offer(client, conn)
    declined = client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "decline"}
    )
    assert declined.status_code == 200, declined.text
    assert segment_of(client, slow)["practice_kind"] is None
    assert segment_of(client, slow)["practice_kind_basis"] is None


def test_a_practice_kind_is_set_read_and_cleared(client) -> None:
    sitting = recent_sitting(client, FAST_OFFSETS)
    segment_id = segment_of(client, sitting)["id"]

    setter = client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "set", "kind": "memory"}
    )
    assert setter.status_code == 200, setter.text
    segment = next(s for s in setter.json() if s["id"] == segment_id)
    assert (segment["practice_kind"], segment["practice_kind_basis"]) == ("memory", "manual")

    assert segment_of(client, sitting)["practice_kind"] == "memory", "and survives a re-read"

    cleared = client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "set", "kind": None}
    )
    cleared_segment = next(s for s in cleared.json() if s["id"] == segment_id)
    assert cleared_segment["practice_kind"] is None
    assert cleared_segment["practice_kind_basis"] is None


def test_an_unknown_practice_kind_is_a_422(client) -> None:
    sitting = recent_sitting(client, FAST_OFFSETS)
    segment_id = segment_of(client, sitting)["id"]
    response = client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "set", "kind": "banjo"}
    )
    assert response.status_code == 422


def test_accepting_with_no_offer_is_a_422_and_declining_nothing_is_harmless(client) -> None:
    sitting = recent_sitting(client, FAST_OFFSETS)
    segment_id = segment_of(client, sitting)["id"]
    accepted = client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "accept"}
    )
    assert accepted.status_code == 422
    declined = client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "decline"}
    )
    assert declined.status_code == 200, "a double-click must not 409"


def test_setting_a_kind_on_a_missing_segment_is_a_404(client) -> None:
    response = client.patch(
        "/api/practice/segments/999999/kind", json={"action": "set", "kind": "slow"}
    )
    assert response.status_code == 404


def test_the_kind_split_accounts_for_every_segment_minute(client) -> None:
    """The split is checkable against the rows it claims to summarise.

    Untagged is a bucket rather than an omission, and an unanswered offer lands in it: a
    split that dropped either would not reconcile with the log, and a number nobody can
    reconcile is a number nobody can trust.
    """
    sitting = recent_sitting(client, [0, 7_000, 14_000, 21_000, 40_000, 47_000, 54_000])
    detail = client.get(f"/api/practice/sittings/{sitting['sitting_id']}").json()
    segments = detail["segments"]
    assert len(segments) == 2, "the fixture must produce two segments to be worth asserting on"

    client.patch(
        f"/api/practice/segments/{segments[0]['id']}/kind",
        json={"action": "set", "kind": "slow"},
    )
    split = client.get("/api/practice/analytics/summary?days=365").json()["kinds"]
    split_minutes = sum(entry["minutes"] for entry in split)
    segment_minutes = round(sum((s["end_ms"] - s["start_ms"]) / 60_000.0 for s in segments), 1)
    assert abs(split_minutes - segment_minutes) <= 0.2, (
        f"the kind split must reconcile with the segment minutes ({split} vs {segment_minutes})"
    )
    by_kind = {entry["kind"]: entry for entry in split}
    assert by_kind["slow"]["segments"] == 1
    assert by_kind[None]["segments"] == 1, "the uncharacterised segment has its own bucket"


def test_inference_never_overwrites_a_kind_a_person_chose(client, conn) -> None:
    """Re-running the offer pass must be safe, which is what makes it automatic.

    The segment is deliberately one an offer *would* be produced for - it is the slow
    one, and the piece has a baseline - so deleting the guard changes the outcome. A test
    on a segment no offer would ever fire for would pass with the guard removed.
    """
    slow, segment_id = a_piece_with_a_slow_offer(client, conn)
    client.patch(
        f"/api/practice/segments/{segment_id}/kind", json={"action": "set", "kind": "memory"}
    )
    written = store.offer_practice_kinds(conn, slow["sitting_id"])
    conn.commit()
    assert written == 0, "a labelled segment is not a candidate for an offer"
    segment = segment_of(client, slow)
    assert (segment["practice_kind"], segment["practice_kind_basis"]) == ("memory", "manual")
```

No new import is needed: the reconciliation check compares with `abs(...) <= 0.2` rather than
`pytest.approx`, and `store` is already imported by this module.

### Step 3.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py
```

Expected: failures on the new tests (`404` for the missing route, `KeyError: 'kinds'`,
`AttributeError: offer_practice_kinds`), and every pre-existing test still passing.

### Step 3.3 — add the models

In `backend/app/practice/models.py`, after `SourceSplit`:

```python
class PracticeKindSplit(BaseModel):
    """Logged minutes per practice kind, with the uncharacterised as a bucket.

    ``kind`` is None for segments nobody has characterised. That is a real state and not
    a fault, and it must appear: a split that dropped it could not be reconciled against
    the segments it claims to summarise.
    """

    kind: str | None = None
    minutes: float
    notes: int
    segments: int


class PracticeKindRequest(BaseModel):
    """Answer the kind question for one segment.

    ``action`` is required rather than inferred from ``kind``, because choosing a kind by
    hand and accepting the app's offer are different facts about where the value came
    from — the same distinction ``pedal_basis`` exists to preserve.
    """

    action: Literal["set", "accept", "decline"]
    kind: PracticeKind | None = None
```

and add to `AnalyticsSummary`:

```python
    kinds: list[PracticeKindSplit] = Field(default_factory=list)
```

### Step 3.4 — read the columns

In `backend/app/practice/store.py`, `_segment_rows`, add to the SELECT (after `g.identified_by`):

```sql
               g.identified_by,
               g.practice_kind,
               g.practice_kind_basis,
```

and to the `SegmentSummary(...)` construction (after `identified_by=`):

```python
                identified_by=data["identified_by"],
                practice_kind=data["practice_kind"],
                practice_kind_basis=data["practice_kind_basis"],
```

and to `SegmentSummary` in `models.py` (after `identified_by`):

```python
    practice_kind: PracticeKind | None = None
    #: 'offered' is a proposal the player has not answered and counts in no aggregate.
    practice_kind_basis: PracticeKindBasis | None = None
```

### Step 3.5 — write the offer pass, the setter and the split

In `backend/app/practice/store.py`, add to the imports:

```python
from . import kinds
```

Add these three functions after `_tag_from_workouts` (before `ensure_segments`):

```python
def _piece_tempo_baseline(
    conn: sqlite3.Connection, piece_id: int | None, exclude_segment_id: int
) -> tuple[float | None, int]:
    """The piece's own typical note rate, and how many segments it is drawn from.

    Relative to the piece, never to a metronome mark: the log has no score, so there is
    no target tempo to be slower *than*. The segment being judged is excluded so it can
    never provide its own baseline, and the mean is named a mean rather than a median —
    SQLite has no median and inventing one here would be a bigger claim than the data.

    `piece_id` is None for a segment nobody has labelled; there is then no piece to be
    slower than, which is a legitimate "no baseline", not an error.
    """
    if piece_id is None:
        return None, 0
    row = conn.execute(
        """
        SELECT AVG(m.median_tempo) AS typical, COUNT(*) AS n
        FROM segments g
        JOIN segment_metrics m ON m.segment_id = g.id
        WHERE g.piece_id = ?1 AND g.id != ?2 AND m.median_tempo IS NOT NULL
        """,
        (piece_id, exclude_segment_id),
    ).fetchone()
    return (row["typical"], int(row["n"] or 0))


def offer_practice_kinds(conn: sqlite3.Connection, sitting_id: int) -> int:
    """Write an unconfirmed kind proposal on the segments that have none.

    Never touches a row that already carries a kind *or* a basis, whatever they are: a
    proposal may not overwrite a person, and that one guard is what makes re-running the
    pass safe rather than destructive. Returns how many offers were written, which is
    what the tests assert against.
    """
    rows = conn.execute(
        """
        SELECT g.id, g.piece_id, g.source, g.practice_kind, g.practice_kind_basis,
               m.note_count, m.median_tempo, m.restarts
        FROM segments g
        LEFT JOIN segment_metrics m ON m.segment_id = g.id
        WHERE g.sitting_id = ?
        """,
        (sitting_id,),
    ).fetchall()
    written = 0
    for row in rows:
        if row["practice_kind"] is not None or row["practice_kind_basis"] is not None:
            continue
        typical, baseline = _piece_tempo_baseline(conn, row["piece_id"], int(row["id"]))
        offered = kinds.offer_for(
            note_count=int(row["note_count"] or 0),
            is_sight_reading=row["source"] == "sight_reading",
            median_tempo=row["median_tempo"],
            piece_typical_tempo=typical,
            piece_baseline_segments=baseline,
            restarts=row["restarts"],
        )
        if offered is None:
            continue
        conn.execute(
            "UPDATE segments SET practice_kind = ?1, practice_kind_basis = 'offered'"
            " WHERE id = ?2",
            (offered, int(row["id"])),
        )
        written += 1
    return written


def set_practice_kind(
    segment_id: int,
    action: str,
    kind: PracticeKind | None,
    db_path: Path | None = None,
) -> list[SegmentSummary]:
    """Record how a segment was practised, or answer the offer about it.

    The single owner of "someone has decided about the kind", the same way
    ``_settle_label`` is the one owner of a piece decision:

    * ``set`` is the player's own choice. It writes ``basis = 'manual'`` and may replace a
      previous choice, because changing your mind is not a mistake.
    * ``accept`` promotes a pending offer. It is refused when there is no offer, so a
      stale button cannot manufacture one.
    * ``decline`` clears an offer. Declining nothing is a deliberate no-op rather than a
      409: a double-click is not an error.
    """
    with db.transaction(db_path) as conn:
        row = conn.execute(
            "SELECT id, sitting_id, practice_kind, practice_kind_basis FROM segments WHERE id = ?",
            (segment_id,),
        ).fetchone()
        if row is None:
            raise NotFound(f"no segment {segment_id}")

        if action == "accept":
            if row["practice_kind_basis"] != "offered" or row["practice_kind"] is None:
                raise InvalidRequest("this segment has no offer to accept")
            conn.execute(
                "UPDATE segments SET practice_kind_basis = 'accepted' WHERE id = ?",
                (segment_id,),
            )
        elif action == "decline":
            conn.execute(
                "UPDATE segments SET practice_kind = NULL, practice_kind_basis = NULL"
                " WHERE id = ?",
                (segment_id,),
            )
        else:
            conn.execute(
                "UPDATE segments SET practice_kind = ?1, practice_kind_basis = ?2"
                " WHERE id = ?3",
                (kind, None if kind is None else "manual", segment_id),
            )
        return _segment_rows(conn, int(row["sitting_id"]))
```

Add the aggregate next to `sources`:

```python
def kinds_breakdown(conn: sqlite3.Connection, days: int) -> list[PracticeKindSplit]:
    """Logged minutes per practice kind, untagged included.

    Two rules live in this query and both are asserted:

    * the kind is taken through a CASE, so a row whose basis is ``offered`` resolves to
      NULL and lands in the untagged bucket rather than its own. An unanswered question
      must not be counted as a label, and it must not vanish either — a split that
      dropped it could not be reconciled against the segments it summarises;
    * minutes are segment minutes, not sitting minutes, because the axis is per segment.
      The Log dashboard's ``total_minutes`` stays sitting-based and is a different number.
    """
    since = (_today() - timedelta(days=days - 1)).isoformat()
    rows = conn.execute(
        """
        WITH per_segment AS (
            SELECT CASE
                       WHEN g.practice_kind_basis IN ('manual', 'accepted')
                       THEN g.practice_kind
                       ELSE NULL
                   END AS kind,
                   (g.end_ms - g.start_ms) / 60000.0 AS minutes,
                   (SELECT COUNT(*) FROM note_events e
                     WHERE e.sitting_id = g.sitting_id
                       AND e.onset_ms >= g.start_ms
                       AND e.onset_ms <= g.end_ms) AS notes
            FROM segments g
            JOIN sittings s ON s.id = g.sitting_id
            WHERE s.local_date >= ?1
        )
        SELECT kind, SUM(minutes) AS minutes, SUM(notes) AS notes, COUNT(*) AS segments
        FROM per_segment
        GROUP BY kind
        ORDER BY minutes DESC
        """,
        (since,),
    ).fetchall()
    return [
        PracticeKindSplit(
            kind=row["kind"],
            minutes=round(float(row["minutes"] or 0.0), 1),
            notes=int(row["notes"] or 0),
            segments=int(row["segments"] or 0),
        )
        for row in rows
    ]
```

Add `PracticeKind` and `PracticeKindSplit` to the model imports at the top of `store.py` (the API
layer imports `PracticeKindRequest` itself), and `kinds=kinds_breakdown(conn, days),` to
`summary()`'s `AnalyticsSummary(...)` after `sources=sources(conn, days),`.

### Step 3.6 — run the offer pass whenever a kind becomes answerable

Two call sites, because there are two moments at which an offer can become meaningful.

**In `ensure_segments`, after `autotag_sitting(conn, sitting_id)`** — not before it. The `slow`
offer needs a piece to be slower *than*, and at this point in the function a freshly created
segment has `piece_id = NULL`; running the pass before the matcher would mean the rule could only
ever fire on a segment a person had already labelled, which is the case the second call site
covers. `section`, which needs no piece, fires here.

```python
        # Offered, never applied: the proposal is stored with basis 'offered', so it is
        # drawn as a question and counts in nothing until someone answers it. After the
        # matcher, because "slower than usual for this piece" needs the piece.
        offer_practice_kinds(conn, sitting_id)
```

**In `assign_piece`**, after `_settle_label(conn, row, piece_id)` and before the return, so a
segment labelled *after* the fact gets the offer its new label makes possible — and so the rows
returned to the client already carry it:

```python
        _settle_label(conn, row, piece_id)
        # A label can make a kind offer possible that was not before: "slower than usual"
        # needs a piece. Safe to call every time — it writes only where nothing is set.
        offer_practice_kinds(conn, int(row["sitting_id"]))
        return _segment_rows(conn, int(row["sitting_id"]))
```

### Step 3.7 — add the route

In `backend/app/practice/api.py`, in the `# --- segments ---` block after `assign_segment`:

```python
@router.patch("/segments/{segment_id}/kind", response_model=list[SegmentSummary])
def set_segment_kind(segment_id: int, body: PracticeKindRequest) -> list[SegmentSummary]:
    """Say how a segment was practised, or answer the app's offer about it.

    A route of its own rather than a field on ``PATCH /segments/{id}``. The piece label
    and the practice kind are different decisions with different rules — one overrules a
    matcher and records what became of the guess, the other overrules nothing — and a body
    carrying both would have to explain which of the two a null meant.
    """
    return _handle(store.set_practice_kind, segment_id, body.action, body.kind)
```

Add `PracticeKindRequest` to the imports from `.models`.

### Step 3.8 — verify GREEN

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py tests/test_practice_kinds.py tests/test_practice_store.py
```

Expected: all pass.

### Step 3.9 — the two break scripts, and falsify

Create `backend/tools/falsifications/drop_kind_basis_guard.sh`:

```bash
#!/usr/bin/env bash
#
# Break: drop the "an offer is not a label" rule from the kind split.
#
# The CASE is what maps an unanswered proposal onto the untagged bucket. Replacing it with
# the raw column counts an offer as a kind, which is exactly the silent guess the feature
# promises never to make. The test that must catch it is
# test_an_offer_is_a_question_until_it_is_answered.
#
#   ./falsify.sh backend/tools/falsifications/drop_kind_basis_guard.sh "./check.sh --fast"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """            SELECT CASE
                       WHEN g.practice_kind_basis IN ('manual', 'accepted')
                       THEN g.practice_kind
                       ELSE NULL
                   END AS kind,"""
assert needle in text, "the guard is not where this script expects it"
path.write_text(text.replace(needle, "            SELECT g.practice_kind AS kind,", 1))
PY
```

Create `backend/tools/falsifications/let_inference_overwrite_manual.sh`:

```bash
#!/usr/bin/env bash
#
# Break: let the offer pass write over a segment that already carries a kind.
#
# That is the bug that turns an offer into a silent overwrite of the player's own
# decision. The test that must catch it is test_inference_never_overwrites_a_manual_kind.
#
#   ./falsify.sh backend/tools/falsifications/let_inference_overwrite_manual.sh "./check.sh --fast"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """        if row["practice_kind"] is not None or row["practice_kind_basis"] is not None:
            continue
"""
assert needle in text, "the guard is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
```

```bash
chmod +x backend/tools/falsifications/drop_kind_basis_guard.sh \
         backend/tools/falsifications/let_inference_overwrite_manual.sh
backend/tools/falsify.sh backend/tools/falsifications/drop_kind_basis_guard.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py"
backend/tools/falsify.sh backend/tools/falsifications/let_inference_overwrite_manual.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py"
```

Expected: `falsified: the check caught the break` for each.

### Step 3.10 — run the fast tier

```bash
./check.sh --fast
```

Expected: pass, within 180 s.

---

## Task 4 — the timeline asks, and the dashboard answers

**Files.** modify `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`,
`frontend/src/components/SegmentTimeline.svelte`, `frontend/src/components/PracticeLogView.svelte`;
create `frontend/src/lib/kinds.ts`, `frontend/src/lib/kinds.test.ts`.

**Why.** The taxonomy is worth nothing if setting it costs more than a click, and the split is what
makes a week of tagging legible.

**Change Necessity.** Code: the wire fields have no consumer without it.

**Impact / Compatibility.** Additive UI. `SegmentTimeline` gains one prop; nothing it already
renders changes.

### Step 4.1 — write the failing frontend units

Create `frontend/src/lib/kinds.test.ts`:

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { PRACTICE_KINDS, kindCounts, practiceKindLabel } from './kinds.ts';

test('the taxonomy is exactly the seven kinds the API validates', () => {
  assert.deepEqual(
    PRACTICE_KINDS.map((entry) => entry.id),
    ['run_through', 'slow', 'section', 'hands_separate', 'memory', 'warm_up', 'other'],
  );
});

test('sight-reading is not a kind — the segment source already owns it', () => {
  assert.equal(
    (PRACTICE_KINDS.map((entry) => entry.id) as string[]).includes('sight_reading'),
    false,
  );
});

test('a kind has words, and nothing reads as undefined on a screen', () => {
  assert.equal(practiceKindLabel('slow'), 'Slow');
  assert.equal(practiceKindLabel(null), 'Not characterised');
  assert.equal(practiceKindLabel('banjo'), 'banjo');
});

test('an offer is a question and only a confirmed basis counts', () => {
  assert.equal(kindCounts('offered'), false);
  assert.equal(kindCounts('manual'), true);
  assert.equal(kindCounts('accepted'), true);
  assert.equal(kindCounts(null), false);
});
```

### Step 4.2 — verify RED

```bash
cd frontend && npm test
```

Expected: failure resolving `./kinds.ts`.

### Step 4.3 — write the label module

Create `frontend/src/lib/kinds.ts`:

```ts
/**
 * The deliberate-practice taxonomy, as the player sees it.
 *
 * Values are the wire format the API validates; labels are presentation. Both live here
 * rather than in a component because the timeline (where a kind is set) and the Log
 * dashboard (where the split is drawn) must agree on the words.
 */
import type { PracticeKind } from './types';

export const PRACTICE_KINDS: { id: PracticeKind; label: string }[] = [
  { id: 'run_through', label: 'Run-through' },
  { id: 'slow', label: 'Slow' },
  { id: 'section', label: 'Section' },
  { id: 'hands_separate', label: 'Hands separate' },
  { id: 'memory', label: 'From memory' },
  { id: 'warm_up', label: 'Warm-up / technique' },
  { id: 'other', label: 'Other' },
];

/** An unknown value reads as itself; a null reads as the honest "nobody has said". */
export function practiceKindLabel(kind: string | null): string {
  if (kind === null) return 'Not characterised';
  return PRACTICE_KINDS.find((entry) => entry.id === kind)?.label ?? kind;
}

/** Does a stored kind count as a label, or is it still the app's question? */
export function kindCounts(basis: string | null): boolean {
  return basis === 'manual' || basis === 'accepted';
}
```

### Step 4.4 — add the wire types

In `frontend/src/lib/types.ts`, next to `PracticeSource`:

```ts
/** How a segment was practised. Sight-reading is not one: the source owns it. */
export type PracticeKind =
  | 'run_through'
  | 'slow'
  | 'section'
  | 'hands_separate'
  | 'memory'
  | 'warm_up'
  | 'other';

/** 'offered' is the app's question; 'manual' and 'accepted' are answers. */
export type PracticeKindBasis = 'offered' | 'manual' | 'accepted';
```

In `SegmentSummary`, after `identified_by`:

```ts
  practice_kind: PracticeKind | null;
  /** 'offered' means the kind above is a question, not a label. */
  practice_kind_basis: PracticeKindBasis | null;
```

Next to `SourceSplit`:

```ts
/** Logged minutes per practice kind. A null `kind` is the uncharacterised bucket. */
export interface PracticeKindSplit {
  kind: string | null;
  minutes: number;
  notes: number;
  segments: number;
}
```

and in `AnalyticsSummary`, after `sources`:

```ts
  kinds: PracticeKindSplit[];
```

### Step 4.5 — add the API method

In `frontend/src/lib/api.ts`, inside `practice`, after `assignSegment`:

```ts
    /**
     * Say how a segment was practised, or answer the app's offer about it.
     *
     * `set` is your own choice and may replace a previous one; `accept` promotes a
     * pending offer; `decline` clears it. All three return the sitting's segments.
     */
    setSegmentKind: (
      segmentId: number,
      body: { action: 'set' | 'accept' | 'decline'; kind?: PracticeKind | null },
    ) =>
      request<SegmentSummary[]>(`/practice/segments/${segmentId}/kind`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),
```

Add `PracticeKind` to the type imports at the top of `api.ts`.

### Step 4.6 — the timeline

In `frontend/src/components/SegmentTimeline.svelte`:

imports:

```ts
  import { PRACTICE_KINDS, kindCounts, practiceKindLabel } from '../lib/kinds';
```

and `type PracticeKind` in the existing `../lib/types` import list.

`Props`, after `onassign`:

```ts
    onkinds: (
      segmentId: number,
      body: { action: 'set' | 'accept' | 'decline'; kind?: PracticeKind | null },
    ) => void;
```

destructuring:

```ts
  let { detail, pieces, busy, onassign, onkinds, onsplit, onmerge, onresegment, onidentify }: Props =
    $props();
```

In the segment `.head` row, after the sight-reading pill block (`{/if}` that closes
`segment.source === 'sight_reading'`):

```svelte
            {#if segment.practice_kind && kindCounts(segment.practice_kind_basis)}
              <span
                class="pill"
                data-kind={segment.practice_kind}
                title="How this segment was practised — said by you, not inferred"
              >
                {practiceKindLabel(segment.practice_kind)}
              </span>
            {/if}
```

After the closing `{/if}` of the `suggested(segment)` block and before the `.controls` row:

```svelte
          {#if segment.practice_kind_basis === 'offered' && segment.practice_kind}
            <div class="row wrap suggest" data-kind-offer={segment.id}>
              <span class="muted small">{practiceKindLabel(segment.practice_kind)} practice?</span>
              <button class="ghost tiny" disabled={busy} onclick={() => onkinds(segment.id, { action: 'accept' })}>
                Yes
              </button>
              <button class="ghost tiny" disabled={busy} onclick={() => onkinds(segment.id, { action: 'decline' })}>
                No
              </button>
              <span class="muted small">
                from the tempo and the restarts — not from a score, and it counts for nothing
                until you say so
              </span>
            </div>
          {/if}
```

In the `.controls` row, after the piece `<select>`:

```svelte
            <select
              aria-label="How this segment was practised"
              disabled={busy}
              value={segment.practice_kind && kindCounts(segment.practice_kind_basis)
                ? segment.practice_kind
                : ''}
              onchange={(event) => {
                const value = (event.currentTarget as HTMLSelectElement).value;
                onkinds(segment.id, {
                  action: 'set',
                  kind: value === '' ? null : (value as PracticeKind),
                });
              }}
            >
              <option value="">— how practised? —</option>
              {#each PRACTICE_KINDS as entry (entry.id)}
                <option value={entry.id}>{entry.label}</option>
              {/each}
            </select>
```

### Step 4.7 — the log dashboard

In `frontend/src/components/PracticeLogView.svelte`:

add to the imports:

```ts
  import { practiceKindLabel } from '../lib/kinds';
```

add to the `<SegmentTimeline ...>` props, after `onassign`:

```svelte
      onkinds={(segmentId, body) =>
        void edit(() => api.practice.setSegmentKind(segmentId, body))}
```

and inside the *How the time was spent* card, after the `{#each summary.sources ...}` block:

```svelte
      {#if summary.kinds.length > 0}
        <div class="row wrap" data-kind-split>
          {#each summary.kinds as entry (entry.kind ?? 'untagged')}
            <span class="pill" class:accent={entry.kind === 'slow'}>
              {practiceKindLabel(entry.kind)} · {formatMinutes(entry.minutes)} ·
              {entry.segments}
              {entry.segments === 1 ? 'segment' : 'segments'}
            </span>
          {/each}
        </div>
      {/if}
```

### Step 4.8 — verify GREEN

```bash
cd frontend && npm test && npm run check && npm run build
```

Expected: frontend tests pass including the four new ones, `svelte-check` reports 0 errors, the
build succeeds.

### Step 4.9 — falsify the label/counting rule

Temporarily change `kindCounts` to `return basis !== null;` and run `npm test`. Expected:
`an offer is a question and only a confirmed basis counts` fails. Restore with
`git checkout -- frontend/src/lib/kinds.ts` and confirm green.

---

## Task 5 — the browser proves the path, and the docs record it

**Files.** modify `backend/tools/e2e_browser.py`, `README.md`, `AGENT-LOG.md`.

**Why.** The slice is user-visible, so it owes the tier that actually drives a browser; and the
project's own rules require the README line and the shared-log entry.

**Change Necessity.** Code (the scenario) plus docs; no production code changes in this task.

**Impact / Compatibility.** Test and documentation only.

### Step 5.1 — add the browser assertion

In `backend/tools/e2e_browser.py`, inside `scenario_practice_log`, immediately after the existing
tagging assertions (after the `check(...)` that the tag survives a re-read, before the `bars =`
block):

```python
    # --- how it was practised is a second axis from what it was ---
    with page.expect_response(
        lambda r: "/api/practice/segments/" in r.url and r.url.endswith("/kind")
    ):
        page.select_option(
            'select[aria-label="How this segment was practised"] >> nth=0', "slow"
        )
    page.wait_for_timeout(600)
    check(
        page.locator("[data-kind='slow']").count() == 1,
        "a practice kind set by hand is drawn on the timeline",
    )
    check(
        page.evaluate(
            "() => document.querySelector('select[aria-label=\"How this segment was practised\"]').value"
        )
        == "slow",
        "and it survives a re-read",
    )
    split = page.inner_text("[data-kind-split]")
    check("Slow" in split, f"and the log dashboard splits logged time by kind ({split!r})")
    check(
        "Not characterised" in split,
        "while the segment nobody characterised keeps its own bucket, so the split reconciles",
    )
```

### Step 5.2 — run the full tier

```bash
./check.sh --full
```

Expected: `check.sh --full passed`. If the kind select is not found, confirm the frontend was
rebuilt by the tier (`run_e2e.sh` builds it) and that the `aria-label` matches Task 4.6 exactly.

### Step 5.3 — README

In `README.md`, in the practice-log bullets, after the segment-tagging bullet, add:

```markdown
- **How you practised is a second axis from what you played.** Each segment can be marked
  run-through, slow, section, hands-separate, from memory, warm-up or other, and *How the time
  was spent* splits logged minutes by it. The app will offer **slow** (this was well under your
  usual note rate for the piece) or **section** (you stopped and started repeatedly) as a
  question with Yes/No beside it — an offer counts for nothing until you answer it, it never
  overwrites a kind you chose, and hands-separate is never guessed, because a register balance
  is not a measurement of the hands.
```

### Step 5.4 — AGENT-LOG

Append to `AGENT-LOG.md`, following the entry format in its § *Entry format*. `<YYYY-MM-DD>` in the
first line is the date of the run, filled in when the entry is appended — it is the format's own
token, not an unresolved decision:

```markdown
## <YYYY-MM-DD> — sight-reading agent — Phase 20a landed: a segment can say how it was practised

Scope: backend/app/practice/{schema,models,store,api,kinds}.py, backend/app/db.py,
backend/tests/{test_practice_kinds,test_practice_api,test_migration_upgrade}.py,
backend/tools/{falsifications,e2e_browser.py}, frontend/src/lib/{types,api,kinds}.ts,
frontend/src/components/{SegmentTimeline,PracticeLogView}.svelte, README.md
Did: added a second axis to a segment — how it was practised — as
`segments.practice_kind` + `practice_kind_basis`, the pure rules in `practice/kinds.py`, one
route (`PATCH /api/practice/segments/{id}/kind`), and the kind split in the Log dashboard.
Offers are stored with basis 'offered' and are excluded from every aggregate; the offer pass
never touches a row that already carries a kind or a basis. `SCHEMA_VERSION` is now 2.
Impact on the other side: two additive nullable columns on `segments`, one new route and two
additive response fields (`SegmentSummary.practice_kind*`, `AnalyticsSummary.kinds`). No
existing route, column or wire format changed, and `BACKUP_VERSION` is unchanged because the
backup guarantee is one-directional. `resegment` still discards kinds along with labels, and
still asks first.
```

### Step 5.5 — commit

One commit for the slice, after `--full` passes:

```bash
git add -A backend/app/practice/kinds.py backend/tests/test_practice_kinds.py \
  backend/tools/falsifications/drop_practice_kind_added_column.sh \
  backend/tools/falsifications/drop_kind_basis_guard.sh \
  backend/tools/falsifications/let_inference_overwrite_manual.sh \
  backend/app/practice/schema.py backend/app/db.py backend/app/practice/models.py \
  backend/app/practice/store.py backend/app/practice/api.py \
  backend/tests/test_migration_upgrade.py backend/tests/test_practice_api.py \
  backend/tools/e2e_browser.py frontend/src/lib/types.ts frontend/src/lib/api.ts \
  frontend/src/lib/kinds.ts frontend/src/lib/kinds.test.ts \
  frontend/src/components/SegmentTimeline.svelte \
  frontend/src/components/PracticeLogView.svelte README.md AGENT-LOG.md \
  docs/PLAN-PHASE20A.md
git commit -m "Phase 20a: a segment can say how it was practised"
```

Nothing from the Slice 1 work belongs in this commit: it is already committed as `d0aba27`, so
this slice's changes are the only ones staged.

---

## Risks

| Risk | Treatment |
| --- | --- |
| The offer is noisy and becomes a question the player ignores | It is one function call in `ensure_segments` behind one guard; deleting the call and `offer_practice_kinds` removes the feature without touching a stored label. Measured before it is trusted: `offer_practice_kinds` returns a count, and the acceptance test pins that it offers nothing on a labelled segment |
| The split and `total_minutes` disagree and look like a bug | They are different numbers on purpose: the split is segment minutes, `total_minutes` is sitting minutes (which include the silences between segments). The reconciliation invariant is against segment minutes, and the card keeps `total_minutes` labelled as it is today |
| `SCHEMA_VERSION = 2` locks out an older build mid-flight | Intended: `SchemaTooNew` refuses rather than misreads. The deployment is single-host and the backup path is JSON, so a rollback is a restore, not a downgrade |
| A second axis drifts into owning the sight-reading fact | `test_sight_reading_is_not_a_kind` on the backend and in `kinds.test.ts`, and `offer_for` refuses `is_sight_reading` outright |
| `store.py` grows past reviewable size | The rules live in `kinds.py`; store.py gains persistence only. If the slice pushes store.py past ~1900 lines, the next analytics addition extracts `practice/analytics.py` rather than adding a fourth responsibility |

## Retirement

- **`practice_kind_basis = 'offered'` rows** are proposals, not history. If the offer pass is
  deleted, they are cleared by one statement:
  `UPDATE segments SET practice_kind = NULL, practice_kind_basis = NULL WHERE practice_kind_basis = 'offered'`.
  No trigger is scheduled; the trigger is "the offer annoys more than it helps".
- **No old path is retired by this slice.** `segments.source` keeps its meaning and its readers
  (`sources()`, the timeline pill, the workout tagging), and nothing here reads it differently.
- **The `words` labels** in `lib/kinds.ts` are the only place a rename has to happen; the ids are
  the wire format and are not user-facing.

## ADR / baseline-sync signals

- **20-D1** (a second axis, `source` keeps provenance) and **20-D2** (offered, never applied) are
  recorded in `docs/ECOSYSTEM.md` § Phase 20 § *Decisions taken*. This plan implements them; it does
  not create a new decision record, and no ADR directory is created (`TEST-STRATEGY.md` T7).
- On completion, the baseline-sync question is: *did 20a add any fact not already owned by
  `segments`?* The answer must be no — one column set on an existing table, one route on an
  existing owner.

---

```text
Execution Readiness View:
- Intent Lock: store a deliberate-practice kind per segment, offer it but never apply it, and split
  logged time by it; nothing about the sight-reading loop, scoring or generation changes
- Scope Fence: in — the two columns, kinds.py, the route, the split, the timeline control, the log
  card, tests, falsifications, README/AGENT-LOG. Out — 20b-20e, any per-piece or per-sitting kind,
  any auto-applied label, any bar-level or hands inference, the practice map
- Baseline Lock: ECOSYSTEM.md § Phase 20 § 20a + 20-D1/20-D2 (approved, commit bacf049);
  TEST-STRATEGY.md §8 as the strict TDD authority; ./check.sh --fast measured green in 65 s before
  any edit
- Approved Behavior: see 20a's five acceptance bullets; the plan's tests are their mechanical form
- Owner / Contract Constraints: practice/store.py writes; practice/kinds.py decides; models.py owns
  the wire vocabulary; lib/kinds.ts owns the words
- Compatibility Boundary: additive nullable columns; no route shape change; BACKUP_VERSION
  unchanged; SCHEMA_VERSION 1 -> 2 by design
- Retirement Boundary: no old path retired; the offer pass has a stated deletion trigger
- Task Batches: 1 schema, 2 taxonomy module, 3 store + route, 4 frontend, 5 browser + docs
- Test Obligations: one migration test, twelve taxonomy units, ten store/contract tests, one
  reconciliation invariant, four frontend units, one browser assertion; three committed break
  scripts plus two temporary breaks, each observed to fail
- Review Gates: after Task 3 (backend surface complete) and after Task 5 (`--full` green)
- Drift / Rewind Rules: if a step needs a third column, a second route, or an inference beyond
  slow/section, stop and return to the spec — that is a design change, not an implementation detail
- Evidence Required Before Completion: ./check.sh --full passing, each falsification reported as
  "falsified", the reconciliation invariant green, and the AGENT-LOG entry appended
- Advisory Boundary: method-pack execution guidance only; not GateDecision, PolicySnapshot, or
  completion authority
```

```text
Execution Route:
- Decision: inline
- Evidence: the five tasks are strictly sequential on shared files (schema -> kinds -> store ->
  components -> e2e), so isolating parallel writers would cost more than it saves
- Fallback: none needed; if the tree is dirty before Task 1, stop and commit or stash first, because
  falsify.sh reverts a break with `git checkout -- .`
- User confirmation required: no — no authorization, privacy, external-action or irreversible
  boundary is crossed by writing this plan
```

**Next step:** execute with the `executing-plans` skill, batching at the two review gates above. The
first action is the Precondition: the working tree must be clean before any falsification runs.
