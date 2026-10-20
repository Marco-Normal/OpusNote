"""Identifying a segment by comparing it with your own labelled practice.

Adapted from `practice-logger/docs/DESIGN.md` §5, which is where this was designed
and never built. The insight it rests on is the reason there is no score-matching
here: **you are the reference.** Every segment you tag becomes a labelled example,
and a new segment is matched against your own labelled segments rather than against
a library of fingerprints that does not exist.

Five terms, one score, with weights chosen by measurement rather than by the design:

    cosine(pitch-class profile)      what notes, in what proportion
    tempo proximity                  how fast, as a ratio
    register overlap                 which part of the keyboard
    hand overlap                     the two registers compared separately
    interval overlap                 the shape between consecutive attacks

The last two arrived in Phase 22e, after the sitting sequence: they are what let a
one-hand drill be recognised as that hand playing that passage rather than as material
that resembles the whole piece.

Everything here is a pure function of note lists, so a fingerprint is derived and
never stored: change the weights, or fix the tempo rule, and every match is
recomputed from `note_events` rather than needing a migration.

**What the reference material actually looks like.** This was designed for a player
who runs pieces end to end, and that is not how practice works: a segment is usually
a drilled *section*, at whatever tempo the section needed that day, sometimes on one
hand, sometimes staccato. Three consequences are built in rather than hoped away:

* The tempo term is the least trustworthy of the three, because half-speed drilling
  is normal rather than an error. Its weight is set by measurement (see
  `tools/measure_autotag.py`) rather than by the design's original 0.25.
* Register overlap does real work here: it is what tells a right-hand drill from a
  left-hand drill of the same passage.
* A sitting is usually one piece at a time, so a near-tie is broken towards the piece
  the sitting has already been about — the one thing an algorithm cannot know and the
  player would assume.

Two honest limitations, restated from the design because they shape the interface:
pieces in the same key with a similar texture stay confusable, and a piece you have
never tagged cannot be identified. That is why the confidence bands exist, why
matches are offered rather than written except when they are unambiguous, and why
"not this" is recorded.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from functools import cached_property, lru_cache
from operator import mul
from typing import Iterable, Mapping, Sequence

from .metrics import attacks, median_tempo
from .sessionize import Note

#: Pitch classes in an octave. A profile is this long and sums to 1.
PITCH_CLASSES = 12

#: What an unknown tempo scores. Half, not zero: a two-note segment has no
#: measurable rate, and scoring it 0 would reject a match the pitch profile is
#: perfectly capable of making, while scoring it 1 would hand out a free quarter.
NEUTRAL_TEMPO = 0.5

#: Where the two hands are assumed to divide: middle C. The MIDI channel does not carry
#: the hand — a digital piano sends every key on one channel — so a fingerprint splits by
#: register instead, which is the only signal the notes themselves provide.
HAND_SPLIT = 60

#: A hand with fewer notes than this has no shape worth comparing, so it is left out of
#: the hand term rather than compared as noise.
HAND_MIN_NOTES = 2

#: What a hand or interval comparison scores when there is nothing comparable on one side.
#: Half for the same reason as `NEUTRAL_TEMPO`: silence is not evidence either way.
NEUTRAL_HAND = 0.5
NEUTRAL_INTERVAL = 0.5

#: The shortest run of attacks whose intervals say anything. Two notes are one interval.
INTERVAL_MIN = 2


@dataclass(frozen=True)
class Weights:
    """How much each term counts, normalised to sum to 1 before use.

    A parameter rather than three module constants so the weights can be *measured*
    on drill-shaped material instead of inherited: see `tools/measure_autotag.py`,
    which is how `DEFAULT_WEIGHTS` below was chosen.
    """

    pitch_class: float = 0.75
    tempo: float = 0.10
    register: float = 0.15
    #: The terms added after measurement (Phase 22e). Zero until measured to earn their
    #: place, which keeps every score and every sweep in `tools/measure_autotag.py`
    #: comparable with the shipped one.
    hand: float = 0.0
    interval: float = 0.0

    #: Cached because scoring a segment calls it once per labelled example — 56,252 times on
    #: the owner's library — and the answer depends on the ratio of three numbers that cannot
    #: change: this is a frozen dataclass. Weights are few (the default, whatever a caller
    #: passes, and the handful the measuring tool sweeps), so the cache cannot grow.
    @lru_cache(maxsize=None)
    def normalised(self) -> "Weights":
        total = self.pitch_class + self.tempo + self.register + self.hand + self.interval
        if total <= 0:
            raise ValueError("at least one weight must be positive")
        return Weights(
            pitch_class=self.pitch_class / total,
            tempo=self.tempo / total,
            register=self.register / total,
            hand=self.hand / total,
            interval=self.interval / total,
        )


#: Chosen by measurement, not by inheritance: the design's 0.60/0.25/0.15 assumed
#: whole-piece run-throughs at performance tempo, and on drilled sections the tempo
#: term cost more correct answers than it won. The measurement is reproducible —
#: `backend/tools/measure_autotag.py` — and the numbers are in `docs/ECOSYSTEM.md`.
#:
#: The hand and interval terms earn 0.10 and 0.05 at 32 pieces, where the matcher has to
#: tell same-key, same-texture pieces apart: top-1 rises 61.8% -> 64.2% on whole drills and
#: 26.4% -> 29.5% on quarter-length fragments, and the auto band's precision at those
#: weights goes 87.5% -> 100%. On the owner's own library they are exactly neutral
#: (98.2% top-1 either way) because 431 of her 443 labelled segments use both hands; the
#: gain is where the library is hard, and the cost is nothing measurable.
DEFAULT_WEIGHTS = Weights(pitch_class=0.75, tempo=0.10, register=0.15, hand=0.10, interval=0.05)

#: How much closer the sitting's prevailing piece has to be to win a near-tie. Small
#: on purpose: this is a tie-break, not evidence, and a real difference in the notes
#: should still beat "what you were already playing".
CONTEXT_MARGIN = 0.05


@dataclass(frozen=True)
class Fingerprint:
    """What the matcher knows about a stretch of playing.

    Derived on every use rather than stored, so a change to the rules applies
    everywhere at once and nothing can be stale.
    """

    #: Share of the notes in each pitch class, summing to 1 (or all zero).
    pc_profile: tuple[float, ...]
    #: Attack-cluster note rate in BPM, the same measure the log calls tempo.
    note_rate: float | None
    pitch_min: int
    pitch_max: int
    note_count: int
    #: Pitch-class profiles of the notes below and at/above `HAND_SPLIT`, each summing to 1
    #: (or all zero when that hand played nothing). Kept apart because a right-hand drill and
    #: a left-hand drill of the same passage share almost no register, and pooling them into
    #: one profile makes each look like the other.
    low_profile: tuple[float, ...] = (0.0,) * PITCH_CLASSES
    high_profile: tuple[float, ...] = (0.0,) * PITCH_CLASSES
    low_count: int = 0
    high_count: int = 0
    #: Interval classes between consecutive attacks (0-11, undirected), summing to 1. A
    #: transposition moves the same tune through the same intervals, and an octave apart is
    #: interval class 0, so this term does not care which key or which hand the passage was
    #: played in.
    interval_profile: tuple[float, ...] = (0.0,) * PITCH_CLASSES
    interval_count: int = 0

    @property
    def has_notes(self) -> bool:
        return self.note_count > 0

    @cached_property
    def pc_unit(self) -> tuple[float, ...]:
        """The whole-segment profile at length one, for the dot-product comparison."""
        return _unit(self.pc_profile, self.profile_norm)

    @cached_property
    def low_norm(self) -> float:
        return _profile_norm(self.low_profile)

    @cached_property
    def high_norm(self) -> float:
        return _profile_norm(self.high_profile)

    @cached_property
    def low_unit(self) -> tuple[float, ...]:
        return _unit(self.low_profile, self.low_norm)

    @cached_property
    def high_unit(self) -> tuple[float, ...]:
        return _unit(self.high_profile, self.high_norm)

    @cached_property
    def interval_unit(self) -> tuple[float, ...]:
        return _unit(self.interval_profile, self.interval_norm)

    @cached_property
    def interval_norm(self) -> float:
        return _profile_norm(self.interval_profile)

    @cached_property
    def profile_norm(self) -> float:
        """The length of the pitch-class profile, computed once per fingerprint.

        Every comparison divides by it, and one segment is compared with every labelled
        example, so recomputing it inside `cosine` recomputed the *segment's* own length
        once per example. Derived on first use rather than in `__post_init__` because a
        fingerprint that is never scored should not pay for it — and it is not a dataclass
        field, so equality and the repr still describe the notes, not the arithmetic.
        """
        return _profile_norm(self.pc_profile)


@dataclass(frozen=True)
class Example:
    """A labelled segment: one row of training data."""

    segment_id: int
    piece_id: int
    fingerprint: Fingerprint


@dataclass(frozen=True)
class Candidate:
    """One piece's claim on a segment, with the arithmetic shown."""

    piece_id: int
    score: float
    pitch_class: float
    tempo: float
    register: float
    #: How many labelled segments of this piece were examined. Agreement is evidence, but
    #: it is reported rather than folded into `score`, so the number in the interface means
    #: one thing.
    support: int
    #: Best score of a *different* piece, or None when this was the only piece seen. A high
    #: score with a near-tie is not confidence.
    runner_up: float | None
    #: The terms added in Phase 22e. Reported even when their weight is zero, because the
    #: number shown to the player is the arithmetic behind the score, not a subset of it.
    hand: float = 0.0
    interval: float = 0.0

    @property
    def margin(self) -> float:
        return 0.0 if self.runner_up is None else self.score - self.runner_up


