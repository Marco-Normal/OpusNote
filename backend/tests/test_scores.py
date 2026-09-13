"""Scores: attaching a PDF or MusicXML document to a piece.

A score is a *document*, so the checks that matter here are different from a
recording's: the content decides whether it is accepted (a `.pdf` that is not a
PDF is refused before it can become a blank page at the piano), it is stored
byte-for-byte, and it is kept out of the recording counts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import db
from app.config import settings
from app.repertoire import store
from app.repertoire.media_pipeline import (
    MediaError,
    content_hash,
    score_format,
    store_score,
)

#: Enough of a PDF for the header check, which is deliberately all it looks at.
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"

MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1"><measure number="1"/></part>
</score-partwise>
"""


def _write(tmp_path: Path, name: str, data: bytes | str) -> Path:
    path = tmp_path / name
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    return path


# --------------------------------------------------------------------------
# Storing
# --------------------------------------------------------------------------


def test_a_score_is_stored_byte_for_byte_under_its_hash(tmp_path):
    source = _write(tmp_path, "nocturne.pdf", PDF_BYTES)
    stored = store_score(source, media_dir=tmp_path / "media", original_name="nocturne.pdf")

    assert stored.kind == "score"
    assert stored.codec == "pdf"
    assert stored.reused is False
    assert stored.size_bytes == len(PDF_BYTES)

    placed = tmp_path / "media" / stored.file_name
    assert stored.file_name == f"{content_hash(source)}.pdf"
    assert placed.read_bytes() == PDF_BYTES, "a score is not re-encoded"


def test_the_same_document_under_two_names_is_one_file(tmp_path):
    """`.xml` and `.musicxml` are the same format, and the name is the format."""
    xml = _write(tmp_path, "sonata.musicxml", MUSICXML)
    other = _write(tmp_path, "sonata.xml", MUSICXML)

    first = store_score(xml, media_dir=tmp_path / "media")
    second = store_score(other, media_dir=tmp_path / "media")

    assert first.file_name == second.file_name
    assert second.reused is True
    assert len(list((tmp_path / "media").iterdir())) == 1


def test_a_score_whose_content_does_not_match_its_name_is_refused(tmp_path):
    not_a_pdf = _write(tmp_path, "score.pdf", "<html>hello</html>")
    with pytest.raises(MediaError, match="PDF header"):
        store_score(not_a_pdf, media_dir=tmp_path / "media")


def test_plain_xml_is_not_accepted_as_a_score(tmp_path):
    """Plenty of XML is not music; accepting it would render an empty page."""
    page = _write(tmp_path, "page.xml", "<html><body>hi</body></html>")
    with pytest.raises(MediaError, match="not MusicXML"):
        store_score(page, media_dir=tmp_path / "media")


def test_malformed_musicxml_is_refused_with_the_parsers_complaint(tmp_path):
    broken = _write(tmp_path, "broken.musicxml", "<score-partwise><part>")
    with pytest.raises(MediaError, match="not valid XML"):
        store_score(broken, media_dir=tmp_path / "media")


def test_a_compressed_score_says_how_to_unpack_it(tmp_path):
    """`.mxl` is the distribution format for MusicXML, so it is worth a real answer."""
    archive = _write(tmp_path, "score.mxl", b"PK\x03\x04not really a zip")
    with pytest.raises(MediaError, match="unzipped"):
        store_score(archive, media_dir=tmp_path / "media")


def test_an_empty_score_is_refused(tmp_path):
    empty = _write(tmp_path, "empty.pdf", b"")
    with pytest.raises(MediaError, match="empty"):
        store_score(empty, media_dir=tmp_path / "media")


def test_a_score_may_be_identified_without_being_stored(tmp_path):
    """The format check is usable on its own, which is what makes it testable
    without a media directory."""
    assert score_format(_write(tmp_path, "a.pdf", PDF_BYTES), ".pdf") == "pdf"
    assert score_format(_write(tmp_path, "a.xml", MUSICXML), ".xml") == "musicxml"


# --------------------------------------------------------------------------
# The routes
# --------------------------------------------------------------------------


def _piece(client, title: str = "Nocturne") -> int:
    return int(client.post("/api/repertoire/pieces", json={"title": title}).json()["id"])


