# Plan — Phase 20e: audio takes

**Parent spec:** [`ECOSYSTEM.md`](./ECOSYSTEM.md) § *Phase 20* § *20e — audio takes (D1, D2, D3)*,
with decisions 20-D4 and 20e-D1…D8 below. That section owns what and why; this document owns the how.

**Status:** planned.

**Goal.** Record the piano through the machine the app already runs on, at a quality that is honest
about being a convenience rather than an archive, attach each take to the segment it came from, and
make two takes comparable by ear — including at half speed.

**Architecture.** The capture client is a sibling of the existing note capture client: one
`MediaRecorder` per chunk, cut on the server's own segment rule, uploaded through the route that
already exists for recordings. A take lands as an **ordinary media row**, so the content-hashed
storage, the ffmpeg probe and transcode, the waveform and the A/B loop all apply unchanged. The one
thing the row learns is where it came from: `source`, `sitting_id`, `segment_id` and the epoch it
started at.

**Tech stack.** `MediaRecorder` + `getUserMedia` in Chromium; the existing ffmpeg/Opus pipeline; the
existing `<audio>` player; Python/SQLite for the attachment.

**Baseline / authority refs.**

- `docs/ECOSYSTEM.md` § Phase 20 § 20e, plus **20-D4** (a take is not an archive) and 20e-D1…D8.
- `docs/DEPLOYMENT.md` and `deploy/README.md` (the kiosk policy; the plan records what must be
  documented when this lands).
- `docs/PLAN-PHASE20A.md` (migration and falsification mechanics), `PLAN-PHASE20B.md` (the
  `sounding`/`gas` pattern for frontend units and the browser tier).
- `AGENT-LOG.md` § *Rules*.

**Re-read gate.** Written against the tree at `507a387`. Before Task 1:

```bash
cd /home/marco_normal/tmp/SighRTracker
grep -n "def status" -A 12 backend/app/practice/api.py
grep -n "def create_media" -A 24 backend/app/repertoire/store.py
grep -n "def _stage_upload" backend/app/repertoire/api.py
grep -n "FLUSH_INTERVAL_MS" frontend/src/lib/capture.ts
grep -n "playwright.chromium.launch" -A 10 backend/tools/e2e_browser.py
git status --porcelain   # must print nothing before any falsification
```

**Compatibility boundary.** Four additive nullable `media` columns, one new read field
(`PracticeStatus.segment_gap_s`), one new route and one new form field. `BACKUP_VERSION` unchanged — the
table list is derived, and the media rows ride along as they always have. `SCHEMA_VERSION` 3 → 4, so
an older build refuses a database with the new columns rather than misreading it. **No existing route
changes shape, and the recording upload route is untouched**: a captured take is uploaded through the
new route only because a take has no piece to name yet.

**Decision 20e-D1.** Capture follows the **standing capture switch**, in the same spirit as MIDI
capture, and it is mono Opus at about 32 kbps (`audio/webm;codecs=opus`, `audioBitsPerSecond:
32000`) — roughly **14 MB per hour**. The piano's own pen-drive recording remains the archive; this
is the layer that makes a take shareable without finding a memory stick, which is the user's own
stated reason for wanting it. Quality is explicitly **not** an acceptance criterion, and that is what
makes a standing switch affordable.

**Decision 20e-D2.** The client never forks the segment rule. The audio must be cut where the notes
are cut or the two would disagree about where a segment ends — so **`PracticeStatus` gains
`segment_gap_s`** and the cutter reads it. Nothing about the server's timing is duplicated in the
client, and there is no local fallback constant: if the server does not report its gap, arming audio
is refused with a reason rather than cutting takes in the wrong place.

`PracticeStatus` rather than `HostInfo` or `ProfileOut`, both of which were considered.
`HostInfo`'s own docstring scopes it to "what this machine can see" — `sequencer`, `clients`, the
address — and a logging timing is not that. `ProfileOut` does expose settings (`default_rating`,
`pass_threshold`, `exercise_bars`), but they are the *scoring and exercise* settings, and putting a
logging timing there would blur what that payload is for. The segment gap is the practice domain's
own rule, and `PracticeStatus` is the practice domain's own status.

**Decision 20e-D3.** A take is attached to its segment **by epoch range, server-side**. Segments do
not exist until the server makes them, so the client cannot name one; it sends the absolute epoch the
chunk started at, exactly as a note batch does, and the server resolves the sitting and the
overlapping segment. When the sitting is still open there are no segments yet, so the sitting is
attached and `segment_id` stays NULL — and the next take uploaded for that sitting resolves the ones
still missing, so nothing depends on a background job.

