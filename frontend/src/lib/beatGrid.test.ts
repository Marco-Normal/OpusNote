import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildSchedule, toneDbFor, type MetronomePlan } from './beatGrid.ts';

// The metronome's arithmetic, which had no tests at all until now and a recorded defect behind
// it: it was handed seconds-per-*quarter* and treated it as seconds-per-*beat*, which coincides
// only when the beat happens to be a quarter. So 6/8, 9/8, 12/8, 2/2 and 3/8 clicked at the wrong
// rate, counted in wrongly, and in 12/8 ended the run a quarter of the way early — silently
// truncating the performance, which is the worst way for a timing bug to fail.

/** Bars from the server's `measures[]`, which is where beats and units come from. */
function bars(...spec: [beats: number, unitQ: number][]) {
  return { barsBeats: spec.map(([beats]) => beats), barBeatUnits: spec.map(([, unit]) => unit) };
}

function plan(spec: [number, number][], secondsPerQuarter: number, countInBeats = 0): MetronomePlan {
  return { ...bars(...spec), secondsPerQuarter, countInBeats };
}

// --------------------------------------------------------------------------
// The invariant: a bar lasts as long as its notation says
// --------------------------------------------------------------------------

test('every bar lasts its own length in quarters, whatever the beat is', () => {
  // 6/8 is two dotted-quarter beats, 2/2 is two half-note beats, 3/8 is three eighths. All three
  // are the same length as their notation in quarters, and none of them is a quarter-note beat.
  const cases: [string, [number, number][], number][] = [
    ['4/4', [[4, 1]], 4],
    ['3/4', [[3, 1]], 3],
    ['6/8', [[2, 1.5]], 3],
    ['9/8', [[3, 1.5]], 4.5],
    ['12/8', [[4, 1.5]], 6],
    ['2/2', [[2, 2]], 4],
    ['3/8', [[3, 0.5]], 1.5],
  ];
  for (const [name, spec, quarters] of cases) {
    const schedule = buildSchedule(plan(spec, 1));
    assert.equal(
      schedule.scheduledSeconds,
      quarters,
      `${name} should last ${quarters} quarters, not ${schedule.scheduledSeconds}`,
    );
  }
});

test('a compound meter clicks the right number of times for its length', () => {
  // The 12/8 regression: the run ended a quarter of the way early because the beats were timed as
  // quarters. Twelve eighth-notes at four dotted-quarter beats must occupy six quarters.
  const schedule = buildSchedule(plan([[4, 1.5]], 1));
  assert.equal(schedule.clicks.length, 4, 'four dotted-quarter beats in a 12/8 bar');
  assert.equal(schedule.scheduledSeconds, 6);
  const gaps = schedule.clicks.slice(1).map((click, index) => click.at - schedule.clicks[index]!.at);
  assert.deepEqual(gaps, [1.5, 1.5, 1.5], 'every gap is a dotted quarter, not a quarter');
});

test('mixed meter gives each bar its own unit', () => {
  // Alternating 4/4 and 6/8, which is what the meter ladder reaches at the top: the bar lengths
  // differ even though the tempo does not.
  const schedule = buildSchedule(plan([[4, 1], [2, 1.5]], 1));
  const downbeats = schedule.clicks.filter((click) => click.accent).map((click) => click.at);
  assert.deepEqual(downbeats, [0, 4], 'bar 2 starts four quarters in, and lasts three');
  assert.equal(schedule.scheduledSeconds, 7);
});

// --------------------------------------------------------------------------
// The count-in
// --------------------------------------------------------------------------

test('the count-in follows the first bar rather than assuming four beats', () => {
  // A count-in in the wrong meter sets a tempo the player then has to unlearn at the downbeat.
  const inSixEight = buildSchedule(plan([[2, 1.5]], 1, 2));
  assert.equal(inSixEight.clicks.length, 2 + 2);
  assert.equal(inSixEight.downbeatSeconds, 3, 'two dotted-quarter beats of count-in');

  const inFourFour = buildSchedule(plan([[4, 1]], 1, 4));
  assert.equal(inFourFour.downbeatSeconds, 4);
});

test('the downbeat is exactly where the count-in ends, and the exercise starts there', () => {
  const schedule = buildSchedule(plan([[4, 1], [4, 1]], 0.5, 4));
  assert.equal(schedule.downbeatSeconds, 2, 'four quarter beats at half a second each');
  const first = schedule.clicks.find((click) => !click.inCountIn);
  assert.equal(first?.at, schedule.downbeatSeconds);
  assert.equal(first?.bar, 1);
  assert.equal(first?.beat, 1);
});

test('every count-in click is marked as one, and the first is accented', () => {
  const schedule = buildSchedule(plan([[4, 1]], 1, 4));
  const countIn = schedule.clicks.filter((click) => click.inCountIn);
  assert.equal(countIn.length, 4);
  assert.deepEqual(
    countIn.map((click) => click.accent),
    [true, false, false, false],
  );
  assert.deepEqual(
    countIn.map((click) => click.bar),
    [0, 0, 0, 0],
    'count-in bars are not exercise bars',
  );
});

// --------------------------------------------------------------------------
// Accents and edge cases
// --------------------------------------------------------------------------

test('only the first beat of each bar is accented', () => {
  const schedule = buildSchedule(plan([[3, 1], [3, 1]], 1));
  const exercise = schedule.clicks.filter((click) => !click.inCountIn);
  assert.deepEqual(
    exercise.map((click) => click.accent),
    [true, false, false, true, false, false],
  );
  assert.deepEqual(
    exercise.map((click) => [click.bar, click.beat]),
    [
      [1, 1],
      [1, 2],
      [1, 3],
      [2, 1],
      [2, 2],
      [2, 3],
    ],
  );
});

test('an empty exercise is a schedule with nothing in it, not a crash', () => {
  const schedule = buildSchedule(plan([], 1, 2));
  assert.equal(schedule.clicks.length, 2, 'the count-in still happens');
  assert.equal(schedule.scheduledSeconds, schedule.downbeatSeconds);
});

test('a bar with no beats stated falls back rather than dividing by nothing', () => {
  const schedule = buildSchedule({ barsBeats: [4], barBeatUnits: [], secondsPerQuarter: 1 });
  assert.equal(schedule.scheduledSeconds, 4, 'a missing unit means a quarter-note beat');
});

// --------------------------------------------------------------------------
// Volume
// --------------------------------------------------------------------------

test('full volume is minus six decibels, and silence is silence', () => {
  assert.equal(toneDbFor(127), -6);
  assert.equal(toneDbFor(0), -Infinity);
  assert.equal(toneDbFor(-5), -Infinity, 'below the range is silence rather than a loud click');
});

test('the click never gets louder than full volume, and rises with the value', () => {
  assert.equal(toneDbFor(200), -6, 'clamped, so a bad setting cannot clip');
  assert.ok(toneDbFor(64) < toneDbFor(96), 'a higher value is a louder click');
  assert.ok(toneDbFor(96) < 0, 'and still short of unity');
});
