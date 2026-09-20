import { test } from 'node:test';
import assert from 'node:assert/strict';

import { PedalGesture, type ControllerMove } from './pedalGesture.ts';

function move(controller: number, value: number, epochMs: number): ControllerMove {
  return { controller, value, epochMs, channel: 0 };
}

test('every controller number seen is reported, whatever it is', () => {
  const gesture = new PedalGesture();
  gesture.accept(move(1, 127, 0));
  gesture.accept(move(66, 127, 10));
  gesture.accept(move(64, 0, 20));
  assert.deepEqual([...gesture.seen].sort((a, b) => a - b), [1, 64, 66]);
});

test('a press and release of the sostenuto arms and stops capture', () => {
  const gesture = new PedalGesture();
  assert.equal(gesture.accept(move(66, 127, 1_000)), null, 'down is not the gesture');
  assert.equal(gesture.accept(move(66, 0, 1_050)), 'toggle_audio_capture');
});

test('the soft pedal is deliberately unbound: it is played, so a press does nothing', () => {
  // The soft pedal *is* used while playing, so binding capture to it would stop a take in the
  // middle of a phrase nobody meant to end. Only the middle pedal carries the gesture.
  const gesture = new PedalGesture();
  gesture.accept(move(67, 127, 1_000));
  assert.equal(gesture.accept(move(67, 0, 1_100)), null);
  assert.equal(gesture.seen.has(67), true, 'but it is still reported as seen, so the bar can say so');
});

test('a controller nobody bound does nothing, even with a full press', () => {
  const gesture = new PedalGesture();
  gesture.accept(move(11, 127, 1_000));
  assert.equal(gesture.accept(move(11, 0, 1_100)), null);
  assert.equal(gesture.seen.has(11), true, 'but it is still reported as seen');
});

test('the damper carries no gesture: even a deliberate double tap starts nothing', () => {
  // The damper's double tap used to toggle a workout. It was retired deliberately, because
  // the damper is played constantly and the gesture fired in the middle of ordinary
  // pedalling. This test is what keeps the retirement: the taps must stay inert, and the
  // pedal must still be *reported*, so the panel can explain rather than look broken.
  const gesture = new PedalGesture();
  gesture.accept(move(64, 127, 10_000));
  assert.equal(gesture.accept(move(64, 0, 10_100)), null, 'one tap is not a gesture');
  gesture.accept(move(64, 127, 10_300));
  assert.equal(gesture.accept(move(64, 0, 10_400)), null, 'and two taps are still not one');
  assert.equal(gesture.seen.has(64), true, 'but the damper is still reported as seen');
});

test('a release with no press before it is not a gesture', () => {
  const gesture = new PedalGesture();
  assert.equal(gesture.accept(move(66, 0, 500)), null);
});

test('only the sostenuto carries the gesture, and a damper tap carries nothing', () => {
  // Capture from the pedal nobody plays, and nothing at all from the pedal everybody plays.
  // One pedal must not carry both.
  const gesture = new PedalGesture();
  gesture.accept(move(66, 127, 1_000));
  assert.equal(gesture.accept(move(66, 0, 1_010)), 'toggle_audio_capture');
  gesture.accept(move(64, 127, 1_100));
  assert.equal(gesture.accept(move(64, 0, 1_110)), null, 'a damper tap is nothing');
  assert.equal(gesture.seen.has(66), true);
  assert.equal(gesture.seen.has(64), true);
});