**Decision 20e-D5 (ownership).** The **repertoire** domain keeps writing the `media` table; the new
route lives on the repertoire router and *reads* practice tables read-only. That is the same
arrangement `sitting_exists` already records ("the one place the repertoire domain looks at a
practice table, and it is here because the journal now points at the sitting"). The practice domain
never writes `media`, and the repertoire domain never writes `segments`.

```text
TDD Route:
- Mode: auto
- Decision: strict
- Strict authority: docs/TEST-STRATEGY.md §8, the standing rule
- Strict signals: persistence (four columns and a shape the frozen test pins), a public contract (one
  new route and one new response field), a behaviour change (a take attached to a segment), and a new
  producer/consumer pair (the cutter and the server's rule)
- Light eligibility: not applicable
- Test posture: strict RED first for the schema, the attachment and the cutter; the browser assertion
  is watched to fail with a break applied
- Verification: ./check.sh --fast after every task; ./check.sh --full before the slice is called done
```

```text
Requirement Ready Check:
- Requirement source refs: docs/ECOSYSTEM.md § Phase 20 § 20e (approved with the phase), and the
  user's own framing of the purpose: "quick audio sharing", quality not a gate
- Goals and scope refs: the same section's Problem/Design
- User / scenario refs: a player who played something worth sending someone; a player comparing this
  week's take with last month's; a player who wants the hard bars at half speed
- Requirement item refs: capture, attachment, the takes view, the playback rate, the permission, the
  storage report
- Acceptance / verification criteria refs: 20e's six acceptance bullets
- Open blocker questions: none
- Decision: ready
```

```text
Change Necessity:
- User-visible need: every recording in the library arrived by hand, and the MIDI log cannot be sent
  to anybody
- No-change / non-code option: insufficient — a browser cannot record audio through configuration,
  and nothing today links audio to a segment
- Why code change is necessary: there is no `MediaRecorder` or `getUserMedia` call anywhere in
  `frontend/src`, no route that accepts a take without a piece, and no column that says where a take
  came from
- Minimum change boundary: four `media` columns, one `PracticeStatus` field, one repertoire route, one
  capture client with a pure cutter, the takes UI and one rate control, tests, falsifications, docs
- Decision: code-change
```

```text
Existence Check:
- Proposed new surface: `media.source`/`sitting_id`/`segment_id`/`captured_start_ms`;
  `PracticeStatus.segment_gap_s`; `POST /api/repertoire/takes`; `frontend/src/lib/audioCapture.ts`;
  `frontend/src/lib/audioCut.ts`; `frontend/src/components/TakeList.svelte`
- Existing owner / reuse candidate: `repertoire/media_pipeline.py` already probes, hashes,
  transcodes and stores a recording; the upload route and `_stage_upload` already enforce the size cap
  in one place; `CaptureClient` is the standing-switch precedent; `RecordingPlayer` already owns an
  `<audio>` element with a loop; `media` already has a nullable `piece_id`
- Why existing surface is insufficient: the upload route is keyed by `piece_id` and a take has no
  piece until its segment is labelled; the existing pedal/note streams carry no audio; nothing
  reports the segment gap to the client
- Creation proof: 20e's acceptance bullets cannot be met otherwise, and each addition is one column,
  one field, one route or one module beside an existing owner
- Entropy / retirement impact: no new table, no backup change; the cutter is pure and the capture
  client is one module, so removing the feature is deleting two files, one route and one panel. If
  captured audio is never listened to, `source='captured'` is what makes it findable for deletion
- Decision: add-with-proof for the route, the modules and the columns; reuse-existing for the
  pipeline, the player and the standing-switch pattern
```

```text
Architecture Integrity Lens:
- Invariant: the repertoire domain is the only writer of `media`; the practice domain is the only
  writer of `segments`; a take never claims to know a piece the segment does not have; recorded audio
  is never the archive and is never pruned behind the player's back
- Canonical owner / contract: `media_pipeline` stores bytes and `repertoire/store.py` catalogues
  them; the new route reads `segments` read-only for attachment; the client's only job is to cut on
  the server's rule and upload
- Responsibility overlap: none added — the new route calls the same `_stage_upload` and the same
  `store_recording` as the recording upload, so the size cap and the hashing cannot diverge
- Higher-level simplification: a take is a media row, so the waveform, the A/B loop, the library
  listing and the backup all apply with no new concept
- Retirement / falsifier: `source` is one column; deleting the feature leaves captured rows
  identifiable and deletable, and `HANDSFREE`-style coupling is avoided — 20b's pedal action gains
  the arm/stop call, and removing it leaves the button path
- Verdict: proceed
```

```text
Plan-Time Complexity Check:
- Target files: backend/app/repertoire/{store,api,schema,models}.py, frontend/src/lib/{capture,state.svelte,types,api}.ts, frontend/src/components/{DeviceBar,RepertoireView,RecordingPlayer}.svelte
- Existing size / shape signals: `RepertoireView` is already the largest component; `state.svelte.ts`
  is the shared store at ~580 lines; `capture.ts` is a focused 250-line client that this mirrors
- Owner fit: the capture client is its own module; the arm/stop control belongs in the device bar
  where capture already lives; the takes list belongs beside the recordings it lists
- Add-in-place risk: putting the takes list inside `RepertoireView`'s recording block would make the
  largest component larger and mix two different questions ("what is in my library" and "what did I
  just play")
- Better file boundary: `audioCapture.ts` and `TakeList.svelte`; `RepertoireView` gains one mount
- Recommendation: add owner files for the client and the panel; edit-in-place elsewhere
```

```text
Plan Pressure Test:
- Owner / contract / retirement: no new table; one new route on an existing router; four columns the
  frozen test pins; every addition has a named deletion path
- Architecture integrity / higher-level path: reusing the media row is the higher-level
  simplification, and it is what keeps the waveform, the loop and the backup working for free
- Verification scope: migration parity, an attachment test per case (segment found, segment not yet
  made, no segment at all), cutter units, a browser assertion with a fake microphone, three break
  scripts
- Task executability: every step names a file, complete code and an exact command
- Pressure result: proceed
```

---

## Files

**Create**

| Path | Why |
| --- | --- |
| `frontend/src/lib/audioCut.ts` | When to end a take, as a pure decision |
| `frontend/src/lib/audioCut.test.ts` | The gap, the maximum length, and never cutting silence |
| `frontend/src/lib/audioCapture.ts` | `MediaRecorder` + upload, mirroring `CaptureClient` |
| `frontend/src/components/TakeList.svelte` | The takes of a piece, and comparing two |
| `backend/tools/falsifications/drop_capture_segment_link.sh` | Break the epoch attachment |
| `backend/tools/falsifications/drop_media_source_column.sh` | Break the migration parity |
| `backend/tools/falsifications/cut_takes_at_the_wrong_gap.sh` | Break the client's use of the server's rule |

**Modify**

| Path | Change |
| --- | --- |
| `backend/app/repertoire/schema.py` | Four `media` columns in both places |
| `backend/app/db.py` | `SCHEMA_VERSION` 3 → 4 |
| `backend/app/practice/models.py` | `PracticeStatus.segment_gap_s` |
| `backend/app/repertoire/models.py` | `MediaOut` gains the four take fields |
| `backend/app/repertoire/store.py` | Extend the three media reads and `create_media`; `sitting_at`, `segment_at`, `link_unlinked_takes`, `captured_bytes` |
| `backend/app/repertoire/api.py` | `POST /takes` |
| `backend/app/models.py` | `SystemStatus` reports captured-audio bytes |
| `backend/tests/test_migration_upgrade.py` | The frozen `media` shape |
| `backend/tests/test_repertoire.py` | The attachment cases and the size report |
| `frontend/src/lib/types.ts` | `PracticeStatus.segment_gap_s`; `Recording` gains the four fields |
| `frontend/src/lib/api.ts` | `uploadTake` |
| `frontend/src/lib/state.svelte.ts` | The audio capture client, arm/stop, and the pedal action |
| `frontend/src/components/DeviceBar.svelte` | Arm/stop and the "what will be recorded" readout |
| `frontend/src/components/RepertoireView.svelte` | Mount `TakeList` |
| `frontend/src/components/RecordingPlayer.svelte` | The playback-rate control |
| `backend/tools/e2e_browser.py` | Fake-media launch args and `scenario_takes` |
| `deploy/chromium-policy.json`, `deploy/README.md`, `docs/DEPLOYMENT.md` | The audio-capture permission |
| `README.md`, `AGENT-LOG.md`, `docs/ECOSYSTEM.md` | docs |

---

## Task 1 — the client learns the segment rule

**Files.** modify `backend/app/practice/models.py`, `backend/app/practice/api.py`,
`frontend/src/lib/types.ts`, `backend/tests/test_practice_api.py`.

**Why.** The cutter must cut where the server cuts. Without this the client would either hardcode 8
seconds — a constant that then silently disagrees the first time `SRT_SEGMENT_GAP_S` changes — or
guess.

**Change Necessity.** Code: no endpoint reports any server timing value today.

**Impact / Compatibility.** One additive field on an existing response.

### Step 1.1 — write the failing test

`PracticeStatus` is the payload `/api/practice/status` already returns. Append to
`backend/tests/test_practice_api.py`:

```python
def test_the_practice_status_reports_the_segment_gap(client) -> None:
    """The client cuts recorded audio on this rule, so it must not be a second copy of it."""
    from app.config import settings

    body = client.get("/api/practice/status").json()
    assert body["segment_gap_s"] == settings.segment_gap_s
```

### Step 1.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py -k segment_gap
```

Expected: `KeyError: 'segment_gap_s'`.

### Step 1.3 — the field

In `backend/app/practice/models.py`, add to `PracticeStatus`:

```python
    #: Silence the server treats as a segment boundary, in seconds. Reported so the client can
    #: cut recorded audio on the same rule rather than keeping a second copy of it: audio cut
    #: somewhere else would disagree with the notes about where a passage ended.
    segment_gap_s: int = 0
```

and in `backend/app/practice/api.py`'s `status` route (`:100-128`), pass
`segment_gap_s=settings.segment_gap_s` into the `PracticeStatus(...)` it builds. `settings` is
already imported there.

### Step 1.4 — verify GREEN, and the client type

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_practice_api.py
```

In `frontend/src/lib/types.ts`, add to `PracticeStatus` (`:378-387`):

```ts
  /** Silence the server treats as a segment boundary, in seconds. Recorded audio is cut on it. */
  segment_gap_s: number;
```

---

## Task 2 — the media row learns where a take came from

**Files.** modify `backend/app/repertoire/schema.py`, `backend/app/db.py`,
`backend/app/repertoire/models.py`, `backend/app/repertoire/store.py`,
`backend/tests/test_migration_upgrade.py`; create
`backend/tools/falsifications/drop_media_source_column.sh`.

**Why.** Nothing in the library says whether a recording arrived by hand or came off the piano, and
nothing links one to the playing it was.

**Change Necessity.** Code: a column cannot be added by configuration.

**Impact / Compatibility.** Four additive nullable columns. `media` is already in the harness's
`DATA_TABLES`, so no e2e change is needed for the table itself.

### Step 2.1 — write the failing migration test

Append to `backend/tests/test_migration_upgrade.py`:

```python
def test_the_upgraded_database_gains_the_take_columns() -> None:
    """20e: where a captured take came from, on a library that predates capture."""
    path = _build_fixture_db("take-columns.sqlite3")
    db.init_db(path)
    conn = db.connect(path)
    try:
        assert {"source", "sitting_id", "segment_id", "captured_start_ms"} <= _columns(conn, "media")
    finally:
        conn.close()
```

### Step 2.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py -k take_columns
```

### Step 2.3 — the columns

In `backend/app/repertoire/schema.py`, in the `media` CREATE after `loop_end_s`:

```sql
    -- Where this row came from. 'uploaded' is the default and matches every row that
    -- existed before Phase 20e; 'captured' means the app recorded it from the piano. Stored
    -- rather than inferred, because "which of these did I record here?" is a question the
    -- library should answer, and because captured audio is the half that may be deleted.
    source          TEXT NOT NULL DEFAULT 'uploaded',
    -- The playing this take came from. Both are ON DELETE SET NULL for the reason the
    -- journal's `sitting_id` is: deleting the session that produced a take must not delete
    -- the take. `segment_id` is nullable because a take can be uploaded while its sitting is
    -- still open, before the server has made any segments — `create_take` fills it in later.
    sitting_id      INTEGER REFERENCES sittings(id) ON DELETE SET NULL,
    segment_id      INTEGER REFERENCES segments(id) ON DELETE SET NULL,
    -- The absolute epoch the take started at, ms since the Unix epoch, exactly as a note
    -- batch carries its own time. This is what lets the server attach the take to the
    -- segment that was being played, and what lets the takes view say when it happened.
    captured_start_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_media_segment ON media(segment_id);
CREATE INDEX IF NOT EXISTS idx_media_source ON media(source);
```

and to `ADDED_COLUMNS`:

```python
    # Phase 20e — where a take came from. A `DEFAULT 'uploaded'` cannot be expressed through
    # the ADDED_COLUMNS tuple, which carries only a type string, so existing rows arrive NULL
    # and `list_media` reads NULL as 'uploaded'. That is deliberate rather than sloppy: the
    # alternative is a migration statement this mechanism cannot run, and NULL already means
    # "before capture existed" everywhere else in this schema.
    ("media", "source", "TEXT"),
    ("media", "sitting_id", "INTEGER REFERENCES sittings(id) ON DELETE SET NULL"),
    ("media", "segment_id", "INTEGER REFERENCES segments(id) ON DELETE SET NULL"),
    ("media", "captured_start_ms", "INTEGER"),
```

**Read that comment before writing the code.** The fresh-database `CREATE` declares
`source TEXT NOT NULL DEFAULT 'uploaded'`; an upgraded database gets a *nullable* column with no
default, so its existing rows read NULL. The plan accepts that difference and normalises it on read,
because `ADDED_COLUMNS` carries a type string and cannot express a default. The parity test compares
column *names* and foreign keys, not defaults, so it passes — and the read path is what makes the
difference invisible. `list_media` and `get_media` therefore both do
`record["source"] = record["source"] or "uploaded"`.

### Step 2.4 — the version and the frozen shape

`backend/app/db.py`: `SCHEMA_VERSION = 4`.

In `backend/tests/test_migration_upgrade.py`, `EXPECTED_COLUMNS["media"]`:

```python
    "media": {
        "id", "piece_id", "kind", "file_name", "original_name", "title",
        "duration_secs", "size_bytes", "codec", "taken_on", "legacy_id",
        "loop_start_s", "loop_end_s", "created_at", "source", "sitting_id",
        "segment_id", "captured_start_ms",
    },
```

`EXPECTED_INDEXES["media"]` gains `"idx_media_segment"` and `"idx_media_source"`, and the frozen
fixture's guard gains the four columns:

```python
        assert {"source", "sitting_id", "segment_id", "captured_start_ms"}.isdisjoint(
            _columns(conn, "media")
        ), "the fixture predates every ADDED_COLUMNS entry for media"
```

(replacing the existing `assert "loop_end_s" not in _columns(conn, "media")` line, which this
supersedes.)

### Step 2.5 — the reads and the insert

In `backend/app/repertoire/store.py`, every explicit media column list gains the four fields, and
both read paths normalise `source`. The three sites are `list_media` (`:151-169`), `get_media`
(`:203-217`) and `create_media` (`:513-537` — note the name; there is no `insert_media`). For
`list_media`:

```python
    sql = """
        SELECT id, piece_id, kind, file_name, original_name, title,
               duration_secs, size_bytes, codec, taken_on,
               loop_start_s, loop_end_s,
               source, sitting_id, segment_id, captured_start_ms
        FROM media
    """
```

and where it builds the record:

```python
        record = dict(row)
        # NULL `source` is a row that existed before Phase 20e; it was uploaded, because
        # capture did not exist. Normalised here so no caller has to know that.
        record["source"] = record["source"] or "uploaded"
        record["state"] = media_state(str(record["file_name"]))
```

The same two lines in `get_media`.

`create_media` already takes **keyword-only** arguments after `conn`, so the four new ones are added
the same way and every existing caller — the recording upload, the score upload and the legacy
importer — keeps working untouched:

```python
def create_media(
    conn: sqlite3.Connection,
    *,
    piece_id: int | None,
    kind: str,
    file_name: str,
    original_name: str | None,
    title: str | None,
    duration_secs: float | None,
    size_bytes: int | None,
    codec: str | None,
    taken_on: str | None = None,
    source: str = "uploaded",
    sitting_id: int | None = None,
    segment_id: int | None = None,
    captured_start_ms: int | None = None,
) -> int:
```

with the INSERT extended to match. The three existing call sites pass no new arguments, so they keep
writing `source='uploaded'` — which is exactly right for a file that arrived by hand.

### Step 2.6 — the model and the test

In `backend/app/repertoire/models.py`, `MediaOut` gains:

```python
    #: 'uploaded' for a file that arrived by hand, 'captured' for audio the app recorded.
    source: str = "uploaded"
    #: The playing this take came from, when it was recorded here.
    sitting_id: int | None = None
    segment_id: int | None = None
    #: Absolute epoch ms the take started at, for placing it against the notes.
    captured_start_ms: int | None = None
```

### Step 2.7 — verify GREEN and falsify

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py tests/test_repertoire.py tests/test_backup.py
```

Create `backend/tools/falsifications/drop_media_source_column.sh`:

```bash
#!/usr/bin/env bash
#
# Break: delete the 20e ADDED_COLUMNS entry for media.source.
#
# The parity test in test_migration_upgrade.py is what must catch it.
#
#   ./falsify.sh backend/tools/falsifications/drop_media_source_column.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/schema.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = '    ("media", "source", "TEXT"),\n'
assert needle in text, "the line to break is not where this script expects it"
path.write_text(text.replace(needle, "", 1))
PY
```

---

## Task 3 — a take is attached to the segment that was playing

**Files.** modify `backend/app/repertoire/store.py`, `backend/app/repertoire/models.py`,
`backend/app/repertoire/api.py`, `backend/tests/test_repertoire.py`; create
`backend/tools/falsifications/drop_capture_segment_link.sh`.

**Why.** A take with no link is a file with a date; a take attached to its segment is *this passage,
that time*, which is what makes the takes view worth having.

**Change Necessity.** Code: the pipeline catalogues a row but knows nothing about segments.

**Impact / Compatibility.** One new route. The recording upload route is untouched.

### Step 3.1 — the failing tests

Append to `backend/tests/test_repertoire.py`:

```python
def test_a_take_is_attached_to_the_segment_it_was_played_in(client, tone_wav) -> None:
    """The client cannot name a segment — it does not exist when the audio is cut — so the
    server resolves it from the epoch the take started at, exactly as it resolves a note batch
    into a sitting."""
    piece_id = _a_piece(client, "Captured")
    sitting_id = _a_sitting(client)  # a past, closed sitting: it has segments

    # The sitting's own segment, so the take lands in a real window.
    detail = client.get(f"/api/practice/sittings/{sitting_id}").json()
    segment = detail["segments"][0]
    client.patch(f"/api/practice/segments/{segment['id']}", json={"piece_id": piece_id})
    started = _sitting_start_ms(client, sitting_id) + segment["start_ms"]

    with tone_wav.open("rb") as handle:
        created = client.post(
            "/api/repertoire/takes",
            files={"file": ("take.webm", handle, "audio/webm")},
            data={"started_ms": str(started)},
        )
    assert created.status_code == 201, created.text
    take = created.json()
    assert take["source"] == "captured"
    assert take["segment_id"] == segment["id"], "the take found the segment it belongs to"
    assert take["sitting_id"] == sitting_id
    assert take["piece_id"] == piece_id, "and the piece follows the segment's label"
    assert take["captured_start_ms"] == started


def test_a_take_with_no_segment_yet_keeps_its_sitting(client, tone_wav) -> None:
    """A sitting still open has no segments, and the audio must not be thrown away."""
    from app.practice import store as practice_store

    sitting_id = _a_sitting(client)
    started = _sitting_start_ms(client, sitting_id)
    # Undo the segmentation, which is the state an open sitting is in.
    with db.transaction(settings.db_path) as conn:
        conn.execute("DELETE FROM segments WHERE sitting_id = ?", (sitting_id,))

    with tone_wav.open("rb") as handle:
        created = client.post(
            "/api/repertoire/takes",
            files={"file": ("take.webm", handle, "audio/webm")},
            data={"started_ms": str(started)},
        )
    assert created.status_code == 201, created.text
    take = created.json()
    assert take["sitting_id"] == sitting_id, "the sitting is resolvable even with no segments"
    assert take["segment_id"] is None, "and the segment is honestly unknown"
    assert take["piece_id"] is None


def test_a_take_with_no_sitting_at_all_is_refused(client, tone_wav) -> None:
    """Better a 422 with a reason than a recording nobody can place."""
    with tone_wav.open("rb") as handle:
        refused = client.post(
            "/api/repertoire/takes",
            files={"file": ("take.webm", handle, "audio/webm")},
            data={"started_ms": "1000"},
        )
    assert refused.status_code == 422
```

Two helpers are needed and belong with the file's existing `_a_piece`/`_a_sitting`
(`test_repertoire.py:1040-1062`); add beside them:

```python
def _sitting_start_ms(client, sitting_id: int) -> int:
    """The absolute epoch a sitting began at, from the API's own report."""
    row = next(
        item for item in client.get("/api/practice/sittings?limit=50").json()
        if item["id"] == sitting_id
    )
    return int(datetime.fromisoformat(row["started_at"]).timestamp() * 1000)
```

with `from datetime import datetime` added to that module's imports. **Note `_a_sitting` ingests with
`tz_offset_minutes: 0` and a base three hours in the past**, so its segments exist by the time this
test reads them.

### Step 3.2 — verify RED

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py -k take
```

Expected: 404 on `/api/repertoire/takes`.

### Step 3.3 — the store

In `backend/app/repertoire/store.py`, beside `sitting_exists` (`:432-443`), add the read-only practice
lookups — and keep the comment honest about crossing the boundary:

```python
def sitting_at(conn: sqlite3.Connection, epoch_ms: int) -> int | None:
    """The sitting an instant falls in, or None.

    The second place the repertoire domain reads a practice table, for the same stated
    reason as `sitting_exists`: a take is a recording *of* a playing, and the playing is the
    practice domain's. This reads; it never writes.
    """
    row = conn.execute(
        """
        SELECT id FROM sittings
        WHERE ?1 >= started_ms AND ?1 <= ended_ms
        ORDER BY started_ms DESC
        LIMIT 1
        """,
        (epoch_ms,),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def segment_at(conn: sqlite3.Connection, sitting_id: int, epoch_ms: int) -> tuple[int, int | None] | None:
    """The segment an instant falls in, and the piece it is labelled with.

    Only segments that exist are found: a sitting that is still open has none, and that is a
    real answer (the take keeps its sitting and no segment) rather than an error.
    """
    row = conn.execute(
        """
        SELECT g.id AS segment_id, g.piece_id, s.started_ms
        FROM segments g JOIN sittings s ON s.id = g.sitting_id
        WHERE g.sitting_id = ?1
          AND ?2 >= s.started_ms + g.start_ms
          AND ?2 <= s.started_ms + g.end_ms
        ORDER BY g.start_ms
        LIMIT 1
        """,
        (sitting_id, epoch_ms),
    ).fetchone()
    return (int(row["segment_id"]), row["piece_id"]) if row is not None else None


def link_unlinked_takes(conn: sqlite3.Connection, sitting_id: int) -> int:
    """Attach captured takes of a sitting that had no segments when they arrived.

    Called on the *next* take upload for the same sitting, which is enough: segments appear
    when the sitting closes, and the delay is at most one chunk. Nothing here needs a
    background job, and a take that is never linked keeps its sitting, which is the honest
    minimum.
    """
    rows = conn.execute(
        "SELECT id, captured_start_ms FROM media"
        " WHERE source = 'captured' AND sitting_id = ? AND segment_id IS NULL"
        "   AND captured_start_ms IS NOT NULL",
        (sitting_id,),
    ).fetchall()
    linked = 0
    for row in rows:
        found = segment_at(conn, sitting_id, int(row["captured_start_ms"]))
        if found is None:
            continue
        conn.execute(
            "UPDATE media SET segment_id = ?, piece_id = COALESCE(piece_id, ?) WHERE id = ?",
            (found[0], found[1], int(row["id"])),
        )
        linked += 1
    return linked


def captured_bytes(conn: sqlite3.Connection) -> int:
    """Bytes of audio this app recorded, for the System panel.

    Reported rather than pruned: captured audio is the half of the library that may be
    deleted, and the player decides that, not a retention policy (20e-D6).
    """
    total = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) AS total FROM media WHERE source = 'captured'"
    ).fetchone()["total"]
    return int(total or 0)
