import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  PIECE_COLOR_COUNT,
  pieceColorIndex,
  pieceColorSlots,
  segmentAtMs,
  segmentStep,
  seekPlan,
  stripTicks,
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

// --- what a seek does to the sound ---
//
// The strip is one surface with two meanings, and which one applies is not a matter of taste:
// it follows whether anything is playing. Silence in, silence out; sound in, sound moved. These
// tests are the whole rule, because the component can only wire them to a pointer.

const spans = [
  { id: 1, start_ms: 20_000, end_ms: 40_000 },
  { id: 2, start_ms: 60_000, end_ms: 90_000 },
];

test('a seek with nothing playing moves the playhead and starts nothing', () => {
  const plan = seekPlan(null, 120_000, 65_000, segmentAtMs(spans, 65_000));
  assert.deepEqual(plan, { atMs: 65_000, resume: null });
});

test('a seek inside the sounding range keeps that range', () => {
  const playing = { fromMs: 0, toMs: 120_000, segmentId: null };
  const plan = seekPlan(playing, 120_000, 70_000, segmentAtMs(spans, 70_000));
  assert.deepEqual(plan.resume, playing, 'the whole sitting keeps playing the whole sitting');
});

test('a seek out of the sounding range moves the range to the segment it landed in', () => {
  const playing = { fromMs: 20_000, toMs: 40_000, segmentId: 1 };
  const plan = seekPlan(playing, 120_000, 70_000, segmentAtMs(spans, 70_000));
  assert.deepEqual(
    plan.resume,
    { fromMs: 60_000, toMs: 90_000, segmentId: 2 },
    'leaving a segment for another one plays the one you asked for',
  );
});

test('a seek out of the range into a silence falls back to the whole sitting', () => {
  const playing = { fromMs: 20_000, toMs: 40_000, segmentId: 1 };
  const plan = seekPlan(playing, 120_000, 110_000, null);
  assert.deepEqual(plan.resume, { fromMs: 0, toMs: 120_000, segmentId: null });
});

test('a transport step plays even when nothing was playing', () => {
  const whole = { fromMs: 0, toMs: 120_000, segmentId: null };
  const plan = seekPlan(null, 120_000, 30_000, segmentAtMs(spans, 30_000), whole);
  assert.deepEqual(plan.resume, whole, 'a transport button that moved but stayed silent is a dead button');
});

test('a seek is clamped to the sitting at both ends', () => {
  assert.equal(seekPlan(null, 120_000, -5_000, null).atMs, 0);
  assert.equal(seekPlan(null, 120_000, 500_000, null).atMs, 120_000);
});

test('a range already at the very start still counts as containing the start', () => {
  const playing = { fromMs: 0, toMs: 40_000, segmentId: 1 };
  assert.deepEqual(seekPlan(playing, 120_000, 0, segmentAtMs(spans, 0)).resume, playing);
});

// --- stepping from segment to segment ---

test('forward steps to the start of the next segment', () => {
  assert.equal(segmentStep(spans, 25_000, 1, 120_000), 60_000);
  assert.equal(segmentStep(spans, 0, 1, 120_000), 20_000, 'from the intro, the first segment');
});

test('forward past the last segment goes to the end rather than nowhere', () => {
  assert.equal(segmentStep(spans, 85_000, 1, 120_000), 120_000);
});

test('back restarts a segment you are well into, and leaves one you only just entered', () => {
  assert.equal(segmentStep(spans, 30_000, -1, 120_000), 20_000, 'well inside: back to its start');
  assert.equal(
    segmentStep(spans, 61_000, -1, 120_000),
    20_000,
    'a second into the second segment is "previous segment", or repeated presses would stick',
  );
  assert.equal(segmentStep(spans, 70_000, -1, 120_000), 60_000);
});

test('back before the first segment reaches the start of the sitting', () => {
  assert.equal(segmentStep(spans, 0, -1, 120_000), 0);
  assert.equal(segmentStep(spans, 20_500, -1, 120_000), 0, 'there is nothing before the first one');
});

test('stepping with no segments is the two ends of the sitting', () => {
  assert.equal(segmentStep([], 5_000, 1, 120_000), 120_000);
  assert.equal(segmentStep([], 5_000, -1, 120_000), 0);
});

// --- the clock along the strip ---

test('the ruler divides the sitting evenly and starts at zero', () => {
  assert.deepEqual(stripTicks(120_000, 4), [0, 30_000, 60_000, 90_000, 120_000]);
  assert.deepEqual(stripTicks(120_000, 1), [0, 120_000]);
});

test('the ruler survives the degenerate cases', () => {
  assert.deepEqual(stripTicks(0, 4), [0, 0, 0, 0, 0]);
  assert.deepEqual(stripTicks(1_000, 0), [0, 1_000], 'no divisions is still the two ends');
  assert.deepEqual(stripTicks(1_000, -3), [0, 1_000]);
});
