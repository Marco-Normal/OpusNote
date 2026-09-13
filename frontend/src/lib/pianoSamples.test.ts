import { test } from 'node:test';
import assert from 'node:assert/strict';

import { midiOfNote, sampleFile, samplePitches, sampleUrls, toneNoteName } from './pianoSamples.ts';

/** The list the backend serves, as it appears in the status payload. */
const STEMS = [
  'A0', 'C1', 'Ds1', 'Fs1', 'A1',
  'C2', 'Ds2', 'Fs2', 'A2',
  'C3', 'Ds3', 'Fs3', 'A3',
  'C4', 'Ds4', 'Fs4', 'A4',
  'C5', 'Ds5', 'Fs5', 'A5',
  'C6', 'Ds6', 'Fs6', 'A6',
  'C7', 'Ds7', 'Fs7', 'A7',
  'C8',
];

/** Tone's own note pattern, copied from `tone/build/esm/core/type/Frequency.js`. */
const TONE_NOTE = /^([a-g]{1}(?:b|#|##|x|bb|###|#x|x#|bbb)?)(-?[0-9]+)$/i;

test('a file stem becomes a note name a music library can parse', () => {
  assert.equal(toneNoteName('Ds4'), 'D#4');
  assert.equal(toneNoteName('Fs1'), 'F#1');
  assert.equal(toneNoteName('A0'), 'A0', 'no accidental to translate');
  assert.equal(toneNoteName('C8'), 'C8');
});

test('every sample the backend serves is a valid Tone note name', () => {
  // The bug this module exists for: `urls: { Ds4: 'Ds4.mp3' }` throws inside Tone's
  // parser for every sharp note, and the instrument loads nothing.
  for (const stem of STEMS) {
    const name = toneNoteName(stem);
    assert.ok(TONE_NOTE.test(name), `${stem} -> ${name} is not a note name Tone accepts`);
  }
  assert.equal(STEMS.filter((stem) => stem.includes('s')).length, 14, 'fourteen sharps in the set');
});

test('the sharp spelling that a URL allows is not the one a note name needs', () => {
  assert.ok(!TONE_NOTE.test('Ds4'), 'which is why the translation is not optional');
});

test('the url map keys on the note name and points at the file', () => {
  const urls = sampleUrls(['A0', 'Ds4']);
  assert.deepEqual(urls, { A0: 'A0.mp3', 'D#4': 'Ds4.mp3' });
  assert.equal(sampleFile('Fs7'), 'Fs7.mp3');
});

test('the mapping reaches the right pitches', () => {
  assert.equal(midiOfNote('A0'), 21, 'the lowest key on a piano');
  assert.equal(midiOfNote('C4'), 60, 'middle C');
  assert.equal(midiOfNote('D#4'), 63);
  assert.equal(midiOfNote('C8'), 108, 'the highest key');
  assert.equal(midiOfNote('nonsense'), null);
});

test('the sample set spans the keyboard in minor thirds', () => {
  const pitches = samplePitches(STEMS);
  assert.equal(pitches.length, STEMS.length, 'every stem is a pitch');
  assert.deepEqual(
    [...new Set(pitches.slice(1).map((pitch, index) => pitch - pitches[index]))],
    [3],
  );
  assert.equal(pitches[0], 21);
  assert.equal(pitches[pitches.length - 1], 108);
});
