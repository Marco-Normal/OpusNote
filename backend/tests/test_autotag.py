"""Recognising a segment from your own labelled practice.

The matcher's arithmetic is tested in `test_similarity.py`. What is tested here is
everything that makes it part of the app: which segments count as training data,
what is written when a match is confident, what happens when a person disagrees,
and whether the accuracy claim can be checked.

The fixtures are drills rather than whole pieces on purpose: eight notes, drilled
slowly, sometimes one hand — because that is what the log actually contains.
"""

from __future__ import annotations

import dataclasses

import pytest

from app import db
from app.config import settings
from app.practice import store
from app.practice.models import EventBatch, WireNote

#: 2023-11-15, so every sitting created here is closed and segments exist.
BASE_MS = 1_700_011_800_000
#: Ten minutes between drills, comfortably past the five-minute sitting gap, so each
#: drill is its own sitting — which is also what a day of drilling looks like.
STEP_MS = 10 * 60 * 1000

#: Two pieces that are as close as two pieces can be without being the same music.
#: The second differs by one note, which is the case the matcher must not be
#: confident about.
PIECE_A = [60, 62, 64, 65, 67, 69, 71, 72]
PIECE_B = [60, 62, 64, 65, 67, 69, 71, 73]
#: A third that shares nothing: a different key and a different register.
PIECE_C = [45, 48, 52, 55, 57, 60, 48, 52]


def make_drill(index: int, pitches: list[int], *, spacing_ms: int = 250) -> int:
    """One drill in its own sitting, and its id."""
    base = BASE_MS + index * STEP_MS
    events = [
        WireNote(
            epoch_ms=base + position * spacing_ms,
            pitch=pitch,
            velocity=70,
            duration_ms=200,
            channel=0,
        )
        for position, pitch in enumerate(pitches)
    ]
    result = store.ingest(EventBatch(tz_offset_minutes=0, events=events))
    assert result.sitting_id is not None
    return result.sitting_id


def segment_of(sitting_id: int) -> int:
    segments = store.ensure_segments(sitting_id)
    assert len(segments) == 1, "a single drill is a single segment"
    return segments[0].id


def labelled_drill(index: int, pitches: list[int], piece_id: int, **kwargs) -> int:
    """A drill a person has tagged: one row of the training set."""
    sitting_id = make_drill(index, pitches, **kwargs)
    segment_id = segment_of(sitting_id)
    store.assign_piece(segment_id, piece_id)
    return segment_id


def two_pieces() -> tuple[int, int]:
    """Two library pieces. Created by direct insert: the repertoire API is not
    what is under test here."""
    conn = db.connect(settings.db_path)
    try:
        first = conn.execute("INSERT INTO pieces (title) VALUES ('Piece A')").lastrowid
        second = conn.execute("INSERT INTO pieces (title) VALUES ('Piece B')").lastrowid
        conn.commit()
        return int(first), int(second)
    finally:
        conn.close()


def distinct_library() -> tuple[int, int]:
    """Two hand-tagged pieces that sound nothing alike.

    Built so that *no* inferred label appears while building it — every drill here
    is either the first of its piece or far from the other's — which keeps the
    outcome counters clean for the tests that count them. A drill of this library
    then matches confidently, which is what the confident-band tests need.
    """
    piece_a, piece_b = two_pieces()
    labelled_drill(0, PIECE_A, piece_a)
    labelled_drill(1, PIECE_A, piece_a)
    labelled_drill(2, PIECE_C, piece_b)
    return piece_a, piece_b


def twin_library() -> tuple[int, int]:
    """Two pieces one note apart, hand-tagged.

    Nothing here can be identified confidently — the best score is high and the
    runner-up is right behind it — so every band stays at "offered", which is what
    the tests about being asked rather than told need. It is also the honest
    picture of a library in one key.
    """
    piece_a, piece_b = two_pieces()
    labelled_drill(0, PIECE_A, piece_a)
    labelled_drill(1, PIECE_A, piece_a)
    labelled_drill(2, PIECE_B, piece_b)
    labelled_drill(3, PIECE_B, piece_b)
    return piece_a, piece_b


