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
  /** Bar lengths (in notated beats) for the exercise itself, one per bar. */
  barsBeats: number[];
  /**
   * The beat unit per bar, in quarter lengths: 1 for a quarter-note beat, 1.5
   * for the dotted-quarter beat of 6/8, 2 for cut time.
   *
   * This is what makes the metronome correct in compound meter. A beat is not
   * a quarter note, so a single "seconds per beat" derived from the tempo is
   * only right when the meter's beat happens to be a quarter.
   */
  barBeatUnits: number[];
  /** Seconds per quarter note, which is what a tempo marking actually means. */
  secondsPerQuarter: number;
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

  /** Every click, with its offset in seconds from the first count-in click. */
  private clicks: { at: number; accent: boolean; bar: number; beat: number; inCountIn: boolean }[] = [];
  private downbeatSeconds = 0;
  private scheduledSeconds = 0;

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
    this.buildSchedule(plan);
    this.startMs = performance.now();
    this.scheduledUntil = 0;
    this.scheduleAhead();
    this.tick();
  }

  /**
   * Lay out every click up front, in seconds from the first count-in click.
   *
   * Precomputing removes the previous assumption that all beats last the same
   * amount of time, which is false for compound and mixed meters.
   */
  private buildSchedule(plan: MetronomePlan): void {
    const beatsInFirstBar = plan.barsBeats[0] ?? 4;
    const countInUnit = plan.barBeatUnits[0] ?? 1;
    this.clicks = [];
    let elapsed = 0;

    for (let index = 0; index < plan.countInBeats; index += 1) {
      this.clicks.push({
        at: elapsed,
        accent: index % beatsInFirstBar === 0,
        bar: 0,
        beat: index + 1,
        inCountIn: true,
      });
      elapsed += countInUnit * plan.secondsPerQuarter;
    }
    this.downbeatSeconds = elapsed;

    plan.barsBeats.forEach((beats, barIndex) => {
      const unit = plan.barBeatUnits[barIndex] ?? 1;
      for (let beat = 0; beat < beats; beat += 1) {
        this.clicks.push({
          at: elapsed,
          accent: beat === 0,
          bar: barIndex + 1,
          beat: beat + 1,
          inCountIn: false,
        });
        elapsed += unit * plan.secondsPerQuarter;
      }
    });
    this.scheduledSeconds = elapsed;
  }

  stop(): void {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;
    this.plan = null;
  }

  /** `performance.now()` corresponding to the exercise's beat 1. */
  get downbeatMs(): number {
    if (!this.plan) return 0;
    return this.startMs + this.downbeatSeconds * 1000;
  }

  /** Total length of the count-in plus the exercise, in seconds. */
  get durationSeconds(): number {
    return this.scheduledSeconds;
  }

  /**
   * Web Audio needs clicks scheduled slightly ahead of time, so we keep a
   * rolling window filled rather than scheduling the whole exercise at once
   * (which would make `stop()` unable to cancel anything).
   */
  private scheduleAhead(): void {
    if (!this.plan || !this.synth) return;
    const elapsed = (performance.now() - this.startMs) / 1000;
    const horizon = elapsed + LOOKAHEAD_S;

    while (this.scheduledUntil < this.clicks.length && this.clicks[this.scheduledUntil].at < horizon) {
      const click = this.clicks[this.scheduledUntil];
      const when = Tone.now() + Math.max(0, click.at - elapsed);
      const frequency = click.accent ? 1760 : 1174.66;
      try {
        this.synth.triggerAttackRelease(frequency, 0.04, when, click.accent ? 0.9 : 0.55);
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
    if (elapsed >= this.scheduledSeconds) {
      this.stop();
      return;
    }

    // Find the click currently sounding. The count is small (tens), and beats
    // are no longer evenly spaced, so a scan is clearer than arithmetic.
    let index = 0;
    for (let i = this.clicks.length - 1; i >= 0; i -= 1) {
      if (this.clicks[i].at <= elapsed) {
        index = i;
        break;
      }
    }
    const current = this.clicks[index];
    const next = this.clicks[index + 1];
    const span = (next ? next.at : this.scheduledSeconds) - current.at;

    this.listeners.forEach((listener) =>
      listener({
        beat: current.beat,
        bar: current.bar,
        accent: current.accent,
        absoluteBeat: index + 1,
        progress: span > 0 ? Math.max(0, Math.min(1, (elapsed - current.at) / span)) : 0,
        inCountIn: current.inCountIn,
      }),
    );

    this.frame = requestAnimationFrame(this.tick);
  };
}
