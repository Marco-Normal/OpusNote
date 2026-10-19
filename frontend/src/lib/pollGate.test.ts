import { test } from 'node:test';
import assert from 'node:assert/strict';

import { createPollRunner, detailIsStale } from './pollGate.ts';

/** A promise plus the two functions that settle it, so a call can be held in flight. */
function deferred(): { promise: Promise<void>; resolve: () => void; reject: (e: Error) => void } {
  let resolve!: () => void;
  let reject!: (e: Error) => void;
  const promise = new Promise<void>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

test('a refresh already in flight is not started a second time', async () => {
  let calls = 0;
  const gate = deferred();
  const poll = createPollRunner(async () => {
    calls += 1;
    await gate.promise;
  });

  const first = poll.fire();
  const second = poll.fire();
  assert.equal(calls, 1, 'the second call must not reach the server while the first is queued');
  assert.equal(poll.running, true);

  gate.resolve();
  await Promise.all([first, second]);
  assert.equal(calls, 1, 'and the ignored call must not run later either');
  assert.equal(poll.running, false);
});

test('the next refresh after one finishes does run', async () => {
  let calls = 0;
  const poll = createPollRunner(async () => {
    calls += 1;
  });
  await poll.fire();
  await poll.fire();
  assert.equal(calls, 2);
});

test('a refresh that throws still releases the gate', async () => {
  let calls = 0;
  const poll = createPollRunner(async () => {
    calls += 1;
    throw new Error('the server went away');
  });
  await assert.rejects(() => poll.fire());
  assert.equal(poll.running, false, 'a failed read must not wedge the poll for ever');
  await assert.rejects(() => poll.fire());
  assert.equal(calls, 2);
});

const row = { note_count: 120, duration_s: 90, segment_count: 3 };
const detail = { note_count: 120, duration_s: 90, segments: [{}, {}, {}], preparing: false };

test('an unchanged sitting is not re-read', () => {
  assert.equal(detailIsStale(row, detail), false);
});

test('nothing loaded yet is worth reading', () => {
  assert.equal(detailIsStale(row, null), true);
});

test('a sitting still being prepared keeps asking', () => {
  assert.equal(detailIsStale(row, { ...detail, preparing: true }), true);
});

test('a new segment, a new note and a longer sitting all count as changed', () => {
  assert.equal(detailIsStale({ ...row, segment_count: 4 }, detail), true, 'a split appeared');
  assert.equal(detailIsStale({ ...row, segment_count: 2 }, detail), true, 'a merge happened');
  assert.equal(detailIsStale({ ...row, note_count: 121 }, detail), true, 'notes arrived');
  assert.equal(detailIsStale({ ...row, duration_s: 91 }, detail), true, 'the sitting grew');
});
