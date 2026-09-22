import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  PEDAL_DOWN,
  durationOf,
  firstOnset,
  forHands,
  loggedEvents,
  playedEvents,
  resolveOverlaps,
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

test('the pedal-down threshold is the specification rule, written once', () => {
  // 0-63 is off and 64-127 is on. A continuous pedal is stored at full resolution,
  // but every consumer has to answer this one question, so it is answered here and
  // imported by both — the value used to be spelled out twice, in two files.
  assert.equal(PEDAL_DOWN, 64);
  const half = sustained(oneNote(), [pedalAt(0, PEDAL_DOWN - 1), pedalAt(2000, 0)]);
  assert.equal(half[0].duration, 0.5, 'a half-depressed pedal reads as released');
  const down = sustained(oneNote(), [pedalAt(0, PEDAL_DOWN), pedalAt(2000, 0)]);
  assert.equal(down[0].duration, 2, 'and at the threshold it is down');
});

// --------------------------------------------------------------------------
// A re-struck key, and the note-off that used to silence it
// --------------------------------------------------------------------------

const held = (pitch: number, onset: number, duration: number) => ({
  pitch,
  onset,
  duration,
  velocity: 0.6,
  hand: null,
});

test('a note ends where the same key is struck again', () => {
  const notes = resolveOverlaps([held(60, 0, 2), held(60, 1, 3)]);
  assert.equal(notes[0].duration, 1, 'MIDI has one note-off per pitch, so it cannot overlap');
  assert.equal(notes[1].duration, 3, 'the re-struck note keeps its own length');
});

test('notes that never overlap are left exactly as they were', () => {
  const before = [held(60, 0, 0.5), held(60, 1, 0.5)];
  assert.deepEqual(resolveOverlaps(before), before);
});

test('different pitches may overlap freely', () => {
  const before = [held(60, 0, 2), held(64, 0.5, 2)];
  assert.deepEqual(resolveOverlaps(before), before);
});

test('the result is in onset order, so a clamped note-off is sent first', () => {
  const notes = resolveOverlaps([held(60, 1, 1), held(60, 0, 1.5)]);
  assert.deepEqual(
    notes.map((note) => note.onset),
    [0, 1],
    'the player pumps the queue in order, so the earlier note is scheduled first',
  );
});

test('two notes at one instant on one key collapse to the longer', () => {
  const notes = resolveOverlaps([held(60, 0, 0.2), held(60, 0, 0.9)]);
  assert.equal(notes.length, 1, 'a zero-length note is not something that can sound');
  assert.equal(notes[0].duration, 0.9);
});

test('a pedal-held note no longer silences the key struck again under it', () => {
  // The owner's report, measured on their own Brahms session. Sustaining the first
  // note to the pedal-up carries it past a re-strike of the same key, and the stale
  // note-off then killed the second note at the instant the pedal came up — a note
  // the hand was still holding. Both halves are needed: the pedal creates the
  // overlap, and this removes it.
  const sounding = sustained([held(60, 0, 1), held(60, 1.5, 7)], [pedalAt(0, 127), pedalAt(3000, 0)]);
  assert.equal(sounding[0].duration, 3, 'the pedal carries the first note to the pedal-up');

  const scheduled = resolveOverlaps(sounding);
  assert.equal(scheduled[0].duration, 1.5, 'and it stops where the key was struck again');
  assert.equal(scheduled[1].duration, 7, 'the held note keeps every millisecond it was held');
});

// --- the first onset of nothing ---
//
// A regression guard rather than a new claim: `firstOnset` ran the same reduce twice, once to
// test it against `Infinity` and once to answer with it, and the cleanup is behaviour-free. The
// test exists so the rewrite is pinned, and it is falsified by breaking the loop's comparison.

test('the first onset is the lowest one, or zero when there are none', () => {
  assert.equal(firstOnset([]), 0);
  assert.equal(
    firstOnset(
      loggedEvents([{ onset_ms: 400, duration_ms: 100, pitch: 60, velocity: 64, channel: 0 }]),
    ),
    0.4,
  );
  assert.equal(
    firstOnset(
      loggedEvents([
        { onset_ms: 900, duration_ms: 100, pitch: 60, velocity: 64, channel: 0 },
        { onset_ms: 200, duration_ms: 100, pitch: 62, velocity: 64, channel: 0 },
        { onset_ms: 500, duration_ms: 100, pitch: 64, velocity: 64, channel: 0 },
      ]),
    ),
    0.2,
    'the lowest onset wins, not the first in the list',
  );
});