def indistinguishable_library() -> tuple[int, int]:
    """Two pieces with the *same* material, hand-tagged.

    This is what "no confident match" has to mean. The one-note-apart pair above used to be
    the example, but Phase 22b's content term does tell those two apart — one note is a
    difference the local features can see and a whole-segment average cannot — so the tests
    that need a segment the matcher must decline use a pair nothing can separate.
    """
    piece_a, piece_b = two_pieces()
    labelled_drill(0, PIECE_A, piece_a)
    labelled_drill(1, PIECE_A, piece_a)
    labelled_drill(2, PIECE_A, piece_b)
    labelled_drill(3, PIECE_A, piece_b)
    return piece_a, piece_b


def drill_sitting(index: int, pitches: list[int]) -> int:
    """A drill that has been read, so its segments exist and have been identified."""
    sitting_id = make_drill(index, pitches)
    store.sitting_detail(sitting_id)
    return sitting_id


def outcomes_for(segment_id: int) -> list[dict]:
    """What has been decided about one segment, oldest first."""
    conn = db.connect(settings.db_path)
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT guessed_piece_id, resolved_piece_id, action, accepted"
                " FROM identification_outcomes WHERE segment_id = ? ORDER BY id",
                (segment_id,),
            )
        ]
    finally:
        conn.close()


# --------------------------------------------------------------------------
# What the matcher writes, and what it only offers
# --------------------------------------------------------------------------


def test_a_confident_match_is_written_as_an_inferred_label(fresh_db):
    piece_a, _piece_b = distinct_library()
    # The same music again, at the same tempo: nothing left to be unsure about.
    sitting_id = make_drill(10, PIECE_A)

    detail = store.sitting_detail(sitting_id)
    segment = detail.segments[0]
    assert segment.piece_id == piece_a
    assert segment.identified_by == "similarity", "marked as a machine guess"
    assert segment.confidence is not None and segment.confidence > 0.9
    assert segment.candidates == [], "a decided segment asks no questions"


def test_a_match_with_twins_is_offered_rather_than_written(fresh_db):
    """Two pieces with the same notes cannot be told apart, and the matcher must say so
    instead of picking one."""
    piece_a, _piece_b = indistinguishable_library()
    other = make_drill(10, PIECE_A)
    detail = store.sitting_detail(other)
    segment = detail.segments[0]
    assert segment.piece_id is None, "nothing was written"
    assert segment.candidates, "but the candidates are there to look at"
    top = segment.candidates[0]
    assert top.piece_id == piece_a
    assert top.band == "suggest"
    assert top.reason is not None and "close" in top.reason
    assert top.pitch_class > 0.9, "the notes do match: that is the problem"


def test_the_content_term_tells_one_note_apart_twins_apart(fresh_db, monkeypatch):
    """The measured win, stated as the thing that was broken.

    PIECE_A and PIECE_B differ by one note. The whole-segment average scored them inside the
    0.10 near-tie margin, so on the owner's library 46 of 54 segments were downgraded for
    having nothing to compare with and the auto band had never once fired. Asking for the
    ranking rather than the decision makes the margin itself visible.
    """
    piece_a, _piece_b = twin_library()
    sitting_id = make_drill(10, PIECE_A)

    # `settings` is a frozen dataclass, so it is replaced rather than mutated — the same way
    # the server-hardening tests narrow a limit. Only the decision is withheld; the scores
    # are the shipped ones.
    monkeypatch.setattr(
        store, "settings", dataclasses.replace(store.settings, autotag_min_margin=1.0)
    )
    segment = store.sitting_detail(sitting_id).segments[0]
    assert segment.candidates[0].piece_id == piece_a
    assert segment.candidates[0].margin > 0.10, "clear of the near-tie the average saw"


def test_the_candidates_carry_the_arithmetic_that_produced_them(fresh_db, monkeypatch):
    """The ranking is shown, not only the winner: agreeing with a match means seeing the
    numbers it was made from, and an alternative that differs is what makes that possible."""
    twin_library()
    # One note apart, so the two pieces do differ in score. The decision is withheld so that
    # the ranking is what the payload carries rather than an empty list on a written label.
    monkeypatch.setattr(
        store, "settings", dataclasses.replace(store.settings, autotag_min_margin=1.0)
    )
    segment = store.sitting_detail(make_drill(10, PIECE_A)).segments[0]

    assert len(segment.candidates) >= 2, "the alternatives come with it"
    for candidate in segment.candidates:
        assert 0.0 <= candidate.score <= 1.0
        assert 0.0 <= candidate.pitch_class <= 1.0
        assert 0.0 <= candidate.tempo <= 1.0
        assert 0.0 <= candidate.register_overlap <= 1.0
        assert candidate.title
    assert segment.candidates[0].score > segment.candidates[1].score


