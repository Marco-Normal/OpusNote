/**
 * Shared application state.
 *
 * A single runes-based store keeps the MIDI device, profile, and latency
 * calibration in one place so every view reads the same values.
 */

import { api } from './api';
import { CaptureClient, type CaptureStatus } from './capture';
import { MidiInput, type MidiDeviceInfo } from './midi';
import type { AppView, Profile, Workout } from './types';

const LATENCY_STORAGE_KEY = 'srt.latencyMs';
const BARS_STORAGE_KEY = 'srt.bars';
const FOCUS_STORAGE_KEY = 'srt.focusMode';
const CAPTURE_STORAGE_KEY = 'srt.capture';

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
  selectedDeviceId = $state<string | null>(null);

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
    sent: 0,
    failed: 0,
    lastError: null,
    lastSentAt: null,
  });

  /** The running or most recent workout, for the banner and the streak. */
  workout = $state<Workout | null>(null);
  workoutError = $state<string | null>(null);

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
    } catch (error) {
      this.apiOnline = false;
      this.errorMessage = error instanceof Error ? error.message : String(error);
      return;
    }
    await this.refreshProfile();
    await this.refreshWorkout();
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
  }

  async connectMidi(): Promise<void> {
    this.midiError = null;
    try {
      const devices = await this.midi.connect();
      this.devices = devices;
      this.selectedDeviceId = this.midi.selectedId;
      this.midiConnected = devices.length > 0;
      if (devices.length === 0) {
        this.midiError =
          'No MIDI input found. Connect the PX-870 over USB, make sure it is powered on, then rescan.';
      }
      this.midi.onDevices((next) => {
        this.devices = next;
        if (!this.selectedDeviceId && next.length > 0) {
          this.selectDevice(next[0].id);
        }
      });
      // Capture resumes with the device: the preference outlives the connection,
      // so reconnecting after a replug does not silently stop the log.
      if (this.captureEnabled && devices.length > 0) this.capture.start();
    } catch (error) {
      this.midiConnected = false;
      this.midiError = error instanceof Error ? error.message : String(error);
    }
  }

  selectDevice(id: string): void {
    try {
      this.midi.select(id);
      this.selectedDeviceId = id;
      this.midiConnected = true;
      this.midiError = null;
      if (this.captureEnabled) this.capture.start();
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
