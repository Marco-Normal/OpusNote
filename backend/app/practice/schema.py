"""Practice domain schema.

Owns six tables and one column-set, executed by the single initialiser in
:mod:`app.db`. Times are epoch milliseconds — authoritative — alongside
human-readable UTC text, because re-deriving a session start from a
second-precision timestamp would round every onset and quietly destroy every
tempo measurement.

``segments.piece_id`` references the repertoire's ``pieces`` table. That table is
created by a script that runs before this one, so the reference resolves on the
first insert.
"""

from __future__ import annotations

PRACTICE_SCHEMA = """
-- One continuous stretch at the piano, inferred from silence. Called a
-- "sitting" everywhere, including the API, so it is never confused with a
-- workout or with an exercise.
CREATE TABLE IF NOT EXISTS sittings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_ms    INTEGER NOT NULL,
    ended_ms      INTEGER NOT NULL,      -- provisional until the gap closes
    started_at    TEXT NOT NULL,         -- UTC, for humans and SQL tools
    ended_at      TEXT NOT NULL,
    local_date    TEXT NOT NULL,         -- YYYY-MM-DD in the player's timezone
    source        TEXT NOT NULL DEFAULT 'web_midi',
    -- Set when the sitting was closed by something other than silence: the piano
    -- being switched off, which is a far sooner answer to "are they done?" than
    -- waiting out the whole gap. A closed sitting takes no further notes — coming
    -- back after switching the piano off starts a new one, deliberately.
    closed_ms     INTEGER,
    -- The id this row had in the standalone practice-logger, or NULL. Importing
    -- matches on this rather than on the primary key, for the same reason the
    -- repertoire importer does: the two id spaces are independent, and colliding
    -- them lets a re-import overwrite something recorded here.
    legacy_id     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sittings_date ON sittings(local_date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sittings_legacy
    ON sittings(legacy_id) WHERE legacy_id IS NOT NULL;

-- Every raw MIDI note. This is the long-term gold; every metric is recomputable.
CREATE TABLE IF NOT EXISTS note_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sitting_id   INTEGER NOT NULL REFERENCES sittings(id) ON DELETE CASCADE,
    onset_ms     INTEGER NOT NULL,       -- ms since the sitting start
    duration_ms  INTEGER NOT NULL,
    pitch        INTEGER NOT NULL,
    velocity     INTEGER NOT NULL,
    channel      INTEGER
);
-- Makes a retried batch idempotent via INSERT OR IGNORE. Two genuinely distinct
-- notes at the same millisecond and pitch are not physically playable, so the
-- collision cost is zero; without it a dropped response double-counts notes.
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_dedupe
    ON note_events(sitting_id, onset_ms, pitch);
CREATE INDEX IF NOT EXISTS idx_events_sitting ON note_events(sitting_id, onset_ms);

-- Sustain-pedal moves, raw CC64. Stored as a stream of values rather than as
-- derived "pedal down from X to Y" intervals: intervals need an up that may
-- never arrive (a device unplugged mid-passage), and playback can close the last
-- one at the end of the sitting. Nothing here is recomputable from the notes.
CREATE TABLE IF NOT EXISTS pedal_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sitting_id   INTEGER NOT NULL REFERENCES sittings(id) ON DELETE CASCADE,
    onset_ms     INTEGER NOT NULL,       -- ms since the sitting start
    value        INTEGER NOT NULL,       -- the CC value; 64 and above is down
    channel      INTEGER
);
-- The same idempotence as note_events: a retried batch must not double a pedal
-- move, and two genuine moves at one millisecond with one value cannot happen.
CREATE UNIQUE INDEX IF NOT EXISTS idx_pedals_dedupe
    ON pedal_events(sitting_id, onset_ms, value);
CREATE INDEX IF NOT EXISTS idx_pedals_sitting ON pedal_events(sitting_id, onset_ms);

-- Places the player asked to come back to, pressed on the sostenuto.
--
-- Its own stream rather than a column on `pedal_events`: that table is CC64 by contract, and
-- routing CC66 into it would record the middle pedal as sustain and corrupt `pedal_blur` and
-- `pedal_basis`. Raw like the pedal stream rather than derived, because nothing in the notes
-- records that a person asked to come back — but *only* deliberate marks, so an unbound pedal
-- writes nothing here.
CREATE TABLE IF NOT EXISTS sitting_marks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sitting_id   INTEGER NOT NULL REFERENCES sittings(id) ON DELETE CASCADE,
    onset_ms     INTEGER NOT NULL,       -- ms since the sitting start
    epoch_ms     INTEGER NOT NULL        -- what the piano's clock said, for debugging
);
-- The same idempotence as note_events and pedal_events: a retried batch must not double a mark,
-- and two deliberate marks in one millisecond are not physically playable.
CREATE UNIQUE INDEX IF NOT EXISTS idx_marks_dedupe ON sitting_marks(sitting_id, onset_ms);
CREATE INDEX IF NOT EXISTS idx_marks_sitting ON sitting_marks(sitting_id, onset_ms);

-- Every machine guess that was acted on. Without it, "how often is the matcher
-- right?" is answerable only from memory, and the accept/reject buttons would be
-- advice the app forgets the moment it is taken.
--
-- `segment_id` is nullable and SET NULL, not CASCADE. A guess that was made and
-- judged is a fact about the matcher whether or not the boundary it was made under
-- still exists, and `resegment` deletes and rebuilds every segment of a sitting — so
-- a cascade here destroyed the very history this table exists to keep, shrinking the
-- accuracy panel's denominators with no trace. The row survives with no segment; it
-- simply cannot suppress a suggestion for a segment that is gone.
--
-- `action` is what happened to the guess:
--   confirmed — the inferred label was left alone and taken ownership of
--   changed   — the inferred label was overwritten with a different piece
--   rejected  — the inferred label was cleared
--   dismissed — an offered match was declined, so nothing was ever written
-- The live accuracy is confirmed / (confirmed + changed + rejected): only guesses
-- that were actually written can be wrong in the log. Dismissals are recorded so
-- the app stops asking, not so they count as errors.
CREATE TABLE IF NOT EXISTS identification_outcomes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id         INTEGER REFERENCES segments(id) ON DELETE SET NULL,
    guessed_piece_id   INTEGER,
    resolved_piece_id  INTEGER,
    action             TEXT NOT NULL,
    accepted           INTEGER NOT NULL,
    score              REAL,
    resolved_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_outcomes_segment ON identification_outcomes(segment_id);

-- A contiguous chunk of a sitting believed to be one piece or one workout.
CREATE TABLE IF NOT EXISTS segments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sitting_id      INTEGER NOT NULL REFERENCES sittings(id) ON DELETE CASCADE,
    start_ms        INTEGER NOT NULL,
    end_ms          INTEGER NOT NULL,
    -- ON DELETE SET NULL, not CASCADE: deleting a piece must orphan the segment
    -- back to "unidentified", never delete practice history.
    piece_id        INTEGER REFERENCES pieces(id) ON DELETE SET NULL,
    source          TEXT,                -- 'repertoire' | 'sight_reading' | NULL
    workout_id      INTEGER REFERENCES workouts(id) ON DELETE SET NULL,
    confidence      REAL,
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
);
CREATE INDEX IF NOT EXISTS idx_segments_sitting ON segments(sitting_id, start_ms);
CREATE INDEX IF NOT EXISTS idx_segments_piece ON segments(piece_id);

-- Derived metrics per segment, always recomputable from note_events. Stored
-- rather than computed per request so analytics can aggregate in SQL.
CREATE TABLE IF NOT EXISTS segment_metrics (
    segment_id       INTEGER PRIMARY KEY REFERENCES segments(id) ON DELETE CASCADE,
    duration_s       REAL,
    note_count       INTEGER,
    median_tempo     REAL,               -- BPM, measured over attack clusters
    mean_velocity    REAL,
    velocity_stddev  REAL,
    restarts         INTEGER,
    -- Pedal, derived from the raw CC64 stream. `pedal_basis` records which harmony
    -- source produced `pedal_blur`: a score attached in March must not retroactively
    -- relabel January's observed number as score-derived, which is the same rule
    -- `identified_by` and `media.state` follow. NULL basis means no pedal rows for
    -- the sitting at all — imported history — which is not the same as "not used".
    pedal_changes    INTEGER,
    pedal_down_ratio REAL,
    pedal_blur       INTEGER,
    -- Where those attacks were, as a JSON array of ms relative to the sitting, ascending.
    -- `pedal_blur` above is its length. Stored together because `_refresh_metrics` has the
    -- notes and the pedal stream in hand when it computes both, so a position costs nothing
    -- to keep — while re-deriving it on the detail read would put a pass over `note_events`
    -- on the read the timeline uses most.
    pedal_blur_ms    TEXT,
    pedal_basis      TEXT,
    -- Touch, at MIDI controller resolution. Comparable with itself over weeks; not a
    -- claim about loudness, and not comparable with another instrument's.
    median_velocity    REAL,
    velocity_range     REAL,
    -- The same means split at middle C, as a *proxy* for the hands: the piano sends
    -- both hands on one channel, so there is nothing better in a passive log.
    mean_velocity_low  REAL,
    mean_velocity_high REAL
);

-- The version of the matcher's training material, maintained by the triggers below.
--
-- A fingerprint and a content feature per labelled segment are derived from the notes on
-- every read, and on a real library that is about a second of work over a quarter of a
-- million notes producing an answer that only changes when a label or a boundary does. This
-- row is what lets a process keep that answer: the triggers make invalidation the database's
-- job, so no write path — this build's, an older one's, or the other machine's over the LAN
-- — can change the references without the version saying so.
CREATE TABLE IF NOT EXISTS reference_state (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO reference_state (id, version) VALUES (1, 0);

CREATE TRIGGER IF NOT EXISTS trg_segments_reference_insert
AFTER INSERT ON segments
BEGIN
    UPDATE reference_state SET version = version + 1 WHERE id = 1;
END;

-- Only the columns the derived material is a function of. A practice kind or a confidence
-- is not part of a fingerprint or a content feature, and invalidating on those would throw
-- the cache away for a whole sitting every time an offer was answered.
CREATE TRIGGER IF NOT EXISTS trg_segments_reference_update
AFTER UPDATE OF piece_id, identified_by, start_ms, end_ms ON segments
BEGIN
    UPDATE reference_state SET version = version + 1 WHERE id = 1;
END;

CREATE TRIGGER IF NOT EXISTS trg_segments_reference_delete
AFTER DELETE ON segments
BEGIN
    UPDATE reference_state SET version = version + 1 WHERE id = 1;
END;
"""


