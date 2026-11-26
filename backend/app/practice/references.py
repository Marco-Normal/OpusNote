"""Reference cache and feature/fingerprint extraction for segment identification."""

from __future__ import annotations

import collections
import sqlite3
from bisect import bisect_left, bisect_right
from typing import Sequence

from . import shingles
from . import store as _store
from .materialise import _PASSAGES
from .sessionize import Note
from .similarity import Example, Fingerprint, fingerprint
from .store_core import _SEGMENT_COLUMNS

def _notes_for_segments(
    conn: sqlite3.Connection, rows: list[sqlite3.Row]
) -> dict[int, list[Note]]:
    """Notes per segment, fetched sitting by sitting.

    One query per sitting rather than per segment: a sitting holds a few hundred
    notes, and asking for them once is the difference between a handful of queries
    and one per segment on every page load.

    The sitting's notes come back onset-ordered, so each segment's slice is found with
    a binary search rather than by re-scanning the whole list. The scan was quadratic in
    the labels — every labelled segment walked every note of its sitting — and it is on
    every matcher read, so a library that grows made each sitting open slower than the
    last for no reason but the size of the training set.
    """
    by_sitting: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        by_sitting.setdefault(int(row["sitting_id"]), []).append(row)

    out: dict[int, list[Note]] = {int(row["id"]): [] for row in rows}
    for sitting_id, group in by_sitting.items():
        notes = conn.execute(
            "SELECT onset_ms, duration_ms, pitch, velocity, channel FROM note_events"
            " WHERE sitting_id = ? ORDER BY onset_ms, pitch",
            (sitting_id,),
        ).fetchall()
        onsets = [int(note["onset_ms"]) for note in notes]
        for row in group:
            start = int(row["start_ms"])
            end = int(row["end_ms"])
            out[int(row["id"])] = [
                Note(
                    epoch_ms=int(note["onset_ms"]),
                    pitch=int(note["pitch"]),
                    velocity=int(note["velocity"]),
                    duration_ms=int(note["duration_ms"]),
                    channel=note["channel"],
                )
                for note in notes[bisect_left(onsets, start) : bisect_right(onsets, end)]
            ]
    return out


def _notes_in_range(
    conn: sqlite3.Connection, sitting_id: int, start_ms: int, end_ms: int
) -> list[Note]:
    """One segment's notes, read directly off `idx_events_sitting(sitting_id, onset_ms)`.

    `_notes_for_segments` reads a whole sitting and binary-searches each segment's slice out of
    it, which is right when every segment of that sitting is being derived and wrong when one
    is: the read is charged to the sitting, not to the segment, so a single-label change paid
    ~14 ms to obtain a slice that a bounded range query returns in ~0.1 ms.

    The bounds are inclusive at both ends, and the ORDER BY is the one that index is on, so
    this returns the same notes, in the same order, that the binary search would have sliced
    out — which is what lets the incremental path be *equal* to a full rebuild rather than
    merely close.
    """
    return [
        Note(
            epoch_ms=int(note["onset_ms"]),
            pitch=int(note["pitch"]),
            velocity=int(note["velocity"]),
            duration_ms=int(note["duration_ms"]),
            channel=note["channel"],
        )
        for note in conn.execute(
            "SELECT onset_ms, duration_ms, pitch, velocity, channel FROM note_events"
            " WHERE sitting_id = ? AND onset_ms BETWEEN ? AND ?"
            " ORDER BY onset_ms, pitch",
            (sitting_id, start_ms, end_ms),
        )
    ]


