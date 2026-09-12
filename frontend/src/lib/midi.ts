/**
 * Web MIDI input for the Casio PX-870 (or any class-compliant MIDI keyboard).
 *
 * The PX-870 appears as a plain MIDI input over USB Type-B: note on/off,
 * velocity, and sustain on CC64. Nothing vendor-specific is needed.
 *
 * Web MIDI requires a secure context. `localhost` counts as secure, so the dev
 * server is fine; a deployment must use HTTPS.
 */

export interface MidiDeviceInfo {
  id: string;
  name: string;
  manufacturer: string;
}

export interface RawMidiEvent {
  /** Seconds relative to the recording anchor, filled in by the recorder. */
  onset: number;
  pitch: number;
  velocity: number;
  channel: number;
}

/** A note on the wall clock, for passive logging rather than for an exercise. */
export interface MonitorNote {
  /** Absolute time, ms since the Unix epoch — what the practice log stores. */
  epochMs: number;
  pitch: number;
  velocity: number;
  channel: number;
}

/** The same note once it has been released. */
export interface MonitorRelease extends MonitorNote {
  durationMs: number;
}

type NoteHandler = (event: RawMidiEvent) => void;
type SustainHandler = (down: boolean) => void;
type DevicesHandler = (devices: MidiDeviceInfo[]) => void;
type MonitorOnHandler = (note: MonitorNote) => void;
type MonitorOffHandler = (note: MonitorRelease) => void;

interface NoteState {
  onset: number;
  velocity: number;
  channel: number;
}

export class MidiInput {
  private access: MIDIAccess | null = null;
  private input: MIDIInput | null = null;
  /**
   * A queue per pitch, not a single slot.
   *
   * Keyed by pitch alone, a re-struck note before its release overwrote the first
   * onset and lost that note's duration — which is common with the pedal down.
   * The passive log stores durations, so every note needs its own.
   */
  private readonly activeNotes = new Map<number, NoteState[]>();

  /** Anchor in `performance.now()` milliseconds; onsets are measured from it. */
  private anchorMs = 0;
  private recording = false;

  private noteHandlers = new Set<NoteHandler>();
  private sustainHandlers = new Set<SustainHandler>();
  private devicesHandlers = new Set<DevicesHandler>();
  private releaseHandlers = new Set<(pitch: number, durationS: number) => void>();
  /**
   * Passive observers, deliberately outside `recording`.
   *
   * Exercise capture is anchored to a count-in and only listens between Start and
   * the final note. The practice log has no anchor and no end, so it needs a
   * channel that is open whenever the device is.
   */
  private monitorOnHandlers = new Set<MonitorOnHandler>();
  private monitorOffHandlers = new Set<MonitorOffHandler>();

  static isSupported(): boolean {
    return typeof navigator !== 'undefined' && 'requestMIDIAccess' in navigator;
  }

  async connect(): Promise<MidiDeviceInfo[]> {
    if (!MidiInput.isSupported()) {
      throw new Error(
        'This browser has no Web MIDI support. Use Chrome, Edge, or Opera on desktop.',
      );
    }
    this.access = await navigator.requestMIDIAccess({ sysex: false });
    this.access.onstatechange = () => this.emitDevices();
    const devices = this.listDevices();
    if (devices.length > 0 && !this.input) {
      this.select(devices[0].id);
    }
    this.emitDevices();
    return devices;
  }

  listDevices(): MidiDeviceInfo[] {
    if (!this.access) return [];
    const devices: MidiDeviceInfo[] = [];
    this.access.inputs.forEach((input) => {
      devices.push({
        id: input.id,
        name: input.name ?? 'Unnamed MIDI input',
        manufacturer: input.manufacturer ?? '',
      });
    });
    return devices;
  }

  get selectedId(): string | null {
    return this.input?.id ?? null;
  }

  /** Switch inputs. Safe to call before any recording starts. */
  select(id: string): void {
    if (!this.access) throw new Error('Call connect() before select()');
    const available: MIDIInput[] = [];
    this.access.inputs.forEach((input) => available.push(input));
    const next = available.find((input) => input.id === id) ?? null;
    if (!next) throw new Error(`No MIDI input with id ${id}`);

    if (this.input) {
      this.input.onmidimessage = null;
    }
    this.input = next;
    this.input.onmidimessage = (event: MIDIMessageEvent) => this.handleMessage(event);
    this.activeNotes.clear();
  }