```

### Step 3.4 — the route

The contract is the **multipart form**, not a request model — the route carries a file, so it
takes `Form` fields exactly as the recording upload does, and `repertoire/models.py` needs no new
model for it.

In `backend/app/repertoire/api.py`, add after the recording upload route. It reuses `_stage_upload`
and the pipeline wholesale, so the size cap, the hashing and the transcode cannot diverge from the
upload path:

```python
@router.post("/takes", response_model=MediaOut, status_code=201)
def upload_take(
    file: UploadFile = File(...),
    started_ms: int = Form(...),
    title: str | None = Form(default=None),
) -> MediaOut:
    """Catalogue one captured take and attach it to the playing it came from.

    The client cannot name a segment: it cut the audio on the server's silence rule, before the
    server had made any segments at all. So it sends the absolute epoch the chunk started at —
    the same reasoning the note wire format uses — and this resolves the sitting, then the
    segment inside it, then the piece the segment is labelled with.
    """
    with db.transaction(settings.db_path) as conn:
        sitting_id = store.sitting_at(conn, started_ms)
        if sitting_id is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "no sitting covers that time, so this take cannot be placed; "
                    "the capture heartbeat and the sitting gap decide where a playing begins"
                ),
            )
        found = store.segment_at(conn, sitting_id, started_ms)
        # A take that arrives after the sitting closed can attach its predecessors too.
        store.link_unlinked_takes(conn, sitting_id)

    media_dir = Path(settings.media_dir)
    with tempfile.TemporaryDirectory() as scratch:
        staged = _stage_upload(file, scratch=Path(scratch), what="take")
        try:
            info = probe(staged)
        except MediaError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        stored = store_recording(staged, media_dir=media_dir, original_name=file.filename)
        with db.transaction(settings.db_path) as conn:
            existing = store.find_media_by_file_name(conn, stored.file_name)
            if existing is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "that take is byte-for-byte identical to one already in the library "
                        f"(id {existing['id']})"
                    ),
                )
            take_id = store.create_media(
                conn,
                piece_id=found[1] if found is not None else None,
                kind=stored.kind,
                file_name=stored.file_name,
                original_name=file.filename,
                title=title or "Take",
                duration_secs=stored.duration_secs,
                size_bytes=stored.size_bytes,
                codec=stored.codec,
                taken_on=datetime.now(timezone.utc).date().isoformat(),
                source="captured",
                sitting_id=sitting_id,
                segment_id=found[0] if found is not None else None,
                captured_start_ms=started_ms,
            )
            row = store.get_media(conn, take_id)
    assert row is not None
    return MediaOut(**row)
