import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  durationOf,
  forHands,
  loggedEvents,
  playedEvents,
  sounding,
  sustained,
  within,
  writtenEvents,
} from './playback.ts';

const played = (pitch: number, onset: number, duration = 0.4, velocity = 70) => ({
  pitch,
  onset,
  duration,
  velocity,
  channel: 0,
});

const expected = (
  pitch: number,
  onset_s: number,
  duration_q: number,
  hand: 'RH' | 'LH' = 'RH',
) => ({
  index: 0,
  event_id: 0,
  pitch,
  onset_q: onset_s,
  duration_q,
  onset_s,
  hand,
  measure: 1,
  beat: 1,
});

test('a written note gets seconds from quarter notes at the exercise tempo', () => {
  // 120 BPM: a quarter note is half a second, a half note a whole one.
  const events = writtenEvents(
    [expected(60, 0, 1), expected(62, 0.5, 2, 'LH')],
    120,
  );
  assert.equal(events[0].duration, 0.5);
  assert.equal(events[1].duration, 1);
  assert.equal(events[1].onset, 0.5);
  assert.equal(events[1].hand, 'LH');
  assert.equal(events[0].velocity, 0.7);
});

test('an impossible tempo does not produce infinite durations', () => {
  const events = writtenEvents([expected(60, 0, 1)], 0);
  assert.ok(Number.isFinite(events[0].duration));
  assert.ok(events[0].duration > 0);
});

test('a played note inherits the hand of the note it matched', () => {
  // delta = played.onset - expected.onset_s, which is how the scorer stores it.
  const events = playedEvents(
    [played(60, 0.1), played(48, 0.6)],
    [
      { ...expected(60, 0.096, 1, 'RH'), status: 'correct', played_pitch: 60, onset_error_s: 0.004 },
      { ...expected(48, 0.602, 1, 'LH'), status: 'correct', played_pitch: 48, onset_error_s: -0.002 },
    ] as never,
  );
  assert.equal(events[0].hand, 'RH');
  assert.equal(events[1].hand, 'LH');
});

test('a note the score never saw is kept, with no hand', () => {
  const events = playedEvents(
    [played(60, 0.1), played(67, 0.9)],
    [
      { ...expected(60, 0.1, 1), status: 'correct', played_pitch: 60, onset_error_s: 0 },
    ] as never,
  );
  assert.equal(events.length, 2);
  assert.equal(events[1].hand, null);
  assert.equal(events[1].pitch, 67);
});

test('a missed expected note contributes nothing to what was played', () => {
  const events = playedEvents([], [
    { ...expected(60, 0.1, 1), status: 'missed', played_pitch: null, onset_error_s: null },
  ] as never);
  assert.deepEqual(events, []);
});

test('velocity is scaled to 0..1 and never silent', () => {
  const events = playedEvents([played(60, 0, 0.4, 127), played(62, 1, 0.4, 0)], []);
  assert.equal(events[0].velocity, 1);
  assert.ok(events[1].velocity > 0, 'a zero-velocity note would be inaudible');
});

test('a zero-length note still sounds', () => {
  const events = playedEvents([played(60, 0, 0)], []);
  assert.equal(events[0].duration, 0.05);
});

test('sounding removes an initial silence, and leaves zero-based notes alone', () => {
  const notes = playedEvents([played(60, 3), played(62, 3.5)], []);
  assert.equal(sounding(notes)[0].onset, 0);
  assert.equal(sounding(notes)[1].onset, 0.5);
  assert.equal(sounding([]).length, 0);
});

test('filtering by hand keeps notes whose hand is unknown', () => {
  const events = playedEvents(
    [played(60, 0), played(48, 0.5), played(67, 1)],
    [
      { ...expected(60, 0, 1, 'RH'), status: 'correct', played_pitch: 60, onset_error_s: 0 },
      { ...expected(48, 0.5, 1, 'LH'), status: 'correct', played_pitch: 48, onset_error_s: 0 },
    ] as never,
  );
  const right = forHands(events, ['RH']);
  assert.deepEqual(
    right.map((note) => note.pitch),
    [60, 67],
    'the unmatched note is part of what was played, so it stays',
  );
  assert.equal(forHands(events, ['RH', 'LH']).length, 3);
});

test('the duration covers the last release', () => {
  assert.equal(durationOf(playedEvents([played(60, 0, 0.5), played(62, 1, 0.25)], [])), 1.25);
  assert.equal(durationOf([]), 0);
});

