# Plan — Phase 20d: journal and library depth

**Parent spec:** [`ECOSYSTEM.md`](./ECOSYSTEM.md) § *Phase 20* § *20d — journal and library depth
(A2, C1–C4)*, with decision 20-D7. That section owns what and why; this document owns the how.

**Status: landed.** **Phase 21 landed first and took `SCHEMA_VERSION` to 3**, and 20e then took it
to 4, so this plan's "3 → 4" was executed as **4 → 5**. Four defects a review found afterwards are
recorded in `AGENT-LOG.md` (2026-09-17): the tag filter, a null-bar PATCH, the unreported passage
cascade, and a loop passage that named no loop.

**Goal.** Make the journal filterable and comparable, give "bars 12–14 are the problem" somewhere to
live, stop a deliberately paused piece from nagging for ever, and let the library be sorted and
edited in bulk.

**Architecture.** The repertoire domain owns all of it: four additive `piece_journal` columns, one
new `piece_passages` table declared in `REPERTOIRE_SCHEMA`, and routes on the existing
`/api/repertoire` router. One addition lands on the practice side — a `GET /api/practice/pieces`
read — because "least time invested" is a practice number and the only existing route that carries
it drags the whole Log dashboard along. The client composes its sorts and its bulk edits from those
two reads.

**Tech stack.** Python/FastAPI/Pydantic/SQLite, Svelte 5 + TypeScript, pytest, Playwright.

**Baseline / authority refs.**

- `docs/ECOSYSTEM.md` § Phase 20 § 20d, plus 20-D7 (nothing is inferred about bars the app cannot
  see) and the schema note in § Phase 20 (corrected: a new table needs no `ADDED_COLUMNS` entry and
  no backup edit, because `backup.table_names` reads `sqlite_master`).
- `docs/TEST-STRATEGY.md` §8 (the standing rule) and §4 Slice 1 (the migration mechanism).
- `docs/PLAN-PHASE20A.md` (the frozen-shape and migration pattern), `PLAN-PHASE20B.md` (tiers).
- `AGENT-LOG.md` § *Rules*.

**Re-read gate.** Written against the tree at `4ea8eca`. Before Task 1:

```bash
cd /home/marco_normal/tmp/SighRTracker
grep -n "WHERE p.status" backend/app/practice/store.py
grep -n "def get_journal_entry" -A 6 backend/app/repertoire/store.py
grep -n "piece\[\"media\"\] = list_media" backend/app/repertoire/store.py
grep -n "let editingEntry" frontend/src/components/RepertoireView.svelte
git status --porcelain   # must print nothing before any falsification
```

**Compatibility boundary.** Four additive nullable `piece_journal` columns, one new table, one new
read route, and `tags`/`difficulty`/`fluency`/`media_id`/`passages` added to the journal and piece
responses. `BACKUP_VERSION` unchanged — the table list is derived, and an older document simply
carries no rows for the new table. `SCHEMA_VERSION` 3 → 4, so an older build refuses a database that
has the columns rather than misreading it. No existing route changes shape.

**Decision 20d-D1, and the constraint that shapes A2.** There is no score alignment (18b's non-goal,
restated as 20-D7), so the app cannot convert a recording's A/B loop into bar numbers, and it can
never mark a passage as "touched" from passive capture. A passage therefore records **the player's
own bar numbers**, and seeding one from a loop means recording *which* loop it came from
(`source = 'loop'`, `media_id` set) while the bars are typed. `last_worked_on` is stamped by the
player pressing a button, never inferred. Anything else would be the app claiming to see a score it
does not have.

```text
TDD Route:
- Mode: auto
- Decision: strict
- Strict authority: docs/TEST-STRATEGY.md §8, the standing rule
- Strict signals: persistence (four columns plus a new table, with a frozen-shape tripwire), a
  public contract (three new routes and five additive response fields), and a behaviour change (the
  neglected list stops including paused pieces)
- Light eligibility: not applicable
- Test posture: strict RED first for the schema, the store and the routes; for assertions added over
  already-correct reads, apply a break, watch it fail, restore
- Verification: ./check.sh --fast after every task; ./check.sh --full before the slice is called done
```

```text
Requirement Ready Check:
- Requirement source refs: docs/ECOSYSTEM.md § Phase 20 § 20d (approved with the phase)
- Goals and scope refs: the same section's Problem/Design
- User / scenario refs: a player writing "coda needs slow work" and later finding it by tag; a player
  marking bars 12–14 and wanting to know what they have not touched in a month; a player who paused a
  piece on purpose and does not want to be told about it
- Requirement item refs: four journal columns, the passages table, the neglected fix, the sort read,
  the list QoL
- Acceptance / verification criteria refs: 20d's five acceptance bullets
- Open blocker questions: none
- Decision: ready
```

```text
Change Necessity:
- User-visible need: the journal cannot be filtered or compared, "bars 12–14" has nowhere to live,
  a paused piece nags for ever, and the library cannot be sorted by effort
- No-change / non-code option: insufficient — a prose search cannot express a tag filter, and no
  existing column can hold a bar range
- Why code change is necessary: columns, one table, three routes, one read and the UI are all code
- Minimum change boundary: repertoire schema/models/store/api, one practice route, the Repertoire
  client, tests, falsifications, docs
- Decision: code-change
```

```text
Existence Check:
- Proposed new surface: four `piece_journal` columns; the `piece_passages` table; three repertoire
  routes; one practice read route; `PieceDetail.passages`; five response fields
- Existing owner / reuse candidate: `piece_journal` already owns dated prose and already has the
  `sitting_id` precedent for a nullable link; `discard`-style JSON columns are the project's existing
  way to store a list; `by_piece()` already computes every number the sorts need; `list_pieces`
  already owns the library list
- Why existing surface is insufficient: no column can express a bar range or a tag, and the only
  route carrying per-piece practice minutes is the analytics summary, which also computes a year of
  calendar, the recent sittings and the neglected list — pulling that into the library view to sort a
  list is the wrong trade
- Creation proof: 20d's acceptance bullets cannot be met by configuration or by an existing column
- Entropy / retirement impact: one new table with one index and no backup change; no tag table (a
  single player's library does not need one, and the same judgement was recorded for 20a); the
  passages list is deletable with its table
- Decision: add-with-proof for the table and the read route; reuse-existing for the columns' owner,
  the JSON storage and `by_piece`
```

```text
Architecture Integrity Lens:
- Invariant: nothing in this slice claims to know a score. Bar numbers are the player's; a passage's
  provenance is `source` + `media_id`; `last_worked_on` is only ever set by a person
- Canonical owner / contract: the repertoire domain owns the journal and the passages; the practice
  domain owns `by_piece`, and the new read exposes it rather than duplicating it
- Responsibility overlap: none — the practice read is a thin projection of an existing function, not
  a second implementation, and the sort composition happens in one component
- Higher-level simplification: `media_id` mirrors `sitting_id` exactly, including `ON DELETE SET
  NULL`, so one rule covers both links
- Retirement / falsifier: if the sort turns out to need all-time numbers beyond the 3650-day cap, the
  read gains a parameter rather than a second route; if passages are never returned to, the table and
  its panel go together
- Verdict: proceed
```

```text
Plan-Time Complexity Check:
- Target files: backend/app/repertoire/store.py (574), api.py (597), frontend/src/components/RepertoireView.svelte (1454)
- Existing size / shape signals: `RepertoireView` is the largest component in the app and already
  owns the library list, the piece detail, the journal form, the entry editor and the media list
- Owner fit: every new control belongs beside what it edits; the sorts belong with the filters
- Add-in-place risk: the journal editor and the passages panel are new sections in an already-large
  component
- Better file boundary: extract the passages panel to its own component
  (`PassageList.svelte`), leaving `RepertoireView` to own the list, the filters and the sorts
- Recommendation: add owner file for the passages panel; edit-in-place elsewhere
```

```text
Plan Pressure Test:
- Owner / contract / retirement: one new table with no backup impact; three routes on an existing
  router; one thin read on the practice router
- Architecture integrity / higher-level path: no score alignment is invented, and the practice read
  is a projection rather than a copy
- Verification scope: migration parity, a contract test per route, the neglected behaviour, the
  sort's agreement with `by_piece`, one browser scenario extension, four break scripts
- Task executability: every step names a file, complete code and an exact command
- Pressure result: proceed
```

---

## Files

**Create**

| Path | Why |
| --- | --- |
| `frontend/src/components/PassageList.svelte` | The focus-passage panel, extracted so `RepertoireView` does not grow a fourth section |
| `backend/tools/falsifications/drop_journal_added_column.sh` | Break the migration parity for `piece_journal.tags` |
| `backend/tools/falsifications/let_paused_pieces_nag.sh` | Restore the neglected defect |
| `backend/tools/falsifications/ignore_the_tag_filter.sh` | Break the tag filter |
| `backend/tools/falsifications/forget_the_passage_provenance.sh` | Break `source`/`media_id` on a seeded passage |

**Modify**