```

**The duplicate is caught before the insert**, exactly as the score route catches it.
`store_recording` returns `reused=True` when the content hash already names a file on disk, and
`media.file_name` is `UNIQUE`, so an identical take would collide on insert. Checking first gives a
409 that says where it already lives rather than a bare integrity error:

```python
        stored = store_recording(staged, media_dir=media_dir, original_name=file.filename)
        with db.transaction(settings.db_path) as conn:
            existing = store.find_media_by_file_name(conn, stored.file_name)
            if existing is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "that take is byte-for-byte identical to one already in the library "
                        f"(id {existing['id']})"
                    ),
                )
```

A byte-identical take is a real thing a player can produce, so it is refused with a reason rather
than crashing.

**The filename is part of the contract.** `_stage_upload` takes the suffix from
`file.filename` and `store_recording` refuses anything outside `KNOWN_SUFFIXES`, so a
`MediaRecorder` blob appended with no filename is a 422 even though `.webm` is accepted. The client
must name it (`form.append('file', blob, 'take.webm')`, Step 4.5), and this plan states it here
because the failure message would otherwise look like a format problem rather than a naming one.

Imports needed in `api.py`: `sqlite3` (already), `datetime`/`timezone`, and `store_recording` and
`MediaError` (already imported for the upload path).

### Step 3.5 — a duplicate take

Append to `tests/test_repertoire.py`:

```python
def test_the_same_take_twice_is_refused_with_a_reason(client, tone_wav) -> None:
    """Takes are content-addressed, so an identical take is one take."""
    _a_sitting(client)
    import time

    started = int(time.time() * 1000) - 3 * 60 * 60 * 1000
    with tone_wav.open("rb") as handle:
        first = client.post(
            "/api/repertoire/takes",
            files={"file": ("take.webm", handle, "audio/webm")},
            data={"started_ms": str(started)},
        )
    assert first.status_code == 201, first.text
    with tone_wav.open("rb") as handle:
        second = client.post(
            "/api/repertoire/takes",
            files={"file": ("take.webm", handle, "audio/webm")},
            data={"started_ms": str(started)},
        )
    assert second.status_code == 409, second.text
    assert "identical" in second.json()["detail"]
