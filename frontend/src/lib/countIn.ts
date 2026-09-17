/**
 * How many beats of count-in to play.
 *
 * Stored as **bars**, not beats, because a bar is not a fixed number of beats: 6/8 has
 * two dotted-quarter beats and 4/4 has four quarters. Storing beats would make "two bars"
 * mean different things in different meters, which is the same mistake the metronome's
 * `secondsPerQuarter` comment records for the beat unit.
 *
 * Pure, and in its own module rather than in `metronome.ts`, because that file imports
 * Tone and cannot be loaded by `node --test`.
 */

/** The choices offered: none, one bar, two bars. */
export const COUNT_IN_BARS = [0, 1, 2] as const;
export type CountInBars = (typeof COUNT_IN_BARS)[number];

export function countInBeats(bars: number, barsBeats: number[]): number {
  const beatsPerBar = barsBeats[0] ?? 4;
  return Math.max(0, Math.trunc(bars)) * beatsPerBar;
}
