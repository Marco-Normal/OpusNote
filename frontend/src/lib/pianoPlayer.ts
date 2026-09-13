/**
 * Making sound: the piano, a sampled piano, or a synthesiser.
 *
 * Three instruments, because they answer three different situations:
 *
 * - **`midi`** sends the notes to the *piano itself*, through a Web MIDI output.
 *   This is the only one that is actually a piano, and it is the default wherever a
 *   piano is connected — which on the piano machine is always.
 * - **`piano`** is the Salamander Grand Piano, downloaded once and served by our own
 *   backend. Real samples, works on a viewer with no piano attached.
 * - **`synth`** is built from Tone's oscillators and always available, including
 *   before the one-time download. It is an FM approximation, not a piano, and the
 *   interface says so rather than pretending.
 *
 * **One player for the whole app.** Every component used to construct its own, so
 * two of them (a results panel and a history row, say) could sound at once and
 * neither Stop button knew about the other. `sharedPlayer()` is the only instance;
 * starting anything stops whatever was playing.
 *
 * **Stop has to stop.** `triggerAttackRelease` schedules notes on the audio clock,
 * and releasing the voices does nothing about a note scheduled for four seconds'
 * time — which is exactly the bug where Stop appeared to be ignored. Playback is
 * scheduled as a `Tone.Part` and cancelled on stop; MIDI output is handed out in a
 * short rolling window, so at most a few hundred milliseconds of notes can be in
 * flight, and a second all-notes-off is sent after that window has passed.
 */

import * as Tone from 'tone';

import { fromTime, type SynthNote } from './playback';
import { sampleUrls } from './pianoSamples';

export type Instrument = 'midi' | 'piano' | 'synth';

export interface PlaybackHandle {
  /** Seconds from the start of the *source* material, offset included. */
  elapsed: number;
  /** Length of the whole source material, in seconds. */
  total: number;
}

export interface PlayOptions {
  /** Where in the source material to begin, in seconds. */
  from?: number;
  /** Stop when the source timeline reaches this, in seconds. */
  until?: number;
  onProgress?: (handle: PlaybackHandle) => void;
  onDone?: () => void;
  /** Something that stopped the sound happening, in words worth showing. */
  onError?: (message: string) => void;
}

/** What the player needs from a MIDI output, so it can be faked in a test. */
export interface MidiSink {
  send(bytes: number[], timestamp?: number): void;
  available(): boolean;
}

const LEAD_IN_S = 0.12;

/** How far ahead MIDI notes are queued, and how often the queue is refilled. */
const MIDI_WINDOW_MS = 400;
const MIDI_PUMP_MS = 150;

/** Sent after the scheduling window has drained, to catch anything already handed
 * to the MIDI stack: a queued note-on cannot be recalled, only followed by silence. */
const MIDI_FLUSH_MS = MIDI_WINDOW_MS + 150;

const PREFERENCE_KEY = 'srt.instrument';

export class PianoPlayer {
  private synth: Tone.PolySynth<Tone.FMSynth> | null = null;
  private piano: Tone.Sampler | null = null;
  private part: Tone.Part<{ time: number; note: SynthNote }> | null = null;
  private frame: number | null = null;
  private startedAt = 0;
  private offset = 0;
  private total = 0;
  private end = Infinity;
  private playing = false;

  private sink: MidiSink | null = null;
  /** True while playback is going out over MIDI, so a stop knows to silence it. */
  private midiActive = false;
  private queue: SynthNote[] = [];
  private queueIndex = 0;
  private pump: ReturnType<typeof setInterval> | null = null;
  private flush: ReturnType<typeof setTimeout> | null = null;

  private instrument: Instrument = 'synth';
  private pianoReady = false;
  /** Why the sampled piano is not available, or null. Shown, not swallowed. */
  sampleError: string | null = null;
  /**
   * Told when the sample set changes state, so the interface can mirror it.
   *
   * The player owns this because the player is what loads: a caller inferring
   * "ready" from "the files are on disk" is what let a sample set that Tone could
   * not decode look installed right up until it failed.
   */
  onSample: ((state: 'loading' | 'ready' | 'failed', error: string | null) => void) | null = null;
  /** Told what the audio context is doing, which is otherwise invisible. */
  onAudio: ((state: string) => void) | null = null;
  /**
   * Pitch to the moment its note-off is due, in `performance.now()` terms.
   *
   * Kept so a stop can turn off exactly what is still sounding. A timer per note
   * would be the obvious alternative and would mean thousands of pending timers for
   * a long sitting, most of them for notes that stopped hours ago.
   */
  private readonly sounding = new Map<number, number>();