| Path | Change |
| --- | --- |
| `backend/app/repertoire/schema.py` | Four columns in both places, the `piece_passages` table and its index |
| `backend/app/db.py` | `SCHEMA_VERSION` 3 → 4 |
| `backend/app/repertoire/models.py` | `tags`/`difficulty`/`fluency`/`media_id` on the three journal models; `PassageOut`/`PassageCreate`/`PassageUpdate`; `PieceDetail.passages` |
| `backend/app/repertoire/store.py` | One row decoder for journal tags; extend create/update; a `tag` filter; passages CRUD; attach passages in `get_piece` |
| `backend/app/repertoire/api.py` | Three passage routes; the `tag` query param on both journal reads |
| `backend/app/practice/store.py` | `WHERE p.status = 'active'` in `neglected()` |
| `backend/app/practice/api.py` | `GET /pieces` returning `by_piece` |
| `backend/tests/test_migration_upgrade.py` | The frozen shape |
| `backend/tests/test_repertoire.py` | Journal tags/ratings/take, passages, the sort read |
| `backend/tests/test_practice_api.py` | The neglected fix |
| `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts` | The new fields and four client methods |
| `frontend/src/components/RepertoireView.svelte` | Tags and ratings in both journal forms, the tag filter, the take link, the passages panel, the sorts, the saved view and bulk edits |
| `backend/tools/e2e_browser.py` | `scenario_repertoire` gains four assertions |
| `README.md`, `AGENT-LOG.md`, `docs/ECOSYSTEM.md` | docs |

---

## Task 1 — the schema

**Files.** modify `backend/app/repertoire/schema.py`, `backend/app/db.py`,
`backend/tests/test_migration_upgrade.py`; create
`backend/tools/falsifications/drop_journal_added_column.sh`.

**Why.** Nothing else in the slice can be written before the columns and the table exist.

**Change Necessity.** Code: SQLite cannot gain a column or a table without a migration statement.

**Impact / Compatibility.** Additive and nullable. A new table needs **no** `ADDED_COLUMNS` entry
(`CREATE TABLE IF NOT EXISTS` runs on every `init_db`) and **no** backup edit
(`backup.table_names` reads `sqlite_master`), which is the correction recorded in the spec.

### Step 1.1 — write the failing migration tests

Append to `backend/tests/test_migration_upgrade.py`:

```python
def test_the_upgraded_database_gains_the_journal_columns() -> None:
    """20d: tags, two ratings and a take link arrive on a library that predates them."""
    path = _build_fixture_db("journal-columns.sqlite3")
    db.init_db(path)
    conn = db.connect(path)
    try:
        assert {"tags", "difficulty", "fluency", "media_id"} <= _columns(conn, "piece_journal")
    finally:
        conn.close()


def test_the_passage_table_exists_on_fresh_and_upgraded_databases() -> None:
    """A new table needs no ADDED_COLUMNS entry: the CREATE runs on every init."""
    upgraded = _build_fixture_db("passages-upgraded.sqlite3")
    db.init_db(upgraded)
    fresh = _fresh_path("passages-fresh.sqlite3")
    db.init_db(fresh)

    for path in (upgraded, fresh):
        conn = db.connect(path)
        try:
            assert "piece_passages" in _tables(conn)
            assert _columns(conn, "piece_passages") == {
                "id", "piece_id", "start_bar", "end_bar", "label", "source",
                "media_id", "created_at", "last_worked_on",
            }
        finally:
            conn.close()
```

### Step 1.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py
```

Expected: both new tests fail on the missing columns and table.

### Step 1.3 — the columns and the table

In `backend/app/repertoire/schema.py`, in the `piece_journal` CREATE, after `sitting_id`:

```sql
    -- Free-text labels for one entry ("coda", "fingering", "memorisation"). A JSON array in
    -- one column rather than a table of its own: this is one player's library of a few
    -- hundred entries, and Phase 20a's plan records the same judgement for practice kinds.
    -- Written with `db.json_dump`, so it is compact and a quoted-tag LIKE is unambiguous.
    tags              TEXT,
    -- How hard it felt and how well it went, 1..5, nullable. Two numbers rather than one
    -- because "hard and it went well" is a different fact from "easy and it did not".
    difficulty        INTEGER,
    fluency           INTEGER,
    -- The take this was written about, when it was written about one. SET NULL for exactly
    -- the reason `sitting_id` is: deleting a recording must never delete prose.
    media_id          INTEGER REFERENCES media(id) ON DELETE SET NULL,
```

and, after the `media` table's index, the new table:

```sql
-- A stretch of a piece worth returning to: "bars 12-14, the left-hand leaps".
--
-- The app cannot see a score — there is no alignment, by decision 18b/20-D7 — so the bar
-- numbers are the player's own reading and nothing here is derived from the log. `source`
-- says whether the passage was typed or seeded from a recording's A/B loop, and `media_id`
-- names that loop. Seeding therefore records *provenance*, not a bar conversion the app is
-- in no position to make.
CREATE TABLE IF NOT EXISTS piece_passages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    piece_id        INTEGER NOT NULL REFERENCES pieces(id) ON DELETE CASCADE,
    start_bar       INTEGER NOT NULL,
    end_bar         INTEGER NOT NULL,
    label           TEXT,
    source          TEXT NOT NULL DEFAULT 'manual',   -- 'manual' | 'loop'
    media_id        INTEGER REFERENCES media(id) ON DELETE SET NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- The last day the player said they worked on it, or NULL for never. The list sorts
    -- the never-touched first, which is the whole reason the list exists.
    last_worked_on  TEXT
);
CREATE INDEX IF NOT EXISTS idx_passages_piece
    ON piece_passages(piece_id, last_worked_on, start_bar);
```

and to `ADDED_COLUMNS`:

```python
    # Phase 20d — the journal gains labels, two ratings and a take link. `media_id` needs
    # its REFERENCES spelled out for the same reason `sitting_id` does: an ALTER that omits
    # it leaves an upgraded database with a dangling reference.
    ("piece_journal", "tags", "TEXT"),
    ("piece_journal", "difficulty", "INTEGER"),
    ("piece_journal", "fluency", "INTEGER"),
    ("piece_journal", "media_id", "INTEGER REFERENCES media(id) ON DELETE SET NULL"),
```

### Step 1.4 — the harness must know the table exists

`backend/tools/e2e_browser.py`'s `reset_all()` refuses to run when a table in `sqlite_master` is in
neither `DATA_TABLES` nor `REFERENCE_TABLES` (`e2e_browser.py:1871-1876`), and its list is
deliberately explicit rather than derived — "a backup must not forget a table; a reset must not
silently clear one that a later phase added without anyone deciding it should be cleared". So a new
table is a **loud failure in every browser scenario** until it is named. Add it to `DATA_TABLES`
(`e2e_browser.py:1823-1839`), after `"piece_journal"`:

```python
DATA_TABLES = (
    "composers",
    "pieces",
    "piece_journal",
    "piece_passages",
    "media",
    ...
)
```

This is the step that would otherwise turn a green `--fast` into a red `--full` for a reason with
nothing to do with the feature, which is exactly why it is in the schema task rather than deferred
to Task 7.

### Step 1.5 — bump the version and freeze the shape

`backend/app/db.py`: `SCHEMA_VERSION = 4`.

In `backend/tests/test_migration_upgrade.py`:

```python
    "piece_journal": {
        "id", "piece_id", "entry_date", "content", "practice_minutes", "sitting_id",
        "legacy_id", "created_at", "tags", "difficulty", "fluency", "media_id",
    },
```

add to `EXPECTED_COLUMNS`:

```python
    "piece_passages": {
        "id", "piece_id", "start_bar", "end_bar", "label", "source", "media_id",
        "created_at", "last_worked_on",
    },
```

add `"piece_passages": {"idx_passages_piece"},` to `EXPECTED_INDEXES` (match the surrounding
format — read it first: `grep -n "EXPECTED_INDEXES" -A 25 tests/test_migration_upgrade.py`), and
extend the frozen fixture's guard:

```python
        assert {"sitting_id", "tags", "difficulty", "fluency", "media_id"}.isdisjoint(
            _columns(conn, "piece_journal")
        ), "the fixture predates every ADDED_COLUMNS entry for piece_journal"
```

### Step 1.6 — verify GREEN

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py tests/test_backup.py
```

### Step 1.7 — falsify the migration

Create `backend/tools/falsifications/drop_journal_added_column.sh`:

```bash
#!/usr/bin/env bash
#
# Break: delete the 20d ADDED_COLUMNS entry for piece_journal.tags.
#
# Without it the ALTER never runs on a library that predates the column, so the upgraded
# schema is missing a column a fresh one has. The parity test in test_migration_upgrade.py
# is what must catch it.
#
#   ./falsify.sh backend/tools/falsifications/drop_journal_added_column.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '    ("piece_journal", "tags", "TEXT"),\n'
assert needle in text, "the line to break is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
```

```bash
chmod +x backend/tools/falsifications/drop_journal_added_column.sh
backend/tools/falsify.sh backend/tools/falsifications/drop_journal_added_column.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py"
```

---

## Task 2 — the neglected list stops nagging about a paused piece

**Files.** modify `backend/app/practice/store.py`, `backend/tests/test_practice_api.py`; create
`backend/tools/falsifications/let_paused_pieces_nag.sh`.

