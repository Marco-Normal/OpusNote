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
    legacy_id         INTEGER,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_journal_legacy
    ON piece_journal(legacy_id) WHERE legacy_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_journal_piece ON piece_journal(piece_id, entry_date DESC);

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
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_media_legacy
    ON media(legacy_id) WHERE legacy_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_media_piece ON media(piece_id);
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