def test_a_manual_label_is_never_overwritten(fresh_db):
    """The one thing auto-tagging must never do: disagree with a person who has
    already answered."""
    piece_a, piece_b = distinct_library()
    sitting_id = make_drill(10, PIECE_A)
    segment_id = segment_of(sitting_id)
    assert store.sitting_detail(sitting_id).segments[0].identified_by == "similarity"
    store.assign_piece(segment_id, piece_b)  # deliberately "wrong"

    with db.transaction() as conn:
        report = store.autotag_sitting(conn, sitting_id)

    assert report.assigned == 0
    detail = store.sitting_detail(sitting_id)
    assert detail.segments[0].piece_id == piece_b
    assert detail.segments[0].identified_by == "manual"
    # And the matcher's guess is on the record as overruled, not quietly replaced.
    assert [row["action"] for row in outcomes_for(segment_id)] == ["changed"]


def test_a_segment_too_short_to_recognise_is_not_guessed_at(fresh_db):
    distinct_library()
    sitting_id = make_drill(10, [60, 62, 64])
    segment = store.sitting_detail(sitting_id).segments[0]
    assert segment.piece_id is None
    assert segment.candidates, "the ranking exists"
    assert segment.candidates[0].band == "none"
    assert segment.candidates[0].reason is not None
    assert "notes" in segment.candidates[0].reason


def test_nothing_is_offered_when_nothing_is_labelled(fresh_db):
    two_pieces()
    sitting_id = make_drill(0, PIECE_A)
    segment = store.sitting_detail(sitting_id).segments[0]
    assert segment.piece_id is None
    assert segment.candidates == [], "there is no reference to match against yet"


def test_the_matcher_does_not_train_on_its_own_guesses(fresh_db):
    """A wrong inference must not become evidence for the same mistake."""
    piece_a, _piece_b = distinct_library()
    sitting_id = make_drill(10, PIECE_A)
    assert store.sitting_detail(sitting_id).segments[0].identified_by == "similarity"

    conn = db.connect(settings.db_path)
    try:
        training = {row["id"] for row in store._labelled_rows(conn)}
        inferred = conn.execute(
            "SELECT id FROM segments WHERE identified_by = 'similarity'"
        ).fetchall()
    finally:
        conn.close()

    assert inferred, "the guess was written"
    assert not ({int(row["id"]) for row in inferred} & training), "but it is not training data"
    conn = db.connect(settings.db_path)
    try:
        assert piece_a in {row["piece_id"] for row in store._labelled_rows(conn)}, (
            "the hand-tagged drills still are"
        )
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Disagreeing
# --------------------------------------------------------------------------


def _inferred_segment(index: int = 10) -> tuple[int, int, int]:
    """A sitting whose single segment carries an inferred label.

    Returns ``(sitting_id, segment_id, guessed_piece_id)``. Built on the distinct
    library, so the guess is confident and the outcome counters start clean.
    """
    piece_a, _piece_b = distinct_library()
    sitting_id = make_drill(index, PIECE_A)
    segment = store.sitting_detail(sitting_id).segments[0]
    assert segment.identified_by == "similarity", "the fixture needs a written guess"
    return sitting_id, segment.id, piece_a


def _offered_segment(index: int = 10) -> tuple[int, int]:
    """A sitting whose single segment is *offered* a piece but not given one."""
    indistinguishable_library()
    sitting_id = make_drill(index, PIECE_A)
    segment = store.sitting_detail(sitting_id).segments[0]
    assert segment.piece_id is None and segment.candidates, "offered, not written"
    return sitting_id, segment.id


def test_rejecting_a_match_clears_it_and_records_the_mistake(fresh_db):
    sitting_id, segment_id, _guess = _inferred_segment()
    store.resolve_identification(segment_id, "reject")

    segment = store.sitting_detail(sitting_id).segments[0]
    assert segment.piece_id is None
    assert segment.identified_by is None
    assert len(outcomes_for(segment_id)) == 1
    assert outcomes_for(segment_id)[0]["action"] == "rejected"

    quality = store.identification_quality()
    assert (quality.rejected, quality.confirmed, quality.changed) == (1, 0, 0)
    assert quality.live_precision == 0.0, "the guess was written and it was wrong"


