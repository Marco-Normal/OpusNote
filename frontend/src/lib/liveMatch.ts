/**
 * Live note matching for in-exercise feedback.
 *
 * This is *display only*. The authoritative score always comes from the API,
 * whose matcher uses proper precision/recall and continuity analysis. Doing a
 * cheap nearest-neighbour match here keeps the notation responsive as you play
 * without duplicating the real scoring logic in the browser.
 */

import type { ExpectedNote, NoteStatus } from './types';

export interface LiveMatch {
  index: number | null;
  status: NoteStatus;
}

export class LiveMatcher {
  private readonly claimed = new Set<number>();
  private readonly statuses = new Map<number, NoteStatus>();
  private extraCount = 0;

  constructor(
    private readonly expected: ExpectedNote[],
    /** Seconds. Slightly looser than the server's window, for responsiveness. */
    private readonly windowS = 0.25,
  ) {}

  /** Register a note-on. Returns the expected note it was attributed to, if any. */
  register(pitch: number, onset: number): LiveMatch {
    let bestIndex = -1;
    let bestDistance = Number.POSITIVE_INFINITY;

    for (const note of this.expected) {
      if (this.claimed.has(note.index) || note.pitch !== pitch) continue;
      const distance = Math.abs(note.onset_s - onset);
      if (distance <= this.windowS && distance < bestDistance) {
        bestDistance = distance;
        bestIndex = note.index;
      }
    }

    if (bestIndex >= 0) {
      this.claimed.add(bestIndex);
      this.statuses.set(bestIndex, 'correct');
      return { index: bestIndex, status: 'correct' };
    }

    // Nothing at this pitch: attribute it to the nearest unclaimed expected note
    // so the score can show "this is the note you got wrong".
    let wrongIndex = -1;
    let wrongDistance = Number.POSITIVE_INFINITY;
    for (const note of this.expected) {
      if (this.claimed.has(note.index)) continue;
      const distance = Math.abs(note.onset_s - onset);
      if (distance <= this.windowS * 1.5 && distance < wrongDistance) {
        wrongDistance = distance;
        wrongIndex = note.index;
      }
    }

    if (wrongIndex >= 0) {
      this.claimed.add(wrongIndex);
      this.statuses.set(wrongIndex, 'wrong_pitch');
      return { index: wrongIndex, status: 'wrong_pitch' };
    }

    this.extraCount += 1;
    return { index: null, status: 'extra' };
  }

  /** Snapshot of per-note statuses so far. */
  get snapshot(): Map<number, NoteStatus> {
    return new Map(this.statuses);
  }

  get progress(): { done: number; total: number; correct: number; wrong: number; extra: number } {
    let correct = 0;
    let wrong = 0;
    this.statuses.forEach((status) => {
      if (status === 'correct') correct += 1;
      else wrong += 1;
    });
    return { done: this.claimed.size, total: this.expected.length, correct, wrong, extra: this.extraCount };
  }

  get isComplete(): boolean {
    return this.claimed.size >= this.expected.length;
  }

  /** Mark every note the player never reached as missed. */
  finalSnapshot(): Map<number, NoteStatus> {
    const result = new Map(this.statuses);
    for (const note of this.expected) {
      if (!result.has(note.index)) result.set(note.index, 'missed');
    }
    return result;
  }
}
