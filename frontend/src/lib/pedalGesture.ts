/**
 * The pedals as hands-free switches.
 *
 * The PX-870 has three pedals, and the middle one is barely used musically — which is
 * exactly what makes it usable as a control. Nothing here reads musical state: it is
 * handed controller moves and returns an action, so the decision is pure and can be
 * tested without a piano.
 *
 * **Discovery first.** `seen` records every controller number the piano has actually
 * sent, because a gesture bound to a message the instrument never sends is a feature
 * that silently does not exist. The device bar reports `seen`, so "the pedal does
 * nothing" can be answered by looking rather than by guessing.
 *
 * **Two actions, two gestures.** The sostenuto arms and stops capture; the damper's
 * double tap toggles a workout. The mapping follows what each pedal is worth: a take is
 * armed and stopped every session, so it gets the pedal nobody plays, while starting a
 * workout is rarer and can afford a deliberate double tap — which stays gated on silence,
 * because the damper *is* played. The soft pedal is used while playing, so it is bound to
 * nothing at all.
 */

/** One controller move, on the wall clock like every other MIDI event here. */
export interface ControllerMove {
  /** Absolute time, ms since the Unix epoch. */
  epochMs: number;
  /** The CC number: 64 damper, 66 sostenuto, 67 soft. */
  controller: number;
  value: number;
  channel: number;
}

export type HandsfreeAction = 'toggle_workout' | 'toggle_audio_capture';

/**
 * The one pedal that is *not* played.
 *
 * The damper is used constantly and the soft pedal is used while playing, so neither can carry
 * a gesture that a musician will fire by accident: the soft pedal especially, where a press
 * mid-phrase would stop the take being recorded. The sostenuto is the middle pedal almost
 * nobody touches, so it is the only one bound to capture. The damper keeps a last-resort
 * double tap, and that tap carries the workout.
 */
export const HANDSFREE_CONTROLLERS: readonly number[] = [66];

/** MIDI's own rule, shared with the sustain path rather than spelled out twice. */
const DOWN = 64;

/** Two damper taps within this window are one deliberate gesture. */
const DOUBLE_TAP_MS = 700;

/** ... and only when nothing has been played for this long. */
const SILENCE_MS = 2_000;

export class PedalGesture {
  /** Every controller number seen so far. A report, never consent. */
  readonly seen = new Set<number>();

  private readonly down = new Map<number, boolean>();
  private lastTapMs: number | null = null;

  /**
   * Feed one controller move; get an action back, or null.
   *
   * `lastNoteMs` is the wall clock of the last note heard, or null when nothing has been
   * played this session. It is consulted **only** for the damper fallback: the sostenuto is
   * not played, so a press on it is unambiguous, while a press on the damper is exactly what
   * playing looks like.
   */
  accept(move: ControllerMove, lastNoteMs: number | null): HandsfreeAction | null {
    this.seen.add(move.controller);
    const isDown = move.value >= DOWN;
    const wasDown = this.down.get(move.controller) ?? false;
    this.down.set(move.controller, isDown);

    if (HANDSFREE_CONTROLLERS.includes(move.controller)) {
      // A dedicated pedal: one deliberate press and release is the whole gesture.
      return wasDown && !isDown ? 'toggle_audio_capture' : null;
    }

    if (move.controller === 64 && wasDown && !isDown) {
      const quiet = lastNoteMs === null || move.epochMs - lastNoteMs >= SILENCE_MS;
      if (!quiet) {
        this.lastTapMs = null;
        return null;
      }
      if (this.lastTapMs !== null && move.epochMs - this.lastTapMs <= DOUBLE_TAP_MS) {
        this.lastTapMs = null;
        return 'toggle_workout';
      }
      this.lastTapMs = move.epochMs;
    }
    return null;
  }
}
