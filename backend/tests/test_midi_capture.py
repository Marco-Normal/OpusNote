"""Tests for headless ALSA MIDI capture and active-capture heartbeat protection."""

from __future__ import annotations

from app.practice import capture_status
from app.practice.midi_capture import (
    MAX_BUFFERED,
    MAX_HOLD_MS,
    MidiCaptureBuffer,
    NoteGate,
    local_tz_offset_minutes,
    looks_silent,
    port_matches,
)


def test_looks_silent_and_port_matches() -> None:
    assert looks_silent("Midi Through:Midi Through Port-0 14:0") is True
    assert looks_silent("System:Timer 0:0") is True
    assert looks_silent("opus-note-capture:input 128:0") is True
    assert looks_silent("CASIO USB-MIDI:CASIO USB-MIDI MIDI 1 24:0") is False

    assert port_matches("Midi Through:Midi Through Port-0 14:0", "") is False
    assert port_matches("CASIO USB-MIDI:CASIO USB-MIDI MIDI 1 24:0", "") is True
    assert port_matches("CASIO USB-MIDI:CASIO USB-MIDI MIDI 1 24:0", "casio") is True
    assert port_matches("CASIO USB-MIDI:CASIO USB-MIDI MIDI 1 24:0", "roland") is False


def test_note_gate_dedupes_across_ports_and_keeps_same_port_repeats() -> None:
    gate = NoteGate(window_ms=30)
    assert gate.accept(60, 80, "port-a", 1_000) is True
    # Duplicate from a second port inside the window is dropped.
    assert gate.accept(60, 80, "port-b", 1_010) is False
    # A fast repeat on the *same* port is accepted.
    assert gate.accept(60, 80, "port-a", 1_020) is True
    # Outside the window, a different port is accepted.
    assert gate.accept(60, 80, "port-b", 1_060) is True


def test_buffer_pairs_notes_fifo_handles_vel0_and_cc64() -> None:
    buf = MidiCaptureBuffer()
    port = "CASIO USB-MIDI:CASIO USB-MIDI MIDI 1 24:0"

    # Note 60 pressed twice before release (FIFO duration pairing)
    buf.handle_message(port, [0x90, 60, 80], 1_000)
    buf.handle_message(port, [0x90, 60, 90], 1_200)
    # Note-off via 0x80 for first press
    buf.handle_message(port, [0x80, 60, 0], 1_300)
    # Note-off via 0x90 velocity 0 for second press
    buf.handle_message(port, [0x90, 60, 0], 1_550)
    # Sustain CC64 down and up
    buf.handle_message(port, [0xB0, 64, 127], 1_100)
    buf.handle_message(port, [0xB0, 64, 0], 1_600)
    # Unrelated CC (e.g. modulation) is ignored by sustain stream
    buf.handle_message(port, [0xB0, 1, 50], 1_250)

    notes, pedals = buf.take_batch(1_700)
    assert len(notes) == 2
    assert notes[0] == {
        "epoch_ms": 1_000,
        "pitch": 60,
        "velocity": 80,
        "duration_ms": 300,
        "channel": 0,
    }
    assert notes[1] == {
        "epoch_ms": 1_200,
        "pitch": 60,
        "velocity": 90,
        "duration_ms": 350,
        "channel": 0,
    }
    assert pedals == [
        {"epoch_ms": 1_100, "value": 127, "channel": 0},
        {"epoch_ms": 1_600, "value": 0, "channel": 0},
    ]

    # Retry semantics: before ack_batch, take_batch returns the same items
    notes_again, pedals_again = buf.take_batch(1_800)
    assert notes_again == notes
    assert pedals_again == pedals

    # Concurrent arrival while POST is in flight survives ack_batch
    buf.handle_message(port, [0x90, 64, 70], 1_750)
    buf.handle_message(port, [0x80, 64, 0], 1_850)
    buf.ack_batch(len(notes), len(pedals))

    next_notes, next_pedals = buf.take_batch(1_900)
    assert len(next_notes) == 1
    assert next_notes[0]["pitch"] == 64
    assert next_pedals == []