```

### Step 3.6 — verify GREEN and falsify

```bash
cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py
```

Create `backend/tools/falsifications/drop_capture_segment_link.sh`:

```bash
#!/usr/bin/env bash
#
# Break: stop attaching a take to the segment that was playing.
#
# The test that must catch it is test_a_take_is_attached_to_the_segment_it_was_played_in:
# with the link dropped the take is catalogued but cannot say what it was.
#
#   ./falsify.sh backend/tools/falsifications/drop_capture_segment_link.sh \
#     "cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/backend/app/repertoire/api.py"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = """        found = store.segment_at(conn, sitting_id, started_ms)"""
assert needle in text, "the lookup is not where this script expects it"
path.write_text(text.replace(needle, "        found = None", 1))
PY
```

---

## Task 4 — the capture client

**Files.** create `frontend/src/lib/audioCut.ts`, `audioCut.test.ts`, `audioCapture.ts`; modify
`frontend/src/lib/state.svelte.ts`, `frontend/src/components/DeviceBar.svelte`,
`frontend/src/lib/api.ts`, `frontend/src/lib/types.ts`.

**Why.** This is the feature.

**Change Necessity.** Code: nothing in the client touches a microphone today.

**Impact / Compatibility.** Additive. The arm/stop control follows the existing capture switch, and
the pedal action from 20b gains a second action.

### Step 4.1 — write the failing units

Create `frontend/src/lib/audioCut.test.ts`:

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { shouldCut, shouldStart } from './audioCut.ts';

test('a take is cut exactly when the server would cut the notes', () => {
  const base = { nowMs: 100_000, chunkStartedMs: 90_000, segmentGapMs: 8_000, maxChunkMs: 600_000 };
  assert.equal(shouldCut({ ...base, lastNoteMs: 95_000 }), false, 'still playing');
  assert.equal(shouldCut({ ...base, lastNoteMs: 92_001 }), false, 'one ms short of the gap');
  assert.equal(shouldCut({ ...base, lastNoteMs: 92_000 }), true, 'the gap is reached');
  assert.equal(shouldCut({ ...base, lastNoteMs: 91_000 }), true, 'and past it');
});

test('no note at all is treated as silence, not as playing', () => {
  assert.equal(
    shouldCut({ nowMs: 100_000, chunkStartedMs: 90_000, lastNoteMs: null, segmentGapMs: 8_000, maxChunkMs: 600_000 }),
    true,
  );
});

test('a long unbroken passage is cut anyway, at the maximum length', () => {
  const base = { chunkStartedMs: 300_000, segmentGapMs: 8_000, maxChunkMs: 600_000 };
  assert.equal(shouldCut({ ...base, nowMs: 899_000, lastNoteMs: 898_999 }), false, 'short of the cap');
  assert.equal(shouldCut({ ...base, nowMs: 900_001, lastNoteMs: 900_000 }), true, 'past the cap');
});

test('a take starts on the first note and never on silence', () => {
  assert.equal(shouldStart({ lastNoteMs: null, recording: false }), false);
  assert.equal(shouldStart({ lastNoteMs: 5_000, recording: false }), true);
  assert.equal(shouldStart({ lastNoteMs: 5_000, recording: true }), false, 'already recording');
  assert.equal(shouldStart({ lastNoteMs: null, recording: true }), false);
});
```

### Step 4.2 — verify RED

```bash
cd frontend && npm test
```

### Step 4.3 — the pure cutter

Create `frontend/src/lib/audioCut.ts`:

```ts
/**
 * When a take ends.
 *
 * The rule is the server's segment rule, fetched from the practice status rather than repeated here:
 * audio
 * cut somewhere else than the notes would disagree with them about where a passage ended, and the
 * disagreement would be invisible until somebody compared a take with its segment.
 *
 * Pure, and in its own module, because a decision about time is the part of recording that breaks
 * quietly. There is no DOM here and no `MediaRecorder`, so `node --test` can reach it.
 */

export interface CutInput {
  /** Now, ms since the Unix epoch. */
  nowMs: number;
  /** When the current take began recording, ms since the Unix epoch. */
  chunkStartedMs: number;
  /** The last note heard, ms since the Unix epoch, or null if none has been. */
  lastNoteMs: number | null;
  /** Silence the server treats as a segment boundary, in ms. */
  segmentGapMs: number;
  /** A hard ceiling, so one long unbroken passage still produces playable files. */
  maxChunkMs: number;
}

/**
 * Whether to end the current take now.
 *
 * Cutting only ever happens *after* the gap has elapsed, never before, so the take contains the
 * whole of the playing it belongs to. The maximum length is a separate reason to cut, and it is the
 * only case where a take ends while notes are still arriving.
 */
export function shouldCut(input: CutInput): boolean {
  const silence = input.lastNoteMs === null || input.nowMs - input.lastNoteMs >= input.segmentGapMs;
  const tooLong = input.nowMs - input.chunkStartedMs >= input.maxChunkMs;
  return silence || tooLong;
}

/** Whether to open a take. A take begins on a note: recording silence is recording nothing. */
export function shouldStart(input: { lastNoteMs: number | null; recording: boolean }): boolean {
  return !input.recording && input.lastNoteMs !== null;
}
```

### Step 4.4 — the capture client

Create `frontend/src/lib/audioCapture.ts`. It mirrors `CaptureClient`'s shape — a standing switch, a
timer, a buffer that is only cleared once the server has taken it — and adds the one thing audio
needs, which is a device:

```ts
/**
 * The standing audio switch.
 *
 * One `MediaRecorder` per take, rather than one long recording chopped up afterwards: each take has
 * to be a self-contained file for the probe and the transcode to read, and a WebM stream is only
 * complete when the recorder that wrote it stops.
 *
 * Quality is deliberately modest — mono Opus at 32 kbps, about 14 MB an hour. The piano's own
 * pen-drive recording is the archive; this is the layer that makes a take shareable without finding
 * a memory stick (20-D4).
 *
 * Nothing is recorded while nothing is played: a take opens on the first note and closes on the
 * server's own silence gap. Silence is not practice and is not worth storing.
 */
import { shouldCut, shouldStart } from './audioCut';
import { api } from './api';

/** Mono Opus, low bitrate. Not an archive, and not pretending to be one. */
const AUDIO_BITS_PER_SECOND = 32_000;

/** One take never runs longer than this, so a continuous half-hour is four playable files. */
const MAX_TAKE_MS = 10 * 60 * 1000;

/** How often the switch considers whether to open or close a take. */
const TICK_MS = 1_000;

export type CaptureDeviceState = 'unknown' | 'ready' | 'unavailable' | 'denied';

export class AudioCaptureClient {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private startedMs = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  private busy = false;

  deviceState: CaptureDeviceState = 'unknown';
  lastError: string | null = null;
  captured = 0;

  constructor(
    /** The last note any port has heard, or null. The same source the gesture reads. */
    private readonly lastNoteMs: () => number | null,
    /** The server's segment gap, in ms, from the practice status. */
    private readonly segmentGapMs: () => number,
    /** Ask the server whether there is a sitting to attach to, and how to post a take. */
    private readonly upload: (blob: Blob, startedMs: number) => Promise<void>,
    private readonly onStatus: () => void,
  ) {}

  async start(): Promise<void> {
    if (this.timer !== null) return;
    this.lastError = null;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false },
      });
      this.deviceState = 'ready';
    } catch (cause) {
      // `NotAllowedError` is the permission; anything else is a machine with no input at all.
      const name = cause instanceof DOMException ? cause.name : '';
      this.deviceState = name === 'NotAllowedError' ? 'denied' : 'unavailable';
      this.lastError = cause instanceof Error ? cause.message : String(cause);
      this.onStatus();
      return;
    }
    this.timer = setInterval(() => void this.tick(), TICK_MS);
    this.onStatus();
  }

  stop(): void {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    void this.close();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.deviceState = 'unknown';
    this.onStatus();
  }

  private async tick(): Promise<void> {
    if (this.busy) return;
    const now = Date.now();
    if (this.recorder === null) {
      if (shouldStart({ lastNoteMs: this.lastNoteMs(), recording: false })) this.open(now);
      return;
    }
    if (
      shouldCut({
        nowMs: now,
        chunkStartedMs: this.startedMs,
        lastNoteMs: this.lastNoteMs(),
        segmentGapMs: this.segmentGapMs(),
        maxChunkMs: MAX_TAKE_MS,
      })
    ) {
      await this.close();
    }
  }

  private open(nowMs: number): void {
    if (this.stream === null) return;
    this.chunks = [];
    this.startedMs = nowMs;
    const recorder = new MediaRecorder(this.stream, {
      mimeType: 'audio/webm;codecs=opus',
      audioBitsPerSecond: AUDIO_BITS_PER_SECOND,
    });
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) this.chunks.push(event.data);
    };
    recorder.start();
    this.recorder = recorder;
  }

  /**
   * Close the current take and hand it to the server.
   *
   * The blob is built from the recorder's own chunks *after* `stop()` settles, because the last
   * `dataavailable` fires as part of stopping: reading `this.chunks` before that would upload a
   * file missing its tail, which is the kind of loss nobody notices until a phrase ends early.
   */
  private async close(): Promise<void> {
    const recorder = this.recorder;
    if (recorder === null) return;
    this.busy = true;
    this.recorder = null;
    const startedMs = this.startedMs;
    try {
      await new Promise<void>((resolve) => {
        recorder.onstop = () => resolve();
        recorder.stop();
      });
      const blob = new Blob(this.chunks, { type: 'audio/webm' });
      this.chunks = [];
      if (blob.size > 0) {
        await this.upload(blob, startedMs);
        this.captured += 1;
      }
    } catch (cause) {
      this.lastError = cause instanceof Error ? cause.message : String(cause);
    } finally {
      this.busy = false;
      this.onStatus();
    }
  }
}
```

