"""Reading a sitting as a sequence, rather than as a pile of guesses.

The matcher compares one stretch of playing against the labelled practice and answers in
isolation: the best piece for *this* segment. Practice is not shaped like that. A sitting
is usually one piece taken section by section, sometimes after a warm-up, sometimes with
a detour through something else — and when it is, the neighbouring segments are evidence
about this one. Answering them one at a time throws the strongest signal a sitting has
away, which is why the same matcher does better the moment a person tells it what the
sitting is already about.

This module makes that prior explicit. It is a small hidden Markov model over the pieces
the matcher scored for the sitting: each segment's matcher scores are the emission, and
the transition says a segment usually keeps the piece the one before it had. Forward–
backward turns those scores into a probability for every piece at every position — the
answer to "how likely is it that this part of the sitting was on this piece", not just
"which single comparison scored highest".

Two things it deliberately is not:

* It does not read a database. The caller builds the fragments from the matcher's own
  candidates, so the only duplicates of that logic are in the caller.
* It does not decide that a label should be written. `band` states the probability a
  claim needs, and the caller decides whether that probability is a claim or a question.

The parameters are measured rather than inherited — `backend/tools/measure_autotag.py`
sweeps them over drill-shaped practice in both the usual order (one piece for the whole
sitting) and an interleaved order (a piece switch every segment), because the failure
this model invites is smoothing a real switch into the piece before it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: The score a piece gets when the matcher did not score it for a segment.
#:
#: The matcher returns a candidate for every piece it has labelled examples for, so this
#: only fires for a piece with no references at all — and such a piece is a possibility
#: the model should be able to fall back to, not an impossible one.
ABSENT_SCORE = 0.0


@dataclass(frozen=True)
class Option:
    """One piece's matcher score for one segment."""

    piece_id: int
    score: float


@dataclass(frozen=True)
class Fragment:
    """One segment, as the matcher saw it."""

    #: Whatever the caller uses to key its answers — a segment id, in the app.
    key: int
    options: tuple[Option, ...]
    #: How many notes the segment held. A segment below the matcher's floor is never
    #: guessed at, and that rule survives the sequence pass.
    notes: int = 0


@dataclass(frozen=True)
class Belief:
    """What the sequence says about one segment."""

    key: int
    #: Piece id to the posterior probability the sitting was on it here. Sums to 1.
    probabilities: dict[int, float] = field(default_factory=dict)
    notes: int = 0

    @property
    def chosen(self) -> int | None:
        """The piece the sequence picks, or ``None`` when there was nothing to pick."""
        if not self.probabilities:
            return None
        # Smallest piece id wins a tie, matching `similarity.rank`'s own tie-break.
        return min(self.probabilities, key=lambda piece: (-self.probabilities[piece], piece))

    @property
    def confidence(self) -> float:
        """How much probability the picked piece carries."""
        chosen = self.chosen
        return 0.0 if chosen is None else self.probabilities[chosen]

    @property
    def runner_up(self) -> float:
        """The best probability belonging to some other piece."""
        chosen = self.chosen
        if chosen is None:
            return 0.0
        return max(
            (probability for piece, probability in self.probabilities.items() if piece != chosen),
            default=0.0,
        )

    @property
    def gap(self) -> float:
        """How far ahead the picked piece is: 0 when there is nothing to be ahead of."""
        return self.confidence - self.runner_up


def _logsumexp(values: list[float]) -> float:
    top = max(values)
    if top == -math.inf:
        return -math.inf
    return top + math.log(math.fsum(math.exp(value - top) for value in values))