def test_accepting_a_match_makes_it_yours(fresh_db):
    sitting_id, segment_id, guessed = _inferred_segment()
    store.resolve_identification(segment_id, "accept")

    segment = store.sitting_detail(sitting_id).segments[0]
    assert segment.piece_id == guessed
    assert segment.identified_by == "manual", "a person now owns it"
    assert outcomes_for(segment_id)[0] == {
        "guessed_piece_id": guessed,
        "resolved_piece_id": guessed,
        "action": "confirmed",
        "accepted": 1,
    }

    quality = store.identification_quality()
    assert (quality.confirmed, quality.rejected) == (1, 0)
    assert quality.live_precision == 1.0


def test_changing_a_match_is_an_assignment_and_records_that_the_guess_was_wrong(fresh_db):
    """Replacing an inferred label with another piece is the ordinary assignment
    path — there is no second way to do it — and it still records the overrule."""
    sitting_id, segment_id, guessed = _inferred_segment()
    _first, piece_b = two_pieces()
    assert piece_b != guessed
    store.assign_piece(segment_id, piece_b)

    assert store.sitting_detail(sitting_id).segments[0].piece_id == piece_b
    assert store.sitting_detail(sitting_id).segments[0].identified_by == "manual"
    assert outcomes_for(segment_id)[0]["action"] == "changed"
    assert outcomes_for(segment_id)[0]["accepted"] == 0

    quality = store.identification_quality()
    assert (quality.changed, quality.confirmed) == (1, 0)
    assert quality.live_precision == 0.0


def test_rejecting_something_never_guessed_is_refused(fresh_db):
    piece_a, _piece_b = distinct_library()
    segment_id = labelled_drill(10, PIECE_C, piece_a)
    try:
        store.resolve_identification(segment_id, "reject")
    except store.InvalidRequest as exc:
        assert "no inferred label" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("there was nothing to reject")


def test_declining_an_offered_match_stops_it_being_offered(fresh_db):
    """The player said no to a *suggestion*, which was never written. It must not
    come back on the next reload, and it is not counted as a matcher error."""
    sitting_id, segment_id = _offered_segment()
    store.resolve_identification(segment_id, "dismiss")

    assert store.sitting_detail(sitting_id).segments[0].candidates == []
    assert outcomes_for(segment_id)[0]["action"] == "dismissed"

    quality = store.identification_quality()
    assert quality.dismissed == 1
    assert quality.live_precision is None, "a declined suggestion is not a wrong label"
    assert quality.settled == 0, "and it is not a guess the matcher got wrong"


def test_declining_a_written_label_is_refused(fresh_db):
    _sitting, segment_id, _guess = _inferred_segment()
    try:
        store.resolve_identification(segment_id, "dismiss")
    except store.InvalidRequest as exc:
        assert "reject it instead" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("dismissing a written label should be refused")


@pytest.mark.parametrize("action", ["maybe", "change"])
def test_an_unknown_outcome_is_refused(fresh_db, action):
    """`change` is included deliberately: it used to be an action here and is now
    the assignment path, so it must not quietly linger as a second owner."""
    _sitting, segment_id, _guess = _inferred_segment()
    try:
        store.resolve_identification(segment_id, action)
    except store.InvalidRequest as exc:
        assert "not an identification outcome" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("an unknown action should be refused")


def test_the_piece_dropdown_records_the_same_outcome_as_the_buttons(fresh_db):
    """Two ways to say the same thing must produce one record, or the live accuracy
    figure counts only the mistakes made through one of them."""
    _sitting, segment_id, _guess = _inferred_segment()
    store.assign_piece(segment_id, None)  # the dropdown's "clear"

    assert outcomes_for(segment_id)[0]["action"] == "rejected"
    quality = store.identification_quality()
    assert quality.rejected == 1
    assert quality.live_precision == 0.0


# --------------------------------------------------------------------------
# Measuring it
# --------------------------------------------------------------------------


