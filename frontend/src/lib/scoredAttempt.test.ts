import { test } from 'node:test';
import assert from 'node:assert/strict';

import { ScoredAttempt, isBeforeDownbeat } from './scoredAttempt.ts';

const note = (pitch: number, onset: number, velocity = 64, channel = 0) => ({
  pitch,
  onset,
  velocity,
  channel,
});

test('a played note keeps its pitch, onset, velocity and channel', () => {
  const attempt = new ScoredAttempt();
  attempt.record(note(60, 0.25, 71, 3));
  assert.deepEqual(attempt.notes, [
    { pitch: 60, onset: 0.25, duration: 0, velocity: 71, channel: 3 },
  ]);
});

test('a release applies to the note-on it finishes', () => {
  const attempt = new ScoredAttempt();
  attempt.record(note(60, 0.0));
  attempt.release(60, 1.5);
  assert.equal(attempt.notes[0].duration, 1.5);
});

// The defect this module exists for. The view keyed a `Map` by pitch alone, so the second strike
// of a re-struck key overwrote the first note's slot; because releases arrive oldest-first, the
// first release then landed on the second note and the first was scored with no length at all.
test('a key struck twice before either release is closed oldest-first, both with their own length', () => {
  const attempt = new ScoredAttempt();
  attempt.record(note(60, 0.0));
  attempt.record(note(60, 0.5));
  attempt.release(60, 0.5);
  attempt.release(60, 0.75);

  const [first, second] = attempt.notes;
  assert.equal(first.onset, 0.0);
  assert.equal(first.duration, 0.5, 'the first strike keeps the length it was actually held for');
  assert.equal(second.onset, 0.5);
  assert.equal(second.duration, 0.75);
});

test('a third strike while two are still held queues behind both', () => {
  const attempt = new ScoredAttempt();
  attempt.record(note(60, 0.0));
  attempt.record(note(60, 0.1));
  attempt.record(note(60, 0.2));
  attempt.release(60, 1.0);
  attempt.release(60, 2.0);
  attempt.release(60, 3.0);
  assert.deepEqual(
    attempt.notes.map((item) => item.duration),
    [1.0, 2.0, 3.0],
  );
});

test('releases do not cross pitches', () => {
  const attempt = new ScoredAttempt();
  attempt.record(note(60, 0.0));
  attempt.record(note(64, 0.1));
  attempt.release(64, 0.4);
  attempt.release(60, 0.9);
  assert.deepEqual(
    attempt.notes.map((item) => [item.pitch, item.duration]),
    [
      [60, 0.9],
      [64, 0.4],
    ],
  );
});

test('a release with nothing open is ignored rather than guessed at', () => {
  const attempt = new ScoredAttempt();
  attempt.record(note(60, 0.0));
  attempt.release(67, 0.5); // a note that began before this attempt did
  assert.equal(attempt.notes.length, 1);
  assert.equal(attempt.notes[0].duration, 0);
  assert.equal(attempt.held, 1, 'the open note is still open');
});

test('a release arriving twice for one note leaves the length alone', () => {
  const attempt = new ScoredAttempt();
  attempt.record(note(60, 0.0));
  attempt.release(60, 0.5);
  attempt.release(60, 9.9);
  assert.equal(attempt.notes[0].duration, 0.5);
  assert.equal(attempt.held, 0);
});

test('the snapshot is a copy, so sending it cannot change the attempt', () => {
  const attempt = new ScoredAttempt();
  attempt.record(note(60, 0.0));
  const sent = attempt.notes;
  sent[0].duration = 99;
  assert.equal(attempt.notes[0].duration, 0);
});

test('clear begins a fresh attempt with nothing held', () => {
  const attempt = new ScoredAttempt();
  attempt.record(note(60, 0.0));
  attempt.clear();
  attempt.release(60, 1.0);
  assert.deepEqual(attempt.notes, []);
  assert.equal(attempt.held, 0);
});

// --- the count-in boundary ---------------------------------------------------------------------

test('a note struck during the count-in is before the downbeat', () => {
  assert.equal(isBeforeDownbeat(note(60, -0.3)), true);
});

test('beat 1 itself and anything after it is part of the attempt', () => {
  assert.equal(isBeforeDownbeat(note(60, 0)), false);
  assert.equal(isBeforeDownbeat(note(60, -0.0001)), true);
  assert.equal(isBeforeDownbeat(note(60, 0.4)), false);
});
