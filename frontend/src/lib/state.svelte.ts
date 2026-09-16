/**
 * Shared application state.
 *
 * A single runes-based store keeps the MIDI device, profile, and latency
 * calibration in one place so every view reads the same values.
 */

import { api } from './api';
import { CaptureClient, type CaptureStatus } from './capture';
import { MidiInput, type MidiDeviceInfo, type MidiOutputInfo } from './midi';
import { fingerprint, type PortSnapshot } from './midiDevice';
import { PianoPlayer, sharedPlayer, unlockOnFirstGesture, type Instrument } from './pianoPlayer';
import type { AppView, HostInfo, PianoStatus, Profile, Workout } from './types';

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
  /**
   * Playing back, through whichever instrument is chosen.
   *
   * A single shared player, wired to the MIDI output here: the choice of instrument
   * belongs to the application rather than to whichever component happens to have a
   * play button, and two players sounding at once was a real bug.
   */
  readonly player = sharedPlayer();

  /** Outputs we could play through — in practice, the piano. */
  outputs = $state<MidiOutputInfo[]>([]);
  /** 'midi' through the piano, 'piano' sampled, 'synth' built in. */
  instrument = $state<Instrument>(PianoPlayer.rememberedInstrument() ?? 'midi');
  /** Whether the one-time sample download has been done, and its licence. */
  piano = $state<PianoStatus | null>(null);
  downloadingPiano = $state(false);
  /** Why the sampled piano is not playing, when it is not. */
  pianoError = $state<string | null>(null);
  /** 'unused' | 'loading' | 'ready' | 'failed' | 'absent' — the *player's* answer. */
  sampleState = $state<'unused' | 'loading' | 'ready' | 'failed' | 'absent'>('unused');
  /**
   * What the browser's audio context is doing.
   *
   * The one fact that was missing when "no sound" had no explanation: a suspended
   * context plays nothing and reports nothing, and it looks exactly like a broken
   * instrument or a muted machine.
   */
  audioState = $state('suspended');
  testingSound = $state(false);
  soundError = $state<string | null>(null);

  /** Play a short chord through the chosen instrument. */
  async testSound(): Promise<void> {
    this.testingSound = true;
    this.soundError = null;
    try {
      await this.player.playTest();
    } catch (cause) {
      this.soundError = cause instanceof Error ? cause.message : String(cause);
    } finally {
      this.testingSound = false;
      this.audioState = this.player.audioState;
    }
  }

  readonly capture = new CaptureClient(
    this.midi,
    () => (this.workout?.running ? 'sight_reading' : 'web_midi'),
    (status) => {
      this.captureStatus = status;
    },
  );

  /**
   * Push the stored instrument into the player.
   *
   * The state is the source of truth, but the player is an ordinary object with its
   * own field — so a remembered choice that is never sent to it leaves playback on
   * the player's default, which is how "through the piano" ended up sending nothing.
   */
  constructor() {
    this.player.setInstrument(this.instrument);
    // The audio context may only be started by a gesture, so it is started by the
    // first one — not by a play handler, which fetches the notes first and by then has
    // no gesture left to spend.
    unlockOnFirstGesture();
    this.player.onSample = (state, error) => {
      this.sampleState = state;
      this.pianoError = error;
    };
    this.player.onAudio = (state) => {
      this.audioState = state;
    };
    void this.refreshPiano();
  }

  async refreshPiano(): Promise<void> {
    try {
      this.piano = await api.audio.pianoStatus();
    } catch {
      this.piano = null;
    }
  }

  /**
   * Fetch the sampled piano once, then serve it from our own host.
   *
   * Synchronous on the server and slow enough to notice, so the interface says it is
   * downloading rather than looking frozen.
   */
  async downloadPiano(): Promise<void> {
    this.downloadingPiano = true;
    try {
      await api.audio.downloadPiano();
      await this.refreshPiano();
      if (this.piano?.available) await this.setInstrument('piano');
    } finally {
      this.downloadingPiano = false;
    }
  }

  async setInstrument(instrument: Instrument): Promise<void> {
    this.instrument = instrument;
    this.player.setInstrument(instrument);
    if (instrument !== 'piano') {
      this.sampleState = 'unused';
      return;
    }
    if (this.piano !== null && !this.piano.available) {
      this.sampleState = 'absent';
      return;
    }
    // Loaded on the choice rather than on the first play, so a set that cannot be
    // decoded says so while the player is looking at the control. The state comes
    // from the player's own answer, never from "the files are there".
    await this.player.loadPiano();
  }

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

  /**
   * A journal entry that the Log tab has asked to write about a sitting.
   *
   * The entry belongs to the piece, so writing about a session means going to the
   * piece's page with the sitting attached — and that is a move between two views,
   * which is why the draft is parked here rather than passed down. RepertoireView
   * consumes it and clears it, so it cannot fire twice.
   */
  journalDraft = $state<{ pieceId: number; sittingId: number; measured: string | null } | null>(
    null,
  );

  /** Ask for a journal entry about a sitting, and go where it can be written. */
  writeAboutSitting(pieceId: number, sittingId: number, measured: string | null): void {
    this.journalDraft = { pieceId, sittingId, measured };
    this.view = 'repertoire';
  }

  /**
   * Tell the server the piano has gone, so it can close the open sitting.
   *
   * Idempotent and safe to call when nothing is open: the server answers with a
   * reason, and the revision bump is what makes an open Log view re-read at once
   * rather than five minutes later.
   */
  async finishSitting(): Promise<void> {
    try {
      // The last notes may still be in the capture buffer — the flush runs every two
      // seconds, and a piano switched off right after a chord beats it. Sending them
      // first is what stops the close from closing a sitting that does not have the
      // final chord in it yet, and the notes from arriving afterwards to open a
      // spurious second sitting.
      await this.capture.flush();
      const result = await api.practice.closeSitting();
      if (result.closed) this.revision += 1;
    } catch {
      // Not worth surfacing: the next note opens a sitting anyway, and a failed
      // close only means the silence has to do the job instead.
    }
  }

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
      this.midi.onOutputs((outputs) => {
        this.outputs = outputs;
      });
      // Playback through the piano is wired once, here: the player is shared and the
      // output can appear or vanish with the device, so the sink asks each time
      // rather than holding a port reference that may be gone.
      this.player.setMidiSink({
        send: (bytes, timestamp) => this.midi.send(bytes, timestamp),
        available: () => this.midiConnected && this.midi.hasOutput,
      });
      this.midi.onDevices((next) => {
        const wasConnected = this.devices.length > 0;
        this.devices = next;
        this.midiConnected = next.length > 0;
        if (next.length > 0) this.midiNeedsGesture = false;
        // The piano going away means they have finished, and it is a far sooner
        // answer than waiting out the silence. The server decides whether it was a
        // real end or a blip; this only reports the event.
        if (wasConnected && next.length === 0) void this.finishSitting();
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