def _labelled_rows(
    conn: sqlite3.Connection,
    *,
    exclude_segment_id: int | None = None,
) -> list[sqlite3.Row]:
    """The training set: segments a *person* put a piece on, oldest first.

    Machine guesses are excluded, deliberately. Training on your own guesses
    compounds whatever the matcher got wrong the first time — a mislabelled
    segment would become evidence for the same mistake — and the design's promise
    is that every segment *you* tag becomes the reference.

    There is no cap, and that is Phase 22b's decision rather than an oversight. The matcher
    compares against **every** labelled segment and pools the evidence per piece, so
    matching costs O(pieces) rather than O(labels) and no piece can fall out of a window.
    Truncating to the newest N was measured to evict pieces outright — on the owner's library
    the old window held a single piece for 47 of 54 queries, left the runner-up undefined for
    46 of them, and the auto band could not fire at all — so a cap here is a correctness
    change wearing a performance one's clothes. Work that needs bounding is bounded at the
    caller: `_store.settings.autotag_quality_limit` caps how many segments the accuracy report
    evaluates, and it says so in the report rather than sampling silently.
    """
    sql = (
        f"SELECT {_SEGMENT_COLUMNS} FROM segments g"
        " WHERE g.piece_id IS NOT NULL"
        "   AND (g.identified_by IS NULL OR g.identified_by <> 'similarity')"
    )
    params: list = []
    if exclude_segment_id is not None:
        sql += " AND g.id <> ?"
        params.append(exclude_segment_id)
    sql += " ORDER BY g.sitting_id, g.start_ms"
    return conn.execute(sql, params).fetchall()


def _reference_inputs(row: sqlite3.Row) -> tuple[int, int, int, int | None]:
    """The four facts a labelled segment's derivation is a function of.

    A change in any of them changes either which notes are read (`sitting_id`, `start_ms`,
    `end_ms`) or which piece's signature the features are added to (`piece_id`), so they are
    what the cache diffs against to decide whether a segment needs re-deriving at all.

    `identified_by` is deliberately absent. It decides *membership*, and `_labelled_rows` has
    already applied that filter by the time the diff runs — but it is not an input to a
    fingerprint or a content feature, so a row that merely changes hands between two reference
    states (`manual` → `workout`) does not need re-deriving.
    """
    return (
        int(row["sitting_id"]),
        int(row["start_ms"]),
        int(row["end_ms"]),
        None if row["piece_id"] is None else int(row["piece_id"]),
    )


def labelled_count(conn: sqlite3.Connection) -> int:
    """How many segments a person has labelled, which is the whole reference set."""
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM segments"
            " WHERE piece_id IS NOT NULL"
            "   AND (identified_by IS NULL OR identified_by <> 'similarity')"
        ).fetchone()[0]
    )


def _fingerprints_from(
    rows: list[sqlite3.Row], notes: dict[int, list[Note]]
) -> dict[int, Fingerprint]:
    return {
        int(row["id"]): fingerprint(
            notes.get(int(row["id"]), []), attack_window_ms=_store.settings.attack_window_ms
        )
        for row in rows
    }


def _features_from(
    rows: list[sqlite3.Row], notes: dict[int, list[Note]]
) -> dict[int, collections.Counter]:
    """Each labelled segment's local content features, keyed by segment id."""
    return {
        int(row["id"]): shingles.features(notes.get(int(row["id"]), [])) for row in rows
    }


def references_from(
    conn: sqlite3.Connection, rows: list[sqlite3.Row]
) -> tuple[list[Example], dict[int, collections.Counter]]:
    """The matcher's training material: examples and local features, from one read.

    A fingerprint and a content feature are two projections of the *same* note list, and
    the notes are the expensive part — one query per sitting, and a large result set off a
    slow disk. Deriving both from a single ``_notes_for_segments`` is the difference
    between reading every reference's notes twice per page load and reading them once;
    the callers that need both (the sitting's candidates, the quality report) used to
    fetch the same rows twice, in two different shapes.
    """
    notes = _store._notes_for_segments(conn, rows)
    prints = _fingerprints_from(rows, notes)
    return (
        [
            Example(
                segment_id=int(row["id"]),
                piece_id=int(row["piece_id"]),
                fingerprint=prints[int(row["id"])],
            )
            for row in rows
        ],
        _features_from(rows, notes),
    )


