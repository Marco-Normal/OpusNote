import { test } from 'node:test';
import assert from 'node:assert/strict';

import { formatMinutes } from './types.ts';

// The first tests for this module, which had none. `formatMinutes` is read by a human on every
// screen that reports time, and it never carried a rounded minute into the hour: 119.7 printed
// "1 h 60 min" and 59.6 printed "60 min".

test('minutes below ten keep the decimal, because that is where the difference shows', () => {
  // The docstring's contract: 0.4 -> "0.4 min".
  assert.equal(formatMinutes(0.4), '0.4 min');
  assert.equal(formatMinutes(7.25), '7.3 min');
});

test('minutes round into the hour instead of reporting sixty of them', () => {
  // Measured before the fix: "1 h 60 min", because `Math.round(minutes % 60)` was never carried.
  assert.equal(formatMinutes(119.7), '2 h');
  assert.equal(formatMinutes(59.6), '1 h');
});

test('whole hours drop the minutes entirely', () => {
  assert.equal(formatMinutes(120), '2 h');
  assert.equal(formatMinutes(180), '3 h');
});

test('a part-hour past sixty keeps its minutes and the word', () => {
  // The docstring used to promise `90 -> "1 h 30"` while the code has always printed
  // "1 h 30 min". The code is what every screen already shows, so the docstring was the
  // thing that was wrong; this pins the behaviour that ships.
  assert.equal(formatMinutes(90), '1 h 30 min');
  assert.equal(formatMinutes(119.4), '1 h 59 min');
});

test('minutes under an hour are plain, and nothing at all is zero', () => {
  assert.equal(formatMinutes(45), '45 min');
  assert.equal(formatMinutes(59), '59 min');
  assert.equal(formatMinutes(0), '0 min');
  assert.equal(formatMinutes(-5), '0 min');
  assert.equal(formatMinutes(Number.NaN), '0 min');
});
