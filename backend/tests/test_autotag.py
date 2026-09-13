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
    """Two pieces one note apart cannot be told apart with confidence, and the
    matcher must say so instead of picking one."""
    piece_a, _piece_b = twin_library()
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


def test_the_candidates_carry_the_arithmetic_that_produced_them(fresh_db):
    twin_library()
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
    twin_library()
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
    piece_a, piece_b = two_pieces()
    labelled_drill(0, PIECE_A, piece_a)
    labelled_drill(1, PIECE_A, piece_a)
    labelled_drill(2, PIECE_B, piece_b)
    twin = make_drill(3, PIECE_B)
    segment_of(twin)

    report = store.autotag_unlabelled()
    assert report.assigned == 0, "a one-note-apart twin is not a confident match"
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
    twin_library()
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


def test_the_reference_window_is_capped_and_says_so(fresh_db, monkeypatch):
    """Every read derives a fingerprint per reference, so the set has to be bounded
    or the log gets slower every month for the rest of the library's life."""
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
        store, "settings", dataclasses.replace(store.settings, autotag_training_limit=2)
    )

    quality = store.identification_quality()
    assert quality.labelled == 4, "the count is of everything you tagged"
    assert quality.evaluated == 2, "the work is bounded by the window"
    assert any("newest 2" in note for note in quality.notes)
