"""Recording import: probe, transcode, hash, store.

Mirrors what the Rust app did, so the library keeps its shape:

* **Content-hashed file names.** The hash *is* the identity, so importing the
  same recording twice stores it once, and re-importing never duplicates 138 MB
  of audio. This is why the column is `file_name TEXT NOT NULL UNIQUE`.
* **Re-encoding on import.** Video becomes H.264/AAC in `.mp4`, audio becomes
  Opus in `.ogg`. The player's source files are typically uncompressed WAV or
  phone video; storing them as they arrive would multiply the library size.

ffmpeg does the work through subprocesses. Everything here is a pure function of
a path on disk except `store_recording`, which is the one piece that touches the
database.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: Long enough for an eight-minute recording to be re-encoded on a slow machine,
#: short enough that a wedged ffmpeg does not hang a request forever.
FFMPEG_TIMEOUT_S = 900

AUDIO_SUFFIX = ".ogg"
VIDEO_SUFFIX = ".mp4"

#: Containers we will look inside. A file outside this set is refused with a
#: clear message rather than handed to ffmpeg to guess at.
KNOWN_SUFFIXES = frozenset(
    {
        ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wma", ".aiff", ".aif",
        ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".3gp",
    }
)


class MediaError(RuntimeError):
    """The file could not be imported."""


@dataclass(frozen=True)
class ProbeResult:
    duration_secs: float | None
    size_bytes: int
    codec: str | None
    container: str | None
    has_video: bool
    has_audio: bool

    @property
    def kind(self) -> str:
        return "video" if self.has_video else "audio"


def _run(command: list[str], *, timeout: int = FFMPEG_TIMEOUT_S) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment dependent
        raise MediaError(
            "ffmpeg is not installed or not on PATH. Install it to import recordings."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"ffmpeg timed out after {timeout}s") from exc


def probe(path: Path) -> ProbeResult:
    """Read a recording's real properties.

    Metadata is taken from the file rather than trusted from the client: the
    duration shown in the library has to describe the audio that was actually
    stored, not the audio that was uploaded.
    """
    result = _run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,size,format_name",
            "-show_entries", "stream=codec_type,codec_name",
            "-of", "json",
            str(path),
        ],
        timeout=120,
    )
    if result.returncode != 0:
        raise MediaError(f"ffprobe could not read the file: {result.stderr.strip()[:300]}")

    try:
        payload = json.loads(result.stdout or "{}")
    except ValueError as exc:
        raise MediaError("ffprobe returned something that is not JSON") from exc

    streams = payload.get("streams", [])
    fmt = payload.get("format", {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    video = next((s for s in streams if s.get("codec_type") == "video"), None)

    if audio is None and video is None:
        raise MediaError("the file contains no audio or video stream")

    duration: float | None
    try:
        duration = float(fmt["duration"]) if fmt.get("duration") is not None else None
    except (TypeError, ValueError):
        duration = None

    return ProbeResult(
        duration_secs=duration,
        size_bytes=int(fmt.get("size") or path.stat().st_size),
        codec=(video or audio or {}).get("codec_name"),
        container=fmt.get("format_name"),
        has_video=video is not None,
        has_audio=audio is not None,
    )


def content_hash(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def transcode(source: Path, destination: Path, *, has_video: bool) -> None:
    """Re-encode into the library's storage format.

    Audio-only material is checked first and copied untouched when it is already
    Opus in Ogg: re-encoding a lossy format costs quality and time for nothing.
    Verified on a five-minute recording: 0.08s instead of a full re-encode.
    """
    if not has_video and source.suffix.lower() in {".ogg", ".oga", ".opus"}:
        shutil.copy2(source, destination)
        return

    if has_video:
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
            "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart",  # so the browser can seek before it has all of it
            str(destination),
        ]
    else:
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
            "-c:a", "libopus", "-b:a", "96k",
            str(destination),
        ]

    result = _run(command)
    if result.returncode != 0 or not destination.exists():
        raise MediaError(f"ffmpeg could not convert the file: {result.stderr.strip()[:300]}")


@dataclass(frozen=True)
class StoredRecording:
    file_name: str
    kind: str
    duration_secs: float | None
    size_bytes: int
    codec: str | None
    reused: bool


def store_recording(
    source: Path,
    *,
    media_dir: Path,
    original_name: str | None = None,
) -> StoredRecording:
    """Probe, convert, hash and place one uploaded file.

    Returns the facts to record in the database. Does **not** touch the database:
    the caller owns the transaction.
    """
    if source.suffix.lower() not in KNOWN_SUFFIXES:
        raise MediaError(
            f"{source.suffix or 'a file with no extension'} is not a recognised audio "
            "or video format"
        )

    info = probe(source)
    media_dir.mkdir(parents=True, exist_ok=True)

    # Hash the *original*, not the converted output. That makes the name identify
    # the recording rather than the bytes we happen to store, so re-importing the
    # same source — at a different bitrate, or with a different ffmpeg build —
    # still lands on one entry instead of accumulating copies.
    digest = content_hash(source)
    suffix = VIDEO_SUFFIX if info.has_video else AUDIO_SUFFIX
    file_name = f"{digest}{suffix}"
    destination = media_dir / file_name

    reused = destination.exists()
    if not reused:
        # Convert into a temporary file and move it into place, so a failed or
        # interrupted transcode cannot leave a half-written recording under a
        # name that says it is complete.
        with tempfile.TemporaryDirectory(dir=media_dir) as scratch:
            converted = Path(scratch) / f"recording{suffix}"
            transcode(source, converted, has_video=info.has_video)
            if not converted.exists():
                raise MediaError("ffmpeg produced no output")
            shutil.move(str(converted), destination)

    stored = probe(destination)

    return StoredRecording(
        file_name=file_name,
        kind=info.kind,
        duration_secs=stored.duration_secs,
        size_bytes=stored.size_bytes,
        codec=stored.codec,
        reused=reused,
    )
