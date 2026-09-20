"""Runtime configuration for the Opus Note API.

Everything is overridable by environment variable so the same code runs as a
local script (SQLite file next to the repo) or as a deployed service without a
code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


def _default_data_dir() -> Path:
    """The ecosystem's own data directory.

    Deliberately not `~/.local/share/piano-progress`: that directory belongs to
    the Rust app we are replacing, and borrowing another program's storage is what
    made the data look duplicated across machines.
    """
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "piano-ecosystem"


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    # --- persistence -----------------------------------------------------
    db_path: Path = _env_path("SRT_DB_PATH", _default_data_dir() / "piano.db")
    #: Where recordings live. Content-hashed file names, matching the Rust app,
    #: so an imported recording keeps working without renaming anything.
    media_dir: Path = _env_path("SRT_MEDIA_DIR", _default_data_dir() / "media")
    #: The sampled piano, downloaded once by `POST /api/audio/piano` and served
    #: from `/piano/...`. Kept with the data rather than in the build, because it is
    #: fetched at runtime and must survive a redeploy.
    piano_dir: Path = _env_path("SRT_PIANO_DIR", _default_data_dir() / "piano")
    #: The legacy `piano-progress` database, read once by the importer. Never written.
    legacy_db: Path = _env_path(
        "SRT_LEGACY_DB", Path.home() / ".local" / "share" / "piano-progress" / "piano.db"
    )

    # --- app -------------------------------------------------------------
    api_prefix: str = "/api"
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    frontend_dist: Path = _env_path("SRT_FRONTEND_DIST", REPO_DIR / "frontend" / "dist")

    # --- MVP single-user profile ----------------------------------------
    default_username: str = os.environ.get("SRT_USER", "local")

    # --- adaptive engine --------------------------------------------------
    # Exercise Elo = elo_base + elo_per_level * (mean_level - 1)
    #
    # `elo_base` is the Elo of the *easiest* material, and the ladder has to start
    # low enough that the practice offset still lands inside it. It did not: at 600
    # with a -220 offset, level 2 was unreachable below a rating of 870, so every
    # learner under that saw level 1 forever — 270 rating points of ability
    # collapsed into one level of material, and the exercises never got harder.
    #
    # 480 is where three constraints meet, and it is the only value that satisfies
    # all three:
    #   * the documented example — "a rating of 1000 gets exercises around Elo 780"
    #     — is *exactly* representable, because 780 = 480 + 3 x 100;
    #   * an unrated learner (default_rating, 700) still starts on level 1, since
    #     level 1 covers ratings up to 480 + 220 + 50 = 750;
    #   * it is the smallest such value, so levels open as early as they can.
    # The tests in `tests/test_adaptive.py` pin all three.
    elo_base: float = _env_float("SRT_ELO_BASE", 480.0)
    elo_per_level: float = _env_float("SRT_ELO_PER_LEVEL", 100.0)
    default_rating: float = _env_float("SRT_DEFAULT_RATING", 700.0)
    elo_k: float = _env_float("SRT_ELO_K", 32.0)
    elo_k_calibration: float = _env_float("SRT_ELO_K_CALIBRATION", 56.0)
    # How far around the target Elo an exercise may be picked.
    selection_window: float = _env_float("SRT_SELECTION_WINDOW", 60.0)
    # Fraction of notes a learner should get right on a well-chosen exercise.
    # Exercises are aimed *below* the rating so this stays in the 70-85% zone.
    target_success_rate: float = _env_float("SRT_TARGET_SUCCESS_RATE", 0.78)

    # --- scoring ----------------------------------------------------------
    match_window_s: float = _env_float("SRT_MATCH_WINDOW_S", 0.200)
    # Continuity is about *timing drift*, which by definition can exceed the
    # tight pitch window, so hesitation detection uses a much wider tolerance.
    continuity_window_s: float = _env_float("SRT_CONTINUITY_WINDOW_S", 1.500)
    hesitation_ms: float = _env_float("SRT_HESITATION_MS", 500.0)
    # Onset error (in beats) at which the rhythm sub-score reaches zero.
    rhythm_tolerance_beats: float = _env_float("SRT_RHYTHM_TOLERANCE_BEATS", 0.50)
    weight_pitch: float = _env_float("SRT_WEIGHT_PITCH", 0.50)
    weight_rhythm: float = _env_float("SRT_WEIGHT_RHYTHM", 0.30)
    weight_continuity: float = _env_float("SRT_WEIGHT_CONTINUITY", 0.20)
    pass_threshold: float = _env_float("SRT_PASS_THRESHOLD", 80.0)

    # --- exercise shape ---------------------------------------------------
    exercise_bars: int = _env_int("SRT_EXERCISE_BARS", 4)
    calibration_length: int = _env_int("SRT_CALIBRATION_LENGTH", 8)
    #: Exercises in a workout. Was `SRT_SESSION_LENGTH`, which was dead config
    #: while only single exercises existed; a workout is what it always meant.
    workout_length: int = _env_int("SRT_WORKOUT_LENGTH", 8)
    default_meter: str = "4/4"

    # --- practice logging -------------------------------------------------
    #: Silence that closes a sitting. Long on purpose: walking to the piano,
    #: thinking, and playing again is one sitting.
    sitting_gap_s: int = _env_int("SRT_SITTING_GAP_S", 300)
    #: Silence that splits a sitting into segments — one per piece attempted.
    #:
    #: Measured from a real 42-minute sitting of the owner's (18,688 notes): the
    #: 99th-percentile gap *within* playing was 1.4 s, and only ten gaps in the
    #: whole session exceeded 3 s. The two boundaries they drew by hand — the
    #: changes from Hanon to Brahms and from Brahms to the Beethoven — sat on gaps
    #: of 9.5 s and 11.7 s, which the old default of 20 s could not see. Two
    #: within-piece pauses of 15.1 s and 15.6 s sat above them, so no single
    #: threshold separates those six events: 8 s catches every real change and
    #: costs about two merges, and merging a boundary is one click where splitting
    #: one means typing a position. Erring towards more segments is therefore the
    #: cheaper error, and the setting is here for the day that judgement changes.
    segment_gap_s: int = _env_int("SRT_SEGMENT_GAP_S", 8)
    #: Mid-segment silence counted as a restart rather than as phrasing.
    restart_gap_ms: int = _env_int("SRT_RESTART_GAP_MS", 3000)
    #: Notes closer together than this are one attack, so a chord does not read
    #: as an infinitely fast tempo.
    attack_window_ms: int = _env_int("SRT_ATTACK_WINDOW_MS", 50)

    # --- recognising a segment from your own labelled practice --------------
    #: How many of your closest labelled segments count as evidence.
    autotag_neighbours: int = _env_int("SRT_AUTOTAG_NEIGHBOURS", 6)
    #: At or above this, a match is written as an inferred label. The default is
    #: measured, not inherited — see `backend/tools/measure_autotag.py` and the
    #: numbers in `docs/ECOSYSTEM.md` §10.
    autotag_score_auto: float = _env_float("SRT_AUTOTAG_SCORE_AUTO", 0.85)
    #: At or above this, the match is offered in the timeline and written only if
    #: you accept it. Below it, nothing is claimed.
    autotag_score_prompt: float = _env_float("SRT_AUTOTAG_SCORE_PROMPT", 0.55)
    #: How far ahead of the runner-up a match must be before it is written without
    #: asking. Measured on drill-shaped material: 0.10 was 13/13 correct; 0.05
    #: roughly doubles the coverage at about a 3% error rate.
    autotag_min_margin: float = _env_float("SRT_AUTOTAG_MIN_MARGIN", 0.10)
    #: Below this many notes a segment is not recognised at all. A handful of notes
    #: has no profile worth matching, and guessing from one would be noise wearing
    #: a percentage.
    autotag_min_notes: int = _env_int("SRT_AUTOTAG_MIN_NOTES", 8)
    #: How many of your most recent labelled segments the matcher compares against.
    #: Every read of a sitting derives a fingerprint per reference, so an uncapped
    #: set would make the log slower every month for the rest of the library's life.
    #: The newest ones are also the most representative of what you are playing now.
    autotag_training_limit: int = _env_int("SRT_AUTOTAG_TRAINING_LIMIT", 600)
    #: How many labelled segments the accuracy report evaluates. Leave-one-out is
    #: quadratic in this number, so past the cap it takes the newest and says so in
    #: the report rather than quietly sampling.
    autotag_quality_limit: int = _env_int("SRT_AUTOTAG_QUALITY_LIMIT", 400)

    # --- serving over the LAN ---------------------------------------------
    #: Largest recording accepted by the upload endpoint, in megabytes. A cap that
    #: only trusts the client's declared size is not a cap, so it is enforced while
    #: writing rather than only on the way in.
    max_upload_mb: int = _env_int("SRT_MAX_UPLOAD_MB", 512)
    #: Nightly JSON exports. `deploy/` installs a systemd timer that writes here.
    backup_dir: Path = _env_path("SRT_BACKUP_DIR", _default_data_dir() / "backups")
    #: How many daily backups to keep before the oldest is removed.
    backup_keep: int = _env_int("SRT_BACKUP_KEEP", 14)

    @property
    def weights(self) -> dict[str, float]:
        total = self.weight_pitch + self.weight_rhythm + self.weight_continuity
        return {
            "pitch": self.weight_pitch / total,
            "rhythm": self.weight_rhythm / total,
            "continuity": self.weight_continuity / total,
        }


settings = Settings()