**Why.** `neglected()` filters only `NOT completed`, so `paused` — a status the player chose on
purpose — is reported as neglected for ever. This is a defect the 20d survey found, not a missing
feature.

**Change Necessity.** Code: one query predicate.

**Impact / Compatibility.** A behaviour change to an existing response, and the one to state
plainly: a piece with status `paused` disappears from `neglected`. `completed` already did.

### Step 2.1 — write the failing test

Append to `backend/tests/test_practice_api.py`:

```python
def test_a_paused_piece_does_not_nag(client, conn) -> None:
    """`paused` is a status the player chose; the neglected list must honour it.

    Found while planning 20d: the query filtered `!= 'completed'`, so a piece deliberately
    set aside was reported as neglected for ever — the opposite of what the status is for.
    """
    seed_piece(conn, "Active Etude")
    conn.execute("INSERT INTO pieces (title, status) VALUES ('Paused Etude', 'paused')")
    conn.commit()

    titles = [
        row["title"]
        for row in client.get("/api/practice/analytics/summary?days=30").json()["neglected"]
    ]
    assert "Active Etude" in titles
    assert "Paused Etude" not in titles, f"a paused piece must not be reported ({titles})"
```

### Step 2.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py -k paused
```

Expected: `Paused Etude` is present, so the second assertion fails.

### Step 2.3 — the fix

In `backend/app/practice/store.py`, `neglected()`, replace the predicate:

```python
        -- `active` only. `paused` is a deliberate decision by the player and `completed` is a
        -- piece that is done; reporting either as neglected is the list arguing with them.
        WHERE p.status = 'active'
```

### Step 2.4 — verify GREEN and falsify

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py
```

Create `backend/tools/falsifications/let_paused_pieces_nag.sh`:

```bash
#!/usr/bin/env bash
#
# Break: put the neglected query back to "everything that is not completed".
#
# The test that must catch it is test_a_paused_piece_does_not_nag.
#
#   ./falsify.sh backend/tools/falsifications/let_paused_pieces_nag.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/practice/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "        WHERE p.status = 'active'"
assert needle in text, "the predicate is not where this script expects it"
path.write_text(text.replace(needle, "        WHERE p.status != 'completed'", 1))
PY
```

```bash
chmod +x backend/tools/falsifications/let_paused_pieces_nag.sh
backend/tools/falsify.sh backend/tools/falsifications/let_paused_pieces_nag.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py"
```

---

## Task 3 — the journal gains tags, two ratings and a take

**Files.** modify `backend/app/repertoire/models.py`, `backend/app/repertoire/store.py`,
`backend/app/repertoire/api.py`, `backend/tests/test_repertoire.py`; create
`backend/tools/falsifications/ignore_the_tag_filter.sh`.

**Why.** The journal is prose with a sitting link; it cannot be filtered by subject or compared over
time, and it cannot point at the take it is about.

**Change Necessity.** Code: three columns have no writer and no reader.

**Impact / Compatibility.** Additive on all three journal models and both journal reads.

### Step 3.1 — write the failing tests

Append to `backend/tests/test_repertoire.py` (match the file's existing fixture style — read the top
of the file first):

```python
def test_a_journal_entry_carries_tags_and_two_ratings(client) -> None:
    piece = client.post("/api/repertoire/pieces", json={"title": "Nocturne"}).json()
    created = client.post(
        f"/api/repertoire/pieces/{piece['id']}/journal",
        json={
            "entry_date": "2026-03-01",
            "content": "The coda needs slow work.",
            "tags": ["coda", "  slow  ", "coda", ""],
            "difficulty": 4,
            "fluency": 2,
        },
    )
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["tags"] == ["coda", "slow"], "trimmed, de-duplicated, blanks dropped"
    assert entry["difficulty"] == 4
    assert entry["fluency"] == 2


def test_tags_can_be_changed_and_cleared_one_at_a_time(client) -> None:
    piece = client.post("/api/repertoire/pieces", json={"title": "Etude"}).json()
    entry = client.post(
        f"/api/repertoire/pieces/{piece['id']}/journal",
        json={"entry_date": "2026-03-02", "content": "x", "tags": ["a"], "fluency": 3},
    ).json()

    renamed = client.patch(f"/api/repertoire/journal/{entry['id']}", json={"tags": ["b", "c"]})
    assert renamed.json()["tags"] == ["b", "c"]
    assert renamed.json()["fluency"] == 3, "an unset field is left alone"

    cleared = client.patch(f"/api/repertoire/journal/{entry['id']}", json={"fluency": None})
    assert cleared.json()["fluency"] is None, "an explicit null clears"
    assert cleared.json()["tags"] == ["b", "c"]


def test_a_rating_outside_one_to_five_is_refused(client) -> None:
    piece = client.post("/api/repertoire/pieces", json={"title": "Waltz"}).json()
    for bad in (0, 6, -1):
        response = client.post(
            f"/api/repertoire/pieces/{piece['id']}/journal",
            json={"entry_date": "2026-03-03", "content": "x", "difficulty": bad},
        )
        assert response.status_code == 422, f"{bad} is not a rating"


def test_the_tag_filter_finds_tags_and_not_prose(client) -> None:
    """A tag filter must filter tags. The word appearing in the entry is not a match."""
    tagged = client.post("/api/repertoire/pieces", json={"title": "Tagged"}).json()
    prose = client.post("/api/repertoire/pieces", json={"title": "Prose"}).json()
    client.post(
        f"/api/repertoire/pieces/{tagged['id']}/journal",
        json={"entry_date": "2026-03-04", "content": "no keyword here", "tags": ["coda"]},
    )
    client.post(
        f"/api/repertoire/pieces/{prose['id']}/journal",
        json={"entry_date": "2026-03-05", "content": "the coda is hard"},
    )

    found = client.get("/api/repertoire/journal?tag=coda").json()
    assert [row["piece_title"] for row in found] == ["Tagged"], (
        f"only the tagged entry matches ({found})"
    )
    assert client.get("/api/repertoire/journal?tag=nothing").json() == []


def test_a_journal_entry_can_point_at_a_take_and_survives_it_being_deleted(client) -> None:
    piece_id = _a_piece(client, "Ballade")
    # A recording normally arrives by upload, which needs a real audio file; inserting the
    # catalogue row directly is the honest shortcut here, and the upload path is covered by
    # the media tests above.
    with db.transaction(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO media (id, piece_id, kind, file_name) VALUES (77, ?, 'recording', 'x.ogg')",
            (piece_id,),
        )
    entry = client.post(
        f"/api/repertoire/pieces/{piece_id}/journal",
        json={"entry_date": "2026-03-06", "content": "take 3 is the one", "media_id": 77},
    ).json()
    assert entry["media_id"] == 77

    with db.transaction(settings.db_path) as conn:
        conn.execute("DELETE FROM media WHERE id = 77")
    reread = client.get(f"/api/repertoire/pieces/{piece_id}").json()
    assert reread["journal"][0]["media_id"] is None, "deleting the take must not delete the prose"
    assert reread["journal"][0]["content"] == "take 3 is the one"
```

The imports at the top of `test_repertoire.py` need `from app import db` and
`from app.config import settings`; check and add what is missing.

### Step 3.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py -k "tag or rating or take"
```

Expected: failures on the missing fields and the missing `tag` parameter.

### Step 3.3 — the models

In `backend/app/repertoire/models.py`, add `field_validator` to the pydantic import, then a shared
alias and the three model changes.

Above `JournalCreate`:

```python
#: A label on one entry. Bounded so a pasted paragraph cannot become a tag.
MAX_TAGS = 12
MAX_TAG_LENGTH = 40


def _clean_tags(value: list[str]) -> list[str]:
    """Trim, drop blanks, de-duplicate, cap. Order is the player's, so it is preserved."""
    cleaned = [tag.strip()[:MAX_TAG_LENGTH] for tag in value]
    return [tag for tag in dict.fromkeys(cleaned) if tag][:MAX_TAGS]
```

`JournalCreate` gains:

```python
    #: Short labels for one entry, stored as a JSON array in one column.
    tags: list[str] = Field(default_factory=list)
    #: How hard it felt and how well it went, 1..5. Two numbers because "hard and it went
    #: well" is a different fact from "easy and it did not".
    difficulty: int | None = Field(default=None, ge=1, le=5)
    fluency: int | None = Field(default=None, ge=1, le=5)
    #: The take this was written about. Validated to exist at the route, like `sitting_id`.
    media_id: int | None = None

    _tags = field_validator("tags")(_clean_tags)