def test_quality_is_measured_by_hiding_each_label(fresh_db):
    piece_a, piece_b = two_pieces()
    for index in range(0, 6, 2):
        labelled_drill(index, PIECE_A, piece_a)
        labelled_drill(index + 1, PIECE_C, piece_b)
    # Six hand-tagged drills, three of each piece: every one of them is hidden in
    # turn and matched against the other five.

    quality = store.identification_quality()
    assert quality.labelled == 6
    assert quality.evaluated == 6, "every label is tested, not sampled"
    assert quality.skipped == 0
    assert quality.accuracy is not None
    assert quality.correct_top >= 5, f"two obviously different pieces ({quality.correct_top}/6)"
    assert quality.top3_accuracy is not None and quality.top3_accuracy >= quality.accuracy


def test_quality_with_one_label_says_there_is_nothing_to_measure(fresh_db):
    piece_a, _piece_b = two_pieces()
    labelled_drill(0, PIECE_A, piece_a)

    quality = store.identification_quality()
    assert quality.labelled == 1
    assert quality.evaluated == 0
    assert quality.accuracy is None, "no denominator is not the same as zero"
    assert quality.auto_precision is None
    assert quality.notes and "minimum" in quality.notes[0]


def test_quality_counts_the_labels_written_but_not_yet_acted_on(fresh_db):
    distinct_library()
    store.sitting_detail(make_drill(10, PIECE_A))
    store.sitting_detail(make_drill(11, PIECE_A))

    quality = store.identification_quality()
    assert quality.inferred >= 1, "the matcher wrote labels"
    assert quality.confirmed == 0 and quality.settled == 0, "nobody has judged them yet"
    assert quality.live_precision is None


# --------------------------------------------------------------------------
# The backfill pass, and the routes
# --------------------------------------------------------------------------


def test_the_backfill_matches_segments_that_predate_the_matcher(fresh_db):
    """A library full of unlabelled segments from before the matcher existed."""
    piece_a, piece_b = two_pieces()
    # Drilled first, labelled later: there was nothing to compare against at the
    # time, so the segment was left blank — which is the situation the backfill is
    # for, and the reason it exists at all. Both pieces are labelled, because one
    # piece alone can never be a confident match: there is nothing to beat.
    old = make_drill(0, PIECE_A)
    segment_of(old)
    store.assign_piece(segment_of(make_drill(1, PIECE_A)), piece_a)
    store.assign_piece(segment_of(make_drill(2, PIECE_C)), piece_b)

    report = store.autotag_unlabelled()

    assert report.considered >= 1
    assert report.assigned == 1
    assert store.sitting_detail(old).segments[0].identified_by == "similarity"


def test_the_backfill_leaves_what_it_cannot_judge_alone(fresh_db):
    """It writes the confident band only, exactly like the automatic pass, so
    running it can never invent a label the live path would not have written."""
    indistinguishable_library()
    twin = make_drill(10, PIECE_A)
    segment_of(twin)

    report = store.autotag_unlabelled()
    assert report.assigned == 0, "a segment two pieces both explain is not a confident match"
    assert store.sitting_detail(twin).segments[0].piece_id is None


def test_the_autotag_route_reports_what_it_did(client):
    piece_a, piece_b = two_pieces()
    old = make_drill(0, PIECE_A)
    segment_of(old)
    store.assign_piece(segment_of(make_drill(1, PIECE_A)), piece_a)
    store.assign_piece(segment_of(make_drill(2, PIECE_C)), piece_b)

    body = client.post("/api/practice/autotag").json()
    assert body["considered"] >= 1
    assert body["assigned"] == 1


def test_the_offer_route_ranks_a_segment_through_the_api(client):
    """The suggestion is part of the sitting payload, which is what the timeline
    reads — so there is no second request to make it appear."""
    indistinguishable_library()
    sitting_id = make_drill(10, PIECE_A)

    detail = client.get(f"/api/practice/sittings/{sitting_id}").json()
    candidates = detail["segments"][0]["candidates"]
    assert candidates
    assert {"piece_id", "title", "score", "band", "reason"} <= set(candidates[0])
    assert candidates[0]["band"] == "suggest"


