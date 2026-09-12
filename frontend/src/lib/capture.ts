/**
 * Passive practice capture.
 *
 * The player sits down and plays; there is no "start session" button. Notes go
 * to the backend in batches every couple of seconds, and the server decides
 * which *sitting* they belong to — the client cannot know, because a sitting is
 * defined by silence and only the server sees the whole stream.
 *
 * Three details are load-bearing:
 *
 * - **Absolute time.** Every event carries `epoch_ms`, so a batch that arrives
 *   late is still placed where it happened. The server stores onset relative to
 *   the sitting it assigns.
 * - **Durations come from the release.** A note is held back until it is released
 *   so its duration is real. A note still held at flush time waits for the next
 *   batch instead of being sent with a duration of zero that the dedupe index
 *   would then refuse to correct.
 * - **A failed POST is never a lost note.** The batch stays queued and is retried
 *   on the next tick, so a backend restart costs nothing.
 */

import { api } from './api';
import type { MidiInput, MonitorNote, MonitorRelease } from './midi';
import type { PracticeSource } from './types';

/** How often buffered notes are sent. Matches the standalone logger's cadence. */
const FLUSH_INTERVAL_MS = 2_000;

/**
 * A note held longer than this is sent with the duration it has so far.
 *
 * Real held notes are seconds, not minutes; this only catches the one whose
 * note-off never arrived (a lost message, a device unplugged mid-chord), which
 * would otherwise sit in the buffer forever and never reach the log.
 */
const MAX_HOLD_MS = 15_000;

/**
 * Safety valve. If the backend is unreachable for a very long time, holding
 * everything in memory is worse than dropping the oldest: a browser tab with a
 * growing array is how you lose the whole sitting instead of part of it.
 */
const MAX_BUFFERED = 5_000;

interface CapturedNote {
  epoch_ms: number;
  pitch: number;
  velocity: number;
  /** Filled in at release; 0 while the note is still held. */
  duration_ms: number;
  channel: number | null;
}

export interface CaptureStatus {
  enabled: boolean;
  buffered: number;
  sent: number;
  failed: number;
  lastError: string | null;
  /** Epoch ms of the last note the backend accepted, or null. */
  lastSentAt: number | null;
}

export class CaptureClient {
  private readonly midi: MidiInput;
  private readonly source: () => PracticeSource;
  private readonly onStatus: (status: CaptureStatus) => void;

  /** Notes not yet released, oldest first per pitch. */
  private readonly open = new Map<number, CapturedNote[]>();
  /** Notes ready to send — released, or held past `MAX_HOLD_MS`. */
  private buffer: CapturedNote[] = [];

  private enabled = false;
  private timer: ReturnType<typeof setInterval> | null = null;
  private flushing = false;
  private sent = 0;
  private failed = 0;
  private lastError: string | null = null;
  private lastSentAt: number | null = null;

  constructor(
    midi: MidiInput,
    source: () => PracticeSource,
    onStatus: (status: CaptureStatus) => void,
  ) {
    this.midi = midi;
    this.source = source;
    this.onStatus = onStatus;
    this.midi.onNoteOnMonitor((note) => this.receiveOn(note));
    this.midi.onNoteOffMonitor((note) => this.receiveOff(note));
  }

  get isEnabled(): boolean {
    return this.enabled;
  }

  start(): void {
    if (this.enabled) return;
    this.enabled = true;
    this.timer = setInterval(() => void this.flush(), FLUSH_INTERVAL_MS);
    this.publish();
  }

  /** Stop capturing. Notes still held are dropped: they have no end time. */
  stop(): void {
    this.enabled = false;
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    this.open.clear();
    this.publish();
  }

  /** Send whatever is ready right now, e.g. when the page is being hidden. */
  async flush(): Promise<void> {
    if (this.flushing) return;
    const now = Date.now();
    // Anything held past the cap joins the queue with the duration it has.
    for (const [pitch, notes] of [...this.open]) {
      const remaining: CapturedNote[] = [];
      for (const note of notes) {
        if (now - note.epoch_ms >= MAX_HOLD_MS) {
          note.duration_ms = now - note.epoch_ms;
          this.buffer.push(note);
        } else {
          remaining.push(note);
        }
      }
      if (remaining.length) this.open.set(pitch, remaining);
      else this.open.delete(pitch);
    }

    if (this.buffer.length === 0) {
      this.publish();
      return;
    }

    // Keep the batch in order, and keep the newest notes if the cap is hit.
    this.buffer.sort((a, b) => a.epoch_ms - b.epoch_ms || a.pitch - b.pitch);
    if (this.buffer.length > MAX_BUFFERED) {
      this.buffer = this.buffer.slice(-MAX_BUFFERED);
    }

    const batch = this.buffer;
    this.flushing = true;
    try {
      await api.practice.ingest({
        source: this.source(),
        events: batch,
      });
      // Only now are they gone: a failure below leaves the whole batch queued.
      this.buffer = this.buffer.slice(batch.length);
      this.sent += batch.length;
      this.lastSentAt = batch[batch.length - 1]?.epoch_ms ?? this.lastSentAt;
      this.lastError = null;
    } catch (cause) {
      this.failed += 1;
      this.lastError = cause instanceof Error ? cause.message : String(cause);
    } finally {
      this.flushing = false;
      this.publish();
    }
  }

  private receiveOn(note: MonitorNote): void {
    if (!this.enabled) return;
    const captured: CapturedNote = {
      epoch_ms: note.epochMs,
      pitch: note.pitch,
      velocity: note.velocity,
      duration_ms: 0,
      channel: note.channel ?? null,
    };
    const queue = this.open.get(note.pitch) ?? [];
    queue.push(captured);
    this.open.set(note.pitch, queue);
    this.publish();
  }

  private receiveOff(note: MonitorRelease): void {
    if (!this.enabled) return;
    const queue = this.open.get(note.pitch);
    const captured = queue?.shift();
    if (queue && queue.length === 0) this.open.delete(note.pitch);
    if (!captured) return;
    captured.duration_ms = note.durationMs;
    this.buffer.push(captured);
    this.publish();
  }

  private publish(): void {
    this.onStatus({
      enabled: this.enabled,
      buffered: this.buffer.length,
      sent: this.sent,
      failed: this.failed,
      lastError: this.lastError,
      lastSentAt: this.lastSentAt,
    });
  }
}