```

`JournalUpdate` gains:

```python
    tags: list[str] | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    fluency: int | None = Field(default=None, ge=1, le=5)
    media_id: int | None = None

    @field_validator("tags")
    @classmethod
    def _update_tags(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_tags(value)
```

`JournalEntryOut` gains:

```python
    tags: list[str] = Field(default_factory=list)
    difficulty: int | None = None
    fluency: int | None = None
    media_id: int | None = None
```

### Step 3.4 — the store

In `backend/app/repertoire/store.py`, add a row decoder above `create_journal_entry`:

```python
def _journal_row(row: Any) -> dict[str, Any]:
    """One journal row in the wire shape: the tag array decoded, everything else as stored.

    Written with `db.json_load`, which raises on a corrupt row rather than degrading to an
    empty list — a tag set that silently became "no tags" is a filter that silently stops
    finding things, which is the failure mode Slice 1's T9 decision exists to prevent.
    """
    data = dict(row)
    data["tags"] = db.json_load(data.get("tags"), [])
    return data
```

`create_journal_entry` — extend the INSERT:

```python
    cursor = conn.execute(
        """
        INSERT INTO piece_journal
            (piece_id, entry_date, content, practice_minutes, sitting_id,
             tags, difficulty, fluency, media_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            piece_id,
            fields["entry_date"],
            fields["content"],
            fields.get("practice_minutes"),
            fields.get("sitting_id"),
            db.json_dump(fields.get("tags") or []),
            fields.get("difficulty"),
            fields.get("fluency"),
            fields.get("media_id"),
        ),
    )
```

`update_journal_entry` — extend the allowed keys and encode tags on the way in:

```python
def update_journal_entry(conn: sqlite3.Connection, entry_id: int, changes: dict[str, Any]) -> int:
    allowed = (
        "entry_date", "content", "practice_minutes", "sitting_id",
        "tags", "difficulty", "fluency", "media_id",
    )
    updates = {key: value for key, value in changes.items() if key in allowed}
    if "tags" in updates:
        updates["tags"] = None if updates["tags"] is None else db.json_dump(updates["tags"])
    if not updates:
        return conn.execute(
            "SELECT COUNT(*) FROM piece_journal WHERE id = ?", (entry_id,)
        ).fetchone()[0]
    ...unchanged from here
```

`get_journal_entry` — select the new columns and decode:

```python
def get_journal_entry(conn: sqlite3.Connection, entry_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, piece_id, entry_date, content, practice_minutes, sitting_id,"
        " tags, difficulty, fluency, media_id"
        " FROM piece_journal WHERE id = ?",
        (entry_id,),
    ).fetchone()
    return _journal_row(row) if row else None
```

`list_journal_entries` — add the `tag` parameter and decode. Replace its signature and body:

```python
def list_journal_entries(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
    search: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    """The newest entries across the whole library.

    `tag` matches a *label*, never the prose: the stored array is written with
    `db.json_dump`'s compact separators, so a tag always appears quoted and adjacent to its
    own quotation marks, and `%"coda"%` cannot match the word "coda" in a sentence.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if search:
        clauses.append("(j.content LIKE ? OR p.title LIKE ? OR c.name LIKE ?)")
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern])
    if tag:
        clauses.append("j.tags LIKE ?")
        params.append(f'%"{tag}"%')
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(limit, 500)))
    rows = conn.execute(
        f"""
        SELECT j.id, j.piece_id, j.entry_date, j.content, j.practice_minutes,
               j.sitting_id, j.tags, j.difficulty, j.fluency, j.media_id,
               j.created_at,
               p.title AS piece_title, c.name AS composer_name
        FROM piece_journal j
        JOIN pieces p ON p.id = j.piece_id
        LEFT JOIN composers c ON c.id = p.composer_id
        {where}
        ORDER BY j.entry_date DESC, j.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_journal_row(row) for row in rows]
```

and the per-piece read inside `get_piece` (`store.py:135-146`):

```python
    piece["journal"] = [
        _journal_row(row)
        for row in conn.execute(
            """
            SELECT id, piece_id, entry_date, content, practice_minutes,
                   sitting_id, tags, difficulty, fluency, media_id, created_at
            FROM piece_journal WHERE piece_id = ?
            ORDER BY entry_date DESC, id DESC
            """,
            (piece_id,),
        )
    ]
```

Add a media-existence check beside `sitting_exists`:

```python
def media_exists(conn: sqlite3.Connection, media_id: int) -> bool:
    """Whether this recording is in the library. The same 422-not-500 rule as `sitting_id`."""
    return conn.execute("SELECT 1 FROM media WHERE id = ?", (media_id,)).fetchone() is not None
```

### Step 3.5 — the routes

In `backend/app/repertoire/api.py`, extend `_validate_sitting`'s neighbourhood with a media check
(read the existing `_validate_sitting` first and mirror its shape), then:

- `create_journal_entry` (`:301-309`): after the sitting check, add
  `_validate_media(conn, body.media_id)`.
- `update_journal_entry` (`:313-323`): after the sitting check, add
  `_validate_media(conn, changes.get("media_id"))`.
- `journal_feed` (`:284-297`): add the parameter and pass it through:

```python
@router.get("/journal", response_model=list[JournalEntryOut])
def journal_feed(
    limit: int = Query(default=50, ge=1, le=500),
    search: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> list[JournalEntryOut]:
```

```python
    return [
        JournalEntryOut(**_journal)
        for _journal in store.list_journal_entries(conn, limit=limit, search=search, tag=tag)
    ]
```

### Step 3.6 — verify GREEN and falsify

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py tests/test_backup.py
```

Create `backend/tools/falsifications/ignore_the_tag_filter.sh`:

```bash
#!/usr/bin/env bash
#
# Break: make the tag filter match prose instead of labels.
#
# The test that must catch it is test_the_tag_filter_finds_tags_and_not_prose: with the
# pattern unquoted, the entry whose *content* says "the coda is hard" matches too.
#
#   ./falsify.sh backend/tools/falsifications/ignore_the_tag_filter.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """    if tag:
        clauses.append("j.tags LIKE ?")
        params.append(f'%"{tag}"%')
"""
assert needle in text, "the tag filter is not where this script expects it"
replacement = """    if tag:
        clauses.append("(j.tags LIKE ? OR j.content LIKE ?)")
        params.extend([f"%{tag}%", f"%{tag}%"])
"""
path.write_text(text.replace(needle, replacement, 1))
PY
```

```bash
chmod +x backend/tools/falsifications/ignore_the_tag_filter.sh
backend/tools/falsify.sh backend/tools/falsifications/ignore_the_tag_filter.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py"
```

---

## Task 4 — focus passages

**Files.** modify `backend/app/repertoire/models.py`, `store.py`, `api.py`,
`backend/tests/test_repertoire.py`; create
`backend/tools/falsifications/forget_the_passage_provenance.sh`.

**Why.** "Bars 12–14 are the problem" has nowhere to live, and the list of what has not been touched
recently is the one thing the app can honestly offer without a score.

**Change Necessity.** Code: the table has no writer, reader or route.

**Impact / Compatibility.** Additive: a new table, three routes, and `PieceDetail.passages`.

### Step 4.1 — the models

In `backend/app/repertoire/models.py`, above `DeleteResult`:

```python
#: Where a passage came from. `loop` means it was seeded from a recording's A/B markers, and
#: `media_id` then names that recording; `manual` means it was typed. The app never converts
#: seconds to bars — there is no score alignment (20-D7) — so seeding records provenance only.
PassageSource = Literal["manual", "loop"]


class PassageOut(BaseModel):
    id: int
    piece_id: int
    start_bar: int
    end_bar: int
    label: str | None = None
    source: PassageSource
    media_id: int | None = None
    created_at: str | None = None
    last_worked_on: str | None = None


class PassageCreate(BaseModel):
    start_bar: int = Field(ge=1, le=10_000)
    end_bar: int = Field(ge=1, le=10_000)
    label: str | None = Field(default=None, max_length=200)
    source: PassageSource = "manual"
    media_id: int | None = None

    @model_validator(mode="after")
    def _ordered(self) -> "PassageCreate":
        if self.end_bar < self.start_bar:
            raise ValueError("end_bar must not be before start_bar")
        return self


class PassageUpdate(BaseModel):
    """PATCH body. Unset fields are left alone; an explicit null clears the column."""

    start_bar: int | None = Field(default=None, ge=1, le=10_000)
    end_bar: int | None = Field(default=None, ge=1, le=10_000)
    label: str | None = Field(default=None, max_length=200)
    #: The date the player says they worked on it, or an explicit null to forget that.
    last_worked_on: str | None = Field(default=None, pattern=DATE_PATTERN)
```

and in `PieceDetail`:

```python
    passages: list[PassageOut] = Field(default_factory=list)
```

`model_validator` must be imported from pydantic.

**Note on `PassageUpdate`'s ordering rule.** `start_bar` and `end_bar` are validated *together* in
the route against the row's current values, exactly as the A/B loop markers are, because "end is not
before start" is a property of the pair rather than of either field.

### Step 4.2 — the store

In `backend/app/repertoire/store.py`, add:

```python
def list_passages(conn: sqlite3.Connection, piece_id: int) -> list[dict[str, Any]]:
    """A piece's focus passages, the least recently worked on first.

    Never-touched passages sort first: "I have not looked at this at all" is a stronger
    reason to be shown something than "I looked at it three weeks ago". Ties break on bar
    number so the order is stable between reads.
    """
    rows = conn.execute(
        """
        SELECT id, piece_id, start_bar, end_bar, label, source, media_id,
               created_at, last_worked_on
        FROM piece_passages
        WHERE piece_id = ?
        ORDER BY (last_worked_on IS NOT NULL), last_worked_on ASC, start_bar ASC, id ASC
        """,
        (piece_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def create_passage(conn: sqlite3.Connection, piece_id: int, fields: dict[str, Any]) -> int:
    cursor = conn.execute(
        """
        INSERT INTO piece_passages
            (piece_id, start_bar, end_bar, label, source, media_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            piece_id,
            fields["start_bar"],
            fields["end_bar"],
            fields.get("label"),
            fields.get("source", "manual"),
            fields.get("media_id"),
        ),
    )
    return int(cursor.lastrowid)


