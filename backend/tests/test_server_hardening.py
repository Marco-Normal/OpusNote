"""The boundaries that make a LAN deployment safe without accounts.

Two properties are checked here in both directions:

* the loopback test itself (directly, against a real `Request`), and
* the refusal it produces on a real route (by patching `is_loopback` to False).

`TestClient` is not a socket, so its client address is the literal "testclient".
The shared `client` fixture therefore declares the suite local — see its docstring —
and these tests are what stop that from hiding a broken check.
"""

from __future__ import annotations

from starlette.requests import Request


def _request_from(host: str) -> Request:
    return Request(
        {
            "type": "http",
            "client": (host, 12345),
            "method": "GET",
            "path": "/",
            "headers": [],
        }
    )


def test_ipv4_ipv6_and_mapped_loopback_all_count_as_local() -> None:
    from app.hostinfo import is_loopback

    for host in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"):
        assert is_loopback(_request_from(host)) is True, host
    for host in ("192.168.1.50", "10.0.0.7", "::ffff:192.168.1.50"):
        assert is_loopback(_request_from(host)) is False, host


def test_require_loopback_refuses_a_lan_client() -> None:
    import pytest
    from fastapi import HTTPException

    from app.hostinfo import require_loopback

    with pytest.raises(HTTPException) as error:
        require_loopback(_request_from("192.168.1.50"))
    assert error.value.status_code == 403
    # The message has to say where to go; a bare 403 is a puzzle.
    assert "http://localhost:8000" in str(error.value.detail)


def test_require_loopback_accepts_a_local_client() -> None:
    from app.hostinfo import require_loopback

    assert require_loopback(_request_from("127.0.0.1")) is None


def test_the_host_route_answers_with_this_machines_view(client) -> None:
    body = client.get("/api/host").json()
    assert body["host"] == "testclient"
    assert isinstance(body["sequencer"], bool)
    assert isinstance(body["clients"], list)
    assert "System" in body["clients"] or body["clients"] == []


def test_the_sequencer_probe_accepts_either_signal(monkeypatch) -> None:
    """`/dev/snd/seq` is absent in containers while the sequencer is running."""
    from pathlib import Path

    from app import hostinfo

    monkeypatch.setattr(hostinfo, "SEQUENCER_PATH", Path("/nonexistent/seq"))
    monkeypatch.setattr(hostinfo, "SEQ_CLIENTS_PATH", Path("/nonexistent/clients"))
    assert hostinfo.sequencer_available() is False
    monkeypatch.setattr(hostinfo, "SEQ_CLIENTS_PATH", Path("/proc/asound/seq/clients"))
    assert hostinfo.sequencer_available() is True


def test_alsa_clients_is_empty_rather_than_failing_without_a_sequencer(monkeypatch) -> None:
    from pathlib import Path

    from app import hostinfo

    monkeypatch.setattr(hostinfo, "SEQ_CLIENTS_PATH", Path("/nonexistent/clients"))
    assert hostinfo.alsa_clients() == []


def test_alsa_clients_reads_the_real_procfs_shape(monkeypatch, tmp_path) -> None:
    from app import hostinfo

    fake = tmp_path / "clients"
    fake.write_text(
        "Client info\n"
        "  cur  clients : 2\n"
        'Client   0 : "System" [Kernel Legacy]\n'
        '  Port   0 : "Timer" (Rwe-) [In/Out]\n'
        'Client  24 : "CASIO USB-MIDI" [Kernel]\n'
        '  Port   0 : "CASIO USB-MIDI MIDI 1" (RWe-) [In/Out]\n'
    )
    monkeypatch.setattr(hostinfo, "SEQ_CLIENTS_PATH", fake)
    assert hostinfo.alsa_clients() == ["System", "CASIO USB-MIDI"]


def test_deleting_a_piece_over_the_lan_is_refused(client) -> None:
    """The boundary is enforced on the route, not only in the helper."""
    from app import hostinfo

    piece = client.post("/api/repertoire/pieces", json={"title": "Keep me"}).json()
    hostinfo.is_loopback = lambda request: False
    try:
        refused = client.delete(f"/api/repertoire/pieces/{piece['id']}")
        still_here = client.get(f"/api/repertoire/pieces/{piece['id']}").status_code
    finally:
        hostinfo.is_loopback = lambda request: True
    assert refused.status_code == 403
    assert "piano machine" in refused.json()["detail"]
    assert still_here == 200, "and the row really is still there"


def test_a_merge_import_is_allowed_over_the_lan_but_a_replace_is_not(client) -> None:
    from app import hostinfo

    document = client.get("/api/backup/export").json()
    assert client.post("/api/backup/import", json={"document": document}).status_code == 200

    hostinfo.is_loopback = lambda request: False
    try:
        replaced = client.post(
            "/api/backup/import",
            json={"document": document, "mode": "replace", "confirm": True},
        )
        profile = client.post("/api/profile/reset")
    finally:
        hostinfo.is_loopback = lambda request: True
    assert replaced.status_code == 403, "replace discards everything"
    assert profile.status_code == 403, "resetting the profile discards ratings"


