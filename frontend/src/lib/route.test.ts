import { test } from 'node:test';
import assert from 'node:assert/strict';

import { parseRoute, routeHash, type Route } from './route.ts';

test('a section is a route', () => {
  assert.deepEqual(parseRoute('#/practice'), { name: 'practice' });
  assert.deepEqual(parseRoute('#/log'), { name: 'log' });
  assert.deepEqual(parseRoute('#/repertoire'), { name: 'repertoire' });
});

test('an entity is a route with an id', () => {
  assert.deepEqual(parseRoute('#/repertoire/piece/12'), {
    name: 'repertoire',
    entity: { kind: 'piece', id: 12 },
  });
  assert.deepEqual(parseRoute('#/log/sitting/34'), {
    name: 'log',
    entity: { kind: 'sitting', id: 34 },
  });
  assert.deepEqual(parseRoute('#/stats/attempt/56'), {
    name: 'stats',
    entity: { kind: 'attempt', id: 56 },
  });
});

test('parsing is total: anything unrecognised is null, never a guess', () => {
  for (const bad of ['', '#', '#/', '#/nonsense', '#/repertoire/piece', '#/repertoire/piece/x',
    '#/repertoire/piece/0', '#/log/take/3', '#/repertoire/piece/-1']) {
    assert.equal(parseRoute(bad), null, `${bad} must not parse`);
  }
});

test('an entity attached to the wrong section is refused, not silently moved', () => {
  assert.equal(parseRoute('#/log/piece/12'), null);
  assert.equal(parseRoute('#/stats/sitting/12'), null);
});

test('a round trip is stable', () => {
  const routes: Route[] = [
    { name: 'practice' },
    { name: 'calibrate' },
    { name: 'stats' },
    { name: 'log' },
    { name: 'repertoire' },
    { name: 'repertoire', entity: { kind: 'piece', id: 7 } },
    { name: 'log', entity: { kind: 'sitting', id: 8 } },
    { name: 'stats', entity: { kind: 'attempt', id: 9 } },
  ];
  for (const route of routes) {
    assert.deepEqual(parseRoute(routeHash(route)), route, `${routeHash(route)} did not round trip`);
  }
});