### Step 4.5 — the client method

`frontend/src/lib/api.ts`, in the `repertoire` block:

```ts
    /** Upload one captured take. The server works out the sitting and the segment. */
    uploadTake: (blob: Blob, startedMs: number) => {
      const form = new FormData();
      form.append('file', blob, 'take.webm');
      form.append('started_ms', String(startedMs));
      return requestForm<Recording>('/repertoire/takes', form);
    },
```

and `Recording` in `types.ts` gains the four fields, mirroring `MediaOut`:

```ts
  source: 'uploaded' | 'captured';
  sitting_id: number | null;
  segment_id: number | null;
  captured_start_ms: number | null;
```

### Step 4.6 — the store wiring

In `frontend/src/lib/state.svelte.ts`, beside the existing capture client:

```ts
import { AudioCaptureClient } from './audioCapture';

  /** The standing audio switch. Off until it is armed, and off again on a reload. */
  audioCapture: AudioCaptureClient | null = null;
  audioArmed = $state(false);
  audioDevice = $state<'unknown' | 'ready' | 'unavailable' | 'denied'>('unknown');
  audioNote = $state<string | null>(null);
  takesCaptured = $state(0);

  async function toggleAudioCapture(): Promise<void> {
    if (this.audioArmed) {
      this.audioCapture?.stop();
      this.audioArmed = false;
      this.audioNote = null;
      return;
    }
    // From the server, every time: audio cut somewhere else than the notes would disagree
    // with them about where a passage ended, and a local constant would be that disagreement
    // waiting to happen. A server that cannot say refuses the arming rather than guessing.
    const status = await api.practice.status().catch(() => null);
    if (status === null) {
      this.audioNote =
        'the server did not report its segment gap, so a take could be cut in the wrong place';
      return;
    }
    if (this.audioCapture === null) {
      this.audioCapture = new AudioCaptureClient(
        () => this.lastNoteMs,
        () => status.segment_gap_s * 1000,
        async (blob, startedMs) => {
          await api.repertoire.uploadTake(blob, startedMs);
          // The takes list is per piece and the library view owns it; this only refreshes the
          // number the device bar reports, so a capture cannot leave a stale count behind.
          this.takesCaptured += 1;
        },
        () => {
          this.audioDevice = this.audioCapture?.deviceState ?? 'unknown';
          this.audioNote = this.audioCapture?.lastError ?? null;
        },
      );
    }
    await this.audioCapture.start();
    this.audioArmed = this.audioCapture.deviceState === 'ready';
    this.audioDevice = this.audioCapture.deviceState;
    this.audioNote = this.audioCapture.lastError;
  }
```

`lastNoteMs` is the getter added in 20b; if 20b has not landed, add it as part of this step (it is
four lines and the gesture does not need to exist for it).

### Step 4.7 — the control

In `frontend/src/components/DeviceBar.svelte`, beside the capture pill, add:

```svelte
    <button
      class="ghost"
      data-audio-capture={app.audioArmed ? 'armed' : 'off'}
      onclick={() => void app.toggleAudioCapture()}
    >
      {app.audioArmed ? 'Recording takes' : 'Record takes'}
    </button>
    {#if app.audioArmed}
      <span class="pill good" data-audio-device="ready">
        microphone ready · mono Opus, about 14 MB/hour
      </span>
    {:else if app.audioDevice === 'unavailable'}
      <span class="pill bad" data-audio-device="unavailable">
        no audio input on this machine — nothing can be recorded
      </span>
    {:else if app.audioDevice === 'denied'}
      <span class="pill bad" data-audio-device="denied">
        the browser refused the microphone; on the piano machine the kiosk policy grants it
      </span>
    {/if}
    {#if app.takesCaptured > 0}
      <span class="muted small" data-takes-captured={app.takesCaptured}>
        {app.takesCaptured} take{app.takesCaptured === 1 ? '' : 's'} recorded
      </span>
    {/if}
    {#if app.audioNote}
      <span class="muted small" data-audio-note>{app.audioNote}</span>
    {/if}
```

**The readout is not decoration.** A machine with no input, a refused permission and a working
microphone are three different facts, and the failure mode this avoids is a capture switch that looks
armed and records nothing.

### Step 4.8 — verify

```bash
cd frontend && npm test && npm run check && npm run build
```

### Step 4.9 — falsify the cutter

Create `backend/tools/falsifications/cut_takes_at_the_wrong_gap.sh`:

```bash
#!/usr/bin/env bash
#
# Break: cut a take a second early, so it clips the end of the playing it belongs to.
#
# The test that must catch it is the boundary case in audioCut.test.ts.
#
#   ./falsify.sh backend/tools/falsifications/cut_takes_at_the_wrong_gap.sh "cd frontend && npm test"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TARGET="$ROOT/frontend/src/lib/audioCut.ts"

python3 - "$TARGET" <<'PY'
import pathlib, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
needle = "  const silence = input.lastNoteMs === null || input.nowMs - input.lastNoteMs >= input.segmentGapMs;"
assert needle in text, "the gap rule is not where this script expects it"
path.write_text(
    text.replace(
        needle,
        "  const silence = input.lastNoteMs === null || input.nowMs - input.lastNoteMs >= input.segmentGapMs - 1000;",
        1,
    )
)
PY
```

```bash
chmod +x backend/tools/falsifications/cut_takes_at_the_wrong_gap.sh
backend/tools/falsify.sh backend/tools/falsifications/cut_takes_at_the_wrong_gap.sh "cd frontend && npm test"
```

---

## Task 5 — the takes view and the playback rate

**Files.** create `frontend/src/components/TakeList.svelte`; modify
`frontend/src/components/RecordingPlayer.svelte`,
`frontend/src/components/RepertoireView.svelte`.

**Why.** The audio is useless until it can be found and listened to, and "hear it slower" is the
reason to keep a take at all.

**Change Necessity.** Code.

**Impact / Compatibility.** Additive UI. The rate control is additive on a player that already
exists, and it never changes the stored file.

### Step 5.1 — the rate control

In `frontend/src/components/RecordingPlayer.svelte`, add beside the loop controls (`:164-187`):

```svelte
      <label class="row toggle">
        <span class="muted small">Speed</span>
        <select
          aria-label="Playback speed"
          value={rate}
          onchange={(event) => setRate(Number((event.currentTarget as HTMLSelectElement).value))}
        >
          {#each [1, 0.85, 0.7, 0.5] as option (option)}
            <option value={option}>{option === 1 ? 'normal' : `${option}×`}</option>
          {/each}
        </select>
      </label>
```

with the state and the setter:

```ts
  let rate = $state(1);
  /** Whether the browser is preserving pitch, which is what makes a slow take useful. */
  let preservesPitch = $state(true);

  /**
   * Slow the take down without changing the file.
   *
   * `preservesPitch` is the browser's own time-stretch: at 0.5× the passage is lower *and* slower
   * without it, which is not what a player wants to hear. The readout says which one this browser
   * is doing rather than assuming.
   */
  function setRate(value: number): void {
    rate = value;
    if (!element) return;
    const media = element as HTMLMediaElement & {
      preservesPitch?: boolean;
      webkitPreservesPitch?: boolean;
    };
    // Both spellings: `preservesPitch` is the standard and `webkitPreservesPitch` is what older
    // Chromium builds honour, and a kiosk is exactly the kind of machine that runs an older one.
    media.preservesPitch = true;
    media.webkitPreservesPitch = true;
    media.playbackRate = value;
    preservesPitch = media.preservesPitch !== false || media.webkitPreservesPitch !== false;
  }
```

and a readout under the controls:

```svelte
      {#if rate !== 1}
        <span class="muted small" data-rate-note={preservesPitch ? 'same-pitch' : 'lower-pitch'}>
          {preservesPitch ? 'slower, same pitch' : 'slower and lower — this browser cannot hold pitch'}
        </span>
      {/if}
```

### Step 5.2 — the takes list

Create `frontend/src/components/TakeList.svelte`:

```svelte
<script lang="ts">
  /**
   * What this app recorded, newest first, and any two of them side by side.
   *
   * Only `source === 'captured'` rows appear: a take is audio the app heard, which is a different
   * question from "what is in my library" — that is the recordings list below it, and mixing them
   * would make both harder to read.
   *
   * Comparing two is two independent players, not a mixer. There is no attempt to align them: the
   * app has no score to align against, and pretending to would be the same claim 20-D7 refuses.
   */
  import type { Recording, SegmentSummary } from '../lib/types';
  import { formatClock } from '../lib/clock';
  import RecordingPlayer from './RecordingPlayer.svelte';

  interface Props {
    takes: Recording[];
    /** Segments of the open piece's sittings, so a take can say which passage it was. */
    segments: Map<number, SegmentSummary>;
    onloop: (mediaId: number, loop: { start: number | null; end: number | null }) => void;
    ondelete: (mediaId: number) => void;
  }

  let { takes, segments, onloop, ondelete }: Props = $props();

  let compare = $state<number[]>([]);

  function toggleCompare(id: number): void {
    if (compare.includes(id)) {
      compare = compare.filter((value) => value !== id);
      return;
    }
    // Two at a time, and the older one drops out: a third player makes the page unusable and
    // nothing is gained by hearing three at once.
    compare = [...compare, id].slice(-2);
  }

  function passageOf(take: Recording): string {
    if (take.segment_id === null) return 'not tied to a segment';
    const segment = segments.get(take.segment_id);
    if (segment === undefined) return 'segment no longer exists';
    return `bars from ${formatClock(segment.start_ms / 1000)} to ${formatClock(segment.end_ms / 1000)}`;
  }
</script>

<section class="card" data-takes={takes.length}>
  <h3>Takes this app recorded</h3>
  {#if takes.length === 0}
    <p class="muted small">
      Nothing recorded here yet. Press <em>Record takes</em> in the device bar and play: a take
      starts on the first note and ends when you stop for {Math.round(8)} seconds.
    </p>
  {:else}
    <ul class="takes">
      {#each takes as take (take.id)}
        <li data-take={take.id}>
          <div class="row wrap">
            <span class="mono small">{take.taken_on ?? 'undated'}</span>
            <span class="muted small">{formatClock(take.duration_secs ?? 0)}</span>
            <span class="muted small">{passageOf(take)}</span>
            <button class="ghost tiny" onclick={() => toggleCompare(take.id)}>
              {compare.includes(take.id) ? 'Remove from compare' : 'Compare'}
            </button>
            <button
              class="ghost tiny"
              disabled={!loopback}
              title={loopback ? 'Delete this take' : 'Only on the piano machine'}
              onclick={() => ondelete(take.id)}>×</button
            >
          </div>
          {#if compare.length < 2 || compare.includes(take.id)}
            <RecordingPlayer recording={take} onLoop={(loop) => onloop(take.id, loop)} />
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>
```

`loopback` comes from the app store — add `import { app } from '../lib/state.svelte';` and
`const loopback = $derived(app.host?.loopback ?? false);`, replacing the bare `loopback` references.

### Step 5.3 — mount it

In `frontend/src/components/RepertoireView.svelte`, import `TakeList` and render it above the
recordings list, with the two props it needs:

```svelte
        <TakeList
          takes={recordings.filter((row) => row.source === 'captured')}
          {segments}
          onloop={(mediaId, loop) => void saveLoop(mediaId, loop)}
          ondelete={(mediaId) => void removeRecording(mediaId)}
        />
```

`recordings` already exists (`:416`). `segments` is new: a map of the open piece's segments, built
from the sittings the piece was played in. Fetch it with the practice read that already exists:

```ts
  /** Segments of this piece's sittings, so a take can name the passage it came from. */
  let segments = $state<Map<number, SegmentSummary>>(new Map());

  async function loadSegments(): Promise<void> {
    // Only the sittings that actually produced a take: a piece can hold hundreds of segments
    // across years of practice, and fetching them all to label two takes is the wrong trade.
    const sittingIds = [
      ...new Set(
        (detail?.media ?? [])
          .filter((row) => row.source === 'captured' && row.sitting_id !== null)
          .map((row) => row.sitting_id as number),
      ),
    ];
    const found = new Map<number, SegmentSummary>();
    for (const sittingId of sittingIds) {
      const sitting = await api.practice.sitting(sittingId).catch(() => null);
      for (const segment of sitting?.segments ?? []) found.set(segment.id, segment);
    }
    segments = found;
  }
```

Call it from `afterWrite(pieceId)` so a new take refreshes the labels, and from `open(pieceId)`.

### Step 5.4 — verify

```bash
cd frontend && npm test && npm run check && npm run build
```

---

## Task 6 — the permission, the browser proof and the docs

**Files.** modify `deploy/chromium-policy.json`, `deploy/README.md`, `docs/DEPLOYMENT.md`,
`backend/tools/e2e_browser.py`, `backend/app/models.py`, `backend/app/repertoire/api.py`,
`README.md`, `AGENT-LOG.md`, `docs/ECOSYSTEM.md`.

### Step 6.1 — the kiosk permission

`deploy/chromium-policy.json`:

```json
{
  "MidiAllowedForUrls": ["http://localhost:8000", "http://127.0.0.1:8000"],
  "AudioCaptureAllowedForUrls": ["http://localhost:8000", "http://127.0.0.1:8000"],
  "AudioCaptureAllowed": false,
  "HighEfficiencyModeEnabled": false
}
```

`AudioCaptureAllowed: false` is the important half and is easy to get wrong: without it Chromium
grants audio capture to **every** origin, not only the two named. The named list is the whole
permission; the boolean is what keeps it from being a blanket yes.

Document both in `deploy/README.md` (beside the MIDI permission paragraph) and in
`docs/DEPLOYMENT.md`, in the same terms: the piano machine's kiosk is *automatically* granted the
microphone for its own origin, and nothing else is. Also update the installer's own echo, which
currently says `==> Browser policy (MIDI auto-grant, Memory Saver off)` (`deploy/install.sh:167`), so
somebody reading the install output learns that the policy now grants the microphone too.

### Step 6.2 — the size report

In `backend/app/models.py`, `SystemStatus` gains:

```python
    #: Bytes of audio this app recorded, reported rather than pruned: captured audio is the half of
    #: the library that may be deleted, and the player decides that (20e-D6).
    captured_audio_bytes: int = 0
```

and wherever `SystemStatus` is assembled (find it with
`grep -n "SystemStatus(" backend/app/main.py`), pass `captured_audio_bytes=store.captured_bytes(conn)`.
Add the matching field to `SystemStatus` in `frontend/src/lib/types.ts` and a line to the System card
in `PracticeLogView.svelte`:

```svelte
        <span class="muted small">Recorded here</span>
        <strong>{formatSize(status.captured_audio_bytes)}</strong>
        <span class="muted small">takes this app captured — delete them in Repertoire</span>
```

### Step 6.3 — the browser proof

The harness launches Chromium itself, so the fake microphone is two flags. In
`backend/tools/e2e_browser.py`'s launch args (`:3137-3142`) add:

```python
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
```

`--use-fake-ui-for-media-stream` answers the permission prompt, which is what the kiosk policy does
in the real deployment — so the scenario exercises the same code path without a prompt.

Add `scenario_takes`, registered after `scenario_repertoire`:

```python
def scenario_takes(browser) -> None:
    print("\n[14] Takes: recording what was played, and hearing it slower")
    clear_practice()
    if not api("/api/repertoire/pieces"):
        seed_library(1)
    piece = api("/api/repertoire/pieces")[0]

    page, errors = new_page(browser)
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector("text=Sight-Reading Trainer")
    ensure_midi(page)

    # --- arming reports a real device, not a hopeful switch ---
    with page.expect_response(lambda r: "/api/repertoire/takes" in r.url, timeout=30_000):
        click_button(page, "Record takes")
        play_phrase(page, [60, 64, 67])
        # The take closes on the server's own silence gap, which is 8 s by default.
        page.wait_for_timeout(11_000)
    check(
        page.locator('[data-audio-device="ready"]').count() == 1,
        "the switch reports the microphone it actually got",
    )

    # --- the take is attached to the playing it came from ---
    takes = api(f"/api/repertoire/pieces/{piece['id']}")["media"]
    captured = [row for row in takes if row["source"] == "captured"]
    check(len(captured) >= 1, f"a take was recorded and catalogued ({len(captured)})")
    check(
        captured[0]["sitting_id"] is not None,
        "and it is tied to the playing it was cut from",
    )

    # --- and it plays, at a speed that does not change it ---
    page.click("text=Repertoire")
    page.wait_for_selector(f'[data-take="{captured[0]["id"]}"]', timeout=20_000)
    # The speed control lives in the player's toolbar, which is rendered only once the
    # waveform is open — so the toggle is part of the path, not an optional extra.
    page.click(f'[data-take="{captured[0]["id"]}"] [data-waveform-toggle]')
    page.wait_for_selector('[data-take] select[aria-label="Playback speed"]', timeout=10_000)
    page.select_option('[data-take] select[aria-label="Playback speed"]', "0.5")
    page.wait_for_timeout(300)
    check(
        page.evaluate(
            f"() => document.querySelector('[data-take=\"{captured[0]['id']}\"] audio').playbackRate"
        )
        == 0.5,
        "half speed is applied to the element",
    )
    check(
        page.locator('[data-rate-note="same-pitch"]').count() == 1,
        "and the readout says whether pitch is held",
    )

    check(not errors, f"no console errors ({errors})")
```