#: Columns added after the first release of *this* app. Additive only, so
#: running it against a database created by an earlier version is safe.
ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("sittings", "legacy_id", "INTEGER"),
    ("sittings", "closed_ms", "INTEGER"),
    ("segments", "source", "TEXT"),
    # D1: the CREATE at :118 declares this ON DELETE SET NULL; an ALTER that omits the
    # reference leaves upgraded databases with a dangling `workout_id` when a workout is
    # deleted. SQLite accepts REFERENCES on ADD COLUMN because the default is NULL.
    ("segments", "workout_id", "INTEGER REFERENCES workouts(id) ON DELETE SET NULL"),
    # Phase 18b — the measurements the app already had the data for.
    ("segment_metrics", "pedal_changes", "INTEGER"),
    ("segment_metrics", "pedal_down_ratio", "REAL"),
    ("segment_metrics", "pedal_blur", "INTEGER"),
    ("segment_metrics", "pedal_blur_ms", "TEXT"),
    ("segment_metrics", "pedal_basis", "TEXT"),
    ("segment_metrics", "median_velocity", "REAL"),
    ("segment_metrics", "velocity_range", "REAL"),
    ("segment_metrics", "mean_velocity_low", "REAL"),
    ("segment_metrics", "mean_velocity_high", "REAL"),
    # Phase 20a — how a segment was practised, as a second axis from `source`, which
    # owns *what produced* the segment rather than how it went.
    ("segments", "practice_kind", "TEXT"),
    ("segments", "practice_kind_basis", "TEXT"),
)


