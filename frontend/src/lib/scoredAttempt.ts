/**
 * The notes that make up one scored attempt.
 *
 * Two rules live here, and they are the same rule seen from two sides: *which* note-ons belong to
 * the attempt, and *which* note-on a note-off finishes. Both were wrong in the view that owned this
 * state before, and both were wrong in a way nothing could see — the payload stayed well-formed
 * while carrying a note that was never played and a note whose length was zero.
 *
 * Pure, and in its own module, for the reason `segmentUndo.ts` gives: the pairing is a pure
 * function of the event order, and `node --test` can reach it here. The view owns the DOM, the
 * clock and the network; it should not also own the arithmetic.
 */

import type { PlayedNote } from './types';

/** A note-on, as the capture layer reports it. */
export interface NoteOn {
  pitch: number;
  /** Seconds from beat 1. Negative before beat 1, which is what the count-in produces. */
  onset: number;
  velocity: number;
  channel: number;
}

/**
 * Whether a note-on landed before beat 1, and so is not part of the exercise.
 *
 * The count-in is playing time, not scored time: recording is anchored at beat 1 (deliberately, so
 * a note played early is *measurably* early rather than silently fitted), which means anything
 * played during the count-in arrives with a negative onset. The count-in's own clicks are the first
 * thing the player hears, so a note struck while following them is a warm-up, not an answer.
 *
 * Admitting one anyway is not a small error. The server matches nothing at a negative onset, so the
 * note becomes an unmatched *extra*, which costs pitch precision for every note of the exercise —
 * and in the browser the live matcher has no such guard, so a stray note during the count-in can
 * claim an expected note as correct and, once every note is claimed, finish the run before the
 * player has been counted in.
 */
export function isBeforeDownbeat(note: NoteOn): boolean {
  return note.onset < 0;
}

/**
 * The note-ons of one attempt, with each release applied to the note-on it finishes.
 *
 * A note-on is appended in arrival order, which is onset order, and a note-off closes *the oldest
 * still-unreleased note of that pitch*. That queue is not an optimisation: it is what the MIDI
 * layer already does one level down (`activeNotes` in `midi.ts`), because a piano can be playing the
 * same key again before the first strike has been released.
 *
 * The view used to key a `Map` by pitch alone, which holds one slot per pitch. A re-struck key
 * overwrote that slot, and — because releases arrive oldest-first — the *second* release was applied
 * to the *second* note-on while the first kept the `duration: 0` it was created with. Every held
 * note in a repeated passage was therefore sent to the scorer with no length at all.
 */
export class ScoredAttempt {
  private log: PlayedNote[] = [];
  /** Pitch → indices into `log` awaiting a note-off, oldest first. */
  private readonly open = new Map<number, number[]>();

  /** Append a note-on. Returns its index in the attempt. */
  record(note: NoteOn): number {
    const index = this.log.length;
    this.log.push({
      pitch: note.pitch,
      onset: note.onset,
      duration: 0,
      velocity: note.velocity,
      channel: note.channel,
    });
    const queue = this.open.get(note.pitch);
    if (queue === undefined) this.open.set(note.pitch, [index]);
    else queue.push(index);
    return index;
  }

  /**
   * Apply a note-off. `durationS` is the length the capture layer measured.
   *
   * A release with no open note of that pitch is ignored rather than guessed at: it can only be the
   * tail of a note that began before this attempt did, which is not this attempt's to close.
   */
  release(pitch: number, durationS: number): void {
    const queue = this.open.get(pitch);
    if (queue === undefined) return;
    const index = queue.shift();
    if (queue.length === 0) this.open.delete(pitch);
    if (index === undefined) return;
    this.log[index].duration = durationS;
  }

  /** The attempt so far, as the scoring payload. A copy: the caller may not edit our log. */
  get notes(): PlayedNote[] {
    return this.log.map((note) => ({ ...note }));
  }

  /** Notes recorded but not yet released. */
  get held(): number {
    let total = 0;
    this.open.forEach((queue) => (total += queue.length));
    return total;
  }

  /** Begin a fresh attempt. */
  clear(): void {
    this.log = [];
    this.open.clear();
  }
}