def test_re_segmenting_over_labels_is_refused_over_the_lan(client) -> None:
    """`confirm=false` only recomputes, so only the destructive variant is held back."""
    from app import hostinfo

    from app.practice import store
    from app.practice.models import EventBatch, WireNote

    sitting_id = store.ingest(
        EventBatch(
            tz_offset_minutes=0,
            events=[
                WireNote(
                    epoch_ms=1_700_011_800_000,
                    pitch=60,
                    velocity=70,
                    duration_ms=300,
                    channel=0,
                )
            ],
        )
    ).sitting_id

    hostinfo.is_loopback = lambda request: False
    try:
        recomputed = client.post(
            f"/api/practice/sittings/{sitting_id}/resegment", json={"confirm": False}
        )
        discarded = client.post(
            f"/api/practice/sittings/{sitting_id}/resegment", json={"confirm": True}
        )
    finally:
        hostinfo.is_loopback = lambda request: True
    assert recomputed.status_code == 200
    assert discarded.status_code == 403


def test_the_upload_cap_is_enforced_while_writing(client) -> None:
    """A declared size can lie; the bytes on the way in cannot."""
    import dataclasses

    import app.repertoire.api as repertoire_api
    from app.config import settings as real_settings

    piece = client.post("/api/repertoire/pieces", json={"title": "Cap"}).json()

    # A copy of the real settings with one field changed: replacing the object with a
    # stub takes `db_path` and `media_dir` with it, and the route needs those.
    original = repertoire_api.settings
    repertoire_api.settings = dataclasses.replace(real_settings, max_upload_mb=0)
    try:
        response = client.post(
            f"/api/repertoire/pieces/{piece['id']}/media",
            files={"file": ("take.wav", b"x" * 4096, "audio/wav")},
        )
    finally:
        repertoire_api.settings = original
    assert response.status_code == 413
    assert "larger than" in response.json()["detail"]


def test_the_connection_waits_for_a_lock_instead_of_failing(fresh_db) -> None:
    from app.db import connect

    conn = connect()
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_a_capture_heartbeat_is_reported_back(client) -> None:
    assert client.get("/api/practice/status").json()["capture"] is None
    posted = client.post(
        "/api/practice/capture-status",
        json={"origin": "localhost:8000", "enabled": True, "pending": 3},
    ).json()
    assert posted["enabled"] is True and posted["pending"] == 3
    status = client.get("/api/practice/status").json()
    assert status["capture"]["origin"] == "localhost:8000"
    assert status["capture"]["enabled"] is True


def test_a_stale_heartbeat_is_not_reported() -> None:
    from app.practice import capture_status

    capture_status.reset()
    capture_status.record(origin="localhost:8000", enabled=True, pending=0, now_ms=1_000)
    assert capture_status.snapshot(now_ms=1_000 + capture_status.STALE_AFTER_MS + 1) is None
    assert capture_status.snapshot(now_ms=1_000) is not None
    capture_status.reset()


def test_the_status_reports_the_last_stored_note(client) -> None:
    from app.practice import store
    from app.practice.models import EventBatch, WireNote

    assert client.get("/api/practice/status").json()["last_note_ms"] is None
    store.ingest(
        EventBatch(
            tz_offset_minutes=0,
            events=[
                WireNote(
                    epoch_ms=1_700_011_800_000,
                    pitch=60,
                    velocity=70,
                    duration_ms=300,
                    channel=0,
                )
            ],
        )
    )
    assert client.get("/api/practice/status").json()["last_note_ms"] == 1_700_011_800_300


# --- installation health (Phase 12) ---------------------------------------


def test_the_system_status_reports_what_a_health_panel_needs(client) -> None:
    body = client.get("/api/status/system").json()
    assert body["database_bytes"] > 0, "the database exists and has a size"
    assert body["media"] == {"present": 0, "pending": 0, "missing": 0}
    assert body["backup_dir"]
    assert body["last_backup"] is None, "no backups written in a fresh test"
    assert isinstance(body["sequencer"], bool)
    assert isinstance(body["alsa_clients"], list)
    assert body["latency_suggestion_ms"] is None, "no attempts yet, so nothing to suggest"


def test_the_status_reports_the_newest_backup(tmp_path, fresh_db, client) -> None:
    from datetime import datetime

    from app import backup

    backup.write_backup(out_dir=tmp_path, keep=5, now=datetime(2026, 9, 1))
    backup.write_backup(out_dir=tmp_path, keep=5, now=datetime(2026, 9, 2))

    import dataclasses

    import app.main as main_module
    from app.config import settings as real_settings

    original = main_module.settings
    main_module.settings = dataclasses.replace(real_settings, backup_dir=tmp_path)
    try:
        body = client.get("/api/status/system").json()
    finally:
        main_module.settings = original
    assert body["last_backup"] == "piano-ecosystem-2026-09-02.json"
    assert body["backup_count"] == 2
    assert body["last_backup_seconds"] is not None


def test_a_latency_suggestion_needs_evidence(client) -> None:
    """Three attempts, or it is a bad day rather than a habit."""
    from app import store

    assert client.get("/api/status/system").json()["latency_suggestion_ms"] is None

    exercise = None
    for index in range(3):
        exercise = client.get("/api/exercise/next").json()
        notes = [
            {
                "pitch": note["pitch"],
                # Consistently 60 ms late, which is what a latency setting compensates.
                "onset": note["onset_s"] + 0.06,
                "duration": 0.3,
                "velocity": 70,
                "channel": 0,
            }
            for note in exercise["expected_notes"]
        ]
        client.post(
            "/api/score", json={"exercise_id": exercise["exercise_id"], "notes": notes}
        )

    conn = __import__("app.db", fromlist=["connect"]).connect()
    try:
        bias = store.onset_bias_ms(conn, 1)
    finally:
        conn.close()
    assert bias is not None
    assert 30 < bias < 120, f"a consistent 60 ms lag should be visible (got {bias})"