def decode(
    fragments: list[Fragment],
    *,
    switch: float,
    temperature: float,
) -> list[Belief]:
    """Posterior probability of every piece at every position of one sitting.

    ``switch`` is the a-priori probability that a segment is *not* the piece the one
    before it was. It costs a piece ``log(switch / (n - 1))`` to take over between two
    segments and ``log(1 - switch)`` to stay, so a switch happens when the evidence for it
    outweighs that price — which is exactly the trade the caller wants made explicitly.

    ``temperature`` scales the matcher's scores into log-likelihoods. A low temperature
    trusts each segment's own comparison; a high one lets the sequence overrule it.

    The fragments must be in playing order. A fragment with no options is a position the
    matcher had nothing to say about: it emits a flat distribution, so its answer comes
    entirely from the sequence around it.
    """
    if temperature <= 0:
        raise ValueError(f"temperature must be positive, got {temperature}")
    if not 0 < switch <= 1:
        raise ValueError(f"switch must be in (0, 1], got {switch}")
    if not fragments:
        return []

    pieces = sorted({option.piece_id for fragment in fragments for option in fragment.options})
    if not pieces:
        return [Belief(fragment.key, {}, fragment.notes) for fragment in fragments]
    if len(pieces) == 1:
        # Nothing to be a sequence about: one piece scores, one piece can be meant.
        return [Belief(fragment.key, {pieces[0]: 1.0}, fragment.notes) for fragment in fragments]

    index = {piece: position for position, piece in enumerate(pieces)}
    count = len(pieces)
    stay = math.log1p(-switch) if switch < 1 else -math.inf
    move = math.log(switch / (count - 1))

    emissions: list[list[float]] = []
    for fragment in fragments:
        scores = [ABSENT_SCORE] * count
        for option in fragment.options:
            scores[index[option.piece_id]] = option.score
        # Shifted per position: the posterior is invariant to a constant added to every
        # piece's emission at one position, and the shift keeps the exponentials small.
        top = max(scores)
        emissions.append([(score - top) / temperature for score in scores])

    # Forward: alpha[t][j] is the log-probability of the first t + 1 segments ending with
    # piece j at position t, having summed over every path to get there.
    alpha: list[list[float]] = [list(emissions[0])]
    for emission in emissions[1:]:
        previous = alpha[-1]
        row: list[float] = []
        for target in range(count):
            row.append(
                emission[target]
                + _logsumexp(
                    [
                        previous[source] + (stay if source == target else move)
                        for source in range(count)
                    ]
                )
            )
        alpha.append(row)

    # Backward: beta[t][j] is the log-probability of every segment *after* t, given j at t.
    beta: list[list[float]] = [[0.0] * count]
    for position in range(len(fragments) - 1, 0, -1):
        following = beta[0]
        emission = emissions[position]
        row: list[float] = []
        for source in range(count):
            row.append(
                _logsumexp(
                    [
                        (stay if source == target else move)
                        + emission[target]
                        + following[target]
                        for target in range(count)
                    ]
                )
            )
        beta.insert(0, row)

    beliefs: list[Belief] = []
    for position, fragment in enumerate(fragments):
        log_posterior = [
            alpha[position][piece] + beta[position][piece] for piece in range(count)
        ]
        normaliser = _logsumexp(log_posterior)
        if normaliser == -math.inf:  # pragma: no cover - unreachable with a finite cost
            probabilities = {piece: 1.0 / count for piece in pieces}
        else:
            probabilities = {
                pieces[piece]: math.exp(log_posterior[piece] - normaliser)
                for piece in range(count)
            }
        beliefs.append(Belief(fragment.key, probabilities, fragment.notes))
    return beliefs


def band(
    belief: Belief,
    *,
    auto_probability: float,
    prompt_probability: float,
    min_notes: int,
) -> str:
    """What the sequence's confidence is worth: ``auto``, ``suggest`` or ``none``.

    The thresholds are probabilities now, not score margins, so they mean the one thing a
    person reading the timeline needs them to mean: how often this claim is right. A
    segment with a single possible piece is only ever *offered* — a perfect match with
    nothing to compare it against has not been checked against anything, which is the
    rule the single-segment matcher already follows.
    """
    if not 0 <= prompt_probability <= auto_probability <= 1:
        raise ValueError(
            "expected 0 <= prompt_probability <= auto_probability <= 1, got "
            f"{prompt_probability} and {auto_probability}"
        )
    if belief.chosen is None or belief.notes < min_notes:
        return "none"
    if len(belief.probabilities) < 2:
        return "suggest" if belief.confidence >= prompt_probability else "none"
    if belief.confidence >= auto_probability:
        return "auto"
    if belief.confidence >= prompt_probability:
        return "suggest"
    return "none"