#: The three outcomes a match can have, from the two configured thresholds.
Band = str  # 'auto' | 'suggest' | 'none'


@dataclass(frozen=True)
class Identification:
    candidates: tuple[Candidate, ...]
    band: Band
    #: Why the band is what it is, in words — shown to the player, so it says
    #: something a person can act on rather than naming an internal state.
    reason: str

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None


def fingerprint(notes: Sequence[Note], *, attack_window_ms: int) -> Fingerprint:
    """Summarise a stretch of playing, from its notes alone.

    Each note counts once, chords included. Weighting by duration was the
    alternative — it is what the classic key-finding profiles do — and it was
    rejected here because a held final chord would then outweigh a whole phrase of
    movement, which is the opposite of what identifies a piece.
    """
    if not notes:
        return Fingerprint(
            pc_profile=(0.0,) * PITCH_CLASSES,
            note_rate=None,
            pitch_min=0,
            pitch_max=0,
            note_count=0,
        )

    counts = [0] * PITCH_CLASSES
    low = [0] * PITCH_CLASSES
    high = [0] * PITCH_CLASSES
    for note in notes:
        counts[note.pitch % PITCH_CLASSES] += 1
        (low if note.pitch < HAND_SPLIT else high)[note.pitch % PITCH_CLASSES] += 1
    total = sum(counts)
    profile = tuple(count / total for count in counts)
    low_total = sum(low)
    high_total = sum(high)

    # One interval per pair of *attacks*, so a chord does not produce zero-interval
    # evidence between its own notes: the last note of one attack to the first note of
    # the next, in pitch order within the chord so the choice is deterministic.
    intervals = [0] * PITCH_CLASSES
    previous: Note | None = None
    interval_total = 0
    for note in sorted(notes, key=lambda item: (item.epoch_ms, item.pitch)):
        if previous is not None and note.epoch_ms != previous.epoch_ms:
            intervals[(note.pitch - previous.pitch) % PITCH_CLASSES] += 1
            interval_total += 1
        previous = note

    pitches = [note.pitch for note in notes]
    return Fingerprint(
        pc_profile=profile,
        note_rate=median_tempo(list(notes), attack_window_ms),
        pitch_min=min(pitches),
        pitch_max=max(pitches),
        note_count=len(notes),
        low_profile=tuple(count / low_total for count in low) if low_total else (0.0,) * PITCH_CLASSES,
        high_profile=tuple(count / high_total for count in high) if high_total else (0.0,) * PITCH_CLASSES,
        low_count=low_total,
        high_count=high_total,
        interval_profile=(
            tuple(count / interval_total for count in intervals)
            if interval_total
            else (0.0,) * PITCH_CLASSES
        ),
        interval_count=interval_total,
    )


