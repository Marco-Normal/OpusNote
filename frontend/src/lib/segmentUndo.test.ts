import { test } from 'node:test';
import assert from 'node:assert/strict';

import { inverseOf } from './segmentUndo.ts';
import type { SegmentSummary } from './types';

/** A segment with only the fields the inverse reads; the rest are noise for these tests. */
function seg(id: number, startMs: number, endMs: number, pieceId: number | null = null): SegmentSummary {
  return {
    id,
    sitting_id: 1,
    start_ms: startMs,
    end_ms: endMs,
    piece_id: pieceId,
    piece_title: null,
    composer_name: null,
    source: null,
    workout_id: null,
    confidence: null,
    identified_by: null,
    practice_kind: null,
    practice_kind_basis: null,
    note_count: 1,
    metrics: null,
    candidates: [],
  };
}

test('a split is undone by merging the two halves back', () => {
  const before = [seg(1, 0, 8_000)];
  const after = [seg(1, 0, 3_000), seg(2, 4_000, 8_000)];
  assert.deepEqual(inverseOf(before, after), {
    kind: 'merge',
    segmentId: 1,
    otherId: 2,
    label: 'Undo split',
  });
});

test('a merge is undone by splitting at the boundary that was absorbed', () => {
  const before = [seg(1, 0, 3_000), seg(2, 4_000, 8_000)];
  const after = [seg(1, 0, 8_000)];
  assert.deepEqual(inverseOf(before, after), {
    kind: 'split',
    segmentId: 1,
    atMs: 4_000,
    label: 'Undo merge',
  });
});

test('a piece label is undone by putting the old one back, including a cleared one', () => {
  const before = [seg(1, 0, 8_000, 7)];
  const after = [seg(1, 0, 8_000, null)];
  assert.deepEqual(inverseOf(before, after), {
    kind: 'assign',
    segmentId: 1,
    pieceId: 7,
    label: 'Undo label',
  });

  const wasClear = [seg(1, 0, 8_000, null)];
  const nowLabelled = [seg(1, 0, 8_000, 7)];
  assert.deepEqual(inverseOf(wasClear, nowLabelled), {
    kind: 'assign',
    segmentId: 1,
    pieceId: null,
    label: 'Undo label',
  });
});

test('a re-segment has no inverse, and says so by returning null', () => {
  const before = [seg(1, 0, 3_000), seg(2, 4_000, 8_000)];
  const after = [seg(9, 0, 8_000)];
  assert.equal(inverseOf(before, after), null);
});

test('answering the matcher has no inverse', () => {
  const before = [seg(1, 0, 8_000, null)];
  const after = [seg(1, 0, 8_000, 7)];
  // The id and the label both moved, which is an assign as far as the *rows* are concerned;
  // what makes `identify` different is that the route, not the rows, records the outcome. The
  // view therefore never offers undo for it, and this test pins the reasoning rather than the
  // behaviour: `inverseOf` reports what it can see, and nothing more.
  assert.deepEqual(inverseOf(before, after), {
    kind: 'assign',
    segmentId: 1,
    pieceId: null,
    label: 'Undo label',
  });
});

test('nothing changed means nothing to undo', () => {
  const same = [seg(1, 0, 8_000, 3)];
  assert.equal(inverseOf(same, [seg(1, 0, 8_000, 3)]), null);
});

test('an empty before has no inverse, so the first load cannot offer one', () => {
  assert.equal(inverseOf([], [seg(1, 0, 8_000)]), null);
});
