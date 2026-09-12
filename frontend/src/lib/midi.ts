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

type NoteHandler = (event: RawMidiEvent) => void;
type SustainHandler = (down: boolean) => void;
type DevicesHandler = (devices: MidiDeviceInfo[]) => void;

interface NoteState {
  onset: number;
  velocity: number;
  channel: number;
}

export class MidiInput {
  private access: MIDIAccess | null = null;
  private input: MIDIInput | null = null;
  private readonly activeNotes = new Map<number, NoteState>();

  /** Anchor in `performance.now()` milliseconds; onsets are measured from it. */
  private anchorMs = 0;
  private recording = false;

  private noteHandlers = new Set<NoteHandler>();
  private sustainHandlers = new Set<SustainHandler>();
  private devicesHandlers = new Set<DevicesHandler>();
  private releaseHandlers = new Set<(pitch: number, durationS: number) => void>();

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
      this.activeNotes.set(first, { onset: nowMs, velocity: second, channel });
      if (!this.recording) return;
      const onset = (nowMs - this.anchorMs) / 1000;
      const payload: RawMidiEvent = { onset, pitch: first, velocity: second, channel };
      this.noteHandlers.forEach((handler) => handler(payload));
      return;
    }

    if (status === 0x80 || (status === 0x90 && second === 0)) {
      // Note off
      const state = this.activeNotes.get(first);
      this.activeNotes.delete(first);
      if (state) {
        const durationS = (this.eventTimeMs(event) - state.onset) / 1000;
        this.releaseHandlers.forEach((handler) => handler(first, Math.max(0, durationS)));
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
