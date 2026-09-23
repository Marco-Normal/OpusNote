import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  PedalGesture,
  HOLD_MS,
  DOUBLE_MS,
  type ControllerMove,
  type PedalBindings,
  type PedalFire,
} from './pedalGesture.ts';

/** The mapping these tests exercise. The shipped defaults live in `pedalBindings.ts`. */
const BINDINGS: PedalBindings = {
  single: 'mark_review',
  double: 'toggle_workout',
  hold: 'toggle_audio_capture',
};

function move(controller: number, value: number, epochMs: number): ControllerMove {
  return { controller, value, epochMs, channel: 0 };
}

/** Feed a press and a release, and return everything the recogniser produced. */
function tap(gesture: PedalGesture, atMs: number, heldMs = 0): PedalFire[] {
  const fires = [...gesture.accept(move(66, 127, atMs))];
  fires.push(...gesture.accept(move(66, 0, atMs + heldMs)));
  return fires;
}

const actions = (fires: PedalFire[]) => fires.map((fire) => fire.action);

test('every controller number seen is reported, whatever it is', () => {
  const gesture = new PedalGesture(BINDINGS);
  gesture.accept(move(1, 127, 0));
  gesture.accept(move(66, 127, 10));
  gesture.accept(move(64, 0, 20));
  assert.deepEqual([...gesture.seen].sort((a, b) => a - b), [1, 64, 66]);
});

test('a single tap on the sostenuto fires the single action, stamped when it was pressed', () => {
  const gesture = new PedalGesture(BINDINGS);
  const fires = tap(gesture, 1_000);
  assert.deepEqual(fires, [], 'a tap is held back: it may be the first of two');
  // The window expires and the single fires, still stamped at the press.
  const resolved = gesture.tick(1_000 + DOUBLE_MS);
  assert.deepEqual(actions(resolved), ['mark_review']);
  assert.equal(resolved[0].atMs, 1_000, 'the press time, not the resolution time');
});

test('two taps inside the window are one double, and no single escapes', () => {
  const gesture = new PedalGesture(BINDINGS);
  assert.deepEqual(tap(gesture, 1_000), []);
  const second = tap(gesture, 1_000 + DOUBLE_MS - 50);
  assert.deepEqual(actions(second), ['toggle_workout']);
  assert.equal(second[0].atMs, 1_000 + DOUBLE_MS - 50, 'the press that completed the gesture');
  assert.deepEqual(gesture.tick(10_000), [], 'the first tap was claimed by the double');
});

test('a press held past the threshold is a hold, and fires while the pedal is still down', () => {
  const gesture = new PedalGesture(BINDINGS);
  gesture.accept(move(66, 127, 2_000));
  assert.deepEqual(gesture.tick(2_000 + HOLD_MS - 1), [], 'not yet');
  const fires = gesture.tick(2_000 + HOLD_MS);
  assert.deepEqual(actions(fires), ['toggle_audio_capture']);
  assert.equal(fires[0].atMs, 2_000, 'stamped at the press');
});

test('a hold is not also a tap, and its release fires nothing', () => {
  const gesture = new PedalGesture(BINDINGS);
  gesture.accept(move(66, 127, 2_000));
  gesture.tick(2_000 + HOLD_MS);
  const release = gesture.accept(move(66, 0, 2_000 + HOLD_MS + 100));
  assert.deepEqual(release, [], 'the release of a hold is consumed');
  assert.deepEqual(gesture.tick(9_000), [], 'and it leaves no single behind');
});

test('a tap followed by a hold is the hold alone', () => {
  // The second press claims the pair, so the first tap is not also a single: an accidental
  // tap before a deliberate hold must not fire two actions.
  const gesture = new PedalGesture(BINDINGS);
  tap(gesture, 1_000);
  gesture.accept(move(66, 127, 1_100));
  const held = gesture.tick(1_100 + HOLD_MS);
  assert.deepEqual(actions(held), ['toggle_audio_capture']);
  assert.deepEqual(gesture.tick(1_100 + HOLD_MS + DOUBLE_MS + 1), []);
});

test('a second tap arriving after the window is its own tap, and the first still fires', () => {
  const gesture = new PedalGesture(BINDINGS);
  tap(gesture, 1_000);
  // Expire the first, then tap again well outside the window.
  assert.deepEqual(actions(gesture.tick(1_000 + DOUBLE_MS)), ['mark_review']);
  assert.deepEqual(tap(gesture, 3_000), []);
  assert.deepEqual(actions(gesture.tick(3_000 + DOUBLE_MS)), ['mark_review']);
});

test('a release with no press before it is not a gesture', () => {
  const gesture = new PedalGesture(BINDINGS);
  assert.deepEqual(gesture.accept(move(66, 0, 500)), []);
  assert.deepEqual(gesture.tick(9_000), []);
});

test('a gesture bound to nothing fires nothing, and the pedal is still reported', () => {
  const gesture = new PedalGesture({ single: null, double: null, hold: null });
  assert.deepEqual(tap(gesture, 1_000), []);
  assert.deepEqual(gesture.tick(1_000 + DOUBLE_MS), []);
  assert.equal(gesture.seen.has(66), true);
});

test('only the sostenuto is read: the damper and the soft pedal carry nothing', () => {
  // The invariant this phase exists to keep. The damper is played constantly and the soft pedal
  // mid-phrase, so neither may reach an action however it is pressed.
  const gesture = new PedalGesture(BINDINGS);
  for (const controller of [64, 67]) {
    gesture.accept(move(controller, 127, 1_000));
    assert.deepEqual(gesture.accept(move(controller, 0, 1_010)), []);
    gesture.accept(move(controller, 127, 1_020));
    gesture.accept(move(controller, 0, 1_030));
  }
  assert.deepEqual(gesture.tick(9_000), []);
  assert.equal(gesture.seen.has(64), true, 'but both are still reported as seen');
  assert.equal(gesture.seen.has(67), true);
});

test('a binding can be changed while the pedal is idle and takes effect at once', () => {
  const gesture = new PedalGesture(BINDINGS);
  gesture.setBindings({ single: 'finish_sitting', double: null, hold: null });
  tap(gesture, 1_000);
  assert.deepEqual(actions(gesture.tick(1_000 + DOUBLE_MS)), ['finish_sitting']);
});

test('the recogniser reports whether anything is still waiting on the clock', () => {
  const gesture = new PedalGesture(BINDINGS);
  assert.equal(gesture.pending, false);
  gesture.accept(move(66, 127, 1_000));
  assert.equal(gesture.pending, true, 'a press is waiting for a hold or a release');
  gesture.accept(move(66, 0, 1_010));
  assert.equal(gesture.pending, true, 'a tap is waiting for a possible second');
  gesture.tick(1_010 + DOUBLE_MS);
  assert.equal(gesture.pending, false);
});