  onNote(handler: NoteHandler): () => void {
    this.noteHandlers.add(handler);
    return () => this.noteHandlers.delete(handler);
  }

  onNoteRelease(handler: (pitch: number, durationS: number) => void): () => void {
    this.releaseHandlers.add(handler);
    return () => this.releaseHandlers.delete(handler);
  }

  onSustain(handler: SustainHandler): () => void {
    this.sustainHandlers.add(handler);
    return () => this.sustainHandlers.delete(handler);
  }

  /** Every note-on, whether or not an exercise is being recorded. */
  onNoteOnMonitor(handler: MonitorOnHandler): () => void {
    this.monitorOnHandlers.add(handler);
    return () => this.monitorOnHandlers.delete(handler);
  }

  /** Every note-off, with the duration of the note it completes. */
  onNoteOffMonitor(handler: MonitorOffHandler): () => void {
    this.monitorOffHandlers.add(handler);
    return () => this.monitorOffHandlers.delete(handler);
  }

  onDevices(handler: DevicesHandler): () => void {
    this.devicesHandlers.add(handler);
    return () => this.devicesHandlers.delete(handler);
  }

  /**
   * Start capturing. `anchorMs` is the `performance.now()` value that the
   * exercise's beat 1 corresponds to — everything else is relative to it.
   */
  startRecording(anchorMs: number): void {
    this.anchorMs = anchorMs;
    this.recording = true;
    this.activeNotes.clear();
  }

  stopRecording(): void {
    this.recording = false;
    this.activeNotes.clear();
  }

  get isRecording(): boolean {
    return this.recording;
  }

  /**
   * MIDI timestamps and `performance.now()` share the same time origin in
   * Chromium, but some drivers report 0 or a wildly different clock. Fall back
   * to `performance.now()` when the stamp is not plausible.
   */
  private eventTimeMs(event: MIDIMessageEvent): number {
    const now = performance.now();
    const stamp = event.timeStamp;
    if (typeof stamp === 'number' && stamp > 0 && Math.abs(stamp - now) < 5_000) {
      return stamp;
    }
    return now;
  }

  /**
   * A `performance.now()` instant expressed on the wall clock.
   *
   * Computed per event rather than once at connect time: the two clocks are both
   * monotonic in Chromium, but they are separate, and re-reading the difference
   * costs nothing while removing any drift between them.
   */
  private epochMsFor(nowMs: number): number {
    return Math.round(Date.now() - performance.now() + nowMs);
  }

  private handleMessage(event: MIDIMessageEvent): void {
    const data = event.data;
    if (!data || data.length < 2) return;

    const status = data[0] & 0xf0;
    const channel = data[0] & 0x0f;
    const first = data[1];
    const second = data.length > 2 ? data[2] : 0;

    if (status === 0x90 && second > 0) {
      // Note on
      const nowMs = this.eventTimeMs(event);
      const queue = this.activeNotes.get(first) ?? [];
      queue.push({ onset: nowMs, velocity: second, channel });
      this.activeNotes.set(first, queue);

      this.monitorOnHandlers.forEach((handler) =>
        handler({
          epochMs: this.epochMsFor(nowMs),
          pitch: first,
          velocity: second,
          channel,
        }),
      );

      if (!this.recording) return;
      const onset = (nowMs - this.anchorMs) / 1000;
      const payload: RawMidiEvent = { onset, pitch: first, velocity: second, channel };
      this.noteHandlers.forEach((handler) => handler(payload));
      return;
    }

    if (status === 0x80 || (status === 0x90 && second === 0)) {
      // Note off. Oldest first, so durations survive a re-struck note.
      const queue = this.activeNotes.get(first);
      const state = queue?.shift();
      if (queue && queue.length === 0) this.activeNotes.delete(first);
      if (state) {
        const offMs = this.eventTimeMs(event);
        const durationMs = Math.max(0, offMs - state.onset);
        this.monitorOffHandlers.forEach((handler) =>
          handler({
            epochMs: this.epochMsFor(offMs),
            pitch: first,
            velocity: state.velocity,
            channel: state.channel,
            durationMs: Math.round(durationMs),
          }),
        );
        this.releaseHandlers.forEach((handler) => handler(first, durationMs / 1000));
      }
      return;
    }

    if (status === 0xb0 && first === 64) {
      const down = second >= 64;
      this.sustainHandlers.forEach((handler) => handler(down));
    }
  }

  private emitDevices(): void {
    const devices = this.listDevices();
    this.devicesHandlers.forEach((handler) => handler(devices));
  }
}