def _fingerprints(
    conn: sqlite3.Connection, rows: list[sqlite3.Row]
) -> dict[int, Fingerprint]:
    return _fingerprints_from(rows, _store._notes_for_segments(conn, rows))


def examples_from(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[Example]:
    """Turn labelled segment rows into training examples."""
    prints = _fingerprints(conn, rows)
    return [
        Example(
            segment_id=int(row["id"]),
            piece_id=int(row["piece_id"]),
            fingerprint=prints[int(row["id"])],
        )
        for row in rows
    ]


def _segment_features(
    conn: sqlite3.Connection, rows: list[sqlite3.Row]
) -> dict[int, collections.Counter]:
    """Each labelled segment's local content features, keyed by segment id."""
    return _features_from(rows, _store._notes_for_segments(conn, rows))


def _pool_features(
    rows: list[sqlite3.Row], features: dict[int, collections.Counter]
) -> dict[int, collections.Counter]:
    """One content signature per piece, from the features of the segments that carry it."""
    signatures: dict[int, collections.Counter] = {}
    for row in rows:
        present = features[int(row["id"])]
        if present:
            signatures.setdefault(int(row["piece_id"]), collections.Counter()).update(present)
    return signatures


def _pooled_signatures(
    conn: sqlite3.Connection, *, exclude_segment_id: int | None = None
) -> dict[int, collections.Counter]:
    """One content signature per piece, from every segment a person labelled.

    Per piece and not per segment, which is what retires the reference window: matching
    costs O(pieces) rather than O(labels), a piece learned a year ago is exactly as strong
    as yesterday's, and one heavily-drilled piece can no longer fill the neighbour window and
    leave the runner-up undefined — which is why the auto band had never fired.
    """
    rows = _labelled_rows(conn, exclude_segment_id=exclude_segment_id)
    return _pool_features(rows, _store._segment_features(conn, rows))


def _updated_features(
    cached: dict[int, collections.Counter],
    removed: set[int],
    derived: dict[int, collections.Counter],
) -> dict[int, collections.Counter]:
    """Copy-on-write `local`: drop what left, replace or add what moved, share the rest.

    Sharing the unchanged Counters is safe because they are never mutated — `_pool_features`
    only calls `update`, and the incremental pool below reads them — and it is what keeps a
    one-label change from copying 443 small objects.
    """
    updated = {
        segment_id: features
        for segment_id, features in cached.items()
        if segment_id not in removed
    }
    for segment_id, features in derived.items():
        # A segment whose features came out empty is dropped rather than stored as an empty
        # Counter, which is exactly what a full rebuild leaves behind (`_pool_features` skips
        # them), so the key set cannot diverge from a rebuild.
        if features:
            updated[segment_id] = features
        else:
            updated.pop(segment_id, None)
    return updated


def _adjust_pooled(
    old_features: dict[int, collections.Counter],
    old_pieces: dict[int, int],
    new_features: dict[int, collections.Counter],
    new_pieces: dict[int, int],
    pooled: dict[int, collections.Counter],
) -> dict[int, collections.Counter]:
    """The O(1) pool: subtract each moved segment from its old piece, add it to its new one.

    Only the affected pieces' Counters are copied, because `Counter.subtract` mutates its
    target. A piece whose Counter comes out empty is **removed**, not left as an empty
    signature: `shingles.idf` counts every key of this dict as a document, so a piece left
    behind would shift every IDF weight — and therefore every score — silently and
    library-wide, while looking inert.
    """
    adjusted = dict(pooled)
    affected = set(old_pieces.values()) | set(new_pieces.values())
    for piece_id in affected:
        if piece_id in adjusted:
            adjusted[piece_id] = collections.Counter(adjusted[piece_id])

    for segment_id, features in old_features.items():
        piece_id = old_pieces[segment_id]
        if piece_id in adjusted:
            adjusted[piece_id].subtract(features)
    for segment_id, features in new_features.items():
        adjusted.setdefault(new_pieces[segment_id], collections.Counter()).update(features)

    # `any(counts.values())` rather than `if counts`: `Counter.subtract` leaves the keys it
    # zeroed in place, and a Counter whose values are all zero is still *truthy*, so the plain
    # test would keep the piece and shift every IDF weight. Emptiness here means "this piece has
    # no weight left", not "this dict has no keys".
    return {
        piece_id: counts for piece_id, counts in adjusted.items() if any(counts.values())
    }


def _incremental_references(
    conn: sqlite3.Connection,
    cached: tuple[
        int,
        dict[int, tuple[int, int, int, int | None]],
        list[Example],
        dict[int, collections.Counter],
        dict[int, collections.Counter],
    ],
) -> tuple[
    list[Example],
    dict[int, collections.Counter],
    dict[int, collections.Counter],
    dict[int, tuple[int, int, int, int | None]],
]:
    """Re-derive only the labelled segments whose inputs moved since `cached` was built.

    The version counter says *that* something moved; this says *what*, which is the difference
    between reading one segment's notes and reading every labelled sitting again. The segments
    that did not move keep their fingerprint and their content features, so the only work is a
    range read and a fold per changed segment, plus an O(1) adjustment of the affected pieces'
    pooled signatures.

    `examples` is rebuilt from the current rows in `_labelled_rows`' own order rather than
    patched in place, because the matcher sees a *list*: taking each fingerprint from the
    derived-or-cached map makes the result identical to a full rebuild, tie-breaking included.
    """
    _version, cached_inputs, cached_examples, cached_local, cached_pooled = cached
    by_id = {example.segment_id: example.fingerprint for example in cached_examples}
    rows = _labelled_rows(conn)
    current = {int(row["id"]): _reference_inputs(row) for row in rows}

    removed = cached_inputs.keys() - current.keys()
    # Every segment the base entry did not already hold, plus every one whose inputs moved.
    # Driving this off `cached_inputs` rather than off `examples` matters: a base entry built
    # when the library had no labels at all holds no examples, and the first label written after
    # that must still be derived rather than looked up in a map that cannot contain it.
    moved = [
        segment_id
        for segment_id, inputs in current.items()
        if cached_inputs.get(segment_id) != inputs
    ]
    moved_set = set(moved)

    derived: dict[int, collections.Counter] = {}
    for row in rows:
        segment_id = int(row["id"])
        if segment_id not in moved_set:
            continue
        notes = _store._notes_in_range(
            conn, int(row["sitting_id"]), int(row["start_ms"]), int(row["end_ms"])
        )
        by_id[segment_id] = fingerprint(notes, attack_window_ms=_store.settings.attack_window_ms)
        derived[segment_id] = shingles.features(notes)

    examples = [
        Example(
            segment_id=int(row["id"]),
            piece_id=int(row["piece_id"]),
            fingerprint=by_id[int(row["id"])],
        )
        for row in rows
    ]
    local = _updated_features(cached_local, set(moved) | set(removed), derived)
    # A segment that was *moved* must be subtracted from the piece it left just as a removed one
    # is, so the subtraction side is `moved | removed` read from the **cached** features — the
    # old side of the ledger — while the additions come from the newly derived features.
    # Subtracting only `removed` left a moved segment counted under both pieces.
    #
    # The `& cached_local` intersection is load-bearing: `cached_local` omits segments whose
    # features came out empty, and only what was actually pooled may be subtracted from it.
    leaving = (set(moved) | set(removed)) & cached_local.keys()
    pooled = _adjust_pooled(
        {segment_id: cached_local[segment_id] for segment_id in leaving},
        {segment_id: cached_inputs[segment_id][3] for segment_id in leaving},
        derived,
        {segment_id: current[segment_id][3] for segment_id in moved},
        cached_pooled,
    )
    return examples, local, pooled, current


#: Derived reference material, per database file, validated by `reference_state.version`.
#:
#: The entries hold only what `cached_references` returns, and every consumer reads them —
#: `rank` and `compare` build their own lists and Counters — so one copy can be shared.
#:
#: The leading `inputs` map is what makes a version miss cheap: it records, per labelled
#: segment, the four facts its derivation came from, so the next miss can re-derive only the
#: segments whose inputs actually moved instead of starting over. It is `_reference_inputs`'s
#: shape, keyed by segment id.
_REFERENCES: dict[
    str,
    tuple[
        int,
        dict[int, tuple[int, int, int, int | None]],
        list[Example],
        dict[int, collections.Counter],
        dict[int, collections.Counter],
    ],
] = {}


def forget_references() -> None:
    """Drop every cached derivation.

    Called by ``init_db``: it may have just created or replaced the file a cache entry was
    built from, and a version of zero in a brand-new database must not match an entry left
    over from the one that was there before.

    Both caches go, because both are keyed on facts about a file that no longer exists: the
    reference set by ``reference_state.version``, and the passages by the sitting's own rows
    and note count, which a rebuilt file can reproduce exactly while meaning something else.
    """
    _REFERENCES.clear()
    _PASSAGES.clear()
    # Imported here rather than at module scope: the portrait imports this module for the
    # calendar and the rounding, so a module-level dependency would be a cycle.
    from . import portrait as portrait_module

    portrait_module.forget()


def _database_name(conn: sqlite3.Connection) -> str:
    """The file this connection is reading, so two databases cannot share an entry."""
    for _seq, name, file in conn.execute("PRAGMA database_list"):
        if name == "main":
            return str(file or ":memory:")
    return ":memory:"


def _reference_version(conn: sqlite3.Connection) -> int:
    """The segments triggers' counter, or -1 when the table is not there to ask."""
    row = conn.execute("SELECT version FROM reference_state WHERE id = 1").fetchone()
    return int(row["version"]) if row is not None else -1


def cached_references(
    conn: sqlite3.Connection,
) -> tuple[list[Example], dict[int, collections.Counter], dict[int, collections.Counter]]:
    """The matcher's training material: examples, local features, pooled signatures.

    The same three things `references_from` and `_pool_features` produce, kept until the
    database says a label or a boundary changed. Deriving them is a pass over every labelled
    segment's notes — about a second on the owner's library, and a quarter of a million Note
    objects — and every sitting open, page load and quality report was paying it to get an
    answer that had not moved since the last one.

    A version miss does not start over. The entry carries the inputs each labelled segment's
    derivation came from, so a miss re-reads and re-derives only the segments whose own inputs
    moved — one range query and one fold per changed segment, plus an O(1) adjustment of the
    affected pieces' pooled signatures — and is required to be *equal* to a full rebuild, key
    sets and example order included. A miss with no entry for this file is the cold case and
    builds the whole answer, which is what every read did before the incremental path.

    Invalidation is the database's, not the caller's: ``reference_state.version`` is bumped
    by triggers on ``segments``, so a label written by any code path, by an older build, or
    by the second machine over the LAN invalidates it. A database without the table (one
    built outside ``init_db``) reports -1 and is never cached.
    """
    name = _database_name(conn)
    version = _reference_version(conn)
    cached = _REFERENCES.get(name) if version >= 0 else None
    if cached is not None and cached[0] == version:
        return cached[2], cached[3], cached[4]
    if cached is not None:
        # Something moved, so the version miss is real — but the entry knows the inputs it was
        # built from, so only the segments whose own inputs moved are read and re-derived. The
        # row read is the incremental path's own `_labelled_rows`, returned rather than repeated.
        examples, local, pooled, inputs = _incremental_references(conn, cached)
    else:
        # The cold case: nothing to update from, so build the whole answer. This is not a
        # compatibility branch — it is the behaviour every read had before the incremental path.
        rows = _labelled_rows(conn)
        examples, local = _store.references_from(conn, rows)
        pooled = _pool_features(rows, local)
        inputs = {int(row["id"]): _reference_inputs(row) for row in rows}
    if version >= 0:
        _REFERENCES[name] = (version, inputs, examples, local, pooled)
    return examples, local, pooled

