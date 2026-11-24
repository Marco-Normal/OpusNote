"""Headless ALSA MIDI capture daemon for Opus Note.

Reads MIDI events directly from ALSA sequencer input ports (via ``python-rtmidi``)
and posts note/pedal batches to ``/api/practice/events`` — the exact same wire contract
used by the browser's ``CaptureClient``.

Run standalone or via ``piano-midi-capture.service``:

    python -m app.practice.midi_capture
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import signal
import threading
import time
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import requests

logger = logging.getLogger("app.practice.midi_capture")

FLUSH_INTERVAL_S = 2.0
HEARTBEAT_INTERVAL_S = 15.0
PORT_SCAN_INTERVAL_S = 2.0
MAX_HOLD_MS = 15_000
MAX_BUFFERED = 5_000
NOTE_GATE_WINDOW_MS = 30
CAPTURE_ORIGIN = "alsa"
CLIENT_NAME = "opus-note-capture"

_SILENT_PORT_RE = re.compile(r"midi\s*through|\bsystem\b|opus-note-capture", re.IGNORECASE)


def looks_silent(name: str) -> bool:
    """Return True for virtual/system ALSA ports that never carry keyboard notes."""
    return bool(_SILENT_PORT_RE.search(name))


def port_matches(name: str, port_filter: str = "") -> bool:
    """Return True if an ALSA port should be captured given an optional substring filter."""
    if looks_silent(name):
        return False
    if port_filter:
        return port_filter.lower() in name.lower()
    return True


def local_tz_offset_minutes(now_s: float | None = None) -> int:
    """Return local UTC offset in minutes east of UTC (e.g. -180 for UTC-3)."""
    ts = time.time() if now_s is None else now_s
    offset = datetime.fromtimestamp(ts).astimezone().utcoffset()
    if offset is None:
        return 0
    return int(round(offset.total_seconds() / 60))


class NoteGate:
    """Cross-port echo suppression matching ``frontend/src/lib/midiDevice.ts``."""

    def __init__(self, window_ms: int = NOTE_GATE_WINDOW_MS) -> None:
        self.window_ms = window_ms
        self._recent: dict[tuple[int, int], tuple[str, int]] = {}

    def accept(self, pitch: int, velocity: int, port_name: str, at_ms: int) -> bool:
        """Drop a duplicate (pitch, velocity) from a different port within ``window_ms``."""
        key = (pitch, velocity)
        previous = self._recent.get(key)
        self._prune(at_ms)
        if (
            previous is not None
            and previous[0] != port_name
            and at_ms - previous[1] <= self.window_ms
        ):
            return False
        self._recent[key] = (port_name, at_ms)
        return True

    def _prune(self, now_ms: int) -> None:
        stale = [key for key, (_, seen_at) in self._recent.items() if now_ms - seen_at > 1_000]
        for key in stale:
            del self._recent[key]


class MidiCaptureBuffer:
    """Thread-safe note/pedal capture buffer mirroring ``CaptureClient``."""

    def __init__(self, note_gate_window_ms: int = NOTE_GATE_WINDOW_MS) -> None:
        self._lock = threading.Lock()
        self._gate = NoteGate(window_ms=note_gate_window_ms)
        self._open: dict[int, list[dict[str, Any]]] = {}
        self._notes: list[dict[str, Any]] = []
        self._pedals: list[dict[str, Any]] = []

    def handle_message(self, port_name: str, data: Sequence[int], now_ms: int) -> None:
        """Parse one raw MIDI channel message and buffer completed notes / CC64 moves."""
        if len(data) < 2:
            return
        status = data[0] & 0xF0
        channel = data[0] & 0x0F
        first = int(data[1])
        second = int(data[2]) if len(data) > 2 else 0

        with self._lock:
            if status == 0x90 and second > 0:
                if not self._gate.accept(first, second, port_name, now_ms):
                    return
                queue = self._open.setdefault(first, [])
                queue.append(
                    {
                        "epoch_ms": now_ms,
                        "pitch": first,
                        "velocity": second,
                        "duration_ms": 0,
                        "channel": channel,
                    }
                )
                return

            if status == 0x80 or (status == 0x90 and second == 0):
                queue = self._open.get(first)
                if not queue:
                    return
                note = queue.pop(0)
                if not queue:
                    del self._open[first]
                note["duration_ms"] = max(0, now_ms - int(note["epoch_ms"]))
                self._notes.append(note)
                return

            if status == 0xB0 and first == 64:
                self._pedals.append(
                    {
                        "epoch_ms": now_ms,
                        "value": second,
                        "channel": channel,
                    }
                )

    def take_batch(
        self, now_ms: int, flush_open: bool = False
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Promote timed-out (or all, on flush_open) notes and return sorted batch copies."""
        with self._lock:
            for pitch in list(self._open):
                remaining: list[dict[str, Any]] = []
                for note in self._open[pitch]:
                    held_ms = max(0, now_ms - int(note["epoch_ms"]))
                    if flush_open or held_ms >= MAX_HOLD_MS:
                        note["duration_ms"] = held_ms
                        self._notes.append(note)
                    else:
                        remaining.append(note)
                if remaining:
                    self._open[pitch] = remaining
                else:
                    del self._open[pitch]

            if not self._notes and not self._pedals:
                return [], []

            self._notes.sort(key=lambda item: (item["epoch_ms"], item["pitch"]))
            if len(self._notes) > MAX_BUFFERED:
                self._notes = self._notes[-MAX_BUFFERED:]

            self._pedals.sort(key=lambda item: item["epoch_ms"])
            if len(self._pedals) > MAX_BUFFERED:
                self._pedals = self._pedals[-MAX_BUFFERED:]

            return list(self._notes), list(self._pedals)

    def ack_batch(self, n_notes: int, n_pedals: int) -> None:
        """Drop acknowledged prefix items after a successful POST."""
        with self._lock:
            if n_notes > 0:
                self._notes = self._notes[n_notes:]
            if n_pedals > 0:
                self._pedals = self._pedals[n_pedals:]

    def pending_count(self) -> int:
        with self._lock:
            return len(self._notes)


