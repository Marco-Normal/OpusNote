"""The one-time piano sample download.

No network in these tests: the fetcher is injected. What is worth asserting is the
*bookkeeping* — that every sample is asked for, that a second run is a no-op, that a
failure leaves nothing half-written, and that the licence travels with the status,
because the samples are CC BY and the attribution has to reach the interface.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app import piano
from app.config import settings

#: A stand-in for an mp3. The downloader never parses one, so bytes are enough.
SAMPLE_BYTES = b"ID3\x03\x00\x00\x00not-really-an-mp3"


def _note_midi(name: str) -> int:
    """A0 -> 21, C4 -> 60, Ds4 -> 63. Enough to check the spacing of the set."""
    steps = {"C": 0, "Cs": 1, "D": 2, "Ds": 3, "E": 4, "F": 5, "Fs": 6, "G": 7,
             "Gs": 8, "A": 9, "As": 10, "B": 11}
    letter = name[0].upper()
    rest = name[1:]
    sharp = rest.startswith("s")
    if sharp:
        rest = rest[1:]
    octave = int(rest)
    return 12 * (octave + 1) + steps[letter + ("s" if sharp else "")]


@pytest.fixture
def sample_dir():
    """The directory the app actually serves, emptied around each test.

    Not patched per test: the static mount is created when the app is imported, so a
    patched path would be a different directory from the one the routes serve. It is
    redirected into the scratch tree by `conftest` instead, and wiped here rather than
    relying on the database fixture — a test that installs samples and does not use
    the database would otherwise leave them for the next one.
    """
    directory = Path(settings.piano_dir)
    shutil.rmtree(directory, ignore_errors=True)
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


class Recorder:
    """A fetcher that records what was asked for and can be told to fail."""

    def __init__(self, *, fail: set[str] | None = None, payload: bytes = SAMPLE_BYTES) -> None:
        self.asked: list[str] = []
        self.fail = fail or set()
        self.payload = payload

    def __call__(self, url: str, **_kwargs) -> bytes:
        name = url.rsplit("/", 1)[-1]
        self.asked.append(name)
        if name in self.fail:
            raise OSError("connection reset")
        return self.payload


# --------------------------------------------------------------------------
# The sample set itself
# --------------------------------------------------------------------------


def test_every_third_semitone_is_sampled():
    """The spacing is the whole reason 30 files are enough: Tone pitches between
    neighbours, so a wider gap would be audible."""
    midis = [_note_midi(name) for name in piano.SAMPLE_NOTES]
    assert midis == sorted(midis), "the set is in order"
    assert midis[0] == 21, "A0, the lowest key"
    assert midis[-1] == 108, "C8, the highest"
    gaps = {b - a for a, b in zip(midis, midis[1:])}
    assert gaps == {3}, f"every gap is a minor third ({sorted(gaps)})"


def test_sharp_names_use_an_s_not_a_hash():
    """A `#` in a URL starts a fragment: `D#4.mp3` requests `D`, and the server
    answers 404 with an HTML error page that a loader would happily hand to the
    audio decoder. Measured, not assumed."""
    assert "Ds4" in piano.SAMPLE_FILES
    assert all("#" not in name for name in piano.SAMPLE_FILES.values())


def test_the_licence_travels_with_the_samples():
    assert "CC BY" in piano.SAMPLE_LICENCE
    assert piano.SAMPLE_ATTRIBUTION_URL.startswith("https://")


# --------------------------------------------------------------------------
# Downloading
# --------------------------------------------------------------------------


def test_a_first_run_fetches_every_sample(sample_dir):
    fetch = Recorder()
    report = piano.download_samples(fetch_one=fetch)

    assert report.downloaded == len(piano.SAMPLE_NOTES)
    assert report.skipped == 0 and report.failed == 0
    assert sorted(fetch.asked) == sorted(piano.SAMPLE_FILES.values())
    assert report.bytes == len(SAMPLE_BYTES) * len(piano.SAMPLE_NOTES)
    assert report.status.available is True
    assert (sample_dir / "A0.mp3").read_bytes() == SAMPLE_BYTES


def test_a_second_run_downloads_nothing(sample_dir):
    piano.download_samples(fetch_one=Recorder())
    again = Recorder()
    report = piano.download_samples(fetch_one=again)

    assert report.downloaded == 0
    assert report.skipped == len(piano.SAMPLE_NOTES)
    assert again.asked == [], "nothing is re-fetched"


def test_a_forced_run_replaces_what_is_there(sample_dir):
    piano.download_samples(fetch_one=Recorder())
    again = Recorder(payload=b"ID3different")
    report = piano.download_samples(force=True, fetch_one=again)

    assert report.downloaded == len(piano.SAMPLE_NOTES)
    assert (sample_dir / "A0.mp3").read_bytes() == b"ID3different"


def test_a_failure_leaves_no_half_written_sample(sample_dir):
    fetch = Recorder(fail={"C4.mp3"})
    report = piano.download_samples(fetch_one=fetch)

    assert report.failed == 1
    assert report.downloaded == len(piano.SAMPLE_NOTES) - 1
    assert "C4.mp3" in report.errors[0]
    assert not (sample_dir / "C4.mp3").exists()
    assert list(sample_dir.glob("*.part")) == [], "and no debris"
    # A partial set is not usable: a silent gap mid-keyboard reads as a broken app.
    assert report.status.available is False
    assert report.status.present == len(piano.SAMPLE_NOTES) - 1


def test_an_empty_response_is_a_failure_not_a_silent_sample(sample_dir):
    report = piano.download_samples(fetch_one=Recorder(payload=b""))

    assert report.failed == len(piano.SAMPLE_NOTES)
    assert report.status.available is False


def test_status_before_any_download(sample_dir):
    status = piano.sample_status()
    assert status.available is False
    assert (status.present, status.total, status.bytes) == (0, len(piano.SAMPLE_NOTES), 0)
    assert status.directory == str(sample_dir)


# --------------------------------------------------------------------------
# The routes
# --------------------------------------------------------------------------


def test_the_status_route_reports_the_licence(client):
    body = client.get("/api/audio/piano").json()
    assert body["available"] is False
    assert "CC BY" in body["licence"]
    assert body["total"] == len(piano.SAMPLE_NOTES)


def test_the_download_route_installs_and_then_reports(client, sample_dir, monkeypatch):
    monkeypatch.setattr(piano, "fetch", Recorder())
    installed = client.post("/api/audio/piano")
    assert installed.status_code == 200, installed.text
    body = installed.json()
    assert body["downloaded"] == len(piano.SAMPLE_NOTES)
    assert body["status"]["available"] is True

    # And it is served from our own host from then on: nothing at play time
    # touches the network.
    served = client.get("/piano/A0.mp3")
    assert served.status_code == 200
    assert served.content == SAMPLE_BYTES
    assert client.get("/api/audio/piano").json()["available"] is True


def test_a_total_failure_is_reported_rather_than_silently_succeeding(
    client, sample_dir, monkeypatch
):
    monkeypatch.setattr(piano, "fetch", Recorder(fail=set(piano.SAMPLE_FILES.values())))
    response = client.post("/api/audio/piano")
    assert response.status_code == 502
    assert "could not be downloaded" in response.json()["detail"]
