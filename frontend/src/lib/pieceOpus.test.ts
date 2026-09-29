import { test } from 'node:test';
import assert from 'node:assert/strict';

import { OPUS_NEEDS_A_NUMBER, normaliseOpus, opusProblem } from './pieceOpus.ts';

/**
 * The same table as `backend/tests/test_opus.py::LIBRARY_OPUSES`, which is the authority
 * (`backend/app/repertoire/opus.py`). This file mirrors the rule so the editor can show the
 * canonical form *before* a save; if the two ever disagree, the server's answer is the one
 * that is stored, and a mismatch here is a defect in this file.
 *
 * These are the strings the owner's real library actually held — not tidied ones.
 */
const LIBRARY_OPUSES: [string, string][] = [
  ['Op 10. No. 4', 'Op. 10 No. 4'],
  ['Op 10. No. 1', 'Op. 10 No. 1'],
  ['Op 10 No. 3', 'Op. 10 No. 3'],
  ['Op 15', 'Op. 15'],
  ['Op 19 No. 1', 'Op. 19 No. 1'],
  ['Op 19 No. 2', 'Op. 19 No. 2'],
  ['Op 26 No. 1', 'Op. 26 No. 1'],
  ['Op 28 No. 15', 'Op. 28 No. 15'],
  ['Op 57', 'Op. 57'],
  ['Op 58', 'Op. 58'],
  ['Op 64. No. 3', 'Op. 64 No. 3'],
  ['Op 69 No. 1', 'Op. 69 No. 1'],
  ['Op 90 No. 3', 'Op. 90 No. 3'],
  ['Op 118 No. 2', 'Op. 118 No. 2'],
  ['Op . 78', 'Op. 78'],
  ['D. 817', 'D. 817'],
  ['D. 984', 'D. 984'],
  ['S.566a', 'S. 566a'],
  // The same catalogue number, written two ways by two rows of the same library.
  ['w264', 'W264'],
  ['W264', 'W264'],
];

test('a real spelling becomes the canonical form', () => {
  for (const [raw, canonical] of LIBRARY_OPUSES) {
    assert.equal(normaliseOpus(raw), canonical, raw);
  }
});

test('normalising twice changes nothing', () => {
  // The server runs this over every stored row at startup, so it has to be idempotent.
  for (const [, canonical] of LIBRARY_OPUSES) {
    assert.equal(normaliseOpus(canonical), canonical, canonical);
  }
});

test('case is ignored for the abbreviations', () => {
  assert.equal(normaliseOpus('op. 27 no. 2'), 'Op. 27 No. 2');
  assert.equal(normaliseOpus('OP 27 NO 2'), 'Op. 27 No. 2');
});

test('whitespace is collapsed and trimmed', () => {
  assert.equal(normaliseOpus('  Op.   27   No.   2  '), 'Op. 27 No. 2');
});

test('an absent value stays absent', () => {
  assert.equal(normaliseOpus(null), null);
  assert.equal(normaliseOpus(undefined), null);
  assert.equal(normaliseOpus(''), null);
  assert.equal(normaliseOpus('   '), null);
});

test('something the rule does not recognise is left alone apart from spacing', () => {
  assert.equal(normaliseOpus('see the Henle edition'), 'see the Henle edition');
  assert.equal(normaliseOpus('Book 2'), 'Book 2');
});

test('a value with no number is a problem, with the server’s message', () => {
  assert.equal(opusProblem('Op.'), OPUS_NEEDS_A_NUMBER);
  assert.equal(opusProblem('Sonata'), OPUS_NEEDS_A_NUMBER);
  assert.equal(opusProblem('???'), OPUS_NEEDS_A_NUMBER);
});

test('every real spelling passes the guardrail', () => {
  for (const [raw] of LIBRARY_OPUSES) {
    assert.equal(opusProblem(raw), null, raw);
  }
});

test('clearing the field is not a problem', () => {
  assert.equal(opusProblem(null), null);
  assert.equal(opusProblem(''), null);
});
