"""Segment identification, sitting-level sequence decoding, and autotagging."""

from __future__ import annotations

import collections
import sqlite3
from pathlib import Path
from typing import Iterable, Literal, Sequence

from .. import db
from . import calibration
from . import sequence as sitting_sequence
from . import shingles
from . import store as _store
from .models import AutotagReport, IdentificationQuality, SegmentCandidate, SegmentSummary
from .references import _labelled_rows, _pooled_signatures, cached_references, examples_from, labelled_count
from .sequence import Belief
from .sessionize import Note
from .similarity import DEFAULT_WEIGHTS, Candidate, Example, Identification, Weights, fingerprint, identify
from .store_core import _SEGMENT_COLUMNS, _SETTLED, InvalidRequest, NotFound

def _shares(
    query: collections.Counter,
    signatures: dict[int, collections.Counter],
    *,
    weights: dict | None = None,
) -> dict[int, float]:
    """Each piece's share of the query's local content, when there is anything to compare.

    ``weights`` is `shingles.idf` of ``signatures``. Callers that ask about many segments
    against the *same* signatures pass it in: it depends only on which pieces exist, so
    deriving it here made a sitting with 49 undecided segments walk every piece's features
    49 times for an answer that could not change between them.
    """
    if not signatures:
        return {}
    if weights is None:
        weights = shingles.idf(signatures)
    return {
        piece_id: shingles.containment(query, signature, weights)
        for piece_id, signature in signatures.items()
    }