  get isPlaying(): boolean {
    return this.playing;
  }

  /** Where playback has reached, in source seconds. */
  get position(): number {
    if (!this.playing) return this.offset;
    return Math.min(this.total, this.offset + (performance.now() - this.startedAt) / 1000);
  }

  get current(): Instrument {
    return this.instrument;
  }

  setInstrument(instrument: Instrument): void {
    this.instrument = instrument;
    try {
      localStorage.setItem(PREFERENCE_KEY, instrument);
    } catch {
      // A browser with storage disabled is not a reason to stop playing.
    }
  }

  /** The remembered choice, or null when the player has never chosen. */
  static rememberedInstrument(): Instrument | null {
    try {
      const stored = localStorage.getItem(PREFERENCE_KEY);
      return stored === 'midi' || stored === 'piano' || stored === 'synth' ? stored : null;
    } catch {
      return null;
    }
  }

  /** Where MIDI playback goes. Null means there is no piano to play. */
  setMidiSink(sink: MidiSink | null): void {
    this.sink = sink;
  }

  /**
   * Start the browser's audio, which only a gesture is allowed to do.
   *
   * Called from the click *before* anything is awaited, and again before every
   * Tone-based playback. The second call is free when the context is already
   * running; the first is what makes it running at all, because by the time a play
   * handler has fetched the notes the gesture that started it is over.
   */
  async unlock(): Promise<boolean> {
    try {
      await Tone.start();
      const state = Tone.getContext().state;
      this.onAudio?.(state);
      return state === 'running';
    } catch {
      this.onAudio?.('unavailable');
      return false;
    }
  }

  /** What the browser's audio context is doing: 'running', 'suspended', … */
  get audioState(): string {
    try {
      return Tone.getContext().state;
    } catch {
      return 'unavailable';
    }
  }

  /** A short chord through the chosen instrument, to answer "is this working?". */
  async playTest(): Promise<void> {
    const notes: SynthNote[] = [60, 64, 67].map((pitch, index) => ({
      pitch,
      onset: index * 0.09,
      duration: 0.9,
      velocity: 0.75,
      hand: null,
    }));
    await this.play(notes);
  }

  /**
   * Load the sampled piano, if it is installed.
   *
   * The note names come from the backend that serves the samples, so there is one
   * list of them rather than a copy here that drifts from the one on disk.
   */
  async loadPiano(baseUrl = '/piano/'): Promise<boolean> {
    if (this.pianoReady) {
      this.onSample?.('ready', null);
      return true;
    }
    this.onSample?.('loading', null);
    try {
      const response = await fetch('/api/audio/piano');
      if (!response.ok) throw new Error(`status ${response.status}`);
      const status = (await response.json()) as { available: boolean; notes?: string[] };
      if (!status.available) throw new Error('the samples are not installed');
      const urls = sampleUrls(status.notes ?? []);
      if (Object.keys(urls).length === 0) throw new Error('no samples listed');
      const sampler = new Tone.Sampler({ urls, baseUrl, release: 1.2 }).toDestination();
      sampler.volume.value = -6;
      await Tone.loaded();
      this.piano = sampler;
      this.pianoReady = true;
      this.sampleError = null;
      this.onSample?.('ready', null);
      return true;
    } catch (cause) {
      // A missing or half-installed sample set must not take playback down — the
      // synthesiser is still there, and the interface offers the download. But the
      // reason is kept: silently falling back made "the sampled piano does not work"
      // look identical to "you chose the synthesiser", which cost a round trip.
      this.piano = null;
      this.pianoReady = false;
      this.sampleError = cause instanceof Error ? cause.message : String(cause);
      this.onSample?.('failed', this.sampleError);
      return false;
    }
  }

