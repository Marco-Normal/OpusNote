"""Pedal analysis, and the touch numbers that go with it.

Pure functions over a note list and the stored CC64 stream, in the same shape and
with the same guarantee as :mod:`app.practice.metrics`: everything here is
recomputable from ``note_events`` and ``pedal_events``, so a stored value is a cache
and never the truth.

The raw CC64 stream stays raw in the database. Intervals are a projection of it, and
one that has to be closed at the end of a sitting, because a pedal-up that never
arrives is exactly what an unplugged device looks like.

**Two things this module refuses to do**, both because the data cannot support them:

* It does not model a continuous pedal's damping. Half-pedalling is a position, and
  the MIDI specification's own rule for a switch controller — below 64 is off — is
  what makes an ordinary on/off pedal work at all. A partial pedal therefore reads as
  released. That is a stated limitation, not an oversight.
* It does not know the harmony. Without a score, "the harmony changed" can only mean
  "the pitches under the pedal changed", which is why the blur count carries a
  ``basis`` and why that basis is stored rather than re-derived. When a performance
  can be aligned to a score, a second basis answers the same question from the
  score's own boundaries, and a stored basis is what keeps the two from being
  compared as though they were the same measurement.
"""

from __future__ import annotations

import statistics
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from .sessionize import Note

#: Where a sustain-pedal value counts as "down": the MIDI specification's rule for a
#: switch controller, 0-63 off and 64-127 on. Kept here as the single owner — the
#: playback side imports the same value from the frontend's own constant, and having
#: written it twice is how one rule becomes two.
PEDAL_DOWN = 64

#: How many pitch classes a new attack must bring that the pedal is not already
#: holding for the change to count as harmonic movement rather than a re-strike.
#: Three is a triad: fewer is an ornament or a repeated note.
PEDAL_BLUR_MIN_NEW = 3

#: The only basis that exists today: the boundaries are observed from the sounding
#: pitches. Named rather than implied, so a score-derived basis can be added without
#: quietly reinterpreting what an old number meant.
BASIS_OBSERVED = "observed"

#: Middle C. The split for the register figure, which is a *proxy* for the hands and
#: is labelled as one everywhere it is shown: the piano sends both hands on one MIDI
#: channel, so there is nothing better to go on in a passive log.
REGISTER_SPLIT = 60


@dataclass(frozen=True)
class PedalInterval:
    """One pedal-down stretch, in milliseconds relative to the sitting."""

    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class PedalMetrics:
    """What the pedal did during a segment, or that it was not recorded.

    ``recorded`` is the third state, and it is not a refinement of zero: sittings
    imported from the standalone logger have no pedal rows at all, so a figure
    computed over them would report a fault that was never observed.
    """

    recorded: bool
    changes: int
    down_ratio: float
    blur: int
    #: Where the blur attacks were, in ms relative to the sitting, ascending. `blur` is
    #: `len(blur_at_ms)` and is never computed separately, so the number and the places cannot
    #: disagree — which is the failure a second loop would eventually produce.
    blur_at_ms: tuple[int, ...] = ()


def intervals(pedals: list[tuple[int, int]], end_ms: int | None = None) -> list[PedalInterval]:
    """Turn the raw CC64 stream into the stretches it describes.

    ``pedals`` is ``(onset_ms, value)`` pairs. A press that is never released is
    closed at ``end_ms`` — the end of the material it covers — rather than left open,
    so a device unplugged mid-press cannot produce a stretch that never ends.
    """
    ordered = sorted(pedals, key=lambda move: move[0])
    out: list[PedalInterval] = []
    down: int | None = None
    for onset_ms, value in ordered:
        if value >= PEDAL_DOWN:
            if down is None:
                down = onset_ms
        elif down is not None:
            out.append(PedalInterval(down, onset_ms))
            down = None
    if down is not None:
        out.append(PedalInterval(down, max(down, end_ms if end_ms is not None else down)))
    return out


def changes(pedals: list[tuple[int, int]]) -> int:
    """How many times the pedal crossed the threshold.

    Crossings, not messages: a continuous pedal sends a stream of values on the way
    down and on the way up, and counting messages would report a pedal that is
    "changed" two hundred times a minute.
    """
    count = 0
    down = False
    for _, value in sorted(pedals, key=lambda move: move[0]):
        is_down = value >= PEDAL_DOWN
        if is_down != down:
            count += 1
            down = is_down
    return count


def _down_ratio_of(stretches: list[PedalInterval], span_ms: int) -> float:
    """The share of the span the given stretches cover, 0..1.

    Split out from :func:`down_ratio` so a caller that already built the stretches —
    ``segment_pedal`` does, for the blurs — does not have to rebuild them to measure them.
    """
    if span_ms <= 0:
        return 0.0
    covered = sum(stretch.end_ms - stretch.start_ms for stretch in stretches)
    return round(min(1.0, max(0.0, covered / span_ms)), 3)


def down_ratio(pedals: list[tuple[int, int]], span_ms: int) -> float:
    """The share of the span the pedal was down, 0..1."""
    return _down_ratio_of(intervals(pedals, span_ms), span_ms)


