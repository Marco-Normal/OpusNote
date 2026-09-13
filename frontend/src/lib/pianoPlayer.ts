/**
 * Playing notes back through a synthesiser.
 *
 * Not the piano. The app ships no samples, and pretending otherwise in the interface
 * would be worse than saying so: what this reproduces faithfully is *timing and
 * touch* — onsets, release-derived durations and velocities all come from what was
 * actually played — and what it cannot reproduce is the instrument.
 *
 * Tone is already a dependency for the count-in click, and the audio-context unlock
 * problem is already solved there; this reuses the same idea rather than adding a
 * second audio stack.
 */

import * as Tone from 'tone';

import type { SynthNote } from './playback';

export interface PlaybackHandle {
  /** Seconds since playback started. */
  elapsed: number;
  total: number;
}

export interface PlaybackOptions {
  onProgress?: (handle: PlaybackHandle) => void;
  onDone?: () => void;
}

/** A little air before the first note, so the very first attack is not clipped. */
const LEAD_IN_S = 0.12;

export class PianoPlayer {
  private synth: Tone.PolySynth<Tone.Synth> | null = null;
  private frame: number | null = null;
  private startedAt = 0;
  private total = 0;
  private playing = false;

  get isPlaying(): boolean {
    return this.playing;
  }

  /**
   * Play a set of notes, replacing anything already playing.
   *
   * The audio context is started here rather than on load: browsers refuse to start
   * one without a gesture, and every caller of this is a button.
   */
  async play(notes: readonly SynthNote[], options: PlaybackOptions = {}): Promise<void> {
    this.stop();
    if (notes.length === 0) {
      options.onDone?.();
      return;
    }

    try {
      await Tone.start();
    } catch {
      // No audio in this browser or context. Failing silently is right: the caller
      // has nothing useful to tell the user about a sound that did not happen.
      options.onDone?.();
      return;
    }

    if (!this.synth) {
      this.synth = new Tone.PolySynth(Tone.Synth, {
        // A short, bright envelope: recognisably not a piano, but the attack is
        // crisp enough that timing differences are audible, which is the point.
        oscillator: { type: 'triangle' },
        envelope: { attack: 0.005, decay: 0.18, sustain: 0.25, release: 0.35 },
      }).toDestination();
      this.synth.maxPolyphony = 48;
      this.synth.volume.value = -8;
    }

    const start = Tone.now() + LEAD_IN_S;
    this.total = notes.reduce((end, note) => Math.max(end, note.onset + note.duration), 0);
    for (const note of notes) {
      this.synth.triggerAttackRelease(
        Tone.Frequency(note.pitch, 'midi').toFrequency(),
        Math.max(0.05, note.duration),
        start + note.onset,
        Math.min(1, Math.max(0.05, note.velocity)),
      );
    }

    this.startedAt = start;
    this.playing = true;
    this.report(options, 0);
    this.tick(options);
  }

  stop(): void {
    if (this.frame !== null) {
      cancelAnimationFrame(this.frame);
      this.frame = null;
    }
    if (this.playing) {
      this.synth?.releaseAll();
    }
    this.playing = false;
  }

  /** Release the audio resources entirely, for a component being torn down. */
  dispose(): void {
    this.stop();
    this.synth?.dispose();
    this.synth = null;
  }

  private tick(options: PlaybackOptions): void {
    this.frame = requestAnimationFrame(() => {
      const elapsed = Tone.now() - this.startedAt;
      this.report(options, Math.max(0, elapsed));
      if (elapsed >= this.total) {
        this.frame = null;
        this.playing = false;
        this.report(options, this.total);
        options.onDone?.();
        return;
      }
      this.tick(options);
    });
  }

  private report(options: PlaybackOptions, elapsed: number): void {
    options.onProgress?.({ elapsed, total: this.total });
  }
}
