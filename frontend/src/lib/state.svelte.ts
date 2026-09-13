/**
 * Shared application state.
 *
 * A single runes-based store keeps the MIDI device, profile, and latency
 * calibration in one place so every view reads the same values.
 */

import { api } from './api';
import { CaptureClient, type CaptureStatus } from './capture';
import { MidiInput, type MidiDeviceInfo } from './midi';
import { fingerprint, type PortSnapshot } from './midiDevice';
import type { AppView, HostInfo, Profile, Workout } from './types';

const LATENCY_STORAGE_KEY = 'srt.latencyMs';
const BARS_STORAGE_KEY = 'srt.bars';
const FOCUS_STORAGE_KEY = 'srt.focusMode';
const CAPTURE_STORAGE_KEY = 'srt.capture';
const MIDI_PIN_STORAGE_KEY = 'srt.midi.pin';

/** Exercise lengths offered in the UI. Length is a preference, not difficulty. */
export const BAR_CHOICES = [4, 8, 12, 16] as const;
export type BarChoice = (typeof BAR_CHOICES)[number];

function readBars(): number {
  try {
    const value = Number(localStorage.getItem(BARS_STORAGE_KEY));
    return (BAR_CHOICES as readonly number[]).includes(value) ? value : 4;
  } catch {
    return 4;
  }
}

