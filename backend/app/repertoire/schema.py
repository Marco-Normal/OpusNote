"""Repertoire domain schema.

Kept apart from the SQL in :mod:`app.db` so the domain owns its own tables,
but executed by the same initialiser — one database, one creation path.

Column names deliberately mirror the Rust `piano-progress` schema so the
importer is a straight copy rather than a translation. The single rename is
`notes` -> `piece_journal`: in a database that also stores MIDI `note_events`,
a table called `notes` holding prose is a trap.
"""

from __future__ import annotations

REPERTOIRE_SCHEMA = """
CREATE TABLE IF NOT EXISTS composers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    notes       TEXT,
    -- The id this row had in the legacy piano-progress database, or NULL for
    -- rows created here. Importing matches on this rather than on the primary
    -- key, because the two id spaces are independent and colliding them lets an
    -- import overwrite a piece you created yourself.
    legacy_id   INTEGER,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_composers_legacy
    ON composers(legacy_id) WHERE legacy_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS pieces (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    composer_id  INTEGER REFERENCES composers(id) ON DELETE SET NULL,
    title        TEXT NOT NULL,
    opus         TEXT,
    difficulty   TEXT,
    key          TEXT,
    started_on   TEXT,
    status       TEXT NOT NULL DEFAULT 'active',
    description  TEXT,
    legacy_id    INTEGER,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pieces_legacy
    ON pieces(legacy_id) WHERE legacy_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pieces_composer ON pieces(composer_id);
CREATE INDEX IF NOT EXISTS idx_pieces_status ON pieces(status);

-- Dated prose about a piece. Was `notes` in piano-progress; see the module docstring.
CREATE TABLE IF NOT EXISTS piece_journal (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    piece_id          INTEGER NOT NULL REFERENCES pieces(id) ON DELETE CASCADE,
    entry_date        TEXT NOT NULL,
    content           TEXT NOT NULL,
    practice_minutes  INTEGER,
    -- The sitting this was written about, when it was written about one. The piece
    -- owns the entry and this is only context, which is why it is nullable and why
    -- the reference is SET NULL rather than CASCADE: deleting a sitting must never
    -- delete prose. It links to the *sitting* and not to a segment because
    -- `resegment` deletes and rebuilds every segment of a sitting, and an entry that
    -- the app's own correction action could orphan is not a durable link.
    --
    -- Declared here and in ADDED_COLUMNS so a database created before this column
    -- gets it too. `sittings` is created by the practice script, which runs after
    -- this one; SQLite resolves a foreign key at insert time, not at create time.
    sitting_id        INTEGER REFERENCES sittings(id) ON DELETE SET NULL,
    legacy_id         INTEGER,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_journal_legacy
    ON piece_journal(legacy_id) WHERE legacy_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_journal_piece ON piece_journal(piece_id, entry_date DESC);
CREATE INDEX IF NOT EXISTS idx_journal_sitting ON piece_journal(sitting_id);
CREATE INDEX IF NOT EXISTS idx_journal_date ON piece_journal(entry_date DESC, id DESC);

CREATE TABLE IF NOT EXISTS media (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    piece_id       INTEGER REFERENCES pieces(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL,
    file_name      TEXT NOT NULL UNIQUE,   -- content hash, as the Rust app names them
    original_name  TEXT,
    title          TEXT,
    duration_secs  REAL,
    size_bytes     INTEGER,
    codec          TEXT,
    taken_on       TEXT,
    legacy_id      INTEGER,
    -- The A/B practice loop, in seconds into the *stored* file. Kept in the
    -- database rather than in the browser so the same passage is found again
    -- from the other machine, and so it survives a reload.
    loop_start_s   REAL,
    loop_end_s     REAL,
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
    captured_start_ms INTEGER,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_media_legacy
    ON media(legacy_id) WHERE legacy_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_media_piece ON media(piece_id);
CREATE INDEX IF NOT EXISTS idx_media_segment ON media(segment_id);
CREATE INDEX IF NOT EXISTS idx_media_source ON media(source);
"""


#: Columns added after the first release. `CREATE TABLE IF NOT EXISTS` cannot
#: add a column to a database that already exists, so new columns are declared
#: here as well as in the schema above. Additive only: nothing here drops,
#: renames, or rewrites a column, so running it on an existing library is safe.
ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("composers", "legacy_id", "INTEGER"),
    ("pieces", "legacy_id", "INTEGER"),
    ("piece_journal", "legacy_id", "INTEGER"),
    ("media", "legacy_id", "INTEGER"),
    ("media", "loop_start_s", "REAL"),
    ("media", "loop_end_s", "REAL"),
    # SQLite only accepts a REFERENCES clause on ADD COLUMN when the default is
    # NULL, which is why the piece that owns the entry is NOT NULL and this is not.
    ("piece_journal", "sitting_id", "INTEGER REFERENCES sittings(id) ON DELETE SET NULL"),
    # Phase 20e — where a take came from. The default is expressed in the type string rather than
    # left to the read path: SQLite accepts a constant `DEFAULT` on `ADD COLUMN`, so an upgraded
    # database gets the same NOT NULL column a fresh one does, with its existing rows backfilled
    # to 'uploaded'. That matters beyond tidiness — the backup carries the column by name, and a
    # NULL here would be restored into a fresh database's NOT NULL column, where `merge` drops the
    # row silently and `replace` fails outright.
    ("media", "source", "TEXT NOT NULL DEFAULT 'uploaded'"),
    ("media", "sitting_id", "INTEGER REFERENCES sittings(id) ON DELETE SET NULL"),
    ("media", "segment_id", "INTEGER REFERENCES segments(id) ON DELETE SET NULL"),
    ("media", "captured_start_ms", "INTEGER"),
)


def migrate(conn) -> list[str]:
    """Bring an existing database up to the current schema. Returns what changed.

    Must run *before* `REPERTOIRE_SCHEMA` on an existing database: that script
    creates a partial index on `legacy_id`, which cannot succeed until the
    column exists.
    """
    applied: list[str] = []
    for table, column, kind in ADDED_COLUMNS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table not created yet; the schema above will handle it
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            applied.append(f"{table}.{column}")
    return applied
