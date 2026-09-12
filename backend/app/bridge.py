"""Cross-domain seam: repertoire → sight-reading.

This is the only module that knows about both domains, and it exists so that
neither has to know about the other. `repertoire` stays ignorant of skill levels;
`sight-reading` stays ignorant of pieces. Everything the bridge needs arrives as
plain values.

The point of merging the apps is features like this: *practise sight-reading in
the key of the piece you are working on, at a level that matches it.*
"""

from __future__ import annotations

from dataclasses import dataclass

from .skills_data import KEY_SIGNATURE_LEVELS

#: Difficulty labels as the Rust app writes them, mapped to a starting level.
#: Unrecognised labels fall back to `None` rather than guessing, so a label this
#: table has never seen cannot silently place someone at the wrong level.
DIFFICULTY_LEVELS: dict[str, int] = {
    "beginner": 2,
    "easy": 2,
    "early intermediate": 4,
    "intermediate": 6,
    "late intermediate": 8,
    "advanced": 9,
    "hard": 9,
    "virtuoso": 10,
}

#: Every key spelling the taxonomy knows, across all levels.
_KNOWN_KEYS: frozenset[str] = frozenset(
    key for keys in KEY_SIGNATURE_LEVELS.values() for key in keys
)


@dataclass(frozen=True)
class PracticeSuggestion:
    piece_id: int
    title: str
    composer_name: str | None
    piece_key: str | None
    suggested_key: str | None
    difficulty: str | None
    suggested_level: int | None
    notes: list[str]


def normalise_key(label: str | None) -> tuple[str | None, str | None]:
    """Turn a display key into the trainer's spelling.

    The Rust app stores `"B Major"`, `"C# Minor"`, `"Db Major"`. The trainer's
    `KEY_SIGNATURE_LEVELS` uses `"B"`, `"c#"`, `"Db"` — a lowercase tonic means
    minor. Returns `(key, mode)`; `key` is `None` when the label is unusable.
    """
    if not label or not label.strip():
        return None, None
    parts = label.strip().split()
    tonic = parts[0]
    mode = parts[1].lower() if len(parts) > 1 else "major"
    if mode not in {"major", "minor"}:
        return None, None

    # Normalise the spelling to what the taxonomy uses: an upper-case letter and
    # a lower-case accidental. Doing this case-insensitively matters because
    # labels arrive hand-written — "BB Major" and "bb minor" both mean B-flat.
    letter = tonic[0].upper()
    accidental = tonic[1:].replace("♯", "#").replace("♭", "b").lower()
    if accidental not in {"", "b", "#"}:
        return None, None
    tonic = letter + accidental

    if mode == "minor":
        tonic = tonic.lower()
    return tonic, mode


def suggest_for_piece(
    *,
    piece_id: int,
    title: str,
    composer_name: str | None,
    piece_key: str | None,
    difficulty: str | None,
    status: str | None = None,
) -> PracticeSuggestion:
    """Map one piece onto a sight-reading key and starting level."""
    key, _mode = normalise_key(piece_key)
    suggested_key = key if key in _KNOWN_KEYS else None
    suggested_level = (
        DIFFICULTY_LEVELS.get((difficulty or "").strip().lower()) if difficulty else None
    )

    notes: list[str] = []
    if piece_key and suggested_key is None:
        notes.append(f"key {piece_key!r} is not in the sight-reading key list")
    if difficulty and suggested_level is None:
        notes.append(f"difficulty {difficulty!r} is not a known label")
    if not piece_key:
        notes.append("piece has no key")

    # A piece the player has finished is the wrong thing to sight-read around;
    # say so rather than silently treating every piece the same.
    if status == "completed":
        notes.append("piece is marked completed")

    return PracticeSuggestion(
        piece_id=piece_id,
        title=title,
        composer_name=composer_name,
        piece_key=piece_key,
        suggested_key=suggested_key,
        difficulty=difficulty,
        suggested_level=suggested_level,
        notes=notes,
    )
