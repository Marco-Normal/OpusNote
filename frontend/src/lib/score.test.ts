import { test } from 'node:test';
import assert from 'node:assert/strict';

import { handForPart, inkColor, pageBackground, statusColors } from './score.ts';

// This module was unloadable by `node --test` until the renderer's constructor
// stopped using a TypeScript parameter property, which Node's strip-only type
// handling refuses. Everything below the seam was therefore untested while the
// file held the client's worst recorded defect history.

/**
 * The three configurations the generator actually emits.
 *
 * `generator.py` names the melody part "Right Hand" or "Left Hand" from the
 * resolved texture and gives the accompaniment "Left Hand" as a second part, so
 * these tuples are the real inputs, not invented ones. The middle row is the one
 * the renderer got wrong: a single part named "Left Hand" sits on staff index 0,
 * and reading position instead of identity called it "RH".
 */
test('the hand follows the part name in every configuration the generator emits', () => {
  // texture 1 — the right hand alone.
  assert.equal(handForPart('P1', 'Right Hand', 0), 'RH');
  // texture 2 — the left hand alone. One part, staff index 0.
  assert.equal(handForPart('P1', 'Left Hand', 0), 'LH');
  // texture 3 upward — both hands, melody first.
  assert.equal(handForPart('P1', 'Right Hand', 0), 'RH');
  assert.equal(handForPart('P2', 'Left Hand', 1), 'LH');
});

test('a left-hand part on the first staff is not mistaken for the right hand', () => {
  // The regression, stated as its own claim: position says RH, identity says LH,
  // and identity is the authority because the API labelled the timeline from it.
  assert.equal(handForPart('P1', 'Left Hand', 0), 'LH', 'staff 0 does not mean right hand');
  assert.notEqual(handForPart('P1', 'Left Hand', 0), handForPart('P1', 'Right Hand', 0));
});

test('an explicit id is read before the name, as the backend reads it', () => {
  assert.equal(handForPart('RH1', 'whatever', 0), 'RH');
  assert.equal(handForPart('LH1', 'whatever', 0), 'LH');
  assert.equal(handForPart('LH-staff-2', '', 0), 'LH');
});

test('matching is case-insensitive, because a part name is arbitrary text', () => {
  assert.equal(handForPart('P1', 'LEFT HAND', 0), 'LH');
  assert.equal(handForPart('P1', 'left hand', 0), 'LH');
  assert.equal(handForPart('p1', 'Right Hand', 1), 'RH');
});

test('an unnamed part falls back to order, which is what the backend does', () => {
  // Curated or imported MusicXML may name nothing at all. The fallback is
  // deliberate and mirrors `expected.py`'s `"RH" if index == 0 else "LH"`; it is
  // only for the case where neither the id nor the name says anything.
  assert.equal(handForPart('', '', 0), 'RH');
  assert.equal(handForPart('', '', 1), 'LH');
  assert.equal(handForPart(null, null, 0), 'RH');
  assert.equal(handForPart(undefined, undefined, 1), 'LH');
  // A part named "Piano" with a non-RH/LH id is unnamed as far as this rule goes.
  assert.equal(handForPart('P1', 'Piano', 0), 'RH');
  assert.equal(handForPart('P2', 'Piano', 1), 'LH');
});

/**
 * The palette the fill assertions in the browser suite compare against. These
 * constants were reachable only from the renderer before the constructor change.
 */
test('the score palette is stable per theme and never accidentally equal', () => {
  const light = statusColors(false);
  const dark = statusColors(true);
  assert.equal(light.correct, '#15803d', 'the colour the e2e measures painted noteheads against');
  assert.equal(dark.correct, statusColors(true).correct, 'and it is a constant, not a fresh object each call');
  assert.notDeepEqual(light, dark, 'feedback colours are re-tuned per theme for contrast');
  assert.notEqual(light.correct, light.wrong_pitch, 'correct and wrong must never be the same colour');
  assert.notEqual(pageBackground(false), pageBackground(true), 'the paper differs by theme');
  assert.notEqual(inkColor(false), inkColor(true), 'and so does the ink');
});