def get_passage(conn: sqlite3.Connection, passage_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, piece_id, start_bar, end_bar, label, source, media_id,"
        " created_at, last_worked_on FROM piece_passages WHERE id = ?",
        (passage_id,),
    ).fetchone()
    return dict(row) if row else None


def update_passage(conn: sqlite3.Connection, passage_id: int, changes: dict[str, Any]) -> int:
    allowed = ("start_bar", "end_bar", "label", "last_worked_on")
    updates = {key: value for key, value in changes.items() if key in allowed}
    if not updates:
        return conn.execute(
            "SELECT COUNT(*) FROM piece_passages WHERE id = ?", (passage_id,)
        ).fetchone()[0]
    assignments = ", ".join(f"{column} = :{column}" for column in updates)
    return conn.execute(
        f"UPDATE piece_passages SET {assignments} WHERE id = :passage_id",
        {**updates, "passage_id": passage_id},
    ).rowcount


def delete_passage(conn: sqlite3.Connection, passage_id: int) -> int:
    return conn.execute("DELETE FROM piece_passages WHERE id = ?", (passage_id,)).rowcount
```

and attach them in `get_piece`, after `piece["media"] = list_media(conn, piece_id=piece_id)`:

```python
    piece["passages"] = list_passages(conn, piece_id)
```

Add a piece-existence check for the route (reuse `piece_exists` ✓, already exists).

### Step 4.3 — the routes

In `backend/app/repertoire/api.py`:

```python
@router.post("/pieces/{piece_id}/passages", response_model=PassageOut, status_code=201)
def create_passage(piece_id: int, body: PassageCreate) -> PassageOut:
    """Add a passage to a piece.

    `source='loop'` with a `media_id` records that the passage was seeded from that
    recording's A/B markers. The bars are still the player's: the app has no score to convert
    seconds into bars with, and inventing one would be a claim it cannot support.
    """
    with db.transaction(settings.db_path) as conn:
        if not store.piece_exists(conn, piece_id):
            raise HTTPException(status_code=404, detail=f"no piece {piece_id}")
        _validate_media(conn, body.media_id)
        passage_id = store.create_passage(conn, piece_id, body.model_dump())
        row = store.get_passage(conn, passage_id)
    assert row is not None
    return PassageOut(**row)


@router.patch("/passages/{passage_id}", response_model=PassageOut)
def update_passage(passage_id: int, body: PassageUpdate) -> PassageOut:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="no fields to change")
    with db.transaction(settings.db_path) as conn:
        current = store.get_passage(conn, passage_id)
        if current is None:
            raise HTTPException(status_code=404, detail=f"no passage {passage_id}")
        start = changes.get("start_bar", current["start_bar"])
        end = changes.get("end_bar", current["end_bar"])
        if end < start:
            raise HTTPException(
                status_code=422, detail=f"end_bar {end} is before start_bar {start}"
            )
        store.update_passage(conn, passage_id, changes)
        row = store.get_passage(conn, passage_id)
    assert row is not None
    return PassageOut(**row)


@router.delete(
    "/passages/{passage_id}",
    response_model=DeleteResult,
    dependencies=[Depends(require_loopback)],
)
def delete_passage(passage_id: int) -> DeleteResult:
    with db.transaction(settings.db_path) as conn:
        deleted = store.delete_passage(conn, passage_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"no passage {passage_id}")
    return DeleteResult(deleted=True)
```

`_validate_media(conn, media_id)` mirrors `_validate_sitting`:

```python
def _validate_media(conn: sqlite3.Connection, media_id: int | None) -> None:
    """A stale id is a 422 rather than a foreign-key failure surfacing as a 500."""
    if media_id is not None and not store.media_exists(conn, media_id):
        raise HTTPException(status_code=422, detail=f"no recording {media_id}")
```

Add `PassageCreate`, `PassageOut`, `PassageUpdate` to the model imports.

### Step 4.4 — the tests

Append to `backend/tests/test_repertoire.py`:

```python
def test_a_passage_can_be_typed_and_worked_on(client) -> None:
    piece = client.post("/api/repertoire/pieces", json={"title": "Etude"}).json()
    created = client.post(
        f"/api/repertoire/pieces/{piece['id']}/passages",
        json={"start_bar": 12, "end_bar": 14, "label": "left-hand leaps"},
    )
    assert created.status_code == 201, created.text
    passage = created.json()
    assert passage["source"] == "manual"
    assert passage["media_id"] is None

    worked = client.patch(
        f"/api/repertoire/passages/{passage['id']}", json={"last_worked_on": "2026-03-07"}
    )
    assert worked.json()["last_worked_on"] == "2026-03-07"

    detail = client.get(f"/api/repertoire/pieces/{piece['id']}").json()
    assert detail["passages"][0]["label"] == "left-hand leaps"


def test_a_passage_seeded_from_a_loop_records_the_recording(client) -> None:
    piece = client.post("/api/repertoire/pieces", json={"title": "Ballade"}).json()
    with db.transaction(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO media (id, piece_id, kind, file_name, loop_start_s, loop_end_s)"
            " VALUES (55, ?, 'recording', 'y.ogg', 12.0, 20.0)",
            (piece["id"],),
        )
    created = client.post(
        f"/api/repertoire/pieces/{piece['id']}/passages",
        json={"start_bar": 9, "end_bar": 11, "source": "loop", "media_id": 55},
    )
    assert created.status_code == 201, created.text
    passage = created.json()
    assert passage["source"] == "loop", "the provenance is recorded, not guessed"
    assert passage["media_id"] == 55

    with db.transaction(settings.db_path) as conn:
        conn.execute("DELETE FROM media WHERE id = 55")
    after = client.get(f"/api/repertoire/pieces/{piece['id']}").json()["passages"][0]
    assert after["media_id"] is None, "deleting the recording leaves the passage"
    assert after["source"] == "loop", "and its provenance is still what it was"


def test_a_passage_whose_end_is_before_its_start_is_refused(client) -> None:
    piece = client.post("/api/repertoire/pieces", json={"title": "Waltz"}).json()
    response = client.post(
        f"/api/repertoire/pieces/{piece['id']}/passages",
        json={"start_bar": 14, "end_bar": 12},
    )
    assert response.status_code == 422


def test_passages_sort_the_never_touched_first(client) -> None:
    piece = client.post("/api/repertoire/pieces", json={"title": "Sonata"}).json()
    worked = client.post(
        f"/api/repertoire/pieces/{piece['id']}/passages",
        json={"start_bar": 1, "end_bar": 4, "label": "worked"},
    ).json()
    client.patch(
        f"/api/repertoire/passages/{worked['id']}", json={"last_worked_on": "2026-03-08"}
    )
    client.post(
        f"/api/repertoire/pieces/{piece['id']}/passages",
        json={"start_bar": 30, "end_bar": 32, "label": "untouched"},
    )
    rows = client.get(f"/api/repertoire/pieces/{piece['id']}").json()["passages"]
    assert [row["label"] for row in rows] == ["untouched", "worked"]
```

### Step 4.5 — verify GREEN and falsify

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py
```

Create `backend/tools/falsifications/forget_the_passage_provenance.sh`:

```bash
#!/usr/bin/env bash
#
# Break: stop recording where a seeded passage came from.
#
# The test that must catch it is test_a_passage_seeded_from_a_loop_records_the_recording.
#
#   ./falsify.sh backend/tools/falsifications/forget_the_passage_provenance.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/store.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '            fields.get("source", "manual"),'
assert needle in text, "the provenance is not where this script expects it"
path.write_text(text.replace(needle, '            "manual",', 1))
PY
```

---

## Task 5 — the read the sorts need

**Files.** modify `backend/app/practice/api.py`, `backend/tests/test_practice_api.py`.

**Why.** "Least time invested" and "last played" are practice numbers, and the only route that
carries them today is the analytics summary, which computes a year of calendar, the recent sittings
and the neglected list as well.

**Change Necessity.** Code: no lightweight per-piece practice read exists.

**Impact / Compatibility.** One new read route; `by_piece()` is reused unchanged, so the numbers are
the same ones the Log shows.

### Step 5.1 — write the failing test

Append to `backend/tests/test_practice_api.py`:

```python
def test_the_piece_practice_read_agrees_with_the_dashboard(client, conn) -> None:
    """Two reads of one number must be one number.

    The library sorts by this, and the Log draws it; if they disagree, one of them is lying
    about how much a piece has cost.
    """
    sitting = recent_sitting(client, FAST_OFFSETS)
    piece_id = seed_piece(conn, "Sorted Etude")
    client.patch(
        f"/api/practice/segments/{segment_of(client, sitting)['id']}",
        json={"piece_id": piece_id},
    )

    listed = client.get("/api/practice/pieces?days=365").json()
    from_dashboard = client.get("/api/practice/analytics/summary?days=365").json()["by_piece"]

    assert listed == from_dashboard, "the two reads agree, field for field"
    assert listed and listed[0]["title"] == "Sorted Etude"
```

