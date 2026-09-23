/**
 * The pedals as hands-free switches.
 *
 * The PX-870 has three pedals, and the middle one is barely used musically — which is
 * exactly what makes it usable as a control. Nothing here reads musical state: it is
 * handed controller moves and returns actions, so the decision is pure and can be
 * tested without a piano.
 *
 * **Discovery first.** `seen` records every controller number the piano has actually
 * sent, because a gesture bound to a message the instrument never sends is a feature
 * that silently does not exist. The panel reports `seen`, so "the pedal does nothing"
 * can be answered by looking rather than by guessing.
 *
 * **One pedal, three gestures.** The sostenuto carries a single press, a double press and
 * a press-and-hold; each is bound to one action from the list, or to nothing. The damper
 * and the soft pedal carry nothing at all, because both are *played*: binding a tap on
 * either means an ordinary press fires a command mid-phrase. That was learned twice — the
 * soft pedal ended a take mid-phrase, and the damper's double tap started a workout during
 * ordinary pedalling — so the invariant is the design rather than an obstacle to it.
 *
 * **A fire carries the press's time.** A single tap cannot be told from the first half of a
 * double until the double window expires, so it is resolved late. Stamping it at the press
 * means the lateness costs only the on-screen confirmation, never the accuracy of the place
 * it records.
 *
 * **Nothing here owns the clock.** `accept` is driven by the move's own timestamp and `tick`
 * by whatever calls it, so the whole state machine is deterministic under test.
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

/** Every action a gesture can carry. */
export type HandsfreeAction =
  | 'mark_review'
  | 'toggle_workout'
  | 'toggle_audio_capture'
  | 'finish_sitting';

/** The three gestures one pedal can carry. */
export type PedalGestureKind = 'single' | 'double' | 'hold';

/** One gesture's binding: an action, or nothing at all. */
export type PedalBindings = Record<PedalGestureKind, HandsfreeAction | null>;

/** A gesture that fired, and *when the pedal was pressed* — never when it was resolved. */
export interface PedalFire {
  action: HandsfreeAction;
  /** Absolute time of the press that completed the gesture, ms since the Unix epoch. */
  atMs: number;
}

/**
 * The one pedal that is *not* played.
 *
 * The damper is used constantly and the soft pedal is used while playing, so neither can carry
 * a gesture a musician will fire by accident: the soft pedal especially, where a press
 * mid-phrase would stop the take being recorded. The sostenuto is the middle pedal almost
 * nobody touches, so it is the only one bound to anything — and the only one read.
 */
export const HANDSFREE_CONTROLLERS: readonly number[] = [66];

/** A press held at least this long is a hold rather than a tap. */
export const HOLD_MS = 500;

/**
 * How long a tap waits for a second one.
 *
 * Measured from the release, not the press: a deliberately slow tap is still a tap, and
 * timing the window from the press would expire it before the finger came off.
 */
export const DOUBLE_MS = 300;

/** MIDI's own rule, shared with the sustain path rather than spelled out twice. */
const DOWN = 64;

export class PedalGesture {
  /** Every controller number seen so far. A report, never consent. */
  readonly seen = new Set<number>();

  private readonly down = new Map<number, boolean>();
  private bindings: PedalBindings;

  /** When the current press began, or null when nothing is down. */
  private pressedAt: number | null = null;
  /** Whether the hold has already fired for the current press, so its release is consumed. */
  private holdFired = false;
  /** Whether the current press is the second tap of a pair. */
  private awaitingSecond = false;
  /** A tap waiting to find out whether a second one follows. */
  private pendingTap: { atMs: number; expiresAt: number } | null = null;

  constructor(bindings: PedalBindings) {
    this.bindings = bindings;
  }

  /** A gesture can be rebound while the pedal is idle; the next move uses the new map. */
  setBindings(bindings: PedalBindings): void {
    this.bindings = bindings;
  }

  /** True while a press or a tap is still waiting on the clock. */
  get pending(): boolean {
    return this.pressedAt !== null || this.pendingTap !== null;
  }

  private fire(kind: PedalGestureKind, atMs: number): PedalFire[] {
    const action = this.bindings[kind];
    return action === null ? [] : [{ action, atMs }];
  }

  /** Feed one controller move; get the gestures it completed, in order. */
  accept(move: ControllerMove): PedalFire[] {
    this.seen.add(move.controller);
    if (!HANDSFREE_CONTROLLERS.includes(move.controller)) return [];

    const isDown = move.value >= DOWN;
    const wasDown = this.down.get(move.controller) ?? false;
    this.down.set(move.controller, isDown);
    if (isDown === wasDown) return [];

    if (isDown) {
      this.pressedAt = move.epochMs;
      this.holdFired = false;
      // A second press inside the window claims the pair, so the first tap will not also
      // resolve as a single: an accidental tap before a deliberate hold fires one action.
      this.awaitingSecond = this.pendingTap !== null && move.epochMs <= this.pendingTap.expiresAt;
      if (this.awaitingSecond) this.pendingTap = null;
      return [];
    }

    const pressTime = this.pressedAt;
    this.pressedAt = null;
    if (pressTime === null) return [];
    if (this.holdFired) {
      this.holdFired = false;
      this.awaitingSecond = false;
      return [];
    }
    if (this.awaitingSecond) {
      this.awaitingSecond = false;
      return this.fire('double', pressTime);
    }
    // A plain tap. It may be the first of a double, so it is held back — unless an earlier
    // tap is still pending, which the clock has not yet expired.
    const late = this.pendingTap;
    this.pendingTap = { atMs: pressTime, expiresAt: move.epochMs + DOUBLE_MS };
    return late === null ? [] : this.fire('single', late.atMs);
  }

  /**
   * Resolve whatever the clock has decided: a hold that has reached its threshold, and a
   * single tap whose double window has run out.
   *
   * Separate from `accept` because both need time to pass with no event arriving, and keeping
   * them here rather than in a timer is what makes the state machine testable.
   */
  tick(nowMs: number): PedalFire[] {
    const fires: PedalFire[] = [];
    if (this.pressedAt !== null && !this.holdFired && nowMs - this.pressedAt >= HOLD_MS) {
      this.holdFired = true;
      fires.push(...this.fire('hold', this.pressedAt));
    }
    if (this.pendingTap !== null && nowMs >= this.pendingTap.expiresAt) {
      const atMs = this.pendingTap.atMs;
      this.pendingTap = null;
      fires.push(...this.fire('single', atMs));
    }
    return fires;
  }
}
