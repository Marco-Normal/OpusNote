import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  fallProgress,
  isBlackKey,
  keyLayout,
  pitchRange,
  slotFor,
  timeAtHeight,
  visibleNotes,
} from './pianoRoll.ts';

const note = (pitch: number, onset: number, duration = 0.5) => ({ pitch, onset, duration });

test('the black keys are the black keys', () => {
  // One octave from C: C D E F G A B.
  assert.deepEqual(
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map(isBlackKey),
    [false, true, false, true, false, false, true, false, true, false, true, false],
  );
  assert.equal(isBlackKey(61), true, 'C#4');
  assert.equal(isBlackKey(60), false, 'C4');
});

test('the range is widened to whole octaves with a key of margin', () => {
  // Anchored to A, because A0 is the piano's lowest key: C4..E4 widens to A3..C5
  // rather than to the C-to-B octave a naive rounding would give.
  assert.deepEqual(pitchRange([note(60, 0), note(64, 1)]), { low: 57, high: 72 });
  assert.deepEqual(pitchRange([note(21, 0), note(108, 1)]), { low: 21, high: 108 });
  assert.deepEqual(pitchRange([]), { low: 48, high: 72 }, 'nothing to show, show the middle');
});

test('white keys share the width and black keys sit between them', () => {
  // C4 to B4: seven white keys, five black ones.
  const slots = keyLayout(60, 71);
  const whites = slots.filter((slot) => !slot.black);
  const blacks = slots.filter((slot) => slot.black);
  assert.equal(whites.length, 7);
  assert.equal(blacks.length, 5);
  assert.ok(Math.abs(whites[0].left - 0) < 1e-9);
  assert.ok(Math.abs(whites[0].width - 1 / 7) < 1e-9);
  // C# sits on the boundary between C and D, and is narrower.
  const cSharp = slotFor(slots, 61);
  assert.ok(cSharp !== null && cSharp.black);
  assert.ok(cSharp!.left > whites[0].left && cSharp!.left < whites[1].left + 1e-9);
  assert.ok(cSharp!.width < whites[0].width);
});

test('a black key wins over the white key it is drawn on top of', () => {
  const slots = keyLayout(60, 71);
  assert.equal(slotFor(slots, 61)?.black, true);
  assert.equal(slotFor(slots, 60)?.black, false);
  assert.equal(slotFor(slots, 200), null, 'a pitch outside the range has no column');
});

test('a note falls from the top to the keyboard line as its moment arrives', () => {
  assert.equal(fallProgress(10, 10, 4), 1, 'sounding now is at the keyboard');
  assert.equal(fallProgress(14, 10, 4), 0, 'four seconds away is at the top');
  assert.ok(Math.abs(fallProgress(12, 10, 4) - 0.5) < 1e-9, 'halfway is halfway');
  assert.ok(fallProgress(10, 12, 4) > 1, 'a note left behind is past the line');
});

test('clicking a height gives back the time it represents', () => {
  // The inverse of the fall, so a click means what it looks like.
  assert.equal(timeAtHeight(1, 10, 4), 10);
  assert.equal(timeAtHeight(0, 10, 4), 14);
  assert.equal(timeAtHeight(0.5, 10, 4), 12);
});

test('long notes stay visible after their onset has gone by', () => {
  // The point of a falling-note view for held bass notes: the note started before
  // the window, is still sounding through it, and is drawn across the whole view.
  const slots = keyLayout(48, 72);
  const held = note(48, 0, 12);
  const placed = visibleNotes([held], slots, 6, 4);
  assert.equal(placed.length, 1);
  assert.ok(placed[0].top < 0, 'its onset has passed the top of the view');
  assert.ok(placed[0].top + placed[0].height > 1, 'and it is still sounding at the line');
});

test('a rectangle never has a negative height', () => {
  // The sign of this subtraction is easy to get backwards, and a `max(sliver, …)`
  // turns the mistake into a keyboard of hairlines instead of an error.
  const slots = keyLayout(48, 72);
  for (const item of visibleNotes([note(60, 1, 0.5), note(62, 2, 2)], slots, 0, 4)) {
    assert.ok(item.height > 0, `height ${item.height}`);
    for (const other of visibleNotes([note(64, 3, 1)], slots, 0, 4)) {
      assert.ok(other.height > 0);
    }
  }
  // A half-second note a quarter of the way down the view is an eighth of its height.
  const [placed] = visibleNotes([note(60, 1, 0.5)], slots, 0, 4);
  assert.ok(Math.abs(placed.height - 0.125) < 1e-9, `height ${placed.height}`);
});

test('only the notes in the window are drawn', () => {
  const slots = keyLayout(48, 72);
  const notes = [note(60, 1), note(62, 6), note(64, 20)];
  const placed = visibleNotes(notes, slots, 5, 4);
  assert.deepEqual(
    placed.map((item) => item.note.pitch),
    [62],
    'the past is gone and the future is not on screen yet',
  );
});

test('a note with no column is skipped rather than drawn at the left edge', () => {
  const slots = keyLayout(60, 71);
  const placed = visibleNotes([note(30, 1)], slots, 0, 4);
  assert.deepEqual(placed, []);
});

test('a very short note still gets a visible sliver', () => {
  const slots = keyLayout(60, 72);
  const placed = visibleNotes([note(60, 1, 0.01)], slots, 0, 4);
  assert.equal(placed.length, 1);
  assert.ok(placed[0].height >= 0.004, 'a 10 ms note is a line, not nothing');
});
