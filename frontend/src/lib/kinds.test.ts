import { test } from 'node:test';
import assert from 'node:assert/strict';

import { PRACTICE_KINDS, kindCounts, practiceKindLabel } from './kinds.ts';

test('the taxonomy is exactly the seven kinds the API validates', () => {
  assert.deepEqual(
    PRACTICE_KINDS.map((entry) => entry.id),
    ['run_through', 'slow', 'section', 'hands_separate', 'memory', 'warm_up', 'other'],
  );
});

test('sight-reading is not a kind — the segment source already owns it', () => {
  assert.equal(
    (PRACTICE_KINDS.map((entry) => entry.id) as string[]).includes('sight_reading'),
    false,
  );
});

test('a kind has words, and nothing reads as undefined on a screen', () => {
  assert.equal(practiceKindLabel('slow'), 'Slow');
  assert.equal(practiceKindLabel(null), 'Not characterised');
  assert.equal(practiceKindLabel('banjo'), 'banjo');
});

test('an offer is a question and only a confirmed basis counts', () => {
  assert.equal(kindCounts('offered'), false);
  assert.equal(kindCounts('manual'), true);
  assert.equal(kindCounts('accepted'), true);
  assert.equal(kindCounts(null), false);
});