def _profile_norm(profile: Sequence[float]) -> float:
    """The length of a pitch-class profile. The one place that arithmetic lives."""
    return math.sqrt(sum(a * a for a in profile))


def _unit(profile: Sequence[float], norm: float) -> tuple[float, ...]:
    """The profile scaled to length one, so a comparison is a dot product.

    `rank` scores one segment against every labelled example, and each cosine divides by
    the two lengths it already knows; scaling once when the fingerprint is built turns
    three sums and two lengths per comparison into one sum. Same arithmetic, no square
    roots in the loop.
    """
    if norm == 0.0:
        return tuple(0.0 for _ in profile)
    return tuple(value / norm for value in profile)


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine of two vectors already scaled to length one, clamped into 0..1."""
    return min(1.0, max(0.0, sum(map(mul, left, right))))


def _cosine(
    left: Sequence[float],
    right: Sequence[float],
    norm_left: float,
    norm_right: float,
) -> float:
    """`cosine` with the two lengths already known.

    Split out because `rank` scores one segment against every labelled example: the
    segment's length is the same number every time, and each example's was computed when
    its fingerprint was built, so taking them as arguments removes two of the three sums
    per comparison without changing the arithmetic (the same sum, in the same order).
    """
    if len(left) != len(right):
        raise ValueError("profiles must be the same length")
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    dot = sum(map(mul, left, right))
    return min(1.0, max(0.0, dot / (norm_left * norm_right)))


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity of two non-negative vectors, in 0..1.

    Zero when either side is empty rather than an error: a segment with no notes
    has nothing to say about any piece, and 0 says that correctly.
    """
    return _cosine(left, right, _profile_norm(left), _profile_norm(right))


