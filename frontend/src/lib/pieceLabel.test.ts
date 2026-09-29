import { test } from 'node:test';
import assert from 'node:assert/strict';

import { pieceCredits, pieceLabel, uniquePieceLabels } from './pieceLabel.ts';

test('a piece is named by its title, its composer and its opus', () => {
  assert.equal(
    pieceLabel({ title: 'Sonata', composer_name: 'Beethoven', opus: 'Op. 27 No. 2' }),
    'Sonata · Beethoven · Op. 27 No. 2',
  );
});

test('a part the piece does not have is left out rather than left blank', () => {
  // Two separators with nothing between them reads as a missing value on screen, and a
  // library that has not filled the opus in yet is the ordinary case, not the exception.
  assert.equal(pieceLabel({ title: 'Sonata', composer_name: 'Beethoven' }), 'Sonata · Beethoven');
  assert.equal(pieceLabel({ title: 'Sonata', opus: 'Op. 13' }), 'Sonata · Op. 13');
  assert.equal(pieceLabel({ title: 'Sonata' }), 'Sonata');
  assert.equal(
    pieceLabel({ title: 'Sonata', composer_name: '   ', opus: '' }),
    'Sonata',
    'whitespace is not a name',
  );
});

test('a piece with no title is still nameable', () => {
  // The composer and the opus are what the player is choosing by at that point, and an
  // empty option in a picker is a row you cannot read.
  assert.equal(pieceLabel({ title: null, composer_name: 'Beethoven' }), 'Untitled · Beethoven');
  assert.equal(pieceLabel({ title: null }), 'Untitled');
});

test('the credits are the same facts the label is built from', () => {
  // A bar chart shows the title as the bar and these as the line under it; deriving the
  // second from the first is what stops the two halves disagreeing.
  const piece = { title: 'Ballade', composer_name: 'Brahms', opus: 'Op. 118 No. 3' };
  assert.equal(pieceCredits(piece), 'Brahms · Op. 118 No. 3');
  assert.equal(pieceLabel(piece), `${piece.title} · ${pieceCredits(piece)}`);
  assert.equal(pieceCredits({ title: 'Sonata' }), '', 'nothing to add when there is nothing');
});

test('two pieces that differ only by opus do not read alike', () => {
  // The reported problem: two Beethoven sonatas, both titled "Sonata".
  const labels = uniquePieceLabels(
    [
      { id: 1, title: 'Sonata', composer_name: 'Beethoven', opus: 'Op. 27 No. 2' },
      { id: 2, title: 'Sonata', composer_name: 'Beethoven', opus: 'Op. 13' },
    ],
    (piece) => piece.id,
  );
  assert.equal(labels.get(1), 'Sonata · Beethoven · Op. 27 No. 2');
  assert.equal(labels.get(2), 'Sonata · Beethoven · Op. 13');
});

test('the ordinary piece keeps its short label', () => {
  // The suffix is for a collision, not a style: a library where every option grew a key
  // would be trading one unreadable list for another.
  const labels = uniquePieceLabels(
    [
      { id: 1, title: 'Ballade', composer_name: 'Brahms', opus: 'Op. 118 No. 3', key: 'G minor' },
      { id: 2, title: 'Nocturne', composer_name: 'Chopin', opus: 'Op. 9 No. 2', key: 'Eb Major' },
    ],
    (piece) => piece.id,
  );
  assert.equal(labels.get(1), 'Ballade · Brahms · Op. 118 No. 3');
  assert.equal(labels.get(2), 'Nocturne · Chopin · Op. 9 No. 2');
});

test('a collision gets the next fact that tells the two apart', () => {
  // Title, composer and opus all agree — a re-import, or a library that has not filled the
  // opus in. The key is what a musician would say, so it is preferred.
  const labels = uniquePieceLabels(
    [
      { id: 1, title: 'Sonata', composer_name: 'Beethoven', key: null, difficulty: 'Advanced' },
      { id: 2, title: 'Sonata', composer_name: 'Beethoven', key: 'C# minor', difficulty: null },
    ],
    (piece) => piece.id,
  );
  assert.equal(labels.get(2), 'Sonata · Beethoven · C# minor');
  assert.notEqual(labels.get(1), labels.get(2));
});

test('when no field distinguishes them, the library id does', () => {
  // Two rows that agree on every name are two rows. Showing one label twice is the bug
  // this exists to prevent, so something has to give and it is not the uniqueness.
  const labels = uniquePieceLabels(
    [
      { id: 7, title: 'Sonata', composer_name: 'Beethoven' },
      { id: 8, title: 'Sonata', composer_name: 'Beethoven' },
    ],
    (piece) => piece.id,
  );
  assert.notEqual(labels.get(7), labels.get(8));
  assert.equal(labels.get(7), 'Sonata · Beethoven · #7');
  assert.equal(labels.get(8), 'Sonata · Beethoven · #8');
});

test('every option in a list can be told from every other', () => {
  // The invariant, over a library shaped like the awkward one: duplicates, missing opuses
  // and two rows that agree on everything.
  const library = [
    { id: 1, title: 'Sonata', composer_name: 'Beethoven', opus: 'Op. 27 No. 2' },
    { id: 2, title: 'Sonata', composer_name: 'Beethoven', opus: 'Op. 13' },
    { id: 3, title: 'Sonata', composer_name: 'Beethoven', opus: null, key: 'C# minor' },
    { id: 4, title: 'Sonata', composer_name: 'Beethoven', opus: null, key: 'C# minor' },
    { id: 5, title: 'Ballade', composer_name: 'Brahms', opus: 'Op. 118 No. 3' },
    { id: 6, title: null, composer_name: null, opus: null },
    { id: 7, title: null, composer_name: null, opus: null },
  ];
  const labels = uniquePieceLabels(library, (piece) => piece.id);
  const rendered = [...labels.values()];
  assert.equal(rendered.length, library.length);
  assert.equal(new Set(rendered).size, library.length, `not distinct: ${rendered.join(' | ')}`);
  assert.ok(
    rendered.every((label) => label.trim() !== ''),
    'and none of them is blank',
  );
});
