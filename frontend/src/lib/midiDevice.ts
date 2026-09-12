/**
 * Device selection and note de-duplication.
 *
 * Pure on purpose: this is the part that decides *which* port's bytes count, which
 * a device list containing ALSA's dead `Midi Through Port-0` makes ambiguous, and
 * it must be testable without a browser. `midi.ts` imports this; nothing here
 * touches the DOM, `navigator`, or a clock.
 */

export interface DevicePort {
  id: string;
  name: string;
  manufacturer: string;
}

/** A port plus what has been heard from it, for the device list. */
export interface PortSnapshot extends DevicePort {
  /** Epoch ms of the last note this port carried, or null. */
  lastNoteMs: number | null;
  notes: number;
  inUse: boolean;
  pinned: boolean;
}

/**
 * A stable identity for a device, for remembering a choice across reloads.
 *
 * Chromium's `input.id` is a per-origin salted hash: stable until site data is
 * cleared, which is exactly what happens while setting up a new machine. This is
 * the fallback, so a remembered choice survives that.
 *
 * Comparing *token sets* rather than strings is what makes it work across drivers:
 * one keyboard is `CASIO USB-MIDI MIDI 1` on Linux and `MIDIIN2 (CASIO USB-MIDI)`
 * on Windows, and every difference between those is noise — the port number, the
 * `MIDIIN2` prefix, the repeated `midi`. Order is ignored for the same reason: a
 * driver is free to put the manufacturer first or last.
 */
export function fingerprint(port: DevicePort): string {
  const tokens = (value: string): string[] =>
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ' ')
      .split(' ')
      .filter(Boolean)
      // A bare port number ("MIDI 1", "Port-0") identifies a socket, not a device.
      .filter((token) => !/^\d+$/.test(token))
      // Windows names the second port of one keyboard "MIDIIN2 (…)".
      .filter((token) => !/^midi(in|out)\d*$/.test(token))
      .filter((token) => token !== 'midi' && token !== 'port');

  const parts = new Set([...tokens(port.manufacturer), ...tokens(port.name)]);
  return [...parts].sort().join(' ');
}

/**
 * A port that exists but carries nothing.
 *
 * ALSA always exposes `Midi Through Port-0`, which is a real input as far as Web
 * MIDI is concerned and never sends a byte. It is worth naming in the interface
 * rather than hiding, because "why are there two devices and only one works" is a
 * question a player will otherwise have to answer by experiment.
 */
export function looksSilent(port: DevicePort): boolean {
  return /midi\s*through/i.test(`${port.manufacturer} ${port.name}`);
}

/**
 * Cross-port echo suppression.
 *
 * A note arriving from a *different* port within the window is the same physical
 * key reported twice, so it is dropped. A repeat on the *same* port is always
 * accepted: no human repeats a pitch within 30 ms, and dropping one would be
 * losing a real note.
 */
export class NoteGate {
  private readonly windowMs: number;
  private readonly recent = new Map<string, { portId: string; atMs: number }>();

  constructor(windowMs = 30) {
    this.windowMs = windowMs;
  }

  accept(pitch: number, velocity: number, portId: string, atMs: number): boolean {
    const key = `${pitch}:${velocity}`;
    const previous = this.recent.get(key);
    this.prune(atMs);
    if (previous && previous.portId !== portId && atMs - previous.atMs <= this.windowMs) {
      return false;
    }
    this.recent.set(key, { portId, atMs });
    return true;
  }

  private prune(nowMs: number): void {
    // The map is keyed by pitch and velocity, so it is bounded by 128 * 128; the
    // prune is about keeping it small in practice, not about preventing growth.
    for (const [key, seen] of this.recent) {
      if (nowMs - seen.atMs > 1_000) this.recent.delete(key);
    }
  }
}

/** Per-port evidence of life. Times are epoch ms, so the display needs no clock. */
export class PortActivity {
  private readonly lastMs = new Map<string, number>();
  private readonly noteCount = new Map<string, number>();

  note(portId: string, atMs: number): void {
    this.lastMs.set(portId, atMs);
    this.noteCount.set(portId, (this.noteCount.get(portId) ?? 0) + 1);
  }

  lastNoteMs(portId: string): number | null {
    return this.lastMs.get(portId) ?? null;
  }

  notes(portId: string): number {
    return this.noteCount.get(portId) ?? 0;
  }

  /** The port that most recently carried a note, or null if none has. */
  loudest(portIds: string[]): string | null {
    let best: string | null = null;
    let bestAt = -Infinity;
    for (const id of portIds) {
      const at = this.lastMs.get(id);
      if (at !== undefined && at > bestAt) {
        best = id;
        bestAt = at;
      }
    }
    return best;
  }

  forget(portId: string): void {
    this.lastMs.delete(portId);
    this.noteCount.delete(portId);
  }
}

/**
 * Which port to use.
 *
 * The order is the whole point. An explicit pin in this session wins, then a
 * remembered device, then the port that has actually carried notes — and only then
 * the first port that exists, which used to be the *only* rule and is why a dead
 * ALSA port could be selected.
 */
export function chooseActive(
  ports: DevicePort[],
  options: {
    pinnedId?: string | null;
    pinnedFingerprint?: string | null;
    activity?: PortActivity;
  } = {},
): string | null {
  if (ports.length === 0) return null;
  const ids = ports.map((port) => port.id);
  if (options.pinnedId && ids.includes(options.pinnedId)) return options.pinnedId;
  if (options.pinnedFingerprint) {
    const remembered = ports.find((port) => fingerprint(port) === options.pinnedFingerprint);
    if (remembered) return remembered.id;
  }
  const loud = options.activity?.loudest(ids) ?? null;
  return loud ?? ids[0];
}