def blur_attacks(notes: list[Note], stretches: list[PedalInterval]) -> list[int]:
    """Where the blur attacks were, in ms relative to the sitting, ascending.

    A blur is an attack that brought new harmony over notes the pedal was already holding.

    A blur is counted at an attack inside a pedal-down stretch when both hold:

    * the attack introduces at least ``PEDAL_BLUR_MIN_NEW`` pitch classes that the
      pedal is not already holding, so it is harmonic movement rather than a
      re-strike of what is there; and
    * the pedal *is* holding something — notes whose key was released inside this
      stretch and which are therefore ringing on the pedal alone.

    Only notes released before the attack count as pedal-held: a key still down is
    holding its own damper, and that is playing, not pedalling. This is the proxy the
    module docstring describes — it observes the pitches, and it does not know the
    harmony.

    The positions are returned rather than only counted because a count with no places cannot
    be acted on: "nine blurs" in a two-thousand-note segment says nothing about where to look,
    and this loop already knows.
    """
    if not notes or not stretches:
        return []

    ordered = sorted(notes, key=lambda note: (note.epoch_ms, note.pitch))
    onsets = [note.epoch_ms for note in ordered]
    # A release-ordered view of the same notes. `held` only ever grows as the attack moves
    # later — see the cursor below — so one pass over this list replaces a fresh scan of
    # every note for every cluster, which is what made this quadratic in the segment.
    by_release = sorted(notes, key=lambda note: note.end_ms)
    releases = [note.end_ms for note in by_release]

    found: list[int] = []
    for stretch in stretches:
        # The attacks inside this stretch, clustered the same way `metrics.attacks`
        # clusters them so a chord counts once. Sliced out of the onset-ordered list
        # rather than scanned for, so a stretch costs the notes it actually holds.
        inside = ordered[
            bisect_left(onsets, stretch.start_ms) : bisect_right(onsets, stretch.end_ms)
        ]
        if not inside:
            continue
        clusters: list[list[Note]] = []
        for note in inside:
            if clusters and note.epoch_ms - clusters[-1][0].epoch_ms <= 50:
                clusters[-1].append(note)
            else:
                clusters.append([note])
        # The notes released inside this stretch and before the attack, in release order.
        # Clusters are in onset order, so their attacks are non-decreasing and the cursor
        # never rewinds: `held` accumulates exactly the set the from-scratch scan rebuilt.
        cursor = bisect_left(releases, stretch.start_ms)
        held: set[int] = set()
        for cluster in clusters:
            attack_ms = cluster[0].epoch_ms
            while cursor < len(by_release) and by_release[cursor].end_ms < attack_ms:
                held.add(by_release[cursor].pitch % 12)
                cursor += 1
            if not held:
                continue
            arriving = {note.pitch % 12 for note in cluster}
            if len(arriving - held) >= PEDAL_BLUR_MIN_NEW:
                found.append(attack_ms)
    return found


def blurs(notes: list[Note], stretches: list[PedalInterval]) -> int:
    """How many blur attacks there were. The places are in :func:`blur_attacks`.

    Defined as that list's length rather than by a second loop, so the number and the positions
    cannot disagree — which is the failure a stored cache of the two would otherwise show up as,
    eventually, in the one place nobody looks.
    """
    return len(blur_attacks(notes, stretches))


def segment_pedal(
    notes: list[Note],
    pedals: list[tuple[int, int]],
    *,
    recorded: bool,
) -> PedalMetrics:
    """Everything the pedal did in one segment.

    ``recorded`` says whether the sitting has any pedal rows at all, which only the
    caller can know: an empty list means "not pressed" and "not captured"
    indistinguishably.
    """
    if not recorded:
        return PedalMetrics(recorded=False, changes=0, down_ratio=0.0, blur=0)
    span = 0
    if notes:
        span = max(note.end_ms for note in notes) - min(note.epoch_ms for note in notes)
    stretches = intervals(pedals, span)
    found = blur_attacks(notes, stretches)
    return PedalMetrics(
        recorded=True,
        changes=changes(pedals),
        down_ratio=_down_ratio_of(stretches, span),
        blur=len(found),
        blur_at_ms=tuple(found),
    )


def median_velocity(notes: list[Note]) -> float | None:
    """The middle velocity, which one stray accent cannot drag the way a mean can."""
    if not notes:
        return None
    return round(statistics.median(float(note.velocity) for note in notes), 2)


def velocity_range(notes: list[Note]) -> float | None:
    """Distance between the softest and loudest note, as a MIDI controller value.

    Velocity is a controller number, not decibels: comparable with itself over weeks,
    never a claim about loudness.
    """
    if not notes:
        return None
    velocities = [note.velocity for note in notes]
    return float(max(velocities) - min(velocities))


def register_balance(notes: list[Note]) -> tuple[float | None, float | None]:
    """Mean velocity below and above middle C.

    A **proxy** for the hands, and labelled as one wherever it is shown. The piano
    sends both hands on one MIDI channel, so a passive log has nothing better; in
    two-hand writing it follows the hands closely enough to be worth reporting, and
    in crossed or single-hand writing it does not, which is why it reports rather
    than judges.
    """
    low = [float(note.velocity) for note in notes if note.pitch < REGISTER_SPLIT]
    high = [float(note.velocity) for note in notes if note.pitch >= REGISTER_SPLIT]
    return (
        round(statistics.fmean(low), 2) if low else None,
        round(statistics.fmean(high), 2) if high else None,
    )
