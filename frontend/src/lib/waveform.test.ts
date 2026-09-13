import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  MIN_LOOP_S,
  clampToLoop,
  formatClock,
  peaksFrom,
  placeMarker,
  ratioToTime,
  timeToRatio,
} from './waveform.ts';

function ramp(length: number): Float32Array {
  const samples = new Float32Array(length);
  for (let index = 0; index < length; index += 1) samples[index] = index / length;
  return samples;
}

test('peaks follow the envelope of a ramp', () => {
  const { low, high } = peaksFrom([ramp(400)], 4);

  assert.equal(low.length, 4);
  assert.equal(high.length, 4);
  // A ramp from 0 to 1: each column's ceiling rises and nothing goes negative.
  assert.deepEqual(low, [0, 0, 0, 0]);
  assert.ok(high[0] < high[1] && high[1] < high[2] && high[2] < high[3]);
  assert.ok(high[3] > 0.9, `the last column reaches the end (${high[3]})`);
});

test('the last column always includes the final sample', () => {
  // 10 samples into 3 columns is not a whole number of samples per column, and a
  // stride-based loop would drop the tail — which is where a final chord lives.
  const samples = new Float32Array(10);
  samples[9] = 1;
  const { high } = peaksFrom([samples], 3);
  assert.equal(high[2], 1, 'the loud last sample is pictured');
});

test('channels are pooled, not averaged', () => {
  // A left-hand note present in one channel only must not be halved into
  // near-silence by an average.
  const left = new Float32Array([0, 0, 0, 0]);
  const right = new Float32Array([0, 0.8, 0.8, 0]);
  const { high } = peaksFrom([left, right], 2);
  // Float32 rounding: compare with a tolerance rather than exactly.
  assert.ok(Math.abs(Math.max(...high) - 0.8) < 1e-6, `kept the loud channel (${high})`);
});

test('a silent recording produces a flat line rather than nothing', () => {
  const { low, high } = peaksFrom([new Float32Array(100)], 10);
  assert.equal(low.length, 10);
  assert.ok(high.every((value) => value === 0));
});

test('an empty or absurd column count is handled', () => {
  assert.deepEqual(peaksFrom([], 0), { low: [], high: [] });
  assert.deepEqual(peaksFrom([new Float32Array(0)], 5), {
    low: [0, 0, 0, 0, 0],
    high: [0, 0, 0, 0, 0],
  });
  assert.equal(peaksFrom([ramp(10)], -3).low.length, 0);
});

test('non-finite samples do not poison a column', () => {
  const samples = new Float32Array([0.5, Number.NaN, 0.25]);
  const { low, high } = peaksFrom([samples], 1);
  assert.equal(high[0], 0.5);
  assert.equal(low[0], 0);
});

test('positions and times round-trip', () => {
  assert.equal(timeToRatio(15, 60), 0.25);
  assert.equal(timeToRatio(90, 60), 1, 'past the end clamps');
  assert.equal(timeToRatio(5, 0), 0, 'an unknown duration cannot divide');
  assert.equal(ratioToTime(0.25, 60), 15);
  assert.equal(ratioToTime(-1, 60), 0);
  assert.equal(ratioToTime(2, 60), 60);
});

test('there is no loop until both markers are set', () => {
  assert.equal(clampToLoop(10, null, 20), 10);
  assert.equal(clampToLoop(10, 5, null), 10);
  assert.equal(clampToLoop(10, 20, 20), 10, 'an empty loop is no loop');
  assert.equal(clampToLoop(10, 20, 5), 10, 'an inverted pair is no loop');
});

test('playback outside the loop snaps to its start', () => {
  assert.equal(clampToLoop(2, 5, 9), 5, 'before it');
  assert.equal(clampToLoop(9, 5, 9), 5, 'at the end goes back');
  assert.equal(clampToLoop(30, 5, 9), 5, 'after it, as a native seek past B does');
});

test('playback inside the loop is left alone', () => {
  assert.equal(clampToLoop(6, 5, 9), 6);
  assert.equal(clampToLoop(5, 5, 9), 5);
  assert.equal(clampToLoop(8.999, 5, 9), 8.999);
});

test('a clock reads in minutes and tenths', () => {
  assert.equal(formatClock(3.44), '0:03.4');
  assert.equal(formatClock(63.4), '1:03.4');
  assert.equal(formatClock(600), '10:00.0');
  assert.equal(formatClock(-1), '0:00.0');
  assert.equal(formatClock(Number.NaN), '0:00.0');
});

test('markers can be set one at a time, in either order', () => {
  assert.deepEqual(placeMarker(4, { start: null, end: null }, 'start'), {
    start: 4,
    end: null,
  });
  assert.deepEqual(placeMarker(9, { start: 4, end: null }, 'end'), { start: 4, end: 9 });
  // B first is a legitimate way to mark a passage, so A does not need B to exist.
  assert.deepEqual(placeMarker(9, { start: null, end: null }, 'end'), {
    start: null,
    end: 9,
  });
});

test('a marker placed on the wrong side clears the other one', () => {
  // Rather than a refusal the player cannot act on: the marker visibly goes away.
  assert.deepEqual(placeMarker(10, { start: 4, end: 9 }, 'start'), {
    start: 10,
    end: null,
  });
  assert.deepEqual(placeMarker(2, { start: 4, end: 9 }, 'end'), {
    start: null,
    end: 2,
  });
});

test('a loop too short to be a passage clears the other marker', () => {
  const tooClose = 4 + MIN_LOOP_S / 2;
  assert.deepEqual(placeMarker(tooClose, { start: 4, end: null }, 'end'), {
    start: null,
    end: tooClose,
  });
  // Exactly at the minimum is accepted, so the boundary is inclusive.
  assert.deepEqual(placeMarker(4 + MIN_LOOP_S, { start: 4, end: null }, 'end'), {
    start: 4,
    end: 4 + MIN_LOOP_S,
  });
});
