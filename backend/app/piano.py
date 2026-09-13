"""A real piano sound: fetched once, kept here, served from our own host.

Web Audio can synthesise something piano-shaped, and this app did for a long time.
But a sampled piano is about **2 MB**, the piano machine has a network connection
once, and after that the samples live in the data directory next to the recordings.
So they are downloaded on request and served by this process from then on: nothing
at play time touches the network, and a viewer on the LAN gets the same instrument
as the piano machine.

The samples are the Salamander Grand Piano V3 (a Yamaha C5), recorded by Alexander
Holm and released under CC BY 3.0. The licence requires attribution, so it travels
with the status payload and is shown in the interface next to the download — a
credit that only exists in a README is not really a credit.

Every third semitone is sampled and Tone's `Sampler` pitches between them, which is
the trade the 30 files represent: sampling all 88 keys would be ~6x the size for a
difference nobody practising scales will hear.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import settings

#: The sampled notes, in order: A0 to C8 in minor thirds, which is what makes the
#: pitch-shifting between them at most a semitone and a half.
SAMPLE_NOTES: tuple[str, ...] = (
    "A0", "C1", "Ds1", "Fs1", "A1",
    "C2", "Ds2", "Fs2", "A2",
    "C3", "Ds3", "Fs3", "A3",
    "C4", "Ds4", "Fs4", "A4",
    "C5", "Ds5", "Fs5", "A5",
    "C6", "Ds6", "Fs6", "A6",
    "C7", "Ds7", "Fs7", "A7",
    "C8",
)

#: Note name to file name. `Ds4` rather than `D#4`: a `#` in a URL starts a
#: fragment, so the sharp names are spelled with an `s` — measured, not assumed.
SAMPLE_FILES: dict[str, str] = {note: f"{note}.mp3" for note in SAMPLE_NOTES}

SAMPLE_SOURCE = "https://tonejs.github.io/audio/salamander"

SAMPLE_LICENCE = "Salamander Grand Piano V3 by Alexander Holm — CC BY 3.0"
SAMPLE_ATTRIBUTION_URL = "https://archive.org/details/SalamanderGrandPianoV3"

#: Long enough for 2 MB on a slow connection, short enough that a wedged request
#: does not hang a one-time download forever.
FETCH_TIMEOUT_S = 30


class PianoStatus(BaseModel):
    """Whether a real piano sound is available, and where it came from."""

    available: bool
    present: int
    total: int
    #: The sampled note names, so the client builds its URLs from our list rather
    #: than keeping a second copy of it that can drift.
    notes: list[str] = Field(default_factory=list)
    bytes: int
    directory: str
    source: str
    licence: str
    attribution_url: str


class PianoDownloadReport(BaseModel):
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    bytes: int = 0
    errors: list[str] = Field(default_factory=list)
    status: PianoStatus


router = APIRouter(prefix="/api/audio", tags=["audio"])


def sample_dir() -> Path:
    return Path(settings.piano_dir)


def _present(directory: Path) -> int:
    return sum(1 for name in SAMPLE_FILES.values() if (directory / name).is_file())


def sample_status() -> PianoStatus:
    directory = sample_dir()
    present = _present(directory)
    total_bytes = 0
    if directory.is_dir():
        for name in SAMPLE_FILES.values():
            path = directory / name
            if path.is_file():
                total_bytes += path.stat().st_size
    return PianoStatus(
        # Available only when the whole set is there: half a piano would leave
        # silent gaps in the middle of the keyboard, which reads as a broken app
        # rather than as an unfinished download.
        available=present == len(SAMPLE_FILES),
        present=present,
        total=len(SAMPLE_FILES),
        notes=list(SAMPLE_NOTES),
        bytes=total_bytes,
        directory=str(directory),
        source=SAMPLE_SOURCE,
        licence=SAMPLE_LICENCE,
        attribution_url=SAMPLE_ATTRIBUTION_URL,
    )


def fetch(url: str, *, timeout: int = FETCH_TIMEOUT_S) -> bytes:
    """One file over HTTP. Separated so tests never touch the network."""
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - a fixed https URL
        return response.read()


def download_samples(*, force: bool = False, fetch_one=None) -> PianoDownloadReport:
    """Fetch every missing sample, atomically and idempotently.

    Synchronous on purpose, like the recording upload: it is one 2 MB download that
    happens once, and a job queue plus a status endpoint would be more moving parts
    than the thing it moves. Each file is written to `.part` and renamed, so an
    interrupted download cannot leave a truncated sample that Tone would load as
    silence.
    """
    directory = sample_dir()
    directory.mkdir(parents=True, exist_ok=True)
    # Resolved here rather than as a default argument: a default binds the function
    # at definition time, so replacing `fetch` to keep a test off the network — or to
    # route it through a proxy one day — would quietly do nothing.
    fetch_one = fetch_one or fetch

    report = PianoDownloadReport(status=sample_status())
    for note, name in SAMPLE_FILES.items():
        destination = directory / name
        if destination.is_file() and destination.stat().st_size > 0 and not force:
            report.skipped += 1
            continue
        try:
            payload = fetch_one(f"{SAMPLE_SOURCE}/{name}")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            report.failed += 1
            report.errors.append(f"{name}: {exc}")
            continue
        if not payload:
            report.failed += 1
            report.errors.append(f"{name}: empty response")
            continue
        staged = destination.with_suffix(destination.suffix + ".part")
        staged.write_bytes(payload)
        staged.replace(destination)
        report.downloaded += 1
        report.bytes += len(payload)

    report.status = sample_status()
    return report


@router.get("/piano")
def piano_status() -> PianoStatus:
    """Is a real piano sound installed, and what is it?"""
    return sample_status()


@router.post("/piano")
def piano_download(force: bool = False) -> PianoDownloadReport:
    """Fetch the piano samples once. Safe to re-run: existing files are skipped.

    Not loopback-only, unlike the destructive routes: this adds files to the data
    directory rather than discarding anything, so a viewer on the LAN asking for it
    is a request the piano machine can serve.
    """
    try:
        report = download_samples(force=force)
    except OSError as exc:
        # A data directory we cannot write to. Worth saying plainly rather than
        # handing back a 500 that reads as a bug in the app.
        raise HTTPException(
            status_code=503,
            detail=f"the samples cannot be stored at {sample_dir()}: {exc}",
        ) from exc
    if report.failed and report.downloaded == 0 and report.skipped == 0:
        raise HTTPException(
            status_code=502,
            detail=f"the samples could not be downloaded: {report.errors[0]}",
        )
    return report


def mount_samples(app) -> None:
    """Serve the samples at `/piano/...`.

    The directory is created here rather than left to the download: Starlette raises
    at request time if its directory is missing, so a mount registered before the
    one-time download would make every page load fail until someone installed the
    piano. Creating it costs nothing and means the route is always servable.

    If the data directory cannot be written the mount is skipped rather than
    crashing the application: no samples is a degraded piano sound, and refusing to
    start over one is not a trade worth making.
    """
    directory = sample_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    app.mount(
        "/piano",
        StaticFiles(directory=str(sample_dir()), check_dir=False),
        name="piano-samples",
    )
