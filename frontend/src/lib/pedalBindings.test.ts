import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  DEFAULT_BINDINGS,
  HANDSFREE_ACTIONS,
  assignBinding,
  parseBindings,
  serialiseBindings,
} from './pedalBindings.ts';

test('the default puts the benign action on the easiest gesture', () => {
  // A tapped pedal is the easiest to fire by accident, so it gets the action that costs
  // nothing; stopping a take is the one action that can destroy work, so it needs a hold.
  assert.equal(DEFAULT_BINDINGS.single, 'mark_review');
  assert.equal(DEFAULT_BINDINGS.double, 'toggle_workout');
  assert.equal(DEFAULT_BINDINGS.hold, 'toggle_audio_capture');
  assert.equal(
    HANDSFREE_ACTIONS.includes('finish_sitting') && DEFAULT_BINDINGS.single !== 'finish_sitting',
    true,
  );
});

test('assigning an action takes it from whatever gesture held it', () => {
  // One action, one gesture: two gestures firing the same action is a pedal that does the
  // same thing twice, and the panel would be showing a partition it does not have.
  const before = { single: 'mark_review', double: 'toggle_workout', hold: null } as const;
  const after = assignBinding({ ...before }, 'hold', 'mark_review');
  assert.deepEqual(after, { single: null, double: 'toggle_workout', hold: 'mark_review' });
});

test('clearing a gesture touches no other', () => {
  const after = assignBinding({ ...DEFAULT_BINDINGS }, 'double', null);
  assert.deepEqual(after, {
    single: 'mark_review',
    double: null,
    hold: 'toggle_audio_capture',
  });
});

test('an unreadable preference falls back to the defaults', () => {
  assert.deepEqual(parseBindings(null), DEFAULT_BINDINGS);
  assert.deepEqual(parseBindings('not json'), DEFAULT_BINDINGS);
  assert.deepEqual(parseBindings('[]'), DEFAULT_BINDINGS);
});

test('an unknown action name falls back for that gesture only', () => {
  const parsed = parseBindings('{"single":"play_a_tune","double":null}');
  assert.equal(parsed.single, 'mark_review', 'the unknown name does not disable the pedal');
  assert.equal(parsed.double, null, 'an explicit null is honoured');
  assert.equal(parsed.hold, 'toggle_audio_capture');
});

test('a stored partition with a duplicate keeps the first and clears the rest', () => {
  // Hand-edited storage, or a build that wrote two slots. Keeping both would make one press
  // fire one action and the other gesture the same action, which the panel cannot show.
  const parsed = parseBindings(
    '{"single":"mark_review","double":"mark_review","hold":"mark_review"}',
  );
  assert.deepEqual(parsed, { single: 'mark_review', double: null, hold: null });
});

test('a round trip through storage is lossless', () => {
  const cleared = assignBinding({ ...DEFAULT_BINDINGS }, 'hold', null);
  assert.deepEqual(parseBindings(serialiseBindings(cleared)), cleared);
});