**Two things to verify before trusting this scenario.** `play_phrase` sends notes through the fake
MIDI device and the *note* capture, and the audio recorder sees the same `lastNoteMs` — so a phrase
played through the fake device is enough to open and close a take, with no real sound. And the wait
must exceed the segment gap plus one tick: read the gap from `/api/practice/status` and wait
`gap + 3` seconds rather than hardcoding 11, or the scenario breaks the first time
`SRT_SEGMENT_GAP_S` is changed:

```python
    gap_s = api("/api/practice/status")["segment_gap_s"]
    ...
    page.wait_for_timeout((gap_s + 3) * 1000)
```

### Step 6.4 — run the scenarios

```bash
cd frontend && npm run build >/dev/null && cd .. && backend/tools/run_e2e.sh takes
```

Expected: every assertion `ok`, ending `All browser scenarios passed.` Then the remaining
falsifications:

```bash
backend/tools/falsify.sh backend/tools/falsifications/drop_capture_segment_link.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_repertoire.py"
backend/tools/falsify.sh backend/tools/falsifications/drop_media_source_column.sh \
  "cd backend && .venv/bin/python -m pytest -q tests/test_migration_upgrade.py"
backend/tools/falsify.sh backend/tools/falsifications/cut_takes_at_the_wrong_gap.sh \
  "cd frontend && npm test"
```

### Step 6.5 — docs

`README.md`, in the practice-log section, after the falling-notes paragraph:

```markdown
**Takes.** Press *Record takes* in the device bar and the app records the piano while you play —
mono Opus at about 14 MB an hour, which is a convenience rather than an archive: the piano's own
recording to a USB stick is still the one to keep. A take opens on the first note, closes when you
stop for as long as a segment boundary, and lands attached to the passage it came from. It appears
under **Takes this app recorded** on the piece, where two takes can be put side by side and either
can be played at 0.85×, 0.7× or 0.5× — slower at the same pitch, which the readout states rather
than assumes. A machine with no audio input says so instead of arming a switch that records nothing.
Nothing is deleted for you: the System panel reports how much captured audio there is, and deleting
a take is a click on the piano machine.
```

`AGENT-LOG.md` gains a landed entry following its § *Entry format*, naming: the four columns, the new
route, the fake-media test flags, the `AudioCaptureAllowed: false` detail, that a take is an ordinary
media row, and the falsifications.

`docs/ECOSYSTEM.md`: the Phase 20 row becomes `**Phase 20 landed in full (20a–20e).**` and the 20e
heading is marked `— landed` with a pointer to this plan.

### Step 6.6 — the full tier and the commit

```bash
./check.sh --full
git add -A backend frontend deploy docs README.md AGENT-LOG.md
git commit -m "Phase 20e: audio takes"
```

---

## Risks

| Risk | Treatment |
| --- | --- |
| The machine has no microphone and the switch looks armed | `getUserMedia`'s failure is classified into *denied* and *unavailable*, both rendered, and the browser scenario asserts the ready state rather than the button. A switch that cannot record says so |
| A take uploads while the sitting is still open and loses its segment | `sitting_at` resolves the sitting from the epoch even with no segments, `segment_at` honestly returns nothing, and the next take for that sitting links the ones still missing. Nothing depends on a background job, and a take always keeps its sitting |
| Audio and notes disagree about where a passage ended | The client never holds the rule: `PracticeStatus.segment_gap_s` is the only copy, and `cut_takes_at_the_wrong_gap.sh` proves the boundary case is asserted |
| The kiosk grants the microphone to everything | `AudioCaptureAllowed: false` alongside the named origins, and both are documented in the two deployment documents |
| Captured audio grows without bound | ~14 MB an hour by construction (mono, 32 kbps, and no recording of silence). Reported in the System panel and deleted by hand; no retention policy, because a policy that deletes a take the player wanted is worse than a disk filling up slowly |
| A duplicate take is refused as a server error | Content-addressing makes an identical take the same file, so the route returns a 409 with a reason, and the test asserts it |
| The takes list disappears into the largest component | `TakeList.svelte` is its own component and `RepertoireView` gains one mount and one loader |

## Retirement

- **Nothing is retired.** The recording upload route keeps its behaviour and writes
  `source='uploaded'`; the media reads keep their shape and gain four fields.
- **The capture client and the cutter** are two files with one consumer. Deleting the feature is
  those files, one route, one panel and one button — and `source='captured'` leaves the rows
  identifiable if the player wants them gone.
- **`link_unlinked_takes`** exists only for the open-sitting case; if segments ever became available
  at capture time, deleting it changes nothing about the data.

## ADR / baseline-sync signals

- **20-D4** is implemented as written: quality is not an acceptance criterion, the take is not an
  archive, and nothing prunes it. The bitrate is the consequence, not the goal.
- **20e-D3** (attachment by epoch range, server-side) and **20e-D5** (the repertoire domain keeps
  writing `media` while reading practice tables read-only) are durable boundary decisions with real
  alternatives — a client-named segment, or a practice-owned media writer — both rejected for stated
  reasons. They belong beside `sitting_exists`'s existing note.
- On completion the baseline-sync question is: *is the repertoire domain still the only writer of
  `media`, and does anything recorded depend on a score the app does not have?* The answers must be
  yes and no.

---

```text
Execution Readiness View:
- Intent Lock: record the piano through the machine the app runs on, at a quality honestly labelled
  as convenience; attach each take to the passage it came from; and let two takes be compared by ear,
  including slower at the same pitch
- Scope Fence: in — four media columns, the practice-status segment gap, one route, the cutter and the capture
  client, the takes view, the rate control, the kiosk permission, the size report, one browser
  scenario, docs. Out — archival quality, a retention policy, cross-take mixing or alignment, remote
  capture from the LAN client, and anything that would need a score
- Baseline Lock: ECOSYSTEM.md § 20e + 20-D4; the re-read gate; a clean tree before every falsification
- Approved Behavior: 20e's six acceptance bullets
- Owner / Contract Constraints: the repertoire domain writes `media` and reads practice tables
  read-only; the client cuts on the server's rule and never names a segment; the pipeline is shared,
  not reimplemented
- Compatibility Boundary: four additive nullable media columns, one additive host field, one new
  route; the recording upload route is untouched; SCHEMA_VERSION 3 -> 4; BACKUP_VERSION unchanged
- Retirement Boundary: nothing retired; the capture files, the route and the panel retire together
- Task Batches: 1 the segment gap, 2 the media columns, 3 the attachment, 4 the capture client,
  5 the takes view and rate, 6 the permission, the browser proof and docs
- Test Obligations: two migration tests, four attachment tests, three cutter units, six browser
  assertions, three committed break scripts
- Review Gates: after Task 3 (the server surface is complete and a take can be catalogued) and after
  Task 6 (--full green)
- Drift / Rewind Rules: if a step needs a background job, a retention policy, a client-named segment,
  or a second writer of `media`, stop and return to the spec
- Evidence Required Before Completion: ./check.sh --full passing; all three falsifications reported
  as "falsified"; the take-attachment assertions green; the microphone reported honestly on a machine
  without one; the AGENT-LOG entry appended
- Advisory Boundary: method-pack execution guidance only; not GateDecision, PolicySnapshot, or
  completion authority
```

```text
Execution Route:
- Decision: inline
- Evidence: six tasks, sequential on the repertoire store/route and the client capture path, ending
  in a browser run that needs a built frontend; the risk is concentrated in Task 4, which is one
  module and one pure decision
- Fallback: if `MediaRecorder` proves unavailable in the harness's Chromium, the browser scenario
  calls `skip("scenario_takes", reason)` rather than passing quietly — the harness fails on an
  unexplained skip, which is the behaviour Slice 0 built for exactly this
- User confirmation required: no
```

**This is the last plan in Phase 20.** With 20a landed and 20b–20e planned, the phase is fully
specified; executing the remaining four in order is the next work.
