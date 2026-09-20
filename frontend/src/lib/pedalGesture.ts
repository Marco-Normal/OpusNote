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
 * **One action, one pedal.** The sostenuto arms and stops capture. The damper and the
 * soft pedal are both *played*, so neither carries a gesture: a press on either is
 * playing, not a command. The mapping follows what each pedal is worth — a take is armed
 * and stopped every session, so it goes to the middle pedal almost nobody touches.
 *
 * The damper's double tap used to toggle a workout. It was retired deliberately: it fired
 * in the middle of ordinary pedalling, which is the one thing a hands-free switch must
 * never do. A workout is declared from the banner instead.
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

/**
 * The only action a pedal carries.
 *
 * A single-member union rather than a bare string, because `accept` has to be able to
 * report "nothing happened" — and so that adding a second pedal action is a type change
 * the compiler will point at, rather than a string nobody notices.
 */
export type HandsfreeAction = "toggle_audio_capture";

/**
 * The one pedal that is *not* played.
 *
 * The damper is used constantly and the soft pedal is used while playing, so neither can carry
 * a gesture that a musician will fire by accident: the soft pedal especially, where a press
 * mid-phrase would stop the take being recorded. The sostenuto is the middle pedal almost
 * nobody touches, so it is the only one bound to anything.
 */
export const HANDSFREE_CONTROLLERS: readonly number[] = [66];

/** MIDI's own rule, shared with the sustain path rather than spelled out twice. */
const DOWN = 64;

export class PedalGesture {
  /** Every controller number seen so far. A report, never consent. */
  readonly seen = new Set<number>();

  private readonly down = new Map<number, boolean>();

  /**
   * Feed one controller move; get an action back, or null.
   *
   * A press and release is the whole gesture, and only the sostenuto is bound, so no musical
   * state has to be consulted to tell a command from playing. That is the property that makes
   * this pedal safe to bind at all: every other pedal would need the app to guess whether the
   * musician meant it, and guessing wrong is what retired the damper's double tap.
   */
  accept(move: ControllerMove): HandsfreeAction | null {
    this.seen.add(move.controller);
    const isDown = move.value >= DOWN;
    const wasDown = this.down.get(move.controller) ?? false;
    this.down.set(move.controller, isDown);

    if (HANDSFREE_CONTROLLERS.includes(move.controller)) {
      // A dedicated pedal: one deliberate press and release is the whole gesture.
      return wasDown && !isDown ? "toggle_audio_capture" : null;
    }
    return null;
  }
}
