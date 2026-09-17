import { test } from 'node:test';
import assert from 'node:assert/strict';

import { PedalGesture, type ControllerMove } from './pedalGesture.ts';

function move(controller: number, value: number, epochMs: number): ControllerMove {
  return { controller, value, epochMs, channel: 0 };
}

test('every controller number seen is reported, whatever it is', () => {
  const gesture = new PedalGesture();
  gesture.accept(move(1, 127, 0), null);
  gesture.accept(move(66, 127, 10), null);
  gesture.accept(move(64, 0, 20), null);
  assert.deepEqual([...gesture.seen].sort((a, b) => a - b), [1, 64, 66]);
});

test('a press and release of the sostenuto is the gesture', () => {
  const gesture = new PedalGesture();
  assert.equal(gesture.accept(move(66, 127, 1_000), null), null, 'down is not the gesture');
  assert.equal(gesture.accept(move(66, 0, 1_050), null), 'toggle_workout');
});

test('the soft pedal works the same way, as the second choice', () => {
  const gesture = new PedalGesture();
  gesture.accept(move(67, 127, 1_000), null);
  assert.equal(gesture.accept(move(67, 0, 1_100), null), 'toggle_workout');
});

test('a controller nobody bound does nothing, even with a full press', () => {
  const gesture = new PedalGesture();
  gesture.accept(move(11, 127, 1_000), null);
  assert.equal(gesture.accept(move(11, 0, 1_100), null), null);
  assert.equal(gesture.seen.has(11), true, 'but it is still reported as seen');
});

test('the sustain pedal arms capture on two taps, and only in silence', () => {
  // The damper is played constantly, so it carries the *secondary* action and only when
  // nothing has been played: a double tap here mostly means the player is pedalling.
  const quiet = new PedalGesture();
  quiet.accept(move(64, 127, 10_000), 1_000);
  assert.equal(quiet.accept(move(64, 0, 10_100), 1_000), null, 'one tap is not a gesture');
  quiet.accept(move(64, 127, 10_300), 1_000);
  assert.equal(quiet.accept(move(64, 0, 10_400), 1_000), 'toggle_audio_capture');

  const playing = new PedalGesture();
  playing.accept(move(64, 127, 10_000), 9_900);
  assert.equal(playing.accept(move(64, 0, 10_100), 10_050), null, 'not while playing');
  playing.accept(move(64, 127, 10_200), 10_150);
  assert.equal(playing.accept(move(64, 0, 10_300), 10_250), null, 'and not on the second either');
});

test('two taps far apart are two taps, not a double tap', () => {
  const gesture = new PedalGesture();
  gesture.accept(move(64, 127, 0), null);
  gesture.accept(move(64, 0, 100), null);
  gesture.accept(move(64, 127, 60_000), null);
  assert.equal(gesture.accept(move(64, 0, 60_100), null), null);
});

test('a release with no press before it is not a gesture', () => {
  const gesture = new PedalGesture();
  assert.equal(gesture.accept(move(66, 0, 500), null), null);
});

test('the two dedicated pedals do different-adjacent things, and the damper does neither', () => {
  // The mapping the acceptance bullet needs: a workout from an unused pedal, capture from the
  // damper's deliberate double tap. One pedal must not carry both.
  const gesture = new PedalGesture();
  gesture.accept(move(66, 127, 1_000), null);
  assert.equal(gesture.accept(move(66, 0, 1_010), null), 'toggle_workout');
  gesture.accept(move(64, 127, 1_100), null);
  assert.equal(gesture.accept(move(64, 0, 1_110), null), null, 'a single damper tap is nothing');
  assert.equal(gesture.seen.has(66), true);
  assert.equal(gesture.seen.has(64), true);
});
