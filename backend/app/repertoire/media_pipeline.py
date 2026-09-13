"""Recording and score import: probe, transcode, hash, store.

Mirrors what the Rust app did for recordings, so the library keeps its shape:

* **Content-hashed file names.** The hash *is* the identity, so importing the
  same recording twice stores it once, and re-importing never duplicates 138 MB
  of audio. This is why the column is `file_name TEXT NOT NULL UNIQUE`.
* **Re-encoding on import.** Video becomes H.264/AAC in `.mp4`, audio becomes
  Opus in `.ogg`. The player's source files are typically uncompressed WAV or
  phone video; storing them as they arrive would multiply the library size.

Scores (§ *Scores* at the end) reuse the same hashing and placement but take no
ffmpeg pass, and are identified by their own bytes instead of by ffprobe.

ffmpeg does the work through subprocesses. Everything here is a pure function of
a path on disk except `store_recording` and `store_score`, which return what to
catalogue and leave the database to the caller.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ElementTree
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

#: Scores travel through the same content-hashed storage as recordings but take
#: no ffmpeg pass: there is nothing to probe (their own bytes identify them) and
#: nothing to re-encode (the browser reads a PDF, and OSMD reads MusicXML).
SCORE_SUFFIXES = frozenset({".pdf", ".musicxml", ".xml"})

#: Which format each accepted suffix is, and — because a stored score is named
#: for its format rather than for whatever it happened to be called — the suffix
#: the file gets in the media directory. `.xml` and `.musicxml` collapse onto one,
#: so the same MusicXML under either name is a single stored file.
SCORE_FORMATS: dict[str, str] = {".pdf": "pdf", ".musicxml": "musicxml", ".xml": "musicxml"}

#: What to serve each stored score as. `mimetypes` does not know `.musicxml` at
#: all, and guesses `text/xml` for `.xml`; both are wrong enough that a browser
#: may download the file rather than hand it to a renderer.
SCORE_MEDIA_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "musicxml": "application/vnd.recordare.musicxml+xml",
}

#: A score is an XML document we hand to a parser, so a pathological upload must
#: not be able to chew through memory. Far above any real score: the largest
#: published MusicXML files are single-digit megabytes.
MAX_SCORE_BYTES = 32 * 1024 * 1024

#: `%PDF-` must appear within this many bytes of the start. The specification says
#: the very first line, but files from sloppy producers carry a little junk first
#: and every reader tolerates it, so we do too.
PDF_HEADER_SCAN = 1024


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


# --------------------------------------------------------------------------
# Scores
#
# A score is a *document*, not a recording, and the differences matter: there is
# no duration and no codec to probe, no conversion worth doing, and the file's
# own bytes are the only thing that can tell us whether it is really a PDF or
# really MusicXML. So this path validates content and stores the file untouched.
# --------------------------------------------------------------------------


def _local_name(tag: str) -> str:
    """An element's name without its XML namespace, e.g. `{ns}score-partwise`."""
    return tag.rsplit("}", 1)[-1].strip().lower()


def looks_like_pdf(path: Path) -> bool:
    """Whether the file starts with the PDF header, whatever it is called."""
    with path.open("rb") as handle:
        return b"%PDF-" in handle.read(PDF_HEADER_SCAN)


def musicxml_root(path: Path) -> str | None:
    """The MusicXML root element's name, or ``None`` if this is not MusicXML.

    Well-formedness is checked as a side effect, which is the point: a truncated
    or corrupt score is refused at upload with a real parser's complaint rather
    than at the piano, as a blank page.
    """
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as exc:
        raise MediaError(f"this is not valid XML: {exc}") from exc
    name = _local_name(root.tag)
    return name if name in {"score-partwise", "score-timewise"} else None


def score_format(path: Path, suffix: str) -> str:
    """Identify a score by its content, refusing anything we cannot render.

    The declared suffix chooses which check applies; the content decides whether
    it passes. A `.pdf` that is not a PDF and an `.xml` that is not MusicXML are
    both refused here, so nothing unrenderable reaches the library — where the
    only symptom would be a blank frame on the practice machine.
    """
    key = suffix.lower()
    if key not in SCORE_SUFFIXES:
        raise MediaError(
            "scores must be PDF or uncompressed MusicXML (.musicxml/.xml); "
            "a .mxl archive has to be unzipped first"
        )

    size = path.stat().st_size
    if size == 0:
        raise MediaError("the file is empty")
    if size > MAX_SCORE_BYTES:
        raise MediaError(f"the score is larger than {MAX_SCORE_BYTES // (1024 * 1024)} MB")

    expected = SCORE_FORMATS[key]
    if expected == "pdf":
        if not looks_like_pdf(path):
            raise MediaError("this file does not begin with a PDF header")
        return "pdf"

    if musicxml_root(path) is None:
        raise MediaError(
            "this XML file is not MusicXML: a score's root element must be "
            "<score-partwise> or <score-timewise>"
        )
    return "musicxml"


@dataclass(frozen=True)
class StoredScore:
    file_name: str
    kind: str
    codec: str
    size_bytes: int
    original_name: str | None
    reused: bool


def store_score(
    source: Path,
    *,
    media_dir: Path,
    original_name: str | None = None,
) -> StoredScore:
    """Validate, hash and place one uploaded score.

    Returns the facts to record in the database and does **not** touch it: the
    caller owns the transaction, exactly as `store_recording` does.

    The stored name is the content hash plus the *format* (`.pdf`/`.musicxml`),
    never the uploaded suffix, so the same document uploaded as `.xml` and as
    `.musicxml` is one file. Because the name is derived from content and the
    `media.file_name` column is unique, storing can legitimately produce a name
    that is already catalogued — the caller must check and refuse the duplicate
    row rather than let the insert collide.
    """
    codec = score_format(source, source.suffix)
    media_dir.mkdir(parents=True, exist_ok=True)

    digest = content_hash(source)
    file_name = f"{digest}.{codec}"
    destination = media_dir / file_name

    reused = destination.exists()
    if not reused:
        # Content-addressed, so the file is already its own checksum: copying it
        # into place is all the "conversion" a score needs, and it loses nothing.
        # Staged and moved, like a recording, so an interrupted copy cannot leave
        # a truncated file under a name that claims to be complete.
        with tempfile.TemporaryDirectory(dir=media_dir) as scratch:
            staged = Path(scratch) / f"score.{codec}"
            shutil.copy2(source, staged)
            shutil.move(str(staged), destination)

    return StoredScore(
        file_name=file_name,
        kind="score",
        codec=codec,
        size_bytes=destination.stat().st_size,
        original_name=original_name,
        reused=reused,
    )