def tempo_proximity(left: float | None, right: float | None) -> float:
    """How close two note rates are, as a ratio rather than a difference.

    Ratio, because ten BPM means something quite different at 40 and at 160: the
    design's own measure. 100 against 120 scores higher than 40 against 60, which
    is the behaviour a musician would expect.
    """
    if left is None or right is None:
        return NEUTRAL_TEMPO
    if left <= 0.0 or right <= 0.0:
        return NEUTRAL_TEMPO
    return min(left, right) / max(left, right)


def register_overlap(
    left: tuple[int, int], right: tuple[int, int]
) -> float:
    """How much two pitch ranges share, as intersection over union.

    Inclusive on both ends: the high note is part of the range. An empty range
    (no notes) overlaps nothing, which is the honest answer.
    """
    if left[1] < left[0] or right[1] < right[0]:
        return 0.0
    low = max(left[0], right[0])
    high = min(left[1], right[1])
    intersection = high - low + 1
    if intersection <= 0:
        return 0.0
    union = max(left[1], right[1]) - min(left[0], right[0]) + 1
    return intersection / union


def hand_overlap(left: Fingerprint, right: Fingerprint) -> float:
    """How alike the two hands' shapes are, hands compared separately.

    A right-hand drill of a passage and a left-hand drill of it share almost no register,
    so pooling every note into one profile makes each look like the other's opposite. Each
    side is compared only as far as *both* sides contain it: the weight of a hand is
    ``min(share(left), share(right))``, so a segment that was all right hand is not charged
    for the left-hand notes the reference happened to include, and two mixed recordings are
    compared on both hands. `NEUTRAL_HAND` when neither side has enough on both.
    """
    if left.note_count == 0 or right.note_count == 0:
        return NEUTRAL_HAND
    total = 0.0
    weighted = 0.0
    for unit_left, unit_right, count, other_count in (
        (left.low_unit, right.low_unit, left.low_count, right.low_count),
        (left.high_unit, right.high_unit, left.high_count, right.high_count),
    ):
        if count < HAND_MIN_NOTES or other_count < HAND_MIN_NOTES:
            continue
        share = min(count / left.note_count, other_count / right.note_count)
        total += share
        weighted += share * _dot(unit_left, unit_right)
    if total == 0.0:
        return NEUTRAL_HAND
    return weighted / total