def test_buffer_promotes_held_notes_and_caps_buffer() -> None:
    buf = MidiCaptureBuffer()
    port = "CASIO USB-MIDI"

    buf.handle_message(port, [0x90, 62, 75], 1_000)
    # Not yet past MAX_HOLD_MS
    notes, _ = buf.take_batch(1_000 + MAX_HOLD_MS - 1)
    assert notes == []
    # flush_open=True flushes held notes immediately
    notes, _ = buf.take_batch(1_500, flush_open=True)
    assert len(notes) == 1
    assert notes[0]["duration_ms"] == 500
    buf.ack_batch(1, 0)

    # MAX_HOLD_MS promotion without flush_open
    buf.handle_message(port, [0x90, 63, 75], 2_000)
    notes, _ = buf.take_batch(2_000 + MAX_HOLD_MS)
    assert len(notes) == 1
    assert notes[0]["duration_ms"] == MAX_HOLD_MS
    buf.ack_batch(1, 0)

    # Cap at MAX_BUFFERED keeping newest
    for idx in range(MAX_BUFFERED + 25):
        t = 100_000 + idx * 10
        buf.handle_message(port, [0x90, 60, 64], t)
        buf.handle_message(port, [0x80, 60, 0], t + 5)
    capped_notes, _ = buf.take_batch(200_000)
    assert len(capped_notes) == MAX_BUFFERED
    assert capped_notes[0]["epoch_ms"] == 100_000 + 25 * 10


def test_capture_buffer_ingests_via_api(client) -> None:
    buf = MidiCaptureBuffer()
    port = "CASIO USB-MIDI:CASIO USB-MIDI MIDI 1 24:0"
    buf.handle_message(port, [0x90, 60, 72], 1_700_011_800_000)
    buf.handle_message(port, [0xB0, 64, 127], 1_700_011_800_050)
    buf.handle_message(port, [0x80, 60, 0], 1_700_011_800_400)
    buf.handle_message(port, [0xB0, 64, 0], 1_700_011_800_500)

    notes, pedals = buf.take_batch(1_700_011_800_600)
    resp = client.post(
        "/api/practice/events",
        json={
            "tz_offset_minutes": local_tz_offset_minutes(),
            "source": "web_midi",
            "events": notes,
            "pedals": pedals,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] == 1
    assert body["pedals_accepted"] == 2

    status = client.get("/api/practice/status").json()
    assert status["notes"] == 1
    assert status["last_note_ms"] == 1_700_011_800_400


def test_capture_status_ignores_disabled_heartbeat_from_other_origin() -> None:
    capture_status.reset()
    try:
        capture_status.record(origin="alsa", enabled=True, pending=0, now_ms=10_000)
        # Remote LAN browser viewing the page posts enabled=False: must not clobber active ALSA
        after_lan = capture_status.record(
            origin="192.168.15.7:8000", enabled=False, pending=0, now_ms=20_000
        )
        assert after_lan.origin == "alsa"
        assert after_lan.enabled is True

        # Same origin turning off DOES update
        after_stop = capture_status.record(
            origin="alsa", enabled=False, pending=0, now_ms=25_000
        )
        assert after_stop.origin == "alsa"
        assert after_stop.enabled is False

        # Once active report goes stale, another origin can take over
        capture_status.record(origin="alsa", enabled=True, pending=0, now_ms=10_000)
        stale_takeover = capture_status.record(
            origin="localhost:8000",
            enabled=False,
            pending=0,
            now_ms=10_000 + capture_status.STALE_AFTER_MS + 1,
        )
        assert stale_takeover.origin == "localhost:8000"
        assert stale_takeover.enabled is False
    finally:
        capture_status.reset()