class _AlsaCaptureRunner:
    """Hot-plugging ALSA MIDI listener and HTTP batch poster."""

    def __init__(self, api_url: str, port_filter: str) -> None:
        try:
            import rtmidi
        except ImportError as exc:
            raise RuntimeError(
                "python-rtmidi is required for headless MIDI capture; "
                "install backend/requirements.txt"
            ) from exc

        self._rtmidi = rtmidi
        self._api_url = api_url.rstrip("/")
        self._port_filter = port_filter
        self._buffer = MidiCaptureBuffer()
        self._session = requests.Session()
        self._probe = rtmidi.MidiIn(rtmidi.API_LINUX_ALSA, name=f"{CLIENT_NAME}-probe")
        self._ports: dict[str, Any] = {}
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        last_scan = 0.0
        last_flush = 0.0
        last_heartbeat = 0.0

        try:
            while not self._stop.is_set():
                now_mono = time.monotonic()
                if now_mono - last_scan >= PORT_SCAN_INTERVAL_S:
                    self._scan_ports()
                    last_scan = now_mono

                if now_mono - last_flush >= FLUSH_INTERVAL_S:
                    self._flush(flush_open=False)
                    last_flush = now_mono

                if now_mono - last_heartbeat >= HEARTBEAT_INTERVAL_S:
                    self._send_heartbeat(enabled=True)
                    last_heartbeat = now_mono

                self._stop.wait(0.25)
        finally:
            self._flush(flush_open=True)
            self._send_heartbeat(enabled=False)
            self._close_all_ports()
            try:
                self._probe.close_port()
            except Exception:
                pass
            self._session.close()

    def _scan_ports(self) -> None:
        available = self._probe.get_ports()
        wanted: list[tuple[int, str]] = [
            (idx, name)
            for idx, name in enumerate(available)
            if port_matches(name, self._port_filter)
        ]
        wanted_names = {name for _, name in wanted}
        had_ports = len(self._ports) > 0

        for name in list(self._ports):
            if name not in wanted_names:
                self._close_port(name)

        for idx, name in wanted:
            if name in self._ports:
                continue
            midi_in = self._rtmidi.MidiIn(self._rtmidi.API_LINUX_ALSA, name=CLIENT_NAME)
            midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
            midi_in.set_callback(self._make_callback(name))
            try:
                midi_in.open_port(idx)
            except Exception as exc:
                logger.warning("Failed to open ALSA port %r: %s", name, exc)
                continue
            self._ports[name] = midi_in
            logger.info("Opened ALSA MIDI port: %s", name)

        if had_ports and not self._ports:
            logger.info("All ALSA MIDI ports disconnected; flushing and closing open sitting")
            self._flush(flush_open=True)
            self._close_sitting()

    def _make_callback(self, port_name: str):
        def _callback(event: tuple[list[int], float], _data: Any = None) -> None:
            message, _delta = event
            self._buffer.handle_message(port_name, message, int(time.time() * 1000))

        return _callback

    def _close_port(self, name: str) -> None:
        midi_in = self._ports.pop(name, None)
        if midi_in is None:
            return
        try:
            midi_in.cancel_callback()
            midi_in.close_port()
        except Exception:
            pass
        logger.info("Closed ALSA MIDI port: %s", name)

    def _close_all_ports(self) -> None:
        for name in list(self._ports):
            self._close_port(name)

    def _flush(self, *, flush_open: bool) -> None:
        now_ms = int(time.time() * 1000)
        notes, pedals = self._buffer.take_batch(now_ms, flush_open=flush_open)
        if not notes and not pedals:
            return
        payload = {
            "tz_offset_minutes": local_tz_offset_minutes(now_ms / 1000.0),
            "source": "web_midi",
            "events": notes,
            "pedals": pedals,
        }
        try:
            resp = self._session.post(
                f"{self._api_url}/api/practice/events",
                json=payload,
                timeout=5.0,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning(
                "Failed to post %d notes / %d pedals to %s (keeping queued): %s",
                len(notes),
                len(pedals),
                self._api_url,
                exc,
            )
            return
        self._buffer.ack_batch(len(notes), len(pedals))

    def _send_heartbeat(self, *, enabled: bool) -> None:
        try:
            resp = self._session.post(
                f"{self._api_url}/api/practice/capture-status",
                json={
                    "origin": CAPTURE_ORIGIN,
                    "enabled": enabled,
                    "pending": self._buffer.pending_count(),
                },
                timeout=5.0,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.debug("Capture heartbeat failed: %s", exc)

    def _close_sitting(self) -> None:
        try:
            resp = self._session.post(
                f"{self._api_url}/api/practice/sittings/close",
                timeout=5.0,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.debug("Failed to close open sitting on disconnect: %s", exc)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.practice.midi_capture",
        description="Headless ALSA MIDI capture service for Opus Note.",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("SRT_API_URL", "http://127.0.0.1:8000"),
        help="Base URL of the Opus Note API (default: SRT_API_URL or http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--port",
        default=os.environ.get("SRT_MIDI_PORT", ""),
        help="Optional ALSA port substring filter (default: SRT_MIDI_PORT or all hardware ports)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    runner = _AlsaCaptureRunner(api_url=args.api_url, port_filter=args.port)

    def _on_signal(_signum: int, _frame: Any) -> None:
        runner.request_stop()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    logger.info("Starting headless ALSA MIDI capture -> %s", args.api_url)
    runner.run()
    logger.info("Stopped headless ALSA MIDI capture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