function readFocus(): boolean {
  try {
    return localStorage.getItem(FOCUS_STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

function readCapture(): boolean {
  try {
    // Default on: the whole point of the log is that it happens without asking.
    return localStorage.getItem(CAPTURE_STORAGE_KEY) !== 'false';
  } catch {
    return true;
  }
}

function readPinnedFingerprint(): string | null {
  try {
    return localStorage.getItem(MIDI_PIN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function readStoredLatency(): number {
  try {
    const raw = localStorage.getItem(LATENCY_STORAGE_KEY);
    const value = raw === null ? 0 : Number(raw);
    return Number.isFinite(value) ? Math.max(0, Math.min(500, value)) : 0;
  } catch {
    return 0;
  }
}

class AppState {
  view = $state<AppView>('practice');

  /** One MIDI input shared by every view; connecting twice would double events. */
  readonly midi = new MidiInput();

  midiSupported = $state(MidiInput.isSupported());
  midiConnected = $state(false);
  midiError = $state<string | null>(null);
  devices = $state<MidiDeviceInfo[]>([]);
  /** Every port, with what has been heard from it: drives the device bar. */
  ports = $state<PortSnapshot[]>([]);
  /** The port in use, and the player's explicit choice if there is one. */
  midiActiveId = $state<string | null>(null);
  /** True when a choice is in force, however it was remembered. */
  midiPinned = $state(false);
  /** True when access was granted without an explicit click. */
  midiAutoConnected = $state(false);
  /** True when the browser refused MIDI until the user asks for it. */
  midiNeedsGesture = $state(false);

  private midiWired = false;
  private reconnectTimer: ReturnType<typeof setInterval> | null = null;

  latencyMs = $state(readStoredLatency());

  /**
   * Exercise length. Kept deliberately separate from `difficulty_elo`: a length
   * preference and a skill rating are different things, and conflating them
   * would make the rating mean two things at once.
   */
  bars = $state(readBars());

  /** Hides everything that is not the score, so the music owns the viewport. */
  focusMode = $state(readFocus());

  /**
   * A key to write the next exercises in, set from the Repertoire tab so you can
   * sight-read around the piece you are working on. Not persisted: it describes a
   * piece, and keeping it after moving on would be a trap.
   */
  pinnedKey = $state<string | null>(null);

  /** The piece the pinned key came from, for display. */
  pinnedKeySource = $state<string | null>(null);

  pinKey(key: string | null, source: string | null = null): void {
    this.pinnedKey = key;
    this.pinnedKeySource = source;
  }

  /**
   * Passive capture of everything played, for the practice log.
   *
   * Deliberately app-level rather than owned by the Log section: MIDI only
   * reaches one page, and the log is supposed to record practice without anyone
   * remembering to open a tab. Capture is therefore on whenever the device is.
   */
  readonly capture = new CaptureClient(
    this.midi,
    () => (this.workout?.running ? 'sight_reading' : 'web_midi'),
    (status) => {
      this.captureStatus = status;
    },
  );

  captureEnabled = $state(readCapture());
  captureStatus = $state<CaptureStatus>({
    enabled: false,
    buffered: 0,
    pedals: 0,
    sent: 0,
    failed: 0,
    lastError: null,
    lastSentAt: null,
  });

  /** The running or most recent workout, for the banner and the streak. */
  workout = $state<Workout | null>(null);
  workoutError = $state<string | null>(null);

  /** What the server can tell us about this machine and this request. */
  host = $state<HostInfo | null>(null);
  /**
   * A latency this machine's own timing history suggests, in ms, or null.
   *
   * Suggested, never applied: see DeviceBar.
   */
  latencySuggestionMs = $state<number | null>(null);

  profile = $state<Profile | null>(null);
  apiOnline = $state<boolean | null>(null);
  errorMessage = $state<string | null>(null);

  /** Bumped whenever a performance is recorded, so Stats can refetch. */
  revision = $state(0);

  setLatency(value: number): void {
    const clamped = Math.max(0, Math.min(500, Math.round(value)));
    this.latencyMs = clamped;
    try {
      localStorage.setItem(LATENCY_STORAGE_KEY, String(clamped));
    } catch {
      // Storage may be unavailable (private mode); the in-memory value still works.
    }
  }

  setBars(value: number): void {
    if (!(BAR_CHOICES as readonly number[]).includes(value)) return;
    this.bars = value;
    try {
      localStorage.setItem(BARS_STORAGE_KEY, String(value));
    } catch {
      // Storage may be unavailable (private mode); the in-memory value still works.
    }
  }

  toggleFocus(): void {
    this.focusMode = !this.focusMode;
    try {
      localStorage.setItem(FOCUS_STORAGE_KEY, String(this.focusMode));
    } catch {
      // As above.
    }
  }

  async bootstrap(): Promise<void> {
    try {
      await api.health();
      this.apiOnline = true;
      this.errorMessage = null;
      try {
        this.host = await api.host();
      } catch {
        // Only used to explain the deployment; never block the app on it.
      }
      try {
        const status = await api.systemStatus();
        this.latencySuggestionMs = status.latency_suggestion_ms;
      } catch {
        // Health reporting is a nicety; the app works without it.
      }
    } catch (error) {
      this.apiOnline = false;
      this.errorMessage = error instanceof Error ? error.message : String(error);
      return;
    }
    await this.refreshProfile();
    await this.refreshWorkout();
  }

  /** Called once by the app shell, after `bootstrap()`. */
  async startMidi(): Promise<void> {
    await this.autoConnectMidi();
    if (this.captureEnabled) this.startCaptureHeartbeat();
  }

  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;

  /**
   * Tell the server that capture is running.
   *
   * Without this, a notebook whose browser died is indistinguishable from a quiet
   * evening, and the person reading the statistics from another room cannot tell the
   * difference. The heartbeat carries only liveness; the last note is read from the
   * database by the server.
   */
  private startCaptureHeartbeat(): void {
    if (this.heartbeatTimer !== null) return;
    const send = () => {
      void api.practice
        .reportCapture({
          origin: location.host,
          enabled: this.captureStatus.enabled,
          pending: this.captureStatus.buffered,
        })
        .catch(() => {
          // A failed heartbeat is a symptom, not a cause: the capture bar already
          // shows the API being unreachable.
        });
    };
    send();
    this.heartbeatTimer = setInterval(send, 15_000);
  }

  async refreshProfile(): Promise<void> {
    try {
      this.profile = await api.profile();
    } catch (error) {
      this.errorMessage = error instanceof Error ? error.message : String(error);
    }
  }

  setCapture(enabled: boolean): void {
    this.captureEnabled = enabled;
    try {
      localStorage.setItem(CAPTURE_STORAGE_KEY, String(enabled));
    } catch {
      // Storage may be unavailable (private mode); the in-memory value still works.
    }
    if (enabled && this.midiConnected) this.capture.start();
    else this.capture.stop();
    if (enabled) this.startCaptureHeartbeat();
  }

  /**
   * Ask for MIDI access and attach to whatever is there.
   *
   * `quiet` is for the automatic attempts: a refusal there is not an error worth
   * showing, because the browser may simply require a gesture, and the Connect
   * button is the honest fallback.
   */
  async connectMidi(options: { quiet?: boolean } = {}): Promise<void> {
    if (!this.midiWired) {
      this.midiWired = true;
      this.midi.onPorts((ports) => {
        this.ports = ports;
        this.midiActiveId = this.midi.activeId;
        this.midiPinned = this.midi.hasPin;
      });
      this.midi.onDevices((next) => {
        this.devices = next;
        this.midiConnected = next.length > 0;
        if (next.length > 0) this.midiNeedsGesture = false;
      });
    }
    if (!options.quiet) this.midiError = null;
    try {
      const devices = await this.midi.connect();
      this.devices = devices;
      this.midiConnected = devices.length > 0;
      this.midiNeedsGesture = false;
      this.midiActiveId = this.midi.activeId;
      this.midiPinned = this.midi.hasPin;
      if (devices.length === 0 && !options.quiet) {
        this.midiError =
          'No MIDI input found. Connect the PX-870 over USB, make sure it is powered on, then rescan.';
      }
      // Capture is app-level and follows the device: reconnecting after a replug
      // must not silently stop the log.
      if (this.captureEnabled && devices.length > 0) {
        this.capture.start();
        this.startCaptureHeartbeat();
      }
    } catch (error) {
      this.midiConnected = false;
      if (options.quiet) {
        // A refusal without a gesture is not worth shouting about; it only means
        // the Connect button is needed once.
        this.midiNeedsGesture = true;
      } else {
        this.midiError = error instanceof Error ? error.message : String(error);
      }
    }
  }

  /**
   * Try to connect with no interaction, then keep trying.
   *
   * On the notebook a managed policy has already granted the MIDI permission, so
   * this succeeds silently on load. Everywhere else the browser may want a
   * gesture; a bare refusal only arms the Connect button.
   */
  async autoConnectMidi(): Promise<void> {
    if (!this.midiSupported || this.midiConnected) return;
    this.midi.restorePin(readPinnedFingerprint());
    await this.connectMidi({ quiet: true });
    this.midiAutoConnected = this.midiConnected;
    this.startReconnectLoop();
  }

  /**
   * A piano switched on ten minutes after the machine is already running is the
   * normal case, so poll while nothing is attached.
   *
   * `statechange` covers plugging and unplugging; this covers the browser not
   * delivering it, and the piano having been off when the page loaded.
   */
  private startReconnectLoop(): void {
    if (this.reconnectTimer !== null) return;
    const attempt = () => {
      if (this.midiConnected || !this.midiSupported) {
        if (this.reconnectTimer !== null) clearInterval(this.reconnectTimer);
        this.reconnectTimer = null;
        return;
      }
      void this.connectMidi({ quiet: true });
    };
    this.reconnectTimer = setInterval(attempt, 5_000);
    // A laptop that was asleep is the other way devices go missing.
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') attempt();
    });
  }

  /** Use only this device, or null to go back to automatic selection. */
  pinDevice(id: string | null): void {
    try {
      this.midi.pin(id);
      this.midiPinned = this.midi.hasPin;
      this.midiActiveId = this.midi.activeId;
      const active = this.ports.find((port) => port.id === id);
      if (active) {
        // Stored as a fingerprint so the choice survives the id changing, which is
        // exactly what happens when site data is cleared during a setup.
        localStorage.setItem(MIDI_PIN_STORAGE_KEY, fingerprint(active));
      } else {
        localStorage.removeItem(MIDI_PIN_STORAGE_KEY);
      }
    } catch (error) {
      this.midiError = error instanceof Error ? error.message : String(error);
    }
  }

  async refreshWorkout(): Promise<void> {
    try {
      this.workout = await api.workout.current();
      this.workoutError = null;
    } catch (error) {
      this.workoutError = error instanceof Error ? error.message : String(error);
    }
  }

  async startWorkout(): Promise<void> {
    this.workoutError = null;
    try {
      this.workout = await api.workout.start();
    } catch (error) {
      this.workoutError = error instanceof Error ? error.message : String(error);
    }
  }

  async finishWorkout(): Promise<void> {
    if (!this.workout) return;
    this.workoutError = null;
    try {
      // Send whatever is still buffered first: finishing a workout closes a
      // window, and notes played seconds before pressing Finish belong to it.
      await this.capture.flush();
      this.workout = await api.workout.finish(this.workout.id);
      this.revision += 1;
    } catch (error) {
      this.workoutError = error instanceof Error ? error.message : String(error);
    }
  }
}

export const app = new AppState();