### Step 5.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py -k piece_practice_read
```

Expected: 404 on `/api/practice/pieces`.

### Step 5.3 — the route

In `backend/app/practice/api.py`, in the analytics block:

```python
@router.get("/pieces", response_model=list[PiecePractice])
def piece_practice_list(
    days: int = Query(default=365, ge=1, le=3650),
    conn: sqlite3.Connection = Depends(get_conn),
) -> list[PiecePractice]:
    """Per-piece logged practice, for callers that want only this.

    `days` is explicit rather than implied: the library's "least time invested" sort asks for
    the widest window it can, and a caller that wanted the Log's default would otherwise get
    a year of it by accident. The numbers come from the same `by_piece` the dashboard uses,
    so the two can never disagree.
    """
    return store.by_piece(conn, days)
```

Add `PiecePractice` to the imports from `.models`.

### Step 5.4 — verify GREEN

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py
```

---

## Task 6 — the library and the journal

**Files.** create `frontend/src/components/PassageList.svelte`; modify
`frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`,
`frontend/src/components/RepertoireView.svelte`.

**Why.** None of the above is reachable without a control.

**Change Necessity.** Code.

**Impact / Compatibility.** Additive UI. The one behaviour a player will notice is the saved view:
the filters and the sort are remembered across reloads.

### Step 6.1 — types and client

`frontend/src/lib/types.ts`: add `tags: string[]; difficulty: number | null; fluency: number | null;
media_id: number | null;` to `JournalEntry`, and `tags?: string[]; difficulty?: number | null;
fluency?: number | null; media_id?: number | null;` to `JournalInput` — the create/update body
carries them too, or the server never sees a tag. Then add

```ts
/** Where a focus passage came from. `loop` means a recording's A/B markers seeded it. */
export type PassageSource = 'manual' | 'loop';

export interface Passage {
  id: number;
  piece_id: number;
  start_bar: number;
  end_bar: number;
  label: string | null;
  source: PassageSource;
  media_id: number | null;
  created_at: string | null;
  last_worked_on: string | null;
}
```

and `passages: Passage[];` on `PieceDetail`.

`frontend/src/lib/api.ts`, in the `repertoire` block:

```ts
    /** Add a passage. `source: 'loop'` records that a recording's markers seeded it. */
    createPassage: (
      pieceId: number,
      body: {
        start_bar: number;
        end_bar: number;
        label?: string | null;
        source?: PassageSource;
        media_id?: number | null;
      },
    ) =>
      request<Passage>(`/repertoire/pieces/${pieceId}/passages`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),

    /** PATCH semantics: an unset field is left alone, an explicit null clears it. */
    updatePassage: (
      passageId: number,
      body: { start_bar?: number; end_bar?: number; label?: string | null; last_worked_on?: string | null },
    ) =>
      request<Passage>(`/repertoire/passages/${passageId}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),

    deletePassage: (passageId: number) =>
      request<DeleteResult>(`/repertoire/passages/${passageId}`, { method: 'DELETE' }),
```

and the `tag` parameter on both journal reads:

```ts
    journal: (filters: { limit?: number; search?: string; tag?: string } = {}) => {
      const query = new URLSearchParams();
      if (filters.limit) query.set('limit', String(filters.limit));
      if (filters.search) query.set('search', filters.search);
      if (filters.tag) query.set('tag', filters.tag);
      return request<JournalEntry[]>(`/repertoire/journal${query.size ? `?${query}` : ''}`);
    },
```

`frontend/src/lib/api.ts` also gains the practice read:

```ts
    /** Per-piece logged practice, for the library's sorts. */
    piecePractice: (days = 365) => request<PiecePractice[]>(`/practice/pieces?days=${days}`),
```

### Step 6.2 — the passages panel

Create `frontend/src/components/PassageList.svelte`:

```svelte
<script lang="ts">
  /**
   * The stretches of a piece worth returning to.
   *
   * The app cannot see a score — there is no alignment, by decision 20-D7 — so the bar
   * numbers are the player's own and *nothing here is inferred*. "Worked on it" is a button,
   * not a detection, and a passage seeded from a recording's A/B loop records which loop it
   * came from while the bars are still typed.
   */
  import { localDate } from '../lib/clock';
  import type { Passage, Recording } from '../lib/types';

  interface Props {
    passages: Passage[];
    recordings: Recording[];
    busy: boolean;
    oncreate: (body: {
      start_bar: number;
      end_bar: number;
      label: string | null;
      source: 'manual' | 'loop';
      media_id: number | null;
    }) => void;
    onworked: (passageId: number) => void;
    ondelete: (passageId: number) => void;
  }

  let { passages, recordings, busy, oncreate, onworked, ondelete }: Props = $props();

  let startBar = $state(1);
  let endBar = $state(4);
  let label = $state('');
  /** Which recording's loop seeded this, or none. */
  let mediaId = $state<number | null>(null);
  let confirmingId = $state<number | null>(null);

  const looped = $derived(recordings.filter((row) => row.loop_start_s !== null));

  function submit(): void {
    if (endBar < startBar) return;
    oncreate({
      start_bar: startBar,
      end_bar: endBar,
      label: label.trim() || null,
      source: mediaId === null ? 'manual' : 'loop',
      media_id: mediaId,
    });
    label = '';
    mediaId = null;
  }

  function staleness(passage: Passage): string {
    if (passage.last_worked_on === null) return 'not worked on yet';
    return `last worked on ${passage.last_worked_on}`;
  }
</script>

