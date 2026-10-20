"""What the calibration is allowed to say about a decoded confidence.

The thresholds are measurements (see ``backend/app/practice/calibration.py`` and
``backend/tools/calibrate_bands.py``), so these tests pin the two axes that produced
them — how long the segment is, and how many pieces could explain it — rather than the
numbers for their own sake.
"""

from __future__ import annotations

from app.practice import calibration

BASE = 0.99


def test_a_short_fragment_in_a_crowded_library_is_never_written() -> None:
    """Nine notes against thirty pieces measured 67-76% precise at every threshold, so no
    confidence can make that shape trustworthy enough to write."""
    assert calibration.auto_probability(notes=9, pieces=30, base=BASE) is None
    assert (
        calibration.writes(confidence=0.99999, notes=9, pieces=30, base=BASE) is False
    )


def test_a_medium_fragment_in_a_crowded_library_needs_more_certainty() -> None:
    """18 notes against thirty pieces reached 98.9% at 0.995, and 90.5% at 0.99 — so the
    bar moves up, and a decode at the configured probability is only offered."""
    assert calibration.auto_probability(notes=18, pieces=30, base=BASE) == 0.995
    assert calibration.writes(confidence=0.996, notes=18, pieces=30, base=BASE) is True
    assert calibration.writes(confidence=0.99, notes=18, pieces=30, base=BASE) is False


def test_a_long_fragment_keeps_the_configured_probability() -> None:
    """From 25 notes upward the decode measured 100% precise, so the calibration adds
    nothing to a segment the app was already willing to write."""
    assert calibration.auto_probability(notes=40, pieces=30, base=BASE) == BASE
    assert calibration.writes(confidence=0.99, notes=40, pieces=30, base=BASE) is True


def test_a_small_library_is_left_alone() -> None:
    """The other axis: a ten-note drill against three pieces is still likely unique, and
    the app has always written it. Caution is for crowded libraries, not short music."""
    assert calibration.auto_probability(notes=10, pieces=3, base=BASE) == BASE
    assert calibration.writes(confidence=0.99, notes=10, pieces=3, base=BASE) is True


def test_a_stricter_configured_probability_is_never_lowered() -> None:
    """The calibration can only add caution: a library that asked for more certainty keeps
    it, even where the measurement would have accepted less."""
    assert calibration.auto_probability(notes=18, pieces=30, base=0.999) == 0.999