test('a logged note needs no conversion beyond milliseconds', () => {
  const events = loggedEvents([
    { onset_ms: 250, duration_ms: 400, pitch: 60, velocity: 64, channel: 0 },
  ]);
  assert.equal(events[0].onset, 0.25);
  assert.equal(events[0].duration, 0.4);
  assert.equal(events[0].hand, null, 'the passive log cannot know the hand');
});

test('a segment takes the notes inside it, edges included', () => {
  const notes = loggedEvents([
    { onset_ms: 0, duration_ms: 100, pitch: 60, velocity: 64, channel: 0 },
    { onset_ms: 500, duration_ms: 100, pitch: 62, velocity: 64, channel: 0 },
    { onset_ms: 1000, duration_ms: 100, pitch: 64, velocity: 64, channel: 0 },
  ]);
  assert.deepEqual(
    within(notes, 0, 500).map((note) => note.pitch),
    [60, 62],
    'a note exactly on the boundary belongs to the segment that ends there',
  );
  assert.deepEqual(within(notes, 501, 999).map((note) => note.pitch), []);
});

// --------------------------------------------------------------------------
// The sustain pedal
// --------------------------------------------------------------------------

const pedalAt = (onset_ms: number, value: number) => ({ onset_ms, value });

/** One note at 0s held for 0.5s, which is what most of these are about. */
const oneNote = () => [
  { pitch: 60, onset: 0, duration: 0.5, velocity: 0.6, hand: null },
];

test('the pedal holds a released note until it is lifted', () => {
  const notes = sustained(oneNote(), [pedalAt(0, 127), pedalAt(2000, 0)]);
  assert.equal(notes[0].duration, 2, 'held to the pedal-up, not to its release');
});

test('a note released after the pedal-up is left alone', () => {
  const notes = sustained(oneNote(), [pedalAt(0, 127), pedalAt(200, 0)]);
  assert.equal(notes[0].duration, 0.5, 'the release is already past the pedal-up');
});

test('pressing the pedal after the release does not bring a note back', () => {
  const notes = sustained(oneNote(), [pedalAt(1000, 127), pedalAt(3000, 0)]);
  assert.equal(notes[0].duration, 0.5, 'the synth has already let it go');
});

test('a pedal pressed before the note still catches it', () => {
  const notes = sustained(
    [{ pitch: 60, onset: 1, duration: 0.5, velocity: 0.6, hand: null }],
    [pedalAt(0, 127), pedalAt(3000, 0)],
  );
  assert.equal(notes[0].duration, 2, 'sounding until 3s, from a start at 1s');
});

test('a re-press only affects the notes under it', () => {
  const notes = sustained(
    [
      { pitch: 60, onset: 0, duration: 0.4, velocity: 0.6, hand: null },
      { pitch: 62, onset: 2, duration: 0.4, velocity: 0.6, hand: null },
      { pitch: 64, onset: 4, duration: 0.4, velocity: 0.6, hand: null },
    ],
    [pedalAt(0, 127), pedalAt(1000, 0), pedalAt(2000, 127), pedalAt(3000, 0)],
  );
  assert.equal(notes[0].duration, 1, 'held to the first pedal-up');
  assert.equal(notes[1].duration, 1, 'held to the second pedal-up');
  assert.equal(notes[2].duration, 0.4, 'released with no pedal down');
});

test('repeated down values do not restart the stretch', () => {
  // A piano sends 127 again on some presses, and a keyboard that repeats it must
  // not move the pedal-up to the wrong place.
  const notes = sustained(oneNote(), [pedalAt(0, 127), pedalAt(300, 127), pedalAt(1000, 0)]);
  assert.equal(notes[0].duration, 1);
});

test('a pedal that is never lifted extends to a tail, not forever', () => {
  const notes = sustained(oneNote(), [pedalAt(0, 127)]);
  assert.equal(notes[0].duration, 1, '0.5s of note + a 0.5s tail');
  assert.ok(Number.isFinite(notes[0].duration));
});

test('a pedal can only lengthen a note', () => {
  const notes = sustained(
    [{ pitch: 60, onset: 0, duration: 5, velocity: 0.6, hand: null }],
    [pedalAt(0, 127), pedalAt(1000, 0)],
  );
  assert.equal(notes[0].duration, 5, 'the note outlasts the pedal stretch');
});

test('no pedalling leaves the notes exactly as they were', () => {
  const before = oneNote();
  const after = sustained(before, []);
  assert.deepEqual(after, before);
  assert.notEqual(after, before, 'and hands back a copy rather than the array it was given');
});