  async play(notes: readonly SynthNote[], options: PlayOptions = {}): Promise<void> {
    this.stop();
    const offset = Math.max(0, options.from ?? 0);
    const total = notes.reduce((end, note) => Math.max(end, note.onset + note.duration), 0);
    const end = Math.min(options.until ?? Infinity, total);
    const material = fromTime(notes, offset).filter((note) => note.onset + offset < end);

    this.offset = offset;
    this.total = total;
    this.end = end;
    if (material.length === 0) {
      options.onProgress?.({ elapsed: total, total });
      options.onDone?.();
      return;
    }

    if (this.instrument === 'midi' && this.sink?.available()) {
      this.playMidi(material, options);
      return;
    }

    // Everything below plays through the browser's audio, so the context has to be
    // running first — and it was not: the sampled-piano branch returned before this
    // point, so choosing the samples meant playing through a suspended context and
    // hearing nothing at all, with no error anywhere.
    const running = await this.unlock();
    if (!running) {
      this.playing = false;
      options.onError?.(
        'the browser would not start audio. Click once anywhere in the page and try again.',
      );
      options.onDone?.();
      return;
    }

    if (this.instrument === 'piano') {
      const ready = this.pianoReady || (await this.loadPiano());
      if (ready) {
        this.playThrough(this.piano as Tone.Sampler, material, options);
        return;
      }
      // The samples were not installed after all: fall through to the synth rather
      // than leaving the button doing nothing.
    }

    this.playThrough(this.synthVoice(), material, options);
  }

  stop(): void {
    if (this.frame !== null) {
      cancelAnimationFrame(this.frame);
      this.frame = null;
    }
    if (this.pump !== null) {
      clearInterval(this.pump);
      this.pump = null;
    }
    if (this.flush !== null) {
      clearTimeout(this.flush);
      this.flush = null;
    }
    // Cancelling the part is what actually stops: `releaseAll` only releases voices
    // that are sounding *now*, while a `Tone.Part` holds every note scheduled for
    // later — which is why Stop used to look broken.
    if (this.part) {
      this.part.stop();
      this.part.cancel();
      this.part.dispose();
      this.part = null;
    }
    this.synth?.releaseAll();
    this.piano?.releaseAll();
    this.queue = [];
    this.queueIndex = 0;
    this.silenceMidi();
    this.playing = false;
  }

  /** Release the audio resources entirely, for a page being torn down. */
  dispose(): void {
    this.stop();
    this.synth?.dispose();
    this.synth = null;
    this.piano?.dispose();
    this.piano = null;
    this.pianoReady = false;
  }

  // ------------------------------------------------------------------
  // Scheduling
  // ------------------------------------------------------------------

  private playThrough(
    instrument: Tone.Sampler | Tone.PolySynth<Tone.FMSynth>,
    material: SynthNote[],
    options: PlayOptions,
  ): void {
    const start = Tone.now() + LEAD_IN_S;
    this.part = new Tone.Part((time, value) => {
      const note = value.note;
      instrument.triggerAttackRelease(
        Tone.Frequency(note.pitch, 'midi').toFrequency(),
        Math.max(0.05, note.duration),
        time,
        note.velocity,
      );
    }, material.map((note) => ({ time: note.onset, note })));
    this.part.start(start);

    this.startedAt = performance.now();
    this.playing = true;
    this.report(options, 0);
    this.tick(options);
  }

  private playMidi(material: SynthNote[], options: PlayOptions): void {
    this.queue = material;
    this.queueIndex = 0;
    this.midiActive = true;
    this.startedAt = performance.now();
    this.playing = true;

    // A rolling window rather than one note per timer: `send` takes a timestamp, so
    // the MIDI stack schedules accurately, and only a fraction of a second of notes
    // is ever in flight — which is also what makes Stop able to cut it off.
    this.pumpQueue();
    this.pump = setInterval(() => this.pumpQueue(), MIDI_PUMP_MS);
    this.report(options, 0);
    this.tick(options);
  }

  private pumpQueue(): void {
    if (!this.sink) return;
    this.pruneSounding();
    const horizonMs = performance.now() - this.startedAt + MIDI_WINDOW_MS;
    while (this.queueIndex < this.queue.length) {
      const note = this.queue[this.queueIndex];
      if (note.onset * 1000 > horizonMs) break;
      this.queueIndex += 1;
      this.sendMidi(note);
    }
  }

  private sendMidi(note: SynthNote): void {
    const sink = this.sink;
    if (!sink) return;
    const channel = 0;
    const on = this.startedAt + note.onset * 1000;
    const off = on + Math.max(50, note.duration * 1000);
    const velocity = Math.max(1, Math.min(127, Math.round(note.velocity * 127)));
    sink.send([0x90 | channel, note.pitch, velocity], on);
    sink.send([0x80 | channel, note.pitch, 0], off);
    this.sounding.set(note.pitch, off);
  }

