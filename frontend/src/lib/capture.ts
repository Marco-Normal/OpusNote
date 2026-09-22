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
import type { MidiInput, MonitorNote, MonitorPedal, MonitorRelease } from './midi';
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

/**
 * A pedal move on its way to the log.
 *
 * Kept apart from the notes because it has no duration and nothing to wait for:
 * it is complete the moment it arrives, so it can be flushed in the same tick.
 * The two lists travel in one batch so a note and the pedal under it keep their
 * relative order on the wire.
 */
interface CapturedPedal {
  epoch_ms: number;
  value: number;
  channel: number | null;
}

export interface CaptureStatus {
  enabled: boolean;
  buffered: number;
  /** Pedal moves waiting to be sent, counted apart from notes. */
  pedals: number;
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
  /** Pedal moves ready to send. Nothing is ever held back here. */
  private pedals: CapturedPedal[] = [];

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
    this.midi.onPedalMonitor((pedal) => this.receivePedal(pedal));
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

  /**
   * Send whatever is ready right now.
   *
   * Asynchronous, so it is the right call for the deliberate exits — finishing a sitting,
   * finishing a workout — where the page is alive to see it through. For a page that is going
   * away, use `flushOnHide`: a request started here is cancelled with the document.
   */
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

    if (this.buffer.length === 0 && this.pedals.length === 0) {
      this.publish();
      return;
    }

    // Keep the batch in order, and keep the newest notes if the cap is hit.
    this.buffer.sort((a, b) => a.epoch_ms - b.epoch_ms || a.pitch - b.pitch);
    if (this.buffer.length > MAX_BUFFERED) {
      this.buffer = this.buffer.slice(-MAX_BUFFERED);
    }
    this.pedals.sort((a, b) => a.epoch_ms - b.epoch_ms);
    if (this.pedals.length > MAX_BUFFERED) {
      this.pedals = this.pedals.slice(-MAX_BUFFERED);
    }

    // Copied, not aliased. Notes and pedal moves keep arriving while the request is
    // in flight and are pushed onto these same arrays, so slicing by the *aliased*
    // array's length afterwards measured the grown list and threw the new arrivals
    // away — silently, and by however much was played during the round trip.
    const batch = this.buffer.slice();
    const pedals = this.pedals.slice();
    this.flushing = true;
    try {
      await api.practice.ingest({
        source: this.source(),
        events: batch,
        pedals,
      });
      // Only now are they gone: a failure below leaves the whole batch queued.
      this.buffer = this.buffer.slice(batch.length);
      this.pedals = this.pedals.slice(pedals.length);
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

  /**
   * Deliver what is ready as the page goes away.
   *
   * Everything between the last 2 s flush and the moment the page is hidden used to be lost —
   * a reload, a kiosk restart or a power cut took the tail of the sitting with it, in a module
   * that otherwise guarantees a failed POST is never a lost note. This is the one path that
   * cannot be asynchronous, so it hands the batch to the browser through `sendBeacon`, which
   * outlives the document.
   *
   * Notes still *held* are included, with the duration they have so far rather than being
   * dropped. `flush()` waits `MAX_HOLD_MS` before doing that, and waiting is exactly what is
   * not available here; the onset, pitch and velocity are the valuable part and a duration
   * that is a lower bound beats losing the note. `stop()` still drops them, because stopping
   * is a deliberate act and hiding is an accident mid-phrase.
   */
  flushOnHide(): void {
    if (!this.enabled) return;
    const now = Date.now();
    for (const notes of this.open.values()) {
      for (const note of notes) {
        note.duration_ms = now - note.epoch_ms;
        this.buffer.push(note);
      }
    }
    this.open.clear();

    if (this.buffer.length === 0 && this.pedals.length === 0) return;

    this.buffer.sort((a, b) => a.epoch_ms - b.epoch_ms || a.pitch - b.pitch);
    if (this.buffer.length > MAX_BUFFERED) this.buffer = this.buffer.slice(-MAX_BUFFERED);
    this.pedals.sort((a, b) => a.epoch_ms - b.epoch_ms);
    if (this.pedals.length > MAX_BUFFERED) this.pedals = this.pedals.slice(-MAX_BUFFERED);

    const batch = this.buffer.slice();
    const pedals = this.pedals.slice();
    // Synchronous by necessity: the answer decides whether these are still ours to keep. If
    // the browser refuses to queue them the batch stays in the buffer, so a page that turns
    // out not to be going away — `pagehide` also fires for a bfcache entry — loses nothing.
    if (!api.practice.ingestOnHide({ source: this.source(), events: batch, pedals })) return;

    this.buffer = this.buffer.slice(batch.length);
    this.pedals = this.pedals.slice(pedals.length);
    this.sent += batch.length;
    this.lastSentAt = batch[batch.length - 1]?.epoch_ms ?? this.lastSentAt;
    this.lastError = null;
    this.publish();
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

  private receivePedal(pedal: MonitorPedal): void {
    if (!this.enabled) return;
    this.pedals.push({
      epoch_ms: pedal.epochMs,
      value: pedal.value,
      channel: pedal.channel ?? null,
    });
    this.publish();
  }

  private publish(): void {
    this.onStatus({
      enabled: this.enabled,
      buffered: this.buffer.length,
      pedals: this.pedals.length,
      sent: this.sent,
      failed: this.failed,
      lastError: this.lastError,
      lastSentAt: this.lastSentAt,
    });
  }
}
