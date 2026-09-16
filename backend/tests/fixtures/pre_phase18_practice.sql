-- A frozen pre-Phase-18 SighRTracker database, as SQL text rather than a binary.
--
-- This is the schema an earlier release left behind: the CREATE scripts in
-- `backend/app/db.py`, `practice/schema.py`, `repertoire/schema.py` and
-- `workout/schema.py` with exactly the `ADDED_COLUMNS` entries removed, so the only
-- way to reach the current shape is `db.init_db` running its migration. That is the
-- point: the migration path runs on the player's real database and had never run in
-- the suite, so a fixture that is silently kept in step with today's schema would
-- prove nothing. `test_migration_upgrade.py` asserts this *pre* shape first, which is
-- what stops a later "fix the fixture" edit from quietly deleting the coverage.
--
-- Deliberately old shapes, in addition to the missing additive columns:
--   * `identification_outcomes.segment_id` is `NOT NULL ... ON DELETE CASCADE`, the
--     shape Phase 18b replaced with a nullable `SET NULL` table rebuild.
--   * `performances` has no `workout_id`; on a fresh database that column exists only
--     because `workout/schema.py`'s `ADDED_COLUMNS` ALTERs it in.
--
-- One row per table, including one `identification_outcomes` row and one
-- `segment_metrics` row carrying all seven old columns. The rows are consistent
-- enough to survive SQLite's deferred foreign-key check at COMMIT.

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE skills (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slug          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL UNIQUE,
    description   TEXT,
    sort_order    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE user_skills (
    user_id           INTEGER NOT NULL,
    skill_id          INTEGER NOT NULL,
    elo_rating        REAL NOT NULL DEFAULT 700.0,
    attempts          INTEGER NOT NULL DEFAULT 0,
    last_practiced_at TIMESTAMP,
    PRIMARY KEY (user_id, skill_id),
    FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE CASCADE,
    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
);

CREATE TABLE exercises (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    musicxml_blob   TEXT NOT NULL,
    difficulty_elo  REAL NOT NULL,
    key_name        TEXT,
    meter           TEXT,
    bars            INTEGER,
    tempo_bpm       REAL,
    generator_seed  INTEGER,
    source          TEXT NOT NULL DEFAULT 'generated',
    params_json     TEXT,
    expected_json   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE exercise_skills (
    exercise_id INTEGER NOT NULL,
    skill_id    INTEGER NOT NULL,
    level       INTEGER NOT NULL,
    PRIMARY KEY (exercise_id, skill_id),
    FOREIGN KEY (exercise_id) REFERENCES exercises(id) ON DELETE CASCADE,
    FOREIGN KEY (skill_id)    REFERENCES skills(id)    ON DELETE CASCADE
);

-- No `workout_id`: that column is added by `workout/schema.py`'s ADDED_COLUMNS.
CREATE TABLE performances (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL,
    exercise_id         INTEGER NOT NULL,
    score               REAL,
    pitch_accuracy      REAL,
    rhythm_accuracy     REAL,
    continuity_accuracy REAL,
    mode                TEXT NOT NULL DEFAULT 'practice',
    tempo_bpm           REAL,
    latency_ms          REAL DEFAULT 0,
    played_notes_json   TEXT,
    analysis_json       TEXT,
    performed_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id)     REFERENCES users(id)     ON DELETE CASCADE,
    FOREIGN KEY (exercise_id) REFERENCES exercises(id) ON DELETE CASCADE
);

CREATE INDEX idx_performances_user_time
    ON performances (user_id, performed_at DESC);

CREATE TABLE rating_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    skill_id       INTEGER NOT NULL,
    before         REAL NOT NULL,
    after          REAL NOT NULL,
    score          REAL,
    performance_id INTEGER REFERENCES performances(id) ON DELETE SET NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE CASCADE,
    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
);
CREATE INDEX idx_rating_events_skill
    ON rating_events (user_id, skill_id, id);
CREATE INDEX idx_exercise_skills_skill
    ON exercise_skills (skill_id);

-- Repertoire, with no `legacy_id` on any table, no `sitting_id` on `piece_journal`,
-- and no loop points on `media`. The partial `legacy_id` indexes are absent with the
-- column; `db.init_db` recreates them once the migration has added it.