  /** Forget the notes whose release has already gone by. */
  private pruneSounding(): void {
    const now = performance.now();
    for (const [pitch, off] of [...this.sounding]) {
      if (off <= now) this.sounding.delete(pitch);
    }
  }

  /**
   * Leave the instrument silent.
   *
   * Notes are turned off explicitly rather than relying on all-notes-off alone: a
   * controller message is only as good as the instrument's handling of it, and a
   * note left hanging on a real piano is the worst outcome this class can produce.
   * The trailing all-notes-off catches anything the *next* window had already
   * queued, which is a note-on that cannot be recalled from the MIDI stack.
   */
  private silenceMidi(): void {
    const sink = this.sink;
    if (!sink || !this.midiActive) return;
    this.midiActive = false;

    // Explicit note-offs for what is still sounding, because a controller message is
    // only as good as the instrument's handling of it — and a note left hanging on a
    // real piano is the worst thing this class can do.
    for (const pitch of this.sounding.keys()) {
      sink.send([0x80, pitch, 0]);
    }
    this.sounding.clear();

    // The sweep runs *unconditionally*, including when nothing is sounding: notes
    // were handed to the MIDI stack with timestamps up to a window ahead, and those
    // have not happened yet. Returning early when the map was empty — which is the
    // normal case, because a short note has already finished by the time anyone
    // reaches for Stop — is what left queued notes still to play.
    const sweep = () => {
      for (let channel = 0; channel < 16; channel += 1) {
        sink.send([0xb0 | channel, 123, 0]); // all notes off
        sink.send([0xb0 | channel, 120, 0]); // all sound off
      }
    };
    sweep();
    // And again after the window has drained, to catch what was already queued.
    this.flush = setTimeout(() => {
      sweep();
      this.flush = null;
    }, MIDI_FLUSH_MS);
  }

  private tick(options: PlayOptions): void {
    this.frame = requestAnimationFrame(() => {
      const elapsed = this.position;
      this.report(options, elapsed);
      if (elapsed >= this.end) {
        this.stop();
        this.report(options, this.end);
        options.onDone?.();
        return;
      }
      this.tick(options);
    });
  }

  private report(options: PlayOptions, elapsed: number): void {
    options.onProgress?.({ elapsed, total: this.total });
  }

  private synthVoice(): Tone.PolySynth<Tone.FMSynth> {
    if (!this.synth) {
      // An FM voice with a piano's shape rather than a pad's: a click of attack, a
      // long decay to almost nothing, and a bright transient that fades faster than
      // the fundamental. Not a piano — the sample set is for that — but it stops
      // sounding like a string section holding a chord.
      this.synth = new Tone.PolySynth(Tone.FMSynth, {
        harmonicity: 2.5,
        modulationIndex: 5,
        oscillator: { type: 'sine' },
        envelope: { attack: 0.003, decay: 1.4, sustain: 0.03, release: 0.9 },
        modulation: { type: 'sine' },
        modulationEnvelope: { attack: 0.003, decay: 0.3, sustain: 0, release: 0.3 },
      }).toDestination();
      this.synth.maxPolyphony = 48;
      this.synth.volume.value = -10;
    }
    return this.synth;
  }
}

let shared: PianoPlayer | null = null;

/**
 * Resume the audio context on the first gesture anywhere in the page.
 *
 * The alternative — starting it inside a play handler — is unreliable, because those
 * handlers fetch the notes before they reach the player, and by then the gesture that
 * began them is over. One listener, removed after it fires.
 */
export function unlockOnFirstGesture(): void {
  if (typeof window === 'undefined') return;
  const resume = () => {
    void sharedPlayer().unlock();
    window.removeEventListener('pointerdown', resume);
    window.removeEventListener('keydown', resume);
  };
  window.addEventListener('pointerdown', resume);
  window.addEventListener('keydown', resume);
}

/**
 * The one player. Every caller shares it, so there is exactly one thing making
 * sound and exactly one Stop that stops it.
 */
export function sharedPlayer(): PianoPlayer {
  if (!shared) shared = new PianoPlayer();
  return shared;
}
