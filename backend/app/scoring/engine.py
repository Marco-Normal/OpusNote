"""Performance scoring.

Pure functions over two lists of notes: what the notation asked for, and what
the MIDI keyboard actually sent. Nothing here touches the database or HTTP,
which is what makes it straightforward to test and to replace with a smarter
model later.

The matching stage is deliberately written for *lists* of notes, so adding
chords and polyphony later is a data change rather than an algorithm change.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence

from ..config import Settings, settings as default_settings
from ..music.expected import ExpectedNote

#: A played note is "wrong pitch" rather than "extra" when it lands this close
#: (in seconds) to an expected note that nothing else matched.
WRONG_PITCH_FRACTION = 1.0


@dataclass(frozen=True)
class PlayedNote:
    pitch: int
    onset: float
    duration: float = 0.0
    velocity: int = 64
    channel: int = 0

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "PlayedNote":
        return PlayedNote(
            pitch=int(data["pitch"]),
            onset=float(data["onset"]),
            duration=float(data.get("duration", 0.0)),
            velocity=int(data.get("velocity", 64)),
            channel=int(data.get("channel", 0)),
        )


@dataclass
class NoteFeedback:
    index: int
    event_id: int
    hand: str
    pitch: int
    measure: int
    beat: float
    onset_s: float
    status: str  # correct | wrong_pitch | missed
    played_pitch: int | None = None
    onset_error_s: float | None = None
    onset_error_beats: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreResult:
    score: float
    pitch_accuracy: float
    rhythm_accuracy: float
    continuity_accuracy: float
    matched: int
    expected_count: int
    played_count: int
    extra_count: int
    missed_count: int
    wrong_pitch_count: int
    mean_onset_error_beats: float
    onset_error_std_beats: float
    hesitation_count: int
    feedback: list[NoteFeedback] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["feedback"] = [item.to_dict() for item in self.feedback]
        return payload


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _match(
    expected: Sequence[ExpectedNote],
    played: Sequence[PlayedNote],
    window_s: float,
) -> tuple[dict[int, tuple[int, float]], dict[int, int]]:
    """Greedy nearest-first matching on (equal pitch, |dt| <= window).

    Returns ``{expected_index: (played_index, dt)}`` and the inverse map.
    """
    candidates: list[tuple[float, int, int, float]] = []
    for expected_index, expected_note in enumerate(expected):
        for played_index, played_note in enumerate(played):
            if played_note.pitch != expected_note.pitch:
                continue
            delta = played_note.onset - expected_note.onset_s
            if abs(delta) <= window_s:
                candidates.append((abs(delta), expected_index, played_index, delta))
    candidates.sort(key=lambda item: item[0])

    matched_expected: dict[int, tuple[int, float]] = {}
    matched_played: dict[int, int] = {}
    for _, expected_index, played_index, delta in candidates:
        if expected_index in matched_expected or played_index in matched_played:
            continue
        matched_expected[expected_index] = (played_index, delta)
        matched_played[played_index] = expected_index
    return matched_expected, matched_played


def score_performance(
    expected: Sequence[ExpectedNote],
    played: Sequence[PlayedNote],
    *,
    tempo_bpm: float,
    latency_ms: float = 0.0,
    config: Settings | None = None,
) -> ScoreResult:
    cfg = config or default_settings
    weights = cfg.weights
    window_s = cfg.match_window_s
    seconds_per_beat = 60.0 / float(tempo_bpm) if tempo_bpm > 0 else 0.5

    # Compensate for the measured round-trip latency of the player's setup.
    adjusted = [
        PlayedNote(
            pitch=note.pitch,
            onset=note.onset - latency_ms / 1000.0,
            duration=note.duration,
            velocity=note.velocity,
            channel=note.channel,
        )
        for note in played
    ]
    adjusted = [note for note in adjusted if note.onset > -window_s * 2]

    matched_expected, matched_played = _match(expected, adjusted, window_s)
    true_positives = len(matched_expected)

    precision = true_positives / len(adjusted) if adjusted else 0.0
    recall = true_positives / len(expected) if expected else 1.0
    denominator = precision + recall
    pitch_accuracy = (2 * precision * recall / denominator) if denominator > 0 else 0.0

    # ---- note-level feedback --------------------------------------------
    feedback: list[NoteFeedback] = []
    unmatched_played = [index for index in range(len(adjusted)) if index not in matched_played]
    for expected_index, expected_note in enumerate(expected):
        match = matched_expected.get(expected_index)
        if match is not None:
            played_index, delta = match
            feedback.append(
                NoteFeedback(
                    index=expected_note.index,
                    event_id=expected_note.event_id,
                    hand=expected_note.hand,
                    pitch=expected_note.pitch,
                    measure=expected_note.measure,
                    beat=round(expected_note.beat, 4),
                    onset_s=round(expected_note.onset_s, 4),
                    status="correct",
                    played_pitch=adjusted[played_index].pitch,
                    onset_error_s=round(delta, 4),
                    onset_error_beats=round(delta / seconds_per_beat, 4),
                )
            )
            continue

        nearest_index: int | None = None
        nearest_distance = window_s * WRONG_PITCH_FRACTION
        for played_index in unmatched_played:
            distance = abs(adjusted[played_index].onset - expected_note.onset_s)
            if distance <= nearest_distance:
                nearest_distance = distance
                nearest_index = played_index
        if nearest_index is not None:
            unmatched_played.remove(nearest_index)
            feedback.append(
                NoteFeedback(
                    index=expected_note.index,
                    event_id=expected_note.event_id,
                    hand=expected_note.hand,
                    pitch=expected_note.pitch,
                    measure=expected_note.measure,
                    beat=round(expected_note.beat, 4),
                    onset_s=round(expected_note.onset_s, 4),
                    status="wrong_pitch",
                    played_pitch=adjusted[nearest_index].pitch,
                )
            )
        else:
            feedback.append(
                NoteFeedback(
                    index=expected_note.index,
                    event_id=expected_note.event_id,
                    hand=expected_note.hand,
                    pitch=expected_note.pitch,
                    measure=expected_note.measure,
                    beat=round(expected_note.beat, 4),
                    onset_s=round(expected_note.onset_s, 4),
                    status="missed",
                )
            )

    # ---- rhythm ----------------------------------------------------------
    onset_errors = [delta for _, delta in matched_expected.values()]
    error_beats = [delta / seconds_per_beat for delta in onset_errors]
    mean_abs_beats = statistics.fmean(abs(value) for value in error_beats) if error_beats else 0.0
    std_beats = statistics.pstdev(error_beats) if len(error_beats) > 1 else 0.0
    tolerance = max(1e-6, cfg.rhythm_tolerance_beats)
    if true_positives:
        rhythm_accuracy = 0.7 * _clamp01(1.0 - mean_abs_beats / tolerance) + 0.3 * _clamp01(
            1.0 - std_beats / tolerance
        )
    else:
        rhythm_accuracy = 0.0

    # ---- continuity ------------------------------------------------------
    # Collapse notes into simultaneous events (one onset per hand+onset group)
    # so chords do not register as a burst of consecutive gaps. Matching here
    # uses the wide window: a hesitation is *late*, not *wrong*.
    wide_matched, _ = _match(expected, adjusted, cfg.continuity_window_s)
    event_order: list[int] = []
    event_expected_onset: dict[int, float] = {}
    event_played_onset: dict[int, float] = {}
    for expected_index, expected_note in enumerate(expected):
        if expected_note.event_id not in event_expected_onset:
            event_order.append(expected_note.event_id)
            event_expected_onset[expected_note.event_id] = expected_note.onset_s
        match = wide_matched.get(expected_index)
        if match is None:
            continue
        played_onset = adjusted[match[0]].onset
        current = event_played_onset.get(expected_note.event_id)
        event_played_onset[expected_note.event_id] = (
            played_onset if current is None else min(current, played_onset)
        )

    gaps_expected: list[float] = []
    gaps_played: list[float] = []
    for first_event, second_event in zip(event_order, event_order[1:]):
        played_first = event_played_onset.get(first_event)
        played_second = event_played_onset.get(second_event)
        if played_first is None or played_second is None:
            continue
        gaps_expected.append(event_expected_onset[second_event] - event_expected_onset[first_event])
        gaps_played.append(played_second - played_first)

    hesitation_count = 0
    for gap_expected, gap_played in zip(gaps_expected, gaps_played):
        if gap_played - gap_expected > cfg.hesitation_ms / 1000.0:
            hesitation_count += 1

    if gaps_expected:
        hesitation_score = 1.0 - hesitation_count / len(gaps_expected)
        ratios = [
            gap_played / gap_expected
            for gap_expected, gap_played in zip(gaps_expected, gaps_played)
            if gap_expected > 1e-6
        ]
        if len(ratios) > 1:
            stability = _clamp01(1.0 - statistics.pstdev(ratios) / 0.35)
        else:
            stability = 1.0
        continuity_accuracy = _clamp01(0.6 * hesitation_score + 0.4 * stability)
    else:
        continuity_accuracy = 0.0

    overall = (
        weights["pitch"] * pitch_accuracy
        + weights["rhythm"] * rhythm_accuracy
        + weights["continuity"] * continuity_accuracy
    ) * 100.0

    return ScoreResult(
        score=round(overall, 2),
        pitch_accuracy=round(pitch_accuracy * 100.0, 2),
        rhythm_accuracy=round(rhythm_accuracy * 100.0, 2),
        continuity_accuracy=round(continuity_accuracy * 100.0, 2),
        matched=true_positives,
        expected_count=len(expected),
        played_count=len(adjusted),
        extra_count=len(unmatched_played),
        missed_count=sum(1 for item in feedback if item.status == "missed"),
        wrong_pitch_count=sum(1 for item in feedback if item.status == "wrong_pitch"),
        mean_onset_error_beats=round(mean_abs_beats, 4),
        onset_error_std_beats=round(std_beats, 4),
        hesitation_count=hesitation_count,
        feedback=feedback,
        weights=weights,
    )


def accuracy_by_hand(feedback: Sequence[NoteFeedback]) -> dict[str, dict[str, float]]:
    buckets: dict[str, dict[str, float]] = {}
    for item in feedback:
        bucket = buckets.setdefault(item.hand, {"correct": 0.0, "wrong_pitch": 0.0, "missed": 0.0, "total": 0.0})
        bucket["total"] += 1
        bucket[item.status] += 1
    out: dict[str, dict[str, float]] = {}
    for hand, bucket in buckets.items():
        total = bucket["total"] or 1.0
        out[hand] = {
            "total": bucket["total"],
            "accuracy": round(100.0 * bucket["correct"] / total, 2),
            "wrong_pitch": bucket["wrong_pitch"],
            "missed": bucket["missed"],
        }
    return out