CREATE TABLE composers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    notes       TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE pieces (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    composer_id  INTEGER REFERENCES composers(id) ON DELETE SET NULL,
    title        TEXT NOT NULL,
    opus         TEXT,
    difficulty   TEXT,
    key          TEXT,
    started_on   TEXT,
    status       TEXT NOT NULL DEFAULT 'active',
    description  TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_pieces_composer ON pieces (composer_id);
CREATE INDEX idx_pieces_status ON pieces (status);

CREATE TABLE piece_journal (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    piece_id          INTEGER NOT NULL REFERENCES pieces(id) ON DELETE CASCADE,
    entry_date        TEXT NOT NULL,
    content           TEXT NOT NULL,
    practice_minutes  INTEGER,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_journal_piece ON piece_journal (piece_id, entry_date DESC);
CREATE INDEX idx_journal_date ON piece_journal (entry_date DESC, id DESC);

CREATE TABLE media (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    piece_id       INTEGER REFERENCES pieces(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL,
    file_name      TEXT NOT NULL UNIQUE,
    original_name  TEXT,
    title          TEXT,
    duration_secs  REAL,
    size_bytes     INTEGER,
    codec          TEXT,
    taken_on       TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_media_piece ON media (piece_id);

-- Practice, without `sittings.legacy_id`/`closed_ms`, without
-- `segments.source`/`workout_id`, without the eight Phase 18b `segment_metrics`
-- columns, and with the old cascading outcome reference.

CREATE TABLE sittings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_ms    INTEGER NOT NULL,
    ended_ms      INTEGER NOT NULL,
    started_at    TEXT NOT NULL,
    ended_at      TEXT NOT NULL,
    local_date    TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT 'web_midi'
);
CREATE INDEX idx_sittings_date ON sittings(local_date DESC);

CREATE TABLE note_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sitting_id   INTEGER NOT NULL REFERENCES sittings(id) ON DELETE CASCADE,
    onset_ms     INTEGER NOT NULL,
    duration_ms  INTEGER NOT NULL,
    pitch        INTEGER NOT NULL,
    velocity     INTEGER NOT NULL,
    channel      INTEGER
);
CREATE UNIQUE INDEX idx_events_dedupe
    ON note_events(sitting_id, onset_ms, pitch);
CREATE INDEX idx_events_sitting ON note_events(sitting_id, onset_ms);

CREATE TABLE pedal_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sitting_id   INTEGER NOT NULL REFERENCES sittings(id) ON DELETE CASCADE,
    onset_ms     INTEGER NOT NULL,
    value        INTEGER NOT NULL,
    channel      INTEGER
);
CREATE UNIQUE INDEX idx_pedals_dedupe
    ON pedal_events(sitting_id, onset_ms, value);
CREATE INDEX idx_pedals_sitting ON pedal_events(sitting_id, onset_ms);

-- The old shape: NOT NULL with ON DELETE CASCADE, which a re-segment would use to
-- destroy the matcher's history. `_detach_outcomes_from_segments` rebuilds it.
CREATE TABLE identification_outcomes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id         INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    guessed_piece_id   INTEGER,
    resolved_piece_id  INTEGER,
    action             TEXT NOT NULL,
    accepted           INTEGER NOT NULL,
    score              REAL,
    resolved_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_outcomes_segment ON identification_outcomes(segment_id);

CREATE TABLE segments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sitting_id      INTEGER NOT NULL REFERENCES sittings(id) ON DELETE CASCADE,
    start_ms        INTEGER NOT NULL,
    end_ms          INTEGER NOT NULL,
    piece_id        INTEGER REFERENCES pieces(id) ON DELETE SET NULL,
    confidence      REAL,
    identified_by   TEXT
);
CREATE INDEX idx_segments_sitting ON segments(sitting_id, start_ms);
CREATE INDEX idx_segments_piece ON segments(piece_id);

-- The seven columns an earlier release had; the eight pedal/touch columns arrive
-- through `practice/schema.py`'s ADDED_COLUMNS.
CREATE TABLE segment_metrics (
    segment_id       INTEGER PRIMARY KEY REFERENCES segments(id) ON DELETE CASCADE,
    duration_s       REAL,
    note_count       INTEGER,
    median_tempo     REAL,
    mean_velocity    REAL,
    velocity_stddev  REAL,
    restarts         INTEGER
);

CREATE TABLE workouts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_ms    INTEGER NOT NULL,
    ended_ms      INTEGER,
    local_date    TEXT NOT NULL,
    target_skill  TEXT,
    bars          INTEGER,
    planned       INTEGER,
    completed     INTEGER NOT NULL DEFAULT 0,
    sitting_id    INTEGER REFERENCES sittings(id) ON DELETE SET NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_workouts_date ON workouts(local_date DESC);
