import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  PIECE_COLOR_COUNT,
  pieceColorIndex,
  pieceColorSlots,
  segmentAtMs,
} from './timelineStrip.ts';

/** Two ids the palette gives the same slot, found rather than hardcoded. */
function clashingPair(): [number, number] {
  const seen = new Map<number, number>();
  for (let id = 1; id <= 500; id += 1) {
    const slot = pieceColorIndex(id);
    const first = seen.get(slot);
    if (first !== undefined) return [first, id];
    seen.set(slot, id);
  }
  throw new Error('no two ids in 1..500 share a slot; the hash is not mixing');
}

test('a slot is always one the stylesheet defines', () => {
  for (const id of [0, 1, 2, 7, 8, 99, 12345, 2 ** 31 - 1]) {
    const slot = pieceColorIndex(id);
    assert.ok(
      Number.isInteger(slot) && slot >= 0 && slot < PIECE_COLOR_COUNT,
      `id ${id} gave slot ${slot}`,
    );
  }
});

test('a piece on its own wears the colour its id gives it', () => {
  // The point of deriving the slot from the id: the same piece is the same colour in every
  // sitting, so an old sitting is read at a glance rather than re-learned each time.
  for (const id of [3, 42, 501]) {
    assert.equal(pieceColorSlots([id]).get(id), pieceColorIndex(id));
  }
});

test('the colour that moves is never the lowest id in the sitting', () => {
  // Resolution walks in id order, so the piece that has been in the library longest keeps the
  // colour it has always had and the newcomer moves. Without that, labelling a *new* piece
  // could recolour an old one, which is the recognition this feature is for.
  const ids = [30, 2, 11, 4];
  assert.equal(pieceColorSlots(ids).get(2), pieceColorIndex(2));
});

test('the answer does not depend on the order the sitting lists its pieces', () => {
  // A split or a re-segment rearranges the attempts; the colours must not follow. The fixture is
  // a clashing pair, because with no clash every order gives the same answer and the assertion
  // could not fail.
  const [low, high] = clashingPair();
  assert.deepEqual(pieceColorSlots([low, high]), pieceColorSlots([high, low]));
  const forwards = pieceColorSlots([4, 11, 2, 30]);
  const backwards = pieceColorSlots([30, 2, 11, 4]);
  assert.deepEqual(forwards, backwards);
});

test('no two pieces in one sitting wear the same colour', () => {
  const ids = Array.from({ length: PIECE_COLOR_COUNT }, (_, index) => index + 1);
  const slots = pieceColorSlots(ids);
  assert.equal(new Set(slots.values()).size, PIECE_COLOR_COUNT);
});

test('a clash moves the later piece, and leaves the earlier one where it was', () => {
  const [low, high] = clashingPair();
  const base = pieceColorIndex(low);
  assert.equal(pieceColorIndex(high), base, 'the pair this test found must actually clash');
  const slots = pieceColorSlots([low, high]);
  assert.equal(slots.get(low), base, 'the lower id keeps its own colour');
  assert.notEqual(slots.get(high), base, 'the higher id moves to a free one');
  // And the whole point of moving it rather than sharing: the two are told apart.
  assert.notEqual(slots.get(high), slots.get(low));
});

test('more pieces than the palette repeats colours without losing any piece', () => {
  const ids = Array.from({ length: PIECE_COLOR_COUNT + 5 }, (_, index) => index + 1);
  const slots = pieceColorSlots(ids);
  assert.equal(slots.size, ids.length, 'every piece still gets a slot');
  for (const slot of slots.values()) {
    assert.ok(slot >= 0 && slot < PIECE_COLOR_COUNT, `slot ${slot} is outside the palette`);
  }
});

test('a repeated or empty list is read without inventing pieces', () => {
  assert.equal(pieceColorSlots([]).size, 0);
  assert.equal(pieceColorSlots([6, 6, 6]).size, 1);
});

// --- which segment a click means ---

const segments = [
  { id: 'a', start_ms: 1_000, end_ms: 2_000 },
  { id: 'b', start_ms: 5_000, end_ms: 6_000 },
];

test('a click inside a segment means that segment', () => {
  assert.equal(segmentAtMs(segments, 1_500)?.id, 'a');
  assert.equal(segmentAtMs(segments, 5_500)?.id, 'b');
});

test('a boundary is inside the segment it closes', () => {
  assert.equal(segmentAtMs(segments, 1_000)?.id, 'a');
  assert.equal(segmentAtMs(segments, 2_000)?.id, 'a');
  assert.equal(segmentAtMs(segments, 5_000)?.id, 'b');
  assert.equal(segmentAtMs(segments, 6_000)?.id, 'b');
});

test('a click in the silence between two segments means the nearer one', () => {
  // 3.5 s is equidistant, and a tie has to resolve the same way every time or the strip would
  // jump to whichever segment the list happened to put first.
  assert.equal(segmentAtMs(segments, 3_500)?.id, 'a', 'a tie stays with the earlier segment');
  assert.equal(segmentAtMs(segments, 4_000)?.id, 'b', 'past the middle it is the later one');
});

test('outside the sitting the nearest edge still answers', () => {
  assert.equal(segmentAtMs(segments, 0)?.id, 'a');
  assert.equal(segmentAtMs(segments, 60_000)?.id, 'b');
});

test('no segments at all is null rather than a guess', () => {
  assert.equal(segmentAtMs([], 1_000), null);
});
