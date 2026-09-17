import { test } from 'node:test';
import assert from 'node:assert/strict';

import { shouldCut, shouldStart } from './audioCut.ts';

test('a take is cut exactly when the server would cut the notes', () => {
  const base = { nowMs: 100_000, chunkStartedMs: 90_000, segmentGapMs: 8_000, maxChunkMs: 600_000 };
  assert.equal(shouldCut({ ...base, lastNoteMs: 95_000 }), false, 'still playing');
  assert.equal(shouldCut({ ...base, lastNoteMs: 92_001 }), false, 'one ms short of the gap');
  assert.equal(shouldCut({ ...base, lastNoteMs: 92_000 }), true, 'the gap is reached');
  assert.equal(shouldCut({ ...base, lastNoteMs: 91_000 }), true, 'and past it');
});

test('no note at all is treated as silence, not as playing', () => {
  assert.equal(
    shouldCut({ nowMs: 100_000, chunkStartedMs: 90_000, lastNoteMs: null, segmentGapMs: 8_000, maxChunkMs: 600_000 }),
    true,
  );
});

test('a long unbroken passage is cut anyway, at the maximum length', () => {
  const base = { chunkStartedMs: 300_000, segmentGapMs: 8_000, maxChunkMs: 600_000 };
  assert.equal(shouldCut({ ...base, nowMs: 899_000, lastNoteMs: 898_999 }), false, 'short of the cap');
  assert.equal(shouldCut({ ...base, nowMs: 900_001, lastNoteMs: 900_000 }), true, 'past the cap');
});

test('a take starts on the first note and never on silence', () => {
  assert.equal(shouldStart({ lastNoteMs: null, recording: false }), false);
  assert.equal(shouldStart({ lastNoteMs: 5_000, recording: false }), true);
  assert.equal(shouldStart({ lastNoteMs: 5_000, recording: true }), false, 'already recording');
  assert.equal(shouldStart({ lastNoteMs: null, recording: true }), false);
});
