/**
 * Metronome and count-in built on Tone.js.
 *
 * Two clocks are involved and they must not be confused:
 *
 * * **Audio** — click scheduling, done ahead of time through Tone so the
 *   Web Audio clock stays sample-accurate.
 * * **Visual / capture** — `performance.now()`, which is the same clock the MIDI
 *   timestamps use.
 *
 * `performance.now()` and `AudioContext.currentTime` advance at the same rate,
 * so a single measured offset converts between them. The beat indicator and the
 * recorded onsets therefore agree with what the player heard, instead of
 * drifting against a scheduled click.
 */

import * as Tone from 'tone';

export interface BeatInfo {
  /** 1-based beat index within the current bar. */
  beat: number;
  /** 1-based bar index. */
  bar: number;
  /** True for the first beat of a bar. */
  accent: boolean;
  /** Whole count-in + exercise beat number, starting at 1. */
  absoluteBeat: number;
  /** 0..1 progress through the current beat, for the visual pulse. */
  progress: number;
  inCountIn: boolean;
}

export interface MetronomePlan {
  /** Bar lengths (in beats) for the exercise itself, one entry per bar. */
  barsBeats: number[];
  /** Seconds per beat. */
  secondsPerBeat: number;
  /** How many beats of count-in to play before beat 1. */
  countInBeats: number;
}

export type BeatListener = (info: BeatInfo) => void;

const LOOKAHEAD_S = 0.1;

export class Metronome {
  private synth: Tone.Synth | null = null;
  private listeners = new Set<BeatListener>();
  private frame = 0;

  /** `performance.now()` at which the very first count-in click sounds. */
  private startMs = 0;
  private plan: MetronomePlan | null = null;
  private scheduledUntil = 0;

  get audioReady(): boolean {
    return Tone.getContext().state === 'running';
  }

  async unlock(): Promise<void> {
    await Tone.start();
    if (!this.synth) {
      this.synth = new Tone.Synth({
        oscillator: { type: 'square' },
        envelope: { attack: 0.001, decay: 0.05, sustain: 0, release: 0.02 },
        volume: -12,
      }).toDestination();
    }
  }

  onBeat(listener: BeatListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Schedule the whole count-in and exercise up front, then drive the visual
   * beat from `performance.now()`.
   */
  start(plan: MetronomePlan): void {
    this.stop();
    this.plan = plan;
    this.startMs = performance.now();
    this.scheduledUntil = 0;
    this.scheduleAhead();
    this.tick();
  }

  stop(): void {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;
    this.plan = null;
  }

  /** `performance.now()` corresponding to the exercise's beat 1. */
  get downbeatMs(): number {
    if (!this.plan) return 0;
    return this.startMs + this.plan.countInBeats * this.plan.secondsPerBeat * 1000;
  }

  /** Total beats including the count-in, for progress display. */
  get totalBeats(): number {
    if (!this.plan) return 0;
    return this.plan.countInBeats + this.plan.barsBeats.reduce((sum, beats) => sum + beats, 0);
  }

  private beatAt(absoluteBeatIndex: number): { bar: number; beat: number; accent: boolean; inCountIn: boolean } {
    const plan = this.plan!;
    if (absoluteBeatIndex < plan.countInBeats) {
      const beatsInBar = plan.barsBeats[0] ?? 4;
      return {
        bar: 0,
        beat: (absoluteBeatIndex % beatsInBar) + 1,
        accent: absoluteBeatIndex % beatsInBar === 0,
        inCountIn: true,
      };
    }
    let remaining = absoluteBeatIndex - plan.countInBeats;
    for (let barIndex = 0; barIndex < plan.barsBeats.length; barIndex += 1) {
      const beats = plan.barsBeats[barIndex];
      if (remaining < beats) {
        return { bar: barIndex + 1, beat: remaining + 1, accent: remaining === 0, inCountIn: false };
      }
      remaining -= beats;
    }
    return { bar: plan.barsBeats.length, beat: 1, accent: false, inCountIn: false };
  }

  /** Offset in seconds from the start of the run to a given absolute beat. */
  private offsetForBeat(absoluteBeatIndex: number): number {
    return absoluteBeatIndex * this.plan!.secondsPerBeat;
  }

  /**
   * Web Audio needs clicks scheduled slightly ahead of time, so we keep a
   * rolling window filled rather than scheduling the whole exercise at once
   * (which would make `stop()` unable to cancel anything).
   */
  private scheduleAhead(): void {
    if (!this.plan || !this.synth) return;
    const total = this.totalBeats;
    const elapsed = (performance.now() - this.startMs) / 1000;
    const horizon = elapsed + LOOKAHEAD_S;

    while (this.scheduledUntil < total && this.offsetForBeat(this.scheduledUntil) < horizon) {
      const offset = this.offsetForBeat(this.scheduledUntil);
      const info = this.beatAt(this.scheduledUntil);
      const when = Tone.now() + Math.max(0, offset - elapsed);
      const frequency = info.accent ? 1760 : 1174.66;
      try {
        this.synth.triggerAttackRelease(frequency, 0.04, when, info.accent ? 0.9 : 0.55);
      } catch {
        // A dropped click is better than a broken practice session.
      }
      this.scheduledUntil += 1;
    }
  }

  private tick = (): void => {
    if (!this.plan) return;
    this.scheduleAhead();

    const elapsed = (performance.now() - this.startMs) / 1000;
    const absolute = elapsed / this.plan.secondsPerBeat;
    const index = Math.floor(absolute);
    const progress = absolute - index;

    if (index >= 0 && index < this.totalBeats) {
      const info = this.beatAt(index);
      const payload: BeatInfo = {
        beat: info.beat,
        bar: info.bar,
        accent: info.accent,
        absoluteBeat: index + 1,
        progress: Math.max(0, Math.min(1, progress)),
        inCountIn: info.inCountIn,
      };
      this.listeners.forEach((listener) => listener(payload));
    } else if (index >= this.totalBeats) {
      this.stop();
      return;
    }

    this.frame = requestAnimationFrame(this.tick);
  };
}
