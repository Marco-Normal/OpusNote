"""Grouping attempts into passages, and passages into piece-sessions."""

from __future__ import annotations

from app.practice.passages import Attempt, derive, piece_sessions

#: Uniform weights, and signatures as plain counters, so these units are about the grouping
#: decision rather than about feature extraction (which has its own suite).
WEIGHTS = {"a": 1.0, "z": 1.0}
SAME = {"a": 10}
DIFFERENT = {"z": 10}


def attempt(id: int, start_ms: int, end_ms: int, piece_id: int | None = None) -> Attempt:
    return Attempt(id=id, start_ms=start_ms, end_ms=end_ms, piece_id=piece_id)


def test_adjacent_attempts_of_one_passage_group() -> None:
    attempts = [attempt(1, 0, 1_000), attempt(2, 5_000, 6_000), attempt(3, 9_000, 10_000)]
    signals = {1: SAME, 2: SAME, 3: SAME}
    out = derive(attempts, signals, WEIGHTS)
    assert len(out) == 1
    assert out[0].attempts == 3
    assert out[0].attempt_ids == (1, 2, 3)
    assert (out[0].start_ms, out[0].end_ms) == (0, 10_000)


def test_different_material_makes_a_new_passage() -> None:
    attempts = [attempt(1, 0, 1_000), attempt(2, 5_000, 6_000)]
    signals = {1: SAME, 2: DIFFERENT}
    out = derive(attempts, signals, WEIGHTS)
    assert len(out) == 2


def test_a_differing_label_is_always_a_boundary() -> None:
    """Two pieces are two passages however alike they sound."""
    attempts = [attempt(1, 0, 1_000, 7), attempt(2, 5_000, 6_000, 8)]
    signals = {1: SAME, 2: SAME}
    assert len(derive(attempts, signals, WEIGHTS)) == 2


def test_a_matching_label_is_not_enough_on_its_own() -> None:
    """Bars 1-16 and bars 40-60 of one piece are two passages, not one."""
    attempts = [attempt(1, 0, 1_000, 7), attempt(2, 5_000, 6_000, 7)]
    signals = {1: SAME, 2: DIFFERENT}
    assert len(derive(attempts, signals, WEIGHTS)) == 2


def test_a_passage_takes_the_label_any_of_its_attempts_carries() -> None:
    attempts = [attempt(1, 0, 1_000), attempt(2, 5_000, 6_000, 7)]
    signals = {1: SAME, 2: SAME}
    out = derive(attempts, signals, WEIGHTS)
    assert len(out) == 1 and out[0].piece_id == 7


def test_an_attempt_with_no_signature_is_its_own_passage() -> None:
    """A segment with no notes cannot be shown to belong with anything."""
    attempts = [attempt(1, 0, 1_000), attempt(2, 5_000, 6_000)]
    signals = {1: SAME}
    assert len(derive(attempts, signals, WEIGHTS)) == 2


def test_nothing_is_no_passages() -> None:
    assert derive([], {}, WEIGHTS) == []


def test_the_round_trip_is_stable() -> None:
    """The same labels always produce the same groups, which is what makes deriving safe."""
    attempts = [attempt(1, 0, 1_000, 7), attempt(2, 5_000, 6_000, 7), attempt(3, 9_000, 10_000, 8)]
    signals = {1: SAME, 2: SAME, 3: SAME}
    first = derive(attempts, signals, WEIGHTS)
    second = derive(attempts, signals, WEIGHTS)
    assert [(p.piece_id, p.attempt_ids) for p in first] == \
           [(p.piece_id, p.attempt_ids) for p in second]
    assert len(first) == 2


def test_piece_sessions_group_adjacent_passages_of_one_piece() -> None:
    """Two attempts of piece 7, then one of piece 8, then two more of piece 7."""
    attempts = [attempt(1, 0, 1_000, 7), attempt(2, 5_000, 6_000, 7),
                attempt(3, 9_000, 10_000, 8),
                attempt(4, 12_000, 13_000, 7), attempt(5, 15_000, 16_000, 7)]
    signals = {1: SAME, 2: SAME, 3: DIFFERENT, 4: SAME, 5: SAME}
    passages = derive(attempts, signals, WEIGHTS)
    assert [(p.piece_id, p.attempts) for p in passages] == [(7, 2), (8, 1), (7, 2)]
    assert piece_sessions(passages) == [(7, (0,)), (8, (1,)), (7, (2,))]