def migrate(conn) -> list[str]:
    """Bring an existing database up to the current schema. Returns what changed.

    Runs *before* ``PRACTICE_SCHEMA``: on a fresh database the tables do not exist
    yet and are skipped (the script creates them whole), while on an existing one
    the new columns are added before anything indexes them.
    """
    applied: list[str] = []
    for table, column, kind in ADDED_COLUMNS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            applied.append(f"{table}.{column}")
    applied.extend(_detach_outcomes_from_segments(conn))
    return applied


def _detach_outcomes_from_segments(conn) -> list[str]:
    """Stop a re-segment from deleting the matcher's track record.

    ``identification_outcomes.segment_id`` was NOT NULL with ``ON DELETE CASCADE``,
    and ``resegment`` deletes and rebuilds every segment of a sitting — so the one
    action the app offers for fixing a bad boundary silently destroyed the history
    the accuracy panel's denominators are made of.

    SQLite cannot alter a constraint, so this is a table rebuild. It is idempotent:
    the shape check is the NOT NULL on ``segment_id``, which only the old table has,
    and a table that does not exist yet is left to the CREATE script.
    """
    columns = list(conn.execute("PRAGMA table_info(identification_outcomes)"))
    if not columns:
        return []  # fresh database; the CREATE above is already the new shape
    by_name = {row[1]: row for row in columns}
    if not by_name["segment_id"][3]:
        return []  # already nullable
    conn.executescript(
        """
        CREATE TABLE identification_outcomes_rebuilt (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            segment_id         INTEGER REFERENCES segments(id) ON DELETE SET NULL,
            guessed_piece_id   INTEGER,
            resolved_piece_id  INTEGER,
            action             TEXT NOT NULL,
            accepted           INTEGER NOT NULL,
            score              REAL,
            resolved_at        TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO identification_outcomes_rebuilt
            (id, segment_id, guessed_piece_id, resolved_piece_id, action,
             accepted, score, resolved_at)
            SELECT id, segment_id, guessed_piece_id, resolved_piece_id, action,
                   accepted, score, resolved_at
            FROM identification_outcomes;
        DROP TABLE identification_outcomes;
        ALTER TABLE identification_outcomes_rebuilt RENAME TO identification_outcomes;
        CREATE INDEX IF NOT EXISTS idx_outcomes_segment
            ON identification_outcomes(segment_id);
        """
    )
    return ["identification_outcomes.segment_id -> ON DELETE SET NULL"]
