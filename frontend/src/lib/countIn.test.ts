import { test } from 'node:test';
import assert from 'node:assert/strict';

import { COUNT_IN_BARS, countInBeats } from './countIn.ts';

test('the choices are none, one bar and two bars', () => {
  assert.deepEqual([...COUNT_IN_BARS], [0, 1, 2]);
});

test('a bar is however many beats the meter puts in it', () => {
  assert.equal(countInBeats(1, [4]), 4, '4/4');
  assert.equal(countInBeats(2, [4]), 8);
  assert.equal(countInBeats(0, [4]), 0);
  assert.equal(countInBeats(1, [2]), 2, '6/8 counts two dotted-quarter beats in a bar');
  assert.equal(countInBeats(1, [3]), 3, '3/4');
});

test('nonsense reads as no count-in rather than as a negative one', () => {
  assert.equal(countInBeats(-1, [4]), 0);
  assert.equal(countInBeats(1.7, [4]), 4, 'fractional bars truncate');
  assert.equal(countInBeats(1, []), 4, 'and an empty meter falls back to four');
});