def segment_identification(
    conn: sqlite3.Connection,
    segment_id: int,
    *,
    examples: list[Example] | None = None,
    signatures: dict[int, collections.Counter] | None = None,
    notes: list[Note] | None = None,
    context_piece_id: int | None = None,
    weights: Weights = DEFAULT_WEIGHTS,
    share_weights: dict | None = None,
) -> Identification:
    """Match one segment against your labelled practice.

    ``examples``, ``signatures`` and ``notes`` are all passed in by callers that identify several
    segments of one sitting, and for the same reason: each is a thing the caller already holds, and
    rebuilding it per segment re-derives work that does not vary between them. The notes are the
    expensive one, because the query is by *sitting* — it returns every note in the sitting however
    few the segment holds — so a sitting with n undecided sections read its own notes n times over.

    ``share_weights`` is `shingles.idf` of ``signatures``, for the same reason and under the same
    rule: it is derived once per sitting. It is ignored when ``signatures`` is not passed, because
    then the signatures this call derives are its own and the caller's weights describe different
    pieces.
    """
    row = conn.execute(
        f"SELECT {_SEGMENT_COLUMNS} FROM segments g WHERE g.id = ?", (segment_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f"no segment {segment_id}")
    if examples is None:
        examples = examples_from(conn, _labelled_rows(conn, exclude_segment_id=segment_id))

    if notes is None:
        notes = _store._notes_for_segments(conn, [row]).get(segment_id, [])
    segment_print = fingerprint(notes, attack_window_ms=_store.settings.attack_window_ms)
    # Pooled once per call unless the caller already has them: a caller identifying several
    # segments of one sitting would otherwise re-derive every reference's features per row.
    # The weights describe signatures the *caller* passed; when the signatures here are derived
    # for this one segment, the caller's weights would describe different pieces, so they are
    # dropped rather than trusted.
    borrowed_signatures = signatures is not None
    if signatures is None:
        signatures = _pooled_signatures(conn, exclude_segment_id=segment_id)
    return identify(
        segment_print,
        examples,
        score_auto=_store.settings.autotag_score_auto,
        score_prompt=_store.settings.autotag_score_prompt,
        min_margin=_store.settings.autotag_min_margin,
        min_notes=_store.settings.autotag_min_notes,
        weights=weights,
        context_piece_id=context_piece_id,
        shares=_shares(
            shingles.features(notes),
            signatures,
            weights=share_weights if borrowed_signatures else None,
        ),
        containment_weight=_store.settings.autotag_containment_weight,
    )


def _piece_labels(conn: sqlite3.Connection, piece_ids: Iterable[int]) -> dict[int, dict]:
    ids = sorted({int(piece) for piece in piece_ids})
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT p.id, p.title, c.name AS composer_name, p.opus
        FROM pieces p LEFT JOIN composers c ON c.id = p.composer_id
        WHERE p.id IN ({placeholders})
        """,
        ids,
    ).fetchall()
    return {int(row["id"]): dict(row) for row in rows}


def _candidate_out(
    conn: sqlite3.Connection,
    candidates: Sequence[Candidate],
    *,
    reason: str,
    band: str,
    context_piece_id: int | None,
    limit: int = 3,
) -> list[SegmentCandidate]:
    labels = _piece_labels(conn, [candidate.piece_id for candidate in candidates[:limit]])
    out: list[SegmentCandidate] = []
    for position, candidate in enumerate(candidates[:limit]):
        label = labels.get(candidate.piece_id, {})
        out.append(
            SegmentCandidate(
                piece_id=candidate.piece_id,
                title=label.get("title") or f"piece {candidate.piece_id}",
                composer_name=label.get("composer_name"),
                opus=label.get("opus"),
                score=round(candidate.score, 4),
                pitch_class=round(candidate.pitch_class, 4),
                tempo=round(candidate.tempo, 4),
                register_overlap=round(candidate.register, 4),
                hand=round(candidate.hand, 4),
                interval=round(candidate.interval, 4),
                support=candidate.support,
                margin=round(candidate.margin, 4),
                band=band if position == 0 else "listed",
                reason=reason if position == 0 else None,
                from_context=context_piece_id is not None
                and candidate.piece_id == context_piece_id,
            )
        )
    return out


def _decode_sitting(
    order: Sequence[int],
    *,
    ranked: dict[int, Sequence[Candidate]],
    note_counts: dict[int, int],
    pinned: dict[int, int] | None = None,
) -> dict[int, sitting_sequence.Belief]:
    """Read one sitting's segments as a sequence: each one borrows from its neighbours.

    A sitting is nearly always one piece at a time — 10.2% of the owner's adjacent
    segments change piece — so the segment either side is evidence the per-segment
    score does not have. `sequence.py` is the model; this is the wiring. Candidate
    scores are the emission, a segment that already has a label is pinned to it, and
    moving to another piece costs what the measured switch rate says it should.

    Decoding the whole sitting before writing anything matters: the old pass wrote
    each label as it went, which made the answer depend on the order the rows came
    back in and let one confident mistake become the next segment's context.
    """
    settled = dict(pinned or {})
    fragments: list[sitting_sequence.Fragment] = []
    for segment_id in order:
        if segment_id in settled:
            options = (sitting_sequence.Option(settled[segment_id], 1.0),)
        else:
            options = tuple(
                sitting_sequence.Option(candidate.piece_id, candidate.score)
                for candidate in ranked.get(segment_id, ())
            )
        fragments.append(
            sitting_sequence.Fragment(
                key=segment_id,
                options=options,
                notes=note_counts.get(segment_id, 0),
            )
        )
    return {
        belief.key: belief
        for belief in sitting_sequence.decode(
            fragments,
            switch=_store.settings.autotag_sequence_switch,
            temperature=_store.settings.autotag_sequence_temperature,
        )
    }


def _sequence_verdict(
    belief: sitting_sequence.Belief, identification: Identification
) -> tuple[str, str]:
    """The band and the sentence for a segment whose neighbours had a say.

    The band comes from the decoded probability, not from the score thresholds: the
    thresholds judge one segment alone, which is the question the sitting's context
    just answered differently. That probability is then put through the measured
    calibration: a short fragment in a crowded library is explained almost as well by
    several pieces, and its smooth confidence is not the frequency with which it is
    right, so the calibration can lower a write to an offer and never raises one.
    The sentence tries to stay true to *why* — a piece
    pulled forward by its neighbours should not read "confident match".
    """
    required = _store.calibration.auto_probability(
        notes=belief.notes,
        pieces=len(belief.probabilities),
        base=_store.settings.autotag_auto_probability,
    )
    band = sitting_sequence.band(
        belief,
        auto_probability=(
            _store.settings.autotag_auto_probability if required is None else required
        ),
        prompt_probability=_store.settings.autotag_prompt_probability,
        min_notes=_store.settings.autotag_min_notes,
    )
    if required is None and band == "auto":
        # The measurement says no threshold makes this shape trustworthy: a short
        # fragment in a crowded library is explained nearly as well by several pieces,
        # so the label is offered instead of written.
        band = "suggest"
    if belief.chosen is None:
        return "none", identification.reason
    raw = identification.best.piece_id if identification.best else None
    if band == "none":
        # A decode may lower a write to an offer, but it may not turn an offer into
        # silence. Two pieces the material explains equally well land either side of
        # the prompt probability by a hair (0.4999 rather than 0.5), and hiding both
        # answers is worse than showing two: nothing is written either way, and the
        # player is the one who can tell them apart.
        if identification.band == "suggest":
            return "suggest", identification.reason
        return band, identification.reason
    if belief.chosen != raw:
        moved = "points here" if band == "auto" else "leans here"
        return band, f"the rest of the sitting {moved}"
    if band == identification.band:
        return band, identification.reason
    # The band changed but the piece did not: the score said one thing and the
    # sitting said another, so neither sentence alone is the whole story.
    return band, "confident match" if band == "auto" else "worth a look"


def _chosen_first(
    candidates: Sequence[Candidate], piece_id: int | None
) -> list[Candidate]:
    """Put the piece the sitting settled on first, keeping the rest in score order."""
    ranked = list(candidates)
    if piece_id is None:
        return ranked
    for position, candidate in enumerate(ranked):
        if candidate.piece_id == piece_id:
            return [candidate, *ranked[:position], *ranked[position + 1 :]]
    return ranked


def _score_and_decode_sitting(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    *,
    wanted: set[int],
    notes_by_segment: dict[int, list[Note]],
    examples: list[Example],
    signatures: dict[int, collections.Counter],
    share_weights: dict[object, float],
) -> tuple[dict[int, Identification], dict[int, Belief]]:
    identifications: dict[int, Identification] = {}
    note_counts: dict[int, int] = {}
    pinned: dict[int, int] = {}
    for row in rows:
        segment_id = int(row["id"])
        if row["piece_id"] is not None:
            # A segment you have already labelled is not a question — it is the
            # anchor the rest of the sitting is read against.
            pinned[segment_id] = int(row["piece_id"])
            continue
        if segment_id not in wanted:
            continue
        seg_notes = notes_by_segment.get(segment_id, [])
        identifications[segment_id] = segment_identification(
            conn,
            segment_id,
            examples=examples,
            signatures=signatures,
            notes=seg_notes,
            # No context nudge here: the sequence below is the smoothing, and
            # charging the previous piece twice is how a wrong label spreads.
            context_piece_id=None,
            share_weights=share_weights,
        )
        note_counts[segment_id] = len(seg_notes)

    beliefs = _decode_sitting(
        [int(row["id"]) for row in rows],
        ranked={
            segment_id: identification.candidates
            for segment_id, identification in identifications.items()
        },
        note_counts=note_counts,
        pinned=pinned,
    )
    return identifications, beliefs


def candidates_for_sitting(conn: sqlite3.Connection, sitting_id: int) -> dict[int, list[SegmentCandidate]]:
    """What each unlabelled segment of a sitting might be.

    Computed on read rather than stored, because a suggestion is a statement about
    the labels you have *now*: tagging today's segment can change what yesterday's
    unlabelled one should be, and a stored suggestion would not know that.

    Segments that have already been resolved — accepted, rejected or dismissed —
    are skipped, so a declined suggestion does not come back on every reload.
    """
    rows = conn.execute(
        f"SELECT {_SEGMENT_COLUMNS}, g.workout_id FROM segments g"
        " WHERE g.sitting_id = ? ORDER BY g.start_ms",
        (sitting_id,),
    ).fetchall()

    undecided = [
        int(row["id"])
        for row in rows
        if row["piece_id"] is None
        # A workout segment is sight-reading by declaration, and an inferred label
        # is a question already answered; only a blank, unquestioned segment is
        # worth offering a piece for.
        and row["identified_by"] not in _SETTLED
        and row["identified_by"] != "similarity"
        and int(row["workout_id"] or 0) == 0
        and not _has_outcome(conn, int(row["id"]))
    ]
    if not undecided:
        return {}
    labelled = _labelled_rows(conn)
    if not labelled:
        return {}
    # The same reference material for every sitting, kept until a label or a boundary
    # changes it: signatures are pooled per piece, so it is one answer for the whole library
    # rather than one per sitting, and rebuilding it here was the page's second-long stall.
    examples, _local, signatures = cached_references(conn)
    # Derived once for the whole sitting: it depends only on which pieces have labelled
    # segments, not on the segment being asked about.
    share_weights = shingles.idf(signatures)
    # This sitting's notes, read once for every segment that is about to be asked about. The
    # query is by *sitting*, so asking per segment returned the whole note list each time and
    # kept one segment's share of it: the cost of an edit grew with how many unlabelled
    # sections were still open, and vanished the moment the last one was labelled.
    wanted = set(undecided)
    notes_by_segment = _store._notes_for_segments(
        conn, [row for row in rows if int(row["id"]) in wanted]
    )

    out: dict[int, list[SegmentCandidate]] = {}
    identifications, beliefs = _score_and_decode_sitting(
        conn,
        rows,
        wanted=wanted,
        notes_by_segment=notes_by_segment,
        examples=examples,
        signatures=signatures,
        share_weights=share_weights,
    )
    context: int | None = None
    for row in rows:
        segment_id = int(row["id"])
        if row["piece_id"] is not None:
            context = int(row["piece_id"])
        identification = identifications.get(segment_id)
        if identification is None or not identification.candidates:
            continue
        belief = beliefs[segment_id]
        band, reason = _sequence_verdict(belief, identification)
        out[segment_id] = _candidate_out(
            conn,
            _chosen_first(identification.candidates, belief.chosen),
            reason=reason,
            band=band,
            context_piece_id=context,
        )
    return out


def _has_outcome(conn: sqlite3.Connection, segment_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM identification_outcomes WHERE segment_id = ? LIMIT 1", (segment_id,)
    ).fetchone()
    return row is not None


def _record_outcome(
    conn: sqlite3.Connection,
    *,
    segment_id: int,
    guessed_piece_id: int | None,
    resolved_piece_id: int | None,
    action: str,
    accepted: bool,
    score: float | None,
) -> None:
    conn.execute(
        "INSERT INTO identification_outcomes"
        " (segment_id, guessed_piece_id, resolved_piece_id, action, accepted, score)"
        " VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        (segment_id, guessed_piece_id, resolved_piece_id, action, 1 if accepted else 0, score),
    )


def _autotag_rows(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> AutotagReport:
    """Identify a run of segments by reading each sitting as one sequence.

    A run of drills from one piece is a sequence, and the segment either side is
    evidence the segment's own score does not carry. So each sitting in the run is
    decoded whole before anything is written: a segment you have already labelled is
    pinned as an anchor, the blanks between anchors borrow from both sides, and a
    change of piece has to beat the measured switch rate. Writing as we went — which
    is what this pass used to do — made the answer depend on the order the rows came
    back in and let one confident mistake become the next segment's context.
    """
    report = AutotagReport(considered=len(rows))
    # The same reference material, and the same cache, as the timeline's suggestions. This pass
    # runs when a sitting is first segmented, which made it the other place a freshly finished
    # sitting rebuilt the whole training set before showing anything.
    examples, _local, signatures = cached_references(conn)
    # Once for the whole pass, for the same reason as the timeline's suggestions.
    share_weights = shingles.idf(signatures)
    if not examples:
        report.notes.append(
            "No labelled segments yet, so there is nothing to compare with. Tag a few "
            "segments by hand and the matcher has a reference."
        )
        report.unresolved = len(rows)
        return report

    # The caller hands rows in play order within a sitting, and by sitting; a new
    # sitting is a boundary of the sequence, never a link in it.
    runs: list[tuple[int, list[sqlite3.Row]]] = []
    for row in rows:
        sitting_id = int(row["sitting_id"])
        if not runs or runs[-1][0] != sitting_id:
            runs.append((sitting_id, []))
        runs[-1][1].append(row)

    for sitting_id, asked in runs:
        wanted = {int(row["id"]) for row in asked}
        # The anchors: a segment that already has a piece is what the blanks are read
        # against, including the ones this pass is not allowed to touch.
        chain = conn.execute(
            f"SELECT {_SEGMENT_COLUMNS} FROM segments g"
            " WHERE g.sitting_id = ? ORDER BY g.start_ms",
            (sitting_id,),
        ).fetchall()
        notes_by_segment = _store._notes_for_segments(conn, chain)
        identifications, beliefs = _score_and_decode_sitting(
            conn,
            chain,
            wanted=wanted,
            notes_by_segment=notes_by_segment,
            examples=examples,
            signatures=signatures,
            share_weights=share_weights,
        )
        for row in asked:
            segment_id = int(row["id"])
            identification = identifications[segment_id]
            belief = beliefs[segment_id]
            band, _reason = _sequence_verdict(belief, identification)
            if band == "auto" and belief.chosen is not None:
                chosen = next(
                    (
                        candidate
                        for candidate in identification.candidates
                        if candidate.piece_id == belief.chosen
                    ),
                    None,
                )
                conn.execute(
                    "UPDATE segments SET piece_id = ?1, confidence = ?2,"
                    " identified_by = 'similarity' WHERE id = ?3",
                    (
                        belief.chosen,
                        round(chosen.score if chosen else belief.confidence, 4),
                        segment_id,
                    ),
                )
                report.assigned += 1
            elif band == "suggest":
                report.offered += 1
            else:
                report.unresolved += 1
    return report


def autotag_sitting(conn: sqlite3.Connection, sitting_id: int) -> AutotagReport:
    """Write the matches that are unambiguous for one sitting's unlabelled segments.

    Called where segments are materialised, so a sitting arrives already
    identified rather than waiting for someone to press a button. It writes only
    the confident band and leaves everything else for the timeline to offer.
    """
    rows = conn.execute(
        f"SELECT {_SEGMENT_COLUMNS} FROM segments g"
        " WHERE g.sitting_id = ? AND g.piece_id IS NULL"
        "   AND (g.identified_by IS NULL OR g.identified_by <> 'similarity')"
        " ORDER BY g.start_ms",
        (sitting_id,),
    ).fetchall()
    if not rows:
        return AutotagReport(considered=0)
    return _autotag_rows(conn, rows)


def autotag_unlabelled(db_path: Path | None = None) -> AutotagReport:
    """Look at every unlabelled segment in the library, newest sittings last.

    The backfill path, for a library that was already full of segments before the
    matcher existed. It writes the confident band only, exactly like the automatic
    pass, so re-running it can never invent a label it would not have written.
    """
    # `immediate`: every one of these reads a row and then writes what it read, and the app's
    # own design has two machines writing this file. A deferred transaction would fix its snapshot
    # at the first SELECT and then fail the write as "database is locked" if anything committed in
    # between — SQLITE_BUSY_SNAPSHOT, which `busy_timeout` does not retry.
    with db.transaction(db_path, immediate=True) as conn:
        rows = conn.execute(
            f"SELECT {_SEGMENT_COLUMNS} FROM segments g"
            " WHERE g.piece_id IS NULL"
            "   AND (g.identified_by IS NULL OR g.identified_by <> 'similarity')"
            " ORDER BY g.sitting_id, g.start_ms"
        ).fetchall()
        if not rows:
            return AutotagReport(considered=0)
        return _autotag_rows(conn, rows)


def identification_quality(db_path: Path | None = None) -> IdentificationQuality:
    """How good the matcher is on *your* library, measured by hiding each label.

    Leave-one-out: every labelled segment is matched against all the others, and
    scored on whether the piece you actually tagged it with came back. It is the
    only accuracy claim worth making, because it is computed from the material the
    matcher will really be asked about — including the pieces that sound like each
    other.

    Every labelled segment is now a reference (Phase 22b retired the reference window),
    and the mix over local content is applied here exactly as the live matcher applies it —
    a report that measured a different scorer than the one that writes labels would be a
    number nobody could act on. The sitting is then read as a sequence, exactly as the
    timeline and the ingest pass read it, because the band that gets written is the
    decoded one: reporting the per-segment band would understate the coverage the app
    now has and hide the errors the sequence introduces.

    The work is quadratic in the number of labels, so the newest
    ``autotag_quality_limit`` are evaluated and the report says how many were left
    out rather than quietly sampling.
    """
    conn = db.connect(db_path)
    try:
        # The *count* is of everything you have tagged; the *work* is bounded by the
        # cap, and the report says so rather than presenting a sample as the whole.
        total_labelled = labelled_count(conn)
        labelled = _labelled_rows(conn)
        inferred = int(
            conn.execute(
                "SELECT COUNT(*) FROM segments WHERE identified_by = 'similarity'"
            ).fetchone()[0]
        )
        quality = IdentificationQuality(
            labelled=total_labelled,
            inferred=inferred,
            **_outcome_counts(conn),
        )
        if len(labelled) < 2:
            quality.notes.append(
                "Two labelled segments are the minimum: with one there is nothing to "
                "compare it against."
            )
            return quality

        considered = labelled[-_store.settings.autotag_quality_limit :]
        quality.evaluated = len(considered)
        quality.skipped = len(labelled) - len(considered)
        examples, local, pooled = cached_references(conn)
        prints = {example.segment_id: example.fingerprint for example in examples}

        if quality.skipped:
            quality.notes.append(
                f"evaluated the newest {quality.evaluated} labelled segments; "
                f"{quality.skipped} older ones were left out to keep the report quick"
            )

        # Rank every segment first: the sequence reads a whole sitting at once, so the
        # per-segment work has to be done before any band is decided. Without this pass
        # the report would measure the scorer the app no longer uses.
        ranked: dict[int, Identification] = {}
        for row in considered:
            segment_id = int(row["id"])
            truth = int(row["piece_id"])
            # Leave-one-out over the pooled signatures too: the segment being asked about
            # must not be part of the evidence that answers it.
            signatures = {piece: sig for piece, sig in pooled.items() if piece != truth}
            remainder = pooled[truth] - local[segment_id]
            if remainder:
                signatures[truth] = remainder
            ranked[segment_id] = identify(
                prints[segment_id],
                [example for example in examples if example.segment_id != segment_id],
                score_auto=_store.settings.autotag_score_auto,
                score_prompt=_store.settings.autotag_score_prompt,
                min_margin=_store.settings.autotag_min_margin,
                min_notes=_store.settings.autotag_min_notes,
                shares=_shares(local[segment_id], signatures),
                containment_weight=_store.settings.autotag_containment_weight,
            )

        chains: list[list[sqlite3.Row]] = []
        for row in considered:
            if not chains or int(chains[-1][-1]["sitting_id"]) != int(row["sitting_id"]):
                chains.append([])
            chains[-1].append(row)

        for chain in chains:
            beliefs = _decode_sitting(
                [int(row["id"]) for row in chain],
                ranked={
                    segment_id: identification.candidates
                    for segment_id, identification in ranked.items()
                },
                note_counts={
                    int(row["id"]): prints[int(row["id"])].note_count for row in chain
                },
            )
            for row in chain:
                segment_id = int(row["id"])
                truth = int(row["piece_id"])
                belief = beliefs[segment_id]
                ordered = _chosen_first(ranked[segment_id].candidates, belief.chosen)
                top = belief.chosen
                quality.correct_top += int(top == truth)
                quality.correct_top3 += int(
                    truth in [candidate.piece_id for candidate in ordered[:3]]
                )
                band = sitting_sequence.band(
                    belief,
                    auto_probability=_store.settings.autotag_auto_probability,
                    prompt_probability=_store.settings.autotag_prompt_probability,
                    min_notes=_store.settings.autotag_min_notes,
                )
                if band == "auto":
                    quality.auto_attempted += 1
                    quality.auto_correct += int(top == truth)
                elif band == "suggest":
                    quality.offered_attempted += 1
                    quality.offered_correct += int(top == truth)
                else:
                    quality.unresolved += 1
        return quality
    finally:
        conn.close()


def _outcome_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT action, COUNT(*) AS total FROM identification_outcomes GROUP BY action"
    ).fetchall()
    counts = {row["action"]: int(row["total"]) for row in rows}
    return {
        "confirmed": counts.get("confirmed", 0),
        "changed": counts.get("changed", 0),
        "rejected": counts.get("rejected", 0),
        "dismissed": counts.get("dismissed", 0),
    }


def resolve_identification(
    segment_id: int, action: str, db_path: Path | None = None
) -> list[SegmentSummary]:
    """Answer the question a match asks: it is right, it is wrong, or not now.

    Only the decisions that are *about a guess* live here. Replacing a label with a
    different piece is an ordinary assignment and goes through ``assign_piece`` —
    which also records what became of the guess, so there is exactly one way to
    change a label and exactly one place that notices a guess was overruled.
    ``dismiss`` writes no label at all, because the match was never written either.
    """
    if action not in {"accept", "reject", "dismiss"}:
        raise InvalidRequest(f"{action!r} is not an identification outcome")

    # `immediate`: every one of these reads a row and then writes what it read, and the app's
    # own design has two machines writing this file. A deferred transaction would fix its snapshot
    # at the first SELECT and then fail the write as "database is locked" if anything committed in
    # between — SQLITE_BUSY_SNAPSHOT, which `busy_timeout` does not retry.
    with db.transaction(db_path, immediate=True) as conn:
        row = _store._segment_or_raise(conn, segment_id)
        inferred = row["identified_by"] == "similarity"

        if action == "dismiss":
            if inferred:
                raise InvalidRequest("that label was written by the matcher; reject it instead")
            # Recorded so the app stops asking. A declined suggestion is not an error
            # by the matcher, so it is deliberately not part of the accuracy figure.
            _record_outcome(
                conn,
                segment_id=segment_id,
                guessed_piece_id=None,
                resolved_piece_id=None,
                # The stored vocabulary is the past participle throughout, matching
                # the four counters the quality report reads: a request says
                # "dismiss", the row records that it *was* dismissed.
                action="dismissed",
                accepted=False,
                score=None,
            )
            return _store._segment_rows(conn, int(row["sitting_id"]))

        if not inferred:
            raise InvalidRequest(f"there is no inferred label to {action}")

        _store._settle_label(conn, row, row["piece_id"] if action == "accept" else None)
        return _store._segment_rows(conn, int(row["sitting_id"]))