CREATE INDEX idx_workouts_open ON workouts(ended_ms);

-- One row per table. Times are epoch milliseconds, as the app stores them.
INSERT INTO users (id, username, created_at) VALUES (1, 'player', '2026-01-05 09:00:00');
INSERT INTO skills (id, slug, name, description, sort_order)
    VALUES (1, 'rhythm', 'Rhythm', 'Steady pulse and subdivision', 1);
INSERT INTO user_skills (user_id, skill_id, elo_rating, attempts, last_practiced_at)
    VALUES (1, 1, 705.0, 3, '2026-01-05 10:01:00');
INSERT INTO exercises
    (id, musicxml_blob, difficulty_elo, key_name, meter, bars, tempo_bpm, generator_seed,
     source, params_json, expected_json, created_at)
    VALUES (1, '<score-partwise/>', 700.0, 'C', '4/4', 4, 100.0, 42, 'generated',
            '{"levels":{"rhythm":3},"target_skill":"rhythm"}', '[]', '2026-01-05 09:00:00');
INSERT INTO exercise_skills (exercise_id, skill_id, level) VALUES (1, 1, 3);
INSERT INTO performances
    (id, user_id, exercise_id, score, pitch_accuracy, rhythm_accuracy, continuity_accuracy,
     mode, tempo_bpm, latency_ms, played_notes_json, analysis_json, performed_at)
    VALUES (1, 1, 1, 88.0, 0.9, 0.8, 0.7, 'practice', 100.0, 0.0, '[]',
            '{"feedback":[],"levels":{},"by_hand":{},"weights":{}}',
            '2026-01-05 10:01:00');
INSERT INTO rating_events
    (id, user_id, skill_id, before, after, score, performance_id, created_at)
    VALUES (1, 1, 1, 700.0, 705.0, 88.0, 1, '2026-01-05 10:01:00');

INSERT INTO composers (id, name, notes, created_at)
    VALUES (1, 'Chopin', 'Romantic', '2026-01-05 09:00:00');
INSERT INTO pieces
    (id, composer_id, title, opus, difficulty, key, started_on, status, description,
     created_at)
    VALUES (1, 1, 'Nocturne', 'Op. 9 No. 2', 'Late Intermediate', 'E-flat Major',
            '2026-01-01', 'active', NULL, '2026-01-05 09:00:00');
INSERT INTO piece_journal
    (id, piece_id, entry_date, content, practice_minutes, created_at)
    VALUES (1, 1, '2026-01-05', 'Old-shape entry.', 30, '2026-01-05 09:30:00');
INSERT INTO media
    (id, piece_id, kind, file_name, original_name, title, duration_secs, size_bytes,
     codec, taken_on, created_at)
    VALUES (1, 1, 'audio', 'deadbeef.ogg', 'take.ogg', 'Take 1', 61.5, 1024, 'opus',
            '2026-01-05', '2026-01-05 09:40:00');

INSERT INTO sittings
    (id, started_ms, ended_ms, started_at, ended_at, local_date, source)
    VALUES (1, 1704434400000, 1704434420000, '2026-01-05 10:00:00',
            '2026-01-05 10:00:20', '2026-01-05', 'web_midi');
INSERT INTO note_events (id, sitting_id, onset_ms, duration_ms, pitch, velocity, channel)
    VALUES (1, 1, 0, 300, 60, 70, 0);
INSERT INTO pedal_events (id, sitting_id, onset_ms, value, channel)
    VALUES (1, 1, 200, 127, 0);
INSERT INTO segments
    (id, sitting_id, start_ms, end_ms, piece_id, confidence, identified_by)
    VALUES (1, 1, 0, 20000, 1, 1.0, 'manual');
INSERT INTO identification_outcomes
    (id, segment_id, guessed_piece_id, resolved_piece_id, action, accepted, score, resolved_at)
    VALUES (1, 1, 1, 1, 'confirmed', 1, 0.91, '2026-01-05 10:00:30');
INSERT INTO segment_metrics
    (segment_id, duration_s, note_count, median_tempo, mean_velocity, velocity_stddev, restarts)
    VALUES (1, 20.0, 1, 100.0, 70.0, 0.0, 0);
INSERT INTO workouts
    (id, started_ms, ended_ms, local_date, target_skill, bars, planned, completed,
     sitting_id, created_at)
    VALUES (1, 1704434400000, 1704435000000, '2026-01-05', 'rhythm', 4, 4, 4, 1,
            '2026-01-05 10:00:00');
