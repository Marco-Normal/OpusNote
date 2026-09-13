import { test } from 'node:test';
import assert from 'node:assert/strict';

import { formatClock, parseClock } from './clock.ts';

test('a clock reads in minutes and seconds', () => {
  assert.equal(formatClock(95), '1:35');
  assert.equal(formatClock(9), '0:09');
  assert.equal(formatClock(3800), '1:03:20');
  assert.equal(formatClock(0), '0:00');
});

test('tenths are for a position you are reading', () => {
  assert.equal(formatClock(3.44, true), '0:03.4');
  assert.equal(formatClock(63.4, true), '1:03.4');
  assert.equal(formatClock(600, true), '10:00.0');
  // A duration rounds down to the second; it never gains a spurious tenth.
  assert.equal(formatClock(63.9), '1:03');
});

test('nonsense reads as zero rather than as NaN on a screen', () => {
  assert.equal(formatClock(-1), '0:00');
  assert.equal(formatClock(Number.NaN), '0:00');
  assert.equal(formatClock(Number.POSITIVE_INFINITY), '0:00');
});

test('a typed time is read as seconds, either bare or as a clock', () => {
  // Bare numbers are seconds: this is a seek position, and `45` as minutes would
  // land most of an hour from where it was meant.
  assert.equal(parseClock('45'), 45);
  assert.equal(parseClock('1:30'), 90);
  assert.equal(parseClock('1:01:01'), 3661);
  assert.equal(parseClock(' 2:05 '), 125);
  assert.equal(parseClock('0'), 0);
});

test('something that is not a time is refused rather than guessed at', () => {
  assert.equal(parseClock(''), null);
  assert.equal(parseClock('   '), null);
  assert.equal(parseClock('later'), null);
  assert.equal(parseClock('-5'), null);
  assert.equal(parseClock('1:2:3:4'), null);
  assert.equal(parseClock('1:'), null);
});