def test_the_identification_routes_round_trip(client):
    _sitting, segment_id, _guess = _inferred_segment()
    rejected = client.post(
        f"/api/practice/segments/{segment_id}/identification", json={"action": "reject"}
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()[0]["piece_id"] is None

    quality = client.get("/api/practice/autotag/quality").json()
    assert quality["rejected"] == 1
    assert quality["live_precision"] == 0.0
    assert quality["settled"] == 1


def test_an_unknown_action_is_a_422_not_a_500(client):
    _sitting, segment_id, _guess = _inferred_segment()
    response = client.post(
        f"/api/practice/segments/{segment_id}/identification", json={"action": "maybe"}
    )
    assert response.status_code == 422


def test_every_labelled_segment_is_a_reference(fresh_db):
    """Phase 22b retired the reference window, and this is the retirement.

    Signatures are pooled per piece, so the reference set costs O(pieces) rather than
    O(labels) and there is no reason to truncate it. Truncating was not free: a piece learned
    a year ago fell out of the window, which is the cliff the phase exists to remove.
    """
    piece_a, piece_b = two_pieces()
    for index in range(4):
        labelled_drill(
            index,
            PIECE_A if index % 2 == 0 else PIECE_C,
            piece_a if index % 2 == 0 else piece_b,
        )

    quality = store.identification_quality()
    assert quality.labelled == 4, "the count is of everything you tagged"
    assert quality.evaluated == 4, "and every one of them is compared against the rest"
    assert quality.skipped == 0
    assert not any("reference window" in note for note in quality.notes)


def test_the_quality_report_says_how_much_it_left_out(fresh_db, monkeypatch):
    """The *work* is still bounded, because leave-one-out is quadratic.

    `autotag_quality_limit` caps how many segments are tested, and the report names the
    number rather than presenting a sample as the whole — the same promise the retired
    reference window made, kept where it still means something.
    """
    piece_a, piece_b = two_pieces()
    for index in range(4):
        labelled_drill(
            index,
            PIECE_A if index % 2 == 0 else PIECE_C,
            piece_a if index % 2 == 0 else piece_b,
        )

    # `settings` is a frozen dataclass, so it is replaced rather than mutated —
    # the same way the server-hardening tests narrow a limit.
    monkeypatch.setattr(
        store, "settings", dataclasses.replace(store.settings, autotag_quality_limit=2)
    )

    quality = store.identification_quality()
    assert quality.labelled == 4, "the count is of everything you tagged"
    assert quality.evaluated == 2, "the work is bounded by the evaluation cap"
    assert quality.skipped == 2
    assert any("newest 2" in note for note in quality.notes)


# --------------------------------------------------------------------------
# The reference material is cached, and the database owns the invalidation
#
# Deriving it is a pass over every labelled segment's notes — about a second on the
# owner's library — producing an answer that changes only when a label or a boundary
# does. The tests below are the invalidation contract: a label written by *any* path
# must be visible to the next read, and a write that is not an input to the derived
# material must not throw it away.
# --------------------------------------------------------------------------


def _references():
    """The cached material, read on its own connection the way a request would."""
    conn = db.connect(settings.db_path)
    try:
        return store.cached_references(conn)
    finally:
        conn.close()


def test_reading_the_references_twice_rebuilds_them_once(fresh_db) -> None:
    distinct_library()
    first = _references()
    second = _references()
    assert second[0] is first[0], "the examples were rebuilt with nothing changed"
    assert second[2] is first[2], "and so were the pooled signatures"


def test_labelling_a_segment_adds_it_to_the_cached_references(fresh_db) -> None:
    piece_a, _piece_b = distinct_library()
    before = _references()

    labelled_drill(9, PIECE_A, piece_a)

    after = _references()
    assert len(after[0]) == len(before[0]) + 1, "the new label must reach the training set"
    assert after[0] is not before[0], "and must not be served from the stale list"


def test_relabelling_a_segment_invalidates_the_cached_references(fresh_db) -> None:
    """The case a count- or id-keyed cache misses: the rows are the same, the label is not."""
    piece_a, piece_b = two_pieces()
    segment_id = labelled_drill(0, PIECE_A, piece_a)
    before = _references()

    store.assign_piece(segment_id, piece_b)

    after = _references()
    assert {example.piece_id for example in before[0]} == {piece_a}
    assert {example.piece_id for example in after[0]} == {piece_b}


def test_answering_a_practice_kind_keeps_the_cached_references(fresh_db) -> None:
    """A kind is not an input to a fingerprint or a content feature, so it may not evict."""
    piece_a, _piece_b = two_pieces()
    segment_id = labelled_drill(0, PIECE_A, piece_a)
    before = _references()

    store.set_practice_kind(segment_id, "set", "slow")

    after = _references()
    assert after[0] is before[0], "a practice kind must not throw the references away"


def test_init_db_forgets_the_cached_references(fresh_db) -> None:
    """The path may hold a different database afterwards, so nothing may survive it."""
    distinct_library()
    conn = db.connect(settings.db_path)
    try:
        before = store.cached_references(conn)
        db.init_db(settings.db_path)
        after = store.cached_references(conn)
    finally:
        conn.close()
    assert after[0] is not before[0]


def test_every_label_is_a_reference_however_lopsided_the_library(fresh_db) -> None:
    """Phase 22b retired the reference window as a *correctness* boundary, not a speed one.

    A newest-N cap evicts a piece outright once another piece is practised more often, and a
    piece that has fallen out cannot be recognised — nor can it be anyone's runner-up, which
    is how the auto band stopped firing entirely on the owner's library. This pins the
    decision through `cached_references`, the material every live path reads, so re-adding a
    cap at `_labelled_rows` or at any caller fails here rather than silently trimming the
    matcher's knowledge.
    """
    piece_a, piece_b = two_pieces()
    labelled_drill(0, PIECE_C, piece_b)  # the quiet piece, and the older label
    for index in range(1, 31):
        labelled_drill(index, PIECE_A, piece_a)  # thirty newer labels of one piece

    conn = db.connect(settings.db_path)
    try:
        examples, _local, _pooled = store.cached_references(conn)
    finally:
        conn.close()

    assert len(examples) == 31, "every segment a person labelled is a reference"
    assert {example.piece_id for example in examples} == {piece_a, piece_b}, (
        "a cap would evict the quiet piece and leave the busy one as its own runner-up"
    )


def _unlabelled_sitting(index: int, segments: int) -> int:
    """One sitting whose notes are cut into `segments` unlabelled pieces."""
    sitting_id = make_drill(index, PIECE_A * 3)
    conn = db.connect(settings.db_path)
    try:
        span = int(
            conn.execute(
                "SELECT MAX(onset_ms + duration_ms) FROM note_events WHERE sitting_id = ?",
                (sitting_id,),
            ).fetchone()[0]
        )
        conn.execute("DELETE FROM segments WHERE sitting_id = ?", (sitting_id,))
        for position in range(segments):
            conn.execute(
                "INSERT INTO segments (sitting_id, start_ms, end_ms, piece_id, identified_by)"
                " VALUES (?, ?, ?, NULL, NULL)",
                (sitting_id, span * position // segments, span * (position + 1) // segments),
            )
        conn.commit()
    finally:
        conn.close()
    return sitting_id


def test_reading_a_sitting_does_not_read_its_notes_once_per_open_section(
    fresh_db, monkeypatch
) -> None:
    """The cost that made an edit slow exactly while an unlabelled section remained.

    Each suggestion asked about a segment by *sitting*, so the query returned every note in the
    sitting and kept one segment's share — meaning a sitting read its own notes once for every
    open section, on every edit's re-read of the detail. Once the last section was labelled the
    pass returned early and the slowness vanished, which is the report this guards.

    Counted rather than timed, so the assertion cannot pass by running on a quiet machine: the
    number of note reads must not depend on how many sections are still open.
    """
    piece_a, _piece_b = two_pieces()
    for index in range(4):
        labelled_drill(index, PIECE_A, piece_a)

    small = _unlabelled_sitting(50, 2)
    large = _unlabelled_sitting(60, 8)

    calls = {"n": 0}
    original = store._notes_for_segments

    def counted(conn, rows):
        calls["n"] += 1
        return original(conn, rows)

    # Warm the reference cache first. A cold first read legitimately costs one extra note read
    # to build the references, and this test is about the per-open-section cost, not that one.
    conn = db.connect(settings.db_path)
    try:
        store.cached_references(conn)
    finally:
        conn.close()

    monkeypatch.setattr(store, "_notes_for_segments", counted)

    store.sitting_detail(small)
    after_small = calls["n"]
    store.sitting_detail(large)
    after_large = calls["n"] - after_small

    assert after_small == after_large, (
        "the note read must not grow with how many sections are open: "
        f"2 sections cost {after_small} reads, 8 cost {after_large}"
    )
