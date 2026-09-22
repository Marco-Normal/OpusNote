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

/** The first onset, or 0 when there is nothing. */
export function firstOnset(notes: readonly SynthNote[]): number {
  // The same reduce was written out twice, once to test and once to answer. `Infinity` is the
  // identity for a minimum, so one pass over the list and a fallback is the whole of it.
  let first = Infinity;
  for (const note of notes) {
    if (note.onset < first) first = note.onset;
  }
  return first === Infinity ? 0 : first;
}

/**
 * The notes from `seconds` onwards, rebased so that `seconds` becomes zero.
 *
 * This is what makes seeking possible: the player schedules from now, so every
 * onset has to be relative to the moment playback starts, while the interface still
 * thinks in positions in the sitting.
 *
 * A note that was already sounding at `seconds` is kept, shortened to the part that
 * is left — the alternative is to drop it, which makes seeking into the middle of a
 * held chord sound like a mistake in the recording.
 */
export function fromTime(notes: readonly SynthNote[], seconds: number): SynthNote[] {
  const from = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const out: SynthNote[] = [];
  for (const note of notes) {
    const end = note.onset + note.duration;
    if (end <= from) continue;
    const onset = Math.max(0, note.onset - from);
    out.push({ ...note, onset, duration: Math.max(0.05, end - from - onset) });
  }
  return out;
}

/** A pedal move as stored: CC64, where `PEDAL_DOWN` and above is "down". */
export interface PedalPoint {
  onset_ms: number;
  value: number;
}

/**
 * Where a sustain-pedal value counts as "down".
 *
 * The MIDI specification's own rule for a switch controller: 0-63 is off, 64-127 is
 * on. That is what makes an ordinary on/off pedal work, and it is the reading a
 * continuous pedal gets too — the PX-870 has one, and its full-resolution values are
 * stored in the log, but half-pedalling therefore reads as released.
 *
 * It is exported because two layers have to give the same answer: `midi.ts` when it
 * decodes CC64 off the wire, and this module when it reads stored pedal moves back.
 * It was written out in both places before, which is how one rule becomes two.
 */
export const PEDAL_DOWN = 64;

/**
 * How much longer a note rings when the pedal is still down at the end of the
 * recording. A pedal-up that never arrives must not hold a note forever; half a
 * second is enough to hear the chord fade rather than be cut dead.
 */
const UNCLOSED_PEDAL_TAIL_S = 0.5;

/**
 * Let the sustain pedal hold each note past its release.
 *
 * The piano reports CC64 as a stream of values, so this turns it into the
 * intervals those values describe and extends every note whose release falls
 * inside one. Two details are the whole behaviour:
 *
 * - A pedal pressed *after* a note was released does not bring it back. The synth
 *   has already let it go, and pretending otherwise would invent a sound that
 *   never happened.
 * - A pedal still down at the end extends to the end of the last note plus a
 *   short tail rather than to infinity, so a pedal unplugged mid-press cannot
 *   produce a note that never stops.
 */
export function sustained(
  notes: readonly SynthNote[],
  pedals: readonly PedalPoint[],
): SynthNote[] {
  if (notes.length === 0 || pedals.length === 0) return [...notes];

  const ordered = [...pedals].sort((a, b) => a.onset_ms - b.onset_ms);
  const end = durationOf(notes);
  const intervals: { start: number; end: number }[] = [];
  let down: number | null = null;
  for (const pedal of ordered) {
    const at = pedal.onset_ms / 1000;
    if (pedal.value >= PEDAL_DOWN) {
      // Repeated "down" values are common; only the first starts the stretch.
      if (down === null) down = at;
    } else if (down !== null) {
      intervals.push({ start: down, end: at });
      down = null;
    }
  }
  if (down !== null) intervals.push({ start: down, end: end + UNCLOSED_PEDAL_TAIL_S });
  if (intervals.length === 0) return [...notes];

  return notes.map((note) => {
    const release = note.onset + note.duration;
    for (const interval of intervals) {
      if (interval.start <= release && release < interval.end) {
        // max() so a pedal can only ever lengthen a note: one already sounding
        // past the pedal-up keeps its own end.
        return { ...note, duration: Math.max(note.duration, interval.end - note.onset) };
      }
    }
    return note;
  });
}

/**
 * End a note where the same key is struck again.
 *
 * MIDI carries one note-off per pitch, so two notes of the same pitch cannot overlap
 * in the stream: the earlier note's release stops the pitch, and the later note dies
 * with it however much longer it was held. `sustained()` is what makes that common —
 * extending a released note to the pedal-up routinely carries it past a re-strike of
 * the same key, so the note a hand is *still holding* goes silent at the moment the
 * pedal comes up. Measured on real sessions, that was 1,747 notes, and the worst lost
 * 14.5 seconds of a held note after 27 ms.
 *
 * A re-struck string replaces the previous vibration, so ending the earlier note at
 * the later onset is what the instrument does, not a workaround for it. Two notes at
 * one instant on one key are the same strike and collapse to the longer.
 *
 * The result is in onset order and free of same-pitch overlaps, so a caller that
 * schedules it sequentially emits each clamped note-off before the note-on that
 * follows it — which is the order a re-trigger needs.
 */
export function resolveOverlaps(notes: readonly SynthNote[]): SynthNote[] {
  const ordered = [...notes].sort(
    (a, b) => a.onset - b.onset || a.duration - b.duration || a.pitch - b.pitch,
  );
  const out: SynthNote[] = [];
  const previousOf = new Map<number, number>();
  for (const note of ordered) {
    const previous = previousOf.get(note.pitch);
    if (previous !== undefined) {
      const earlier = out[previous];
      if (earlier.onset + earlier.duration > note.onset) {
        out[previous] = { ...earlier, duration: note.onset - earlier.onset };
      }
    }
    previousOf.set(note.pitch, out.length);
    out.push(note);
  }
  // A note clamped to nothing is one that cannot sound, and leaving it would only
  // re-attack a pitch already sounding at that instant.
  return out.filter((note) => note.duration > 0);
}