def test_a_score_upload_is_catalogued_and_served_as_a_document(client):
    piece_id = _piece(client)
    response = client.post(
        f"/api/repertoire/pieces/{piece_id}/scores",
        files={"file": ("sonata.musicxml", MUSICXML, "application/xml")},
        data={"title": "Sonata in C"},
    )
    assert response.status_code == 201, response.text
    score = response.json()
    assert score["kind"] == "score"
    assert score["codec"] == "musicxml"
    assert score["state"] == "present"
    assert score["title"] == "Sonata in C"
    assert score["duration_secs"] is None

    served = client.get(f"/api/repertoire/media/{score['id']}/file")
    assert served.status_code == 200
    # The type has to be one Chromium hands to a renderer. `mimetypes` alone
    # guesses `text/xml` for `.xml` and knows nothing about `.musicxml`.
    assert served.headers["content-type"].startswith(
        "application/vnd.recordare.musicxml"
    )
    assert served.text == MUSICXML

    detail = client.get(f"/api/repertoire/pieces/{piece_id}").json()
    assert [row["id"] for row in detail["media"]] == [score["id"]]
    assert detail["score_count"] == 1
    assert detail["recording_count"] == 0


def test_a_pdf_score_is_served_as_pdf(client):
    piece_id = _piece(client)
    response = client.post(
        f"/api/repertoire/pieces/{piece_id}/scores",
        files={"file": ("nocturne.pdf", PDF_BYTES, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    served = client.get(f"/api/repertoire/media/{response.json()['id']}/file")
    assert served.headers["content-type"] == "application/pdf"


def test_scores_are_not_counted_as_recordings(client):
    """The health panel says "recordings"; a PDF in that number makes it lie."""
    piece_id = _piece(client)
    client.post(
        f"/api/repertoire/pieces/{piece_id}/scores",
        files={"file": ("sonata.musicxml", MUSICXML, "application/xml")},
    )

    status = client.get("/api/repertoire/status").json()
    assert status["scores"] == 1
    assert status["media_rows"] == 1, "it is still a media row"
    assert status["media_present"] == 0, "but not a recording that is present"

    conn = db.connect(settings.db_path)
    try:
        assert store.media_state_counts(conn) == {"present": 0, "pending": 0, "missing": 0}
        assert store.pending_media(conn) == []
    finally:
        conn.close()


def test_uploading_the_same_score_twice_says_where_it_already_is(client):
    piece_id = _piece(client, "Nocturne")
    upload = lambda: client.post(  # noqa: E731
        f"/api/repertoire/pieces/{piece_id}/scores",
        files={"file": ("nocturne.pdf", PDF_BYTES, "application/pdf")},
    )
    assert upload().status_code == 201
    refused = upload()
    assert refused.status_code == 409, refused.text
    assert "Nocturne" in refused.json()["detail"]
    assert len(list(Path(settings.media_dir).glob("*.pdf"))) == 1


def test_a_score_of_the_wrong_shape_is_refused_before_it_is_stored(client):
    piece_id = _piece(client)
    response = client.post(
        f"/api/repertoire/pieces/{piece_id}/scores",
        files={"file": ("score.pdf", b"<html>not a pdf</html>", "application/pdf")},
    )
    assert response.status_code == 422
    assert "PDF header" in response.json()["detail"]
    assert list(Path(settings.media_dir).glob("*")) == []


def test_uploading_a_score_to_a_missing_piece_is_404(client):
    response = client.post(
        "/api/repertoire/pieces/999/scores",
        files={"file": ("nocturne.pdf", PDF_BYTES, "application/pdf")},
    )
    assert response.status_code == 404


def test_an_empty_score_upload_is_refused(client):
    piece_id = _piece(client)
    response = client.post(
        f"/api/repertoire/pieces/{piece_id}/scores",
        files={"file": ("nocturne.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 422


def test_a_score_can_be_moved_to_another_piece_and_removed(client):
    first = _piece(client, "First")
    second = _piece(client, "Second")
    score = client.post(
        f"/api/repertoire/pieces/{first}/scores",
        files={"file": ("nocturne.pdf", PDF_BYTES, "application/pdf")},
    ).json()

    moved = client.patch(f"/api/repertoire/media/{score['id']}", json={"piece_id": second})
    assert moved.status_code == 200
    assert moved.json()["piece_id"] == second
    assert client.get(f"/api/repertoire/pieces/{first}").json()["score_count"] == 0

    removed = client.delete(f"/api/repertoire/media/{score['id']}")
    assert removed.json() == {"deleted": True, "cascaded": {"files_removed": 1}}
    assert list(Path(settings.media_dir).glob("*")) == []
