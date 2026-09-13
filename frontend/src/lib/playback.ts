/**
 * Turning what happened into something that can be played back.
 *
 * Pure on purpose: the arithmetic that decides *which hand* a played note belonged to
 * and how long a written note lasts is exactly the kind of thing that is tedious to
 * check by ear and trivial to check in a test. `pianoPlayer.ts` does the Tone part.
 */

import type { ExpectedNote, LoggedNote, NoteFeedback, PlayedNote } from './types';

export type Hand = 'RH' | 'LH';

export interface SynthNote {
  /** MIDI pitch. */
  pitch: number;
  /** Seconds from the start of the playback. */
  onset: number;
  /** Seconds. */
  duration: number;
  /** 0..1, scaled from MIDI velocity. */
  velocity: number;
  /** Unknown for a note that matched nothing — it is played either way. */
  hand: Hand | null;
}

/** How far apart two onsets may be and still be called the same note. */
const ONSET_TOLERANCE_S = 0.005;

/** Written material has no velocity of its own; this is a neutral mezzo-forte. */
const WRITTEN_VELOCITY = 0.7;

/**
 * What was actually played, with each note's hand recovered from the score.
 *
 * The scorer pairs a played note with an expected one and stores the *difference*
 * (`played.onset - expected.onset_s`), so the played onset can be reconstructed
 * exactly. Matching on pitch and that onset is how a note with no feedback — an extra
 * note, or a wrong pitch — ends up with `hand: null`, which means "play it regardless
 * of which hands are selected" rather than "guess".
 */
export function playedEvents(
  played: readonly PlayedNote[],
  feedback: readonly NoteFeedback[],
): SynthNote[] {
  const byPitch = new Map<number, { onset: number; hand: Hand }[]>();
  for (const item of feedback) {
    if (item.played_pitch === null || item.onset_error_s === null) continue;
    const onset = item.onset_s + item.onset_error_s;
    const list = byPitch.get(item.played_pitch) ?? [];
    list.push({ onset, hand: item.hand });
    byPitch.set(item.played_pitch, list);
  }

  return played.map((note) => {
    const candidates = byPitch.get(note.pitch) ?? [];
    let best: { onset: number; hand: Hand } | null = null;
    let bestDistance = ONSET_TOLERANCE_S;
    for (const candidate of candidates) {
      const distance = Math.abs(candidate.onset - note.onset);
      if (distance <= bestDistance) {
        best = candidate;
        bestDistance = distance;
      }
    }
    return {
      pitch: note.pitch,
      onset: note.onset,
      duration: Math.max(0.05, note.duration),
      velocity: Math.min(1, Math.max(0.05, note.velocity / 127)),
      hand: best ? best.hand : null,
    };
  });
}

/**
 * The exercise as written.
 *
 * Durations are stored in quarter notes because that is what the notation says, and a
 * performer needs seconds — hence the tempo, which is the exercise's own, so playback
 * matches what the count-in counted.
 */
export function writtenEvents(
  expected: readonly ExpectedNote[],
  tempoBpm: number,
): SynthNote[] {
  const secondsPerQuarter = 60 / (tempoBpm > 0 ? tempoBpm : 90);
  return expected.map((note) => ({
    pitch: note.pitch,
    onset: note.onset_s,
    duration: Math.max(0.05, note.duration_q * secondsPerQuarter),
    velocity: WRITTEN_VELOCITY,
    hand: note.hand,
  }));
}

/**
 * What was logged, from the practice log.
 *
 * No hand: the passive log keeps the MIDI channel, and the piano sends both hands on
 * one channel, so a hand filter here would be invented rather than known. Everything
 * else is exact — these are the durations the piano reported on release.
 */
export function loggedEvents(notes: readonly LoggedNote[]): SynthNote[] {
  return notes.map((note) => ({
    pitch: note.pitch,
    onset: note.onset_ms / 1000,
    duration: Math.max(0.05, note.duration_ms / 1000),
    velocity: Math.min(1, Math.max(0.05, note.velocity / 127)),
    hand: null,
  }));
}

/** The notes whose onsets fall inside a segment. */
export function within(
  notes: readonly SynthNote[],
  startMs: number,
  endMs: number,
): SynthNote[] {
  return notes.filter((note) => {
    const onsetMs = note.onset * 1000;
    return onsetMs >= startMs && onsetMs <= endMs;
  });
}

/** Shift everything so playback starts at once, without an initial silence. */
export function sounding(notes: readonly SynthNote[]): SynthNote[] {
  if (notes.length === 0) return [];
  const first = Math.min(...notes.map((note) => note.onset));
  if (first <= 0) return [...notes];
  return notes.map((note) => ({ ...note, onset: note.onset - first }));
}

/**
 * Filter to the selected hands.
 *
 * A note whose hand is unknown is kept: it is part of what was played, and dropping it
 * would make "left hand only" quietly leave out every wrong note.
 */
export function forHands(notes: readonly SynthNote[], hands: readonly Hand[]): SynthNote[] {
  if (hands.length === 2) return [...notes];
  return notes.filter((note) => note.hand === null || hands.includes(note.hand));
}

/** How long the whole thing lasts, including the final note's release. */
export function durationOf(notes: readonly SynthNote[]): number {
  return notes.reduce((end, note) => Math.max(end, note.onset + note.duration), 0);
}