def interval_overlap(left: Fingerprint, right: Fingerprint) -> float:
    """How alike the two interval-class shapes are: transposition-invariant by construction.

    Two notes are one interval, so a segment shorter than `INTERVAL_MIN` pairs says nothing
    and scores `NEUTRAL_INTERVAL` rather than claiming a shape it does not have.
    """
    if left.interval_count < INTERVAL_MIN or right.interval_count < INTERVAL_MIN:
        return NEUTRAL_INTERVAL
    return _dot(left.interval_unit, right.interval_unit)


def compare(
    segment: Fingerprint,
    candidate: Fingerprint,
    *,
    weights: Weights = DEFAULT_WEIGHTS,
) -> tuple[float, float, float, float, float, float]:
    """Score one candidate against one segment: ``(total, pitch, tempo, register, hand, interval)``."""
    pitch_class = _dot(segment.pc_unit, candidate.pc_unit)
    tempo = tempo_proximity(segment.note_rate, candidate.note_rate)
    register = register_overlap(
        (segment.pitch_min, segment.pitch_max),
        (candidate.pitch_min, candidate.pitch_max),
    )
    hand = hand_overlap(segment, candidate)
    interval = interval_overlap(segment, candidate)
    scaled = weights.normalised()
    total = (
        scaled.pitch_class * pitch_class
        + scaled.tempo * tempo
        + scaled.register * register
        + scaled.hand * hand
        + scaled.interval * interval
    )
    return (min(1.0, max(0.0, total)), pitch_class, tempo, register, hand, interval)


def rank(
    segment: Fingerprint,
    examples: Iterable[Example],
    *,
    weights: Weights = DEFAULT_WEIGHTS,
    context_piece_id: int | None = None,
    shares: Mapping[int, float] | None = None,
    containment_weight: float = 0.0,
) -> list[Candidate]:
    """The pieces that claim this segment, best first.

    Every labelled segment is scored and each piece is represented by its own best one, so
    the evidence is pooled **per piece**: the answer does not depend on how many times a
    piece happens to have been labelled, one heavily-drilled piece cannot crowd another out
    of the evidence, and a piece learned a year ago is exactly as strong as yesterday's.
    That replaced a window over the closest labelled *segments*, and the reason is measured:
    on the owner's own library that window held a single piece for 47 of 54 queries, so
    ``runner_up`` was None, so 46 segments were downgraded to "nothing else to compare it
    with" and the auto band had never once fired.

    ``shares`` is each piece's containment over the local content features, when the caller
    has pooled signatures to compute it. It is mixed into the score **here** rather than
    applied to the result: the band and its reason are statements about the score, so
    blending afterwards would leave them describing numbers nothing uses.

    ``context_piece_id`` is the piece this sitting has already been about. It wins a
    near-tie — within ``CONTEXT_MARGIN`` — because a sitting is normally one piece at a
    time and the player drilling bar 17 has not changed composer between segments. It never
    wins a real difference in the notes.
    """
    by_piece: dict[int, list[tuple[Example, float, float, float, float, float, float]]] = {}
    for example in examples:
        scored = compare(segment, example.fingerprint, weights=weights)
        by_piece.setdefault(example.piece_id, []).append((example, *scored))
    if not by_piece:
        return []

    candidates: list[Candidate] = []
    for piece_id, items in by_piece.items():
        items.sort(key=lambda item: (-item[1], item[0].segment_id))
        best = items[0]
        candidates.append(
            Candidate(
                piece_id=piece_id,
                score=best[1],
                pitch_class=best[2],
                tempo=best[3],
                register=best[4],
                hand=best[5],
                interval=best[6],
                support=len(items),
                runner_up=None,
            )
        )
    candidates.sort(
        key=lambda candidate: (-candidate.score, -candidate.support, candidate.piece_id)
    )
    candidates = [_with_runner_up(candidates, index) for index in range(len(candidates))]

    if shares is not None:
        candidates = blend(candidates, shares, weight=containment_weight)

    if context_piece_id is not None:
        context = next(
            (candidate for candidate in candidates if candidate.piece_id == context_piece_id),
            None,
        )
        # Promoted only into a near-tie, and by movement rather than by re-scoring,
        # so the score a player sees still means what it says.
        if (
            context is not None
            and candidates[0].piece_id != context_piece_id
            and candidates[0].score - context.score <= CONTEXT_MARGIN
        ):
            candidates.remove(context)
            candidates.insert(0, context)
    return candidates


