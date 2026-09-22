import { test } from 'node:test';
import assert from 'node:assert/strict';

import { formatClock, formatDuration, parseClock } from './clock.ts';

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


test('a duration past an hour reads as hours, not as sixty minutes', () => {
  // Measured before the fix: 3599.6 -> "60:00". A take is about 14 MB an hour, so an hour-long
  // recording is an ordinary thing to have, and the playhead was already printing 1:00:00.
  assert.equal(formatDuration(3599.6), '1:00:00');
  assert.equal(formatDuration(3661), '1:01:01');
  assert.equal(formatDuration(3600), '1:00:00');
});

test('a duration under an hour keeps the short form, rounded to the nearest second', () => {
  assert.equal(formatDuration(65), '1:05');
  assert.equal(formatDuration(59.4), '0:59');
  assert.equal(formatDuration(0), '0:00');
});

test('a duration that is not a number says so rather than printing a lie', () => {
  assert.equal(formatDuration(null), '—');
  assert.equal(formatDuration(Number.NaN), '—');
  assert.equal(formatDuration(Number.POSITIVE_INFINITY), '—');
});

// --- what is not a time ---
//
// `Number('1e3')` is 1000 and `Number('0x10')` is 16, so a typed clock used to accept both: a
// mistyped seek to 16:40, and a hex literal nobody meant to type. And `1:99` was read as 159
// seconds rather than refused, which silently seeks somewhere plausible but wrong — exactly what
// the existing dangling-colon rule exists to prevent.

test('exponent and hex notation are not times', () => {
  assert.equal(parseClock('1e3'), null);
  assert.equal(parseClock('0x10'), null);
  assert.equal(parseClock('1E3'), null);
  assert.equal(parseClock('1.5'), null);
});

test('a part of a clock past fifty-nine is refused rather than carried', () => {
  assert.equal(parseClock('1:99'), null);
  assert.equal(parseClock('1:60'), null);
  assert.equal(parseClock('1:01:99'), null);
  assert.equal(parseClock('1:99:01'), null);
  assert.equal(parseClock('1:59'), 119, 'fifty-nine is still a minute count');
  assert.equal(parseClock('1:59:59'), 7199);
});

test('the seconds form has no parts to bound, so any count is allowed', () => {
  assert.equal(parseClock('90'), 90);
  assert.equal(parseClock('3600'), 3600);
});