<section class="card" data-passages={passages.length}>
  <h3>Passages to work on</h3>
  {#if passages.length === 0}
    <p class="muted small">
      Nothing marked. A passage is a bar range you want to come back to — the app cannot find
      them for you, because it cannot see your score.
    </p>
  {:else}
    <ul class="passages">
      {#each passages as passage (passage.id)}
        <li data-passage={passage.id}>
          <span class="mono">bars {passage.start_bar}–{passage.end_bar}</span>
          {#if passage.label}<span>{passage.label}</span>{/if}
          <span class="muted small">{staleness(passage)}</span>
          {#if passage.source === 'loop'}
            <span class="pill" title="Seeded from a recording's A/B markers">
              from a loop
            </span>
          {/if}
          <button class="ghost tiny" disabled={busy} onclick={() => onworked(passage.id)}>
            Worked on it
          </button>
          {#if confirmingId === passage.id}
            <button class="danger tiny" disabled={busy} onclick={() => ondelete(passage.id)}>
              Confirm delete
            </button>
            <button class="ghost tiny" onclick={() => (confirmingId = null)}>Cancel</button>
          {:else}
            <button class="ghost tiny" onclick={() => (confirmingId = passage.id)}>Delete</button>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}

  <div class="row wrap">
    <label class="muted small" for="passage-start">Bars</label>
    <input id="passage-start" type="number" min="1" bind:value={startBar} aria-label="First bar" />
    <span class="muted small">to</span>
    <input type="number" min="1" bind:value={endBar} aria-label="Last bar" />
    <input type="text" bind:value={label} placeholder="what is hard about it" aria-label="Note" />
    {#if looped.length > 0}
      <select bind:value={mediaId} aria-label="Seeded from a recording">
        <option value={null}>not from a recording</option>
        {#each looped as recording (recording.id)}
          <option value={recording.id}>
            {recording.title ?? recording.original_name ?? `recording ${recording.id}`} · loop
          </option>
        {/each}
      </select>
    {/if}
    <button class="primary" disabled={busy || endBar < startBar} onclick={submit}>
      Add passage
    </button>
  </div>
</section>

<style>
  .passages {
    list-style: none;
    margin: 0 0 0.6rem;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }

  .passages li {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
</style>
```

`localDate` is imported but unused in the snippet above — the "worked on it" date is computed in the
parent, where the API call lives. Remove the import when writing the file.

### Step 6.3 — the journal forms, the tag filter and the take link

In `frontend/src/components/RepertoireView.svelte`:

state, beside `journalMinutes` (`:43`) and `editMinutes` (`:49`):

```ts
  let journalTags = $state('');
  let journalDifficulty = $state<number | null>(null);
  let journalFluency = $state<number | null>(null);
  let editTags = $state('');
  let editDifficulty = $state<number | null>(null);
  let editFluency = $state<number | null>(null);
  let feedTag = $state('');
```

helpers, near `localDate()`:

```ts
  /** "coda, slow" → ["coda", "slow"]. The server trims and de-duplicates too. */
  function parseTags(value: string): string[] {
    return value.split(',').map((tag) => tag.trim()).filter((tag) => tag.length > 0);
  }
```

`saveJournal` (`:203-220`) gains the three fields:

```ts
        tags: parseTags(journalTags),
        difficulty: journalDifficulty,
        fluency: journalFluency,
```

and clears them after a successful save.

The entry-editing draft (the block that populates `editContent`, `editDate`, `editMinutes`) gains
`editTags = entry.tags.join(', '); editDifficulty = entry.difficulty; editFluency = entry.fluency;`,
and the save call for an edit gains `tags: parseTags(editTags), difficulty: editDifficulty,
fluency: editFluency`.

The create form and the edit form each gain, beside the minutes input:

```svelte
      <input
        type="text"
        bind:value={journalTags}
        placeholder="tags, comma separated"
        aria-label="Tags for this entry"
      />
      <select bind:value={journalDifficulty} aria-label="How hard it felt">
        <option value={null}>difficulty —</option>
        {#each [1, 2, 3, 4, 5] as value (value)}
          <option value={value}>{value}</option>
        {/each}
      </select>
      <select bind:value={journalFluency} aria-label="How well it went">
        <option value={null}>fluency —</option>
        {#each [1, 2, 3, 4, 5] as value (value)}
          <option value={value}>{value}</option>
        {/each}
      </select>
```

Each rendered entry shows what it carries — after the content, in the entry's row:

```svelte
        {#each entry.tags as tag (tag)}
          <button
            class="pill"
            data-tag={tag}
            title="Filter the journal by this tag"
            onclick={() => (feedTag = tag)}
          >
            {tag}
          </button>
        {/each}
        {#if entry.difficulty !== null}
          <span class="pill mono" data-difficulty={entry.difficulty}>hard {entry.difficulty}/5</span>
        {/if}
        {#if entry.fluency !== null}
          <span class="pill mono" data-fluency={entry.fluency}>went {entry.fluency}/5</span>
        {/if}
        {#if entry.media_id !== null}
          <span class="pill" data-journal-take={entry.media_id}>written about a take</span>
        {/if}
```

and the recordings list gains the take link. In the `{#each recordings …}` block (`:929-965`), beside
the `RecordingPlayer`:

```svelte
                <button
                  class="ghost tiny"
                  data-write-about-take={recording.id}
                  title="Write a journal entry about this recording"
                  onclick={() => {
                    journalDate = localDate();
                    journalMeasure = null;
                    journalSitting = null;
                    journalTake = recording.id;
                    void openScoreId; /* no-op: keeps the row's intent obvious */
                  }}
                >
                  Write about this take
                </button>
```

That handler needs `journalTake` state (`let journalTake = $state<number | null>(null);`), cleared on
save like `journalSitting`, and passed to the create call as `media_id: journalTake`.

**Simplify this rather than copy it literally.** `journalTake` is the only new state the take link
needs; the handler should set the date and the take and scroll the journal form into view. The
`void openScoreId` line above is a placeholder for that scroll and must be replaced with

```ts
                    journalForm?.scrollIntoView({ behavior: 'smooth', block: 'center' });
```

with `let journalForm = $state<HTMLElement | null>(null);` and `bind:this={journalForm}` on the
journal form's card.

The feed's tag filter — the feed search already debounces (`:59-65`); extend it to pass both:

```ts
      feedEntries = await api.repertoire.journal({
        limit: 40,
        search: term || undefined,
        tag: feedTag || undefined,
      });
```

with a control beside the feed search:

```svelte
      <input
        type="text"
        bind:value={feedTag}
        placeholder="tag"
        aria-label="Filter the journal by tag"
      />
```

### Step 6.4 — sorts, the saved view and bulk edits

State, near the existing filter state:

```ts
  type SortKey = 'title' | 'composer' | 'last_played' | 'least_time' | 'most_time';
  let sort = $state<SortKey>('title');
  /** Per-piece logged minutes, all-time-capable, for the two effort sorts. */
  let practiceByPiece = $state<PiecePractice[]>([]);
  /** Multi-select for bulk edits. */
  let selected = $state<Set<number>>(new Set());
  let bulkStatus = $state<'active' | 'paused' | 'completed'>('paused');
```

loading the practice numbers with the library.

**The rule for a piece the read does not mention.** `by_piece` inner-joins `segments`, so a piece
with no labelled practice in the window has **no row at all** rather than a zero. Absence is
therefore read as *never played, zero minutes*, which is what makes it sort first under "least time
invested" and "last played" — the strongest form of both answers, and the same distinction
`neglected()` already draws:

```ts
  async function loadPracticeByPiece(): Promise<void> {
    // The widest window the read allows, so "least time invested" means what it says.
    practiceByPiece = await api.practice.piecePractice(3650).catch(() => []);
  }
```

call it beside the existing `loadPieces()` on mount.

the sort itself, applied to the grouped rows before rendering:

```ts
  const practiceIndex = $derived(
    new Map(practiceByPiece.map((row) => [row.piece_id, row])),
  );

  function sorted(rows: PieceSummary[]): PieceSummary[] {
    const copy = [...rows];
    if (sort === 'title') return copy.sort((a, b) => a.title.localeCompare(b.title));
    if (sort === 'composer') {
      return copy.sort((a, b) => (a.composer_name ?? '').localeCompare(b.composer_name ?? ''));
    }
    if (sort === 'last_played') {
      return copy.sort((a, b) => {
        const left = practiceIndex.get(a.id)?.last_played ?? '';
        const right = practiceIndex.get(b.id)?.last_played ?? '';
        // Never played sorts first: it is the strongest form of "not recently".
        return left === right ? a.title.localeCompare(b.title) : left.localeCompare(right);
      });
    }
    const minutes = (id: number) => practiceIndex.get(id)?.minutes ?? 0;
    return copy.sort((a, b) =>
      sort === 'least_time'
        ? minutes(a.id) - minutes(b.id) || a.title.localeCompare(b.title)
        : minutes(b.id) - minutes(a.id) || a.title.localeCompare(b.title),
    );
  }
```

the control, in the `.filters` block (`:524-545`):

```svelte
      <select bind:value={sort} aria-label="Sort the library">
        <option value="title">Title</option>
        <option value="composer">Composer</option>
        <option value="last_played">Last played</option>
        <option value="least_time">Least time invested</option>
        <option value="most_time">Most time invested</option>
      </select>
```

the row checkbox and the bulk bar:

```svelte
            <input
              type="checkbox"
              checked={selected.has(piece.id)}
              aria-label={`Select ${piece.title}`}
              onclick={(event) => {
                event.stopPropagation();
                const next = new Set(selected);
                if (next.has(piece.id)) next.delete(piece.id);
                else next.add(piece.id);
                selected = next;
              }}
            />
```

```svelte
  {#if selected.size > 0}
    <div class="row wrap" data-bulk={selected.size}>
      <span class="muted small">{selected.size} selected</span>
      <select bind:value={bulkStatus} aria-label="Status for the selected pieces">
        <option value="active">Active</option>
        <option value="paused">Paused</option>
        <option value="completed">Completed</option>
      </select>
      <button
        class="primary"
        disabled={busy}
        onclick={() => void applyBulk()}
      >
        Set status
      </button>
      <button class="ghost" onclick={() => (selected = new Set())}>Clear</button>
    </div>
  {/if}
```

```ts
  /**
   * Bulk status, one request per piece.
   *
   * Sequential rather than parallel on purpose: this is a single-user library of tens of
   * pieces, and a partial failure is easier to reason about when the requests are ordered.
   */
  async function applyBulk(): Promise<void> {
    busy = true;
    try {
      for (const id of selected) {
        await api.repertoire.updatePiece(id, { status: bulkStatus });
      }
      selected = new Set();
      await loadPieces();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = false;
    }
  }
```

**The saved view** — the filters and the sort persist, which is the "saved filters" the spec asks for
in the form a single-player library actually needs:

```ts
  const VIEW_STORAGE_KEY = 'srt.repertoire.view';

  function readView(): { status: string; composer: string; grouping: string; sort: string } {
    try {
      const raw = localStorage.getItem(VIEW_STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      return {
        status: typeof parsed.status === 'string' ? parsed.status : '',
        composer: typeof parsed.composer === 'string' ? parsed.composer : '',
        grouping: typeof parsed.grouping === 'string' ? parsed.grouping : 'composer',
        sort: typeof parsed.sort === 'string' ? parsed.sort : 'title',
      };
    } catch {
      return { status: '', composer: '', grouping: 'composer', sort: 'title' };
    }
  }
```

initialise the four fields from `readView()` and add an effect that writes them back on change
(`localStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify({...}))` inside a `try`).

### Step 6.5 — mount the panel

Import `PassageList` and render it in the piece detail beside the journal, after the media section:

```svelte
        <PassageList
          passages={detail.passages}
          {recordings}
          {busy}
          oncreate={(body) => void addPassage(body)}
          onworked={(id) => void markWorkedOn(id)}
          ondelete={(id) => void removePassage(id)}
        />
```

with, beside the other write helpers:

```ts
  async function addPassage(body: {
    start_bar: number;
    end_bar: number;
    label: string | null;
    source: 'manual' | 'loop';
    media_id: number | null;
  }): Promise<void> {
    if (!detail) return;
    try {
      await api.repertoire.createPassage(detail.id, body);
      await afterWrite(detail.id);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  async function markWorkedOn(passageId: number): Promise<void> {
    if (!detail) return;
    try {
      await api.repertoire.updatePassage(passageId, { last_worked_on: localDate() });
      await afterWrite(detail.id);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  async function removePassage(passageId: number): Promise<void> {
    if (!detail) return;
    try {
      await api.repertoire.deletePassage(passageId);
      await afterWrite(detail.id);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }
```

### Step 6.6 — verify

```bash
cd frontend && npm test && npm run check && npm run build
```

---

## Task 7 — the browser proves it, and the docs record it

**Files.** modify `backend/tools/e2e_browser.py`, `README.md`, `AGENT-LOG.md`,
`docs/ECOSYSTEM.md`.

### Step 7.1 — the assertions

In `scenario_repertoire`, after the journal assertions, add:

```python
    # --- tags, ratings and a take: the journal is filterable and comparable ---
    page.fill('[aria-label="Tags for this entry"]', "coda, slow")
    page.select_option('[aria-label="How hard it felt"]', "4")
    with page.expect_response(lambda r: "/journal" in r.url and r.request.method == "POST"):
        page.click("[data-journal-add]")
    page.wait_for_timeout(500)
    check(
        page.locator("[data-tag='coda']").count() >= 1,
        "the entry carries the tag it was given",
    )
    check(
        page.locator("[data-difficulty='4']").count() >= 1,
        "and the difficulty it was given",
    )

    with page.expect_response(lambda r: "/api/repertoire/journal?tag=" in r.url):
        page.fill('[aria-label="Filter the journal by tag"]', "coda")
    page.wait_for_timeout(600)
    check(
        page.locator("[data-tag='coda']").count() >= 1,
        "and the feed can be filtered by it",
    )

    # --- a passage, and its provenance ---
    page.fill('[aria-label="First bar"]', "12")
    page.fill('[aria-label="Last bar"]', "14")
    page.fill('[aria-label="Note"]', "left-hand leaps")
    with page.expect_response(lambda r: r.url.endswith("/passages")):
        click_button(page, "Add passage")
    page.wait_for_selector("[data-passages]", timeout=10_000)
    check(
        "bars 12–14" in page.inner_text("[data-passages]"),
        "the passage is listed with the bars the player typed",
    )
    with page.expect_response(lambda r: "/passages/" in r.url):
        click_button(page, "Worked on it")
    page.wait_for_timeout(500)
    check(
        "not worked on yet" not in page.inner_text("[data-passages]"),
        "and marking it worked on stops it reading as untouched",
    )

    # --- a paused piece is not reported as neglected ---
    api(f"/api/repertoire/pieces/{target['id']}", "PATCH", {"status": "paused"})
    click_button(page, "Log")
    page.wait_for_selector("text=Neglected", timeout=20_000)
    check(
        target["title"] not in page.inner_text(".review"),
        "a paused piece is left out of the neglected list",
    )
```

### Step 7.2 — run the scenarios

```bash
cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh repertoire
```

Expected: every assertion `ok`, ending `All browser scenarios passed.` Then the two remaining
falsifications, which need the browser and so must rebuild:

```bash
backend/tools/falsify.sh backend/tools/falsifications/ignore_the_tag_filter.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py"
backend/tools/falsify.sh backend/tools/falsifications/forget_the_passage_provenance.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py"
backend/tools/falsify.sh backend/tools/falsifications/let_paused_pieces_nag.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py"
```

### Step 7.3 — docs

`README.md`, in the Repertoire section, after the journal paragraph:

```markdown
Journal entries carry **tags** and two ratings — how hard it felt and how well it went — and the
journal feed can be filtered by a tag. A tag matches the label you wrote, never a word that happens to
appear in the prose. An entry can also point at the **recording** it is about (*Write about this
take*), and deleting the recording leaves the prose alone.

**Passages to work on** live on the piece: a bar range and a note ("bars 12–14, the left-hand
leaps"), with *Worked on it* stamping the date so the untouched ones stay at the top. The app cannot
find these for you — it cannot see your score — but a passage can record that it was seeded from a
recording's A/B loop. The library can be sorted by **last played**, **least time invested** or
**most time invested**, several pieces can be selected and re-statused at once, and the filters and
sort you choose are remembered.

A piece you set to **paused** stops appearing in *Neglected*: the status is your decision, and the
list was arguing with it.
```

`AGENT-LOG.md` gains a landed entry following its § *Entry format*, naming: the four columns and the
new table (and that neither needs a backup edit), the `neglected` behaviour change, the provenance
rule for a seeded passage, the falsifications, and the impact on the other side.

`docs/ECOSYSTEM.md`: the Phase 20 row becomes `**20a–20d landed; 20e planned.**`, the 20d heading is
marked `— landed` with a pointer to this plan, and the § 4 data-model inventory gains
`piece_passages` — that block names the repertoire tables and is the one place a new table is listed
by hand:

```
repertoire     composers, pieces, piece_journal, piece_passages, media
```

### Step 7.4 — the full tier and the commit

```bash
./check.sh --full
git add -A backend frontend docs README.md AGENT-LOG.md
git commit -m "Phase 20d: journal and library depth"
```

---

## Risks

| Risk | Treatment |
| --- | --- |
| The app appears to know a score it cannot see | `source` and `media_id` record *provenance*; the bars are typed by the player and `last_worked_on` is only ever set by a button. The panel says in its own empty state that the app cannot find passages for you, and 20-D7 is the decision behind it |
| A tag filter silently matches prose | The stored array is written with `db.json_dump`, whose separators are compact, so `%"coda"%` cannot match the word in a sentence. `test_the_tag_filter_finds_tags_and_not_prose` asserts the negative, and the break script widens the filter to include content so the assertion is seen to fail |
| A corrupt tag array reads as "no tags" | `_journal_row` goes through `db.json_load`, which raises (`CorruptJSON`) rather than degrading — Slice 1's T9 decision |
| The sort and the dashboard disagree about how much a piece has cost | Both read `by_piece`; `test_the_piece_practice_read_agrees_with_the_dashboard` asserts the two responses are equal field for field |
| The `paused` change hides something the player wanted to see | It hides exactly one status, which the player set themselves, and the piece is still in the library with an explicit filter for it. The change is named in the README and in the log entry |
| `RepertoireView` grows past reviewable size | The passages panel is extracted to `PassageList.svelte`; if the component passes ~1,600 lines, the next addition extracts the library list rather than adding a fifth section |

## Retirement

- **Nothing is retired.** `neglected`'s predicate narrows; the journal and the piece detail gain
  fields; no route changes shape.
- **`piece_passages`** is one table with one index and one panel. If passages are never returned to,
  the table, the three routes and `PassageList.svelte` go together, and the only residue is one line
  in `get_piece`.
- **The saved view** is one localStorage key. Clearing it restores the defaults with no migration.

## ADR / baseline-sync signals

- **20-D7** is implemented as written, and this plan adds the mechanical reason: seeding a passage
  from a loop records the loop, because converting seconds to bars would need the alignment that
  decision refuses.
- The `media_id` link is a deliberate mirror of `sitting_id`, including `ON DELETE SET NULL`, so the
  journal has one rule for "the thing this was written about" rather than two.
- On completion the baseline-sync question is: *does anything in the repertoire domain now depend on
  a score the app does not have?* The answer must be no, and `PassageOut.source` is the evidence.

---

```text
Execution Readiness View:
- Intent Lock: a filterable, comparable journal; a place for problem bars with honest provenance;
  a neglected list that honours "paused"; and library sorts and bulk edits
- Scope Fence: in — four journal columns, the passages table and panel, three repertoire routes, one
  practice read, the tag filter, sorts, the saved view, bulk status, one browser scenario extension,
  docs. Out — score alignment, bar inference, a tag table, a named-preset manager, reordering
  pieces, and anything in 20e
- Baseline Lock: ECOSYSTEM.md § 20d + 20-D7 and the corrected schema note; TEST-STRATEGY.md §8; the
  re-read gate; a clean tree before every falsification
- Approved Behavior: 20d's five acceptance bullets
- Owner / Contract Constraints: the repertoire domain owns the journal and the passages; the
  practice domain owns `by_piece` and exposes it through one read; the sort composition lives in one
  component
- Compatibility Boundary: additive columns, one new table, one new read route, five additive response
  fields; no existing route changes shape; SCHEMA_VERSION 3 -> 4; BACKUP_VERSION unchanged
- Retirement Boundary: nothing retired; the passages table and panel retire together
- Task Batches: 1 schema, 2 the neglected fix, 3 journal tags and ratings, 4 passages, 5 the sort
  read, 6 the UI, 7 browser + docs + commit
- Test Obligations: two migration tests, five journal tests, four passage tests, one agreement
  assertion, four browser assertions, four committed break scripts
- Review Gates: after Task 5 (the server surface is complete) and after Task 7 (--full green)
- Drift / Rewind Rules: if a step needs the app to convert seconds to bars, to infer a tag, or to
  make `neglected` narrower than `active`, stop and return to the spec
- Evidence Required Before Completion: ./check.sh --full passing; all four falsifications reported as
  "falsified"; the agreement assertion green; the AGENT-LOG entry appended
- Advisory Boundary: method-pack execution guidance only; not GateDecision, PolicySnapshot, or
  completion authority
```

```text
Execution Route:
- Decision: inline
- Evidence: seven tasks, sequential on two backend files and one component, with the browser check at
  the end; nothing here parallelises usefully
- Fallback: none needed
- User confirmation required: no
```

**Landed.** `PLAN-PHASE20E.md` (audio takes) also landed, completing Phase 20; see `ECOSYSTEM.md`
§ *Phase 20*.