def _with_runner_up(candidates: Sequence[Candidate], index: int) -> Candidate:
    """The same candidate with ``runner_up`` set to the best *other* piece's score.

    Recomputed rather than carried, because "the runner-up" means "the best other piece": a
    value left over from before a re-score would make the margin, and so the band, a
    statement about numbers the matcher is no longer using.
    """
    candidate = candidates[index]
    others = [other.score for position, other in enumerate(candidates) if position != index]
    return replace(candidate, runner_up=max(others) if others else None)


def blend(
    candidates: Sequence[Candidate],
    shares: Mapping[int, float],
    *,
    weight: float,
) -> list[Candidate]:
    """Mix each piece's content share into its score, and re-rank.

    ``weight`` is the share of the mixed score that comes from containment over the local
    features; the rest comes from the global fingerprint. Measured on this app's corpus at
    32 pieces, the mix beats either term alone at whole length *and* at a quarter length —
    the global term wins on whole material and the local term wins on fragments, so neither
    is dropped.
    """
    mixed = [
        replace(
            candidate,
            score=(1.0 - weight) * candidate.score
            + weight * float(shares.get(candidate.piece_id, 0.0)),
        )
        for candidate in candidates
    ]
    mixed.sort(key=lambda candidate: (-candidate.score, -candidate.support, candidate.piece_id))
    return [_with_runner_up(mixed, index) for index in range(len(mixed))]


def identify(
    segment: Fingerprint,
    examples: Iterable[Example],
    *,
    score_auto: float,
    score_prompt: float,
    min_margin: float = 0.0,
    min_notes: int = 0,
    weights: Weights = DEFAULT_WEIGHTS,
    context_piece_id: int | None = None,
    shares: Mapping[int, float] | None = None,
    containment_weight: float = 0.0,
) -> Identification:
    """Decide which band this segment falls in, and say why.

    The bands are the design's, with one addition: a high score is not enough on
    its own. If the runner-up piece is nearly as close, or there is no other piece
    to compare against at all, the match is offered but never written — because
    "the best of several similar answers" is exactly the case this matcher is
    known to get wrong.

    ``shares`` and ``containment_weight`` belong here rather than at the call site: the band
    is a statement about the score, so it has to be decided from the same mixed score the
    caller is shown.
    """
    candidates = rank(
        segment,
        examples,
        weights=weights,
        context_piece_id=context_piece_id,
        shares=shares,
        containment_weight=containment_weight,
    )
    if not candidates:
        return Identification((), "none", "nothing to compare with yet")
    if segment.note_count < min_notes:
        return Identification(
            tuple(candidates),
            "none",
            f"only {segment.note_count} notes — too little to recognise",
        )

    best = candidates[0]
    if best.score < score_prompt:
        return Identification(tuple(candidates), "none", "no close match")

    if best.score >= score_auto:
        if best.runner_up is None:
            return Identification(
                tuple(candidates), "suggest", "nothing else to compare it with"
            )
        if best.margin < min_margin:
            return Identification(
                tuple(candidates),
                "suggest",
                f"too close to another piece ({best.margin:.2f} apart)",
            )
        return Identification(tuple(candidates), "auto", "confident match")

    return Identification(tuple(candidates), "suggest", "worth a look")
