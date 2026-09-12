/**
 * Web MIDI input for the Casio PX-870 (or any class-compliant MIDI keyboard).
 *
 * The PX-870 appears as a plain MIDI input over USB Type-B: note on/off,
 * velocity, and sustain on CC64. Nothing vendor-specific is needed.
 *
 * Web MIDI requires a secure context. `localhost` counts as secure, so the dev
 * server is fine; a deployment must use HTTPS.
 */

import {
  NoteGate,
  PortActivity,
  chooseActive,
  fingerprint,
  type DevicePort,
  type PortSnapshot,
} from './midiDevice';

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
type PortsHandler = (ports: PortSnapshot[]) => void;

interface NoteState {
  onset: number;
  velocity: number;
  channel: number;
}

export class MidiInput {
  private access: MIDIAccess | null = null;
  /**
   * Every input we are attached to.
   *
   * Every input, not one: ALSA exposes a virtual `Midi Through Port-0` that never
   * carries a note, and some keyboards expose more than one port that does.
   * Picking one by position is a coin toss.
   */
  private readonly inputs = new Map<string, MIDIInput>();
  /** Cross-port echo suppression. */
  private readonly gate = new NoteGate();
  /** Which port has actually carried notes. */
  private readonly activity = new PortActivity();
  /** A remembered choice: this session's pin, and the durable fingerprint. */
  private pinnedId: string | null = null;
  private pinnedFingerprint: string | null = null;
  private lastPortsEmitMs = 0;
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
  private portsHandlers = new Set<PortsHandler>();

  static isSupported(): boolean {
    return typeof navigator !== 'undefined' && 'requestMIDIAccess' in navigator;
  }

  async connect(): Promise<MidiDeviceInfo[]> {
    if (!MidiInput.isSupported()) {
      throw new Error(
        'This browser has no Web MIDI support. Use Chrome, Edge, or Opera on desktop.',
      );
    }
    if (this.access) {
      // Already granted: a rescan is just re-reading the device list, and asking
      // again risks a second prompt on a machine nobody is sitting at.
      this.attachAll();
      return this.listDevices();
    }
    this.access = await navigator.requestMIDIAccess({ sysex: false });
    // `statechange` fires when the piano is switched on or unplugged. For a
    // machine left running that is the whole point: no reload, no click.
    this.access.onstatechange = () => this.attachAll();
    this.attachAll();
    return this.listDevices();
  }

  /**
   * Attach to every input present, and detach from any that have gone.
   *
   * Safe to call repeatedly: an input already attached is left alone, so a
   * `statechange` that adds one device does not disturb the others.
   */
  private attachAll(): void {
    const present = new Set<string>();
    this.access?.inputs.forEach((input) => {
      present.add(input.id);
      if (this.inputs.get(input.id) === input) return;
      const portId = input.id;
      input.onmidimessage = (event: MIDIMessageEvent) => this.handleMessage(portId, event);
      this.inputs.set(portId, input);
    });

    for (const [portId, input] of [...this.inputs]) {
      if (present.has(portId)) continue;
      input.onmidimessage = null;
      this.inputs.delete(portId);
      this.activity.forget(portId);
    }
    this.emitPorts(true);
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

  /** The port in use: the pin, else the one that has carried notes. */
  get activeId(): string | null {
    return chooseActive(this.ports(), {
      pinnedId: this.pinnedId,
      pinnedFingerprint: this.pinnedFingerprint,
      activity: this.activity,
    });
  }

  /** Read-only alias, for callers that only need "which device is in use". */
  get selectedId(): string | null {
    return this.activeId;
  }

  get pinnedDeviceId(): string | null {
    return this.pinnedId;
  }

  /**
   * Whether a choice is being honoured.
   *
   * True for a pin made in this session *and* for one restored from storage, which
   * arrives as a fingerprint only. The interface has to say "Pinned" in both cases:
   * a remembered device that is silently obeyed while the label reads "Auto" is a
   * small lie that makes the pin look broken.
   */
  get hasPin(): boolean {
    return this.pinnedId !== null || this.pinnedFingerprint !== null;
  }

  /**
   * Use only this device, or `null` to go back to automatic.
   *
   * Both the id and the fingerprint are remembered: the id is exact for this
   * browser profile, the fingerprint survives the id being invalidated by cleared
   * site data.
   */
  pin(id: string | null): void {
    if (id === null) {
      this.pinnedId = null;
      this.pinnedFingerprint = null;
      this.emitPorts(true);
      return;
    }
    const input = this.inputs.get(id);
    if (!input) throw new Error(`No MIDI input with id ${id}`);
    this.pinnedId = id;
    this.pinnedFingerprint = fingerprint(toDevicePort(input));
    this.emitPorts(true);
  }

  /** Remember a device before it has appeared, e.g. from localStorage on load. */
  restorePin(rememberedFingerprint: string | null): void {
    this.pinnedFingerprint = rememberedFingerprint;
  }

  private ports(): DevicePort[] {
    return [...this.inputs.values()].map(toDevicePort);
  }

  private emitPorts(force = false): void {
    // A fast passage fires this once per note; the display cannot show more than a
    // few updates a second, so they are throttled unless something structural
    // changed (attach, detach, pin).
    const nowMs = performance.now();
    if (!force && nowMs - this.lastPortsEmitMs < 200) return;
    this.lastPortsEmitMs = nowMs;
    const active = this.activeId;
    const snapshot: PortSnapshot[] = this.ports().map((port) => ({
      ...port,
      lastNoteMs: this.activity.lastNoteMs(port.id),
      notes: this.activity.notes(port.id),
      inUse: port.id === active,
      pinned: this.hasPin && port.id === active,
    }));
    this.portsHandlers.forEach((handler) => handler(snapshot));
    this.emitDevices();
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

  /** Every port, with what has been heard from it. */
  onPorts(handler: PortsHandler): () => void {
    this.portsHandlers.add(handler);
    return () => this.portsHandlers.delete(handler);
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

  private handleMessage(portId: string, event: MIDIMessageEvent): void {
    const data = event.data;
    if (!data || data.length < 2) return;
    // A pin is an explicit instruction: the other ports are ignored entirely.
    if (this.pinnedId !== null && portId !== this.pinnedId) return;

    const status = data[0] & 0xf0;
    const channel = data[0] & 0x0f;
    const first = data[1];
    const second = data.length > 2 ? data[2] : 0;

    if (status === 0x90 && second > 0) {
      // Note on
      const nowMs = this.eventTimeMs(event);
      // The same key from a different port inside the window is one physical key
      // reported twice. Dropping it here protects both consumers: the exercise
      // scorer, which would count it as an extra note, and the practice log,
      // which would store it twice.
      if (!this.gate.accept(first, second, portId, nowMs)) return;
      this.activity.note(portId, Date.now());
      this.emitPorts();
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

function toDevicePort(input: MIDIInput): DevicePort {
  return {
    id: input.id,
    name: input.name ?? 'Unnamed MIDI input',
    manufacturer: input.manufacturer ?? '',
  };
}
