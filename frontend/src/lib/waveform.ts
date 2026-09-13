/**
 * A recording's shape, and where the A/B loop is.
 *
 * Pure on purpose. Peaks, marker positions and the decision "has the playhead
 * left the loop yet" are arithmetic — the parts that are tedious to check by
 * watching a canvas and trivial to check in a test. `Waveform.svelte` owns the
 * AudioContext, the canvas and the element; everything it computes with is here.
 */

export interface Peaks {
  /** Per column, the most negative sample (-1..0): the bottom of the envelope. */
  readonly low: readonly number[];
  /** Per column, the most positive sample (0..1): the top of it. */
  readonly high: readonly number[];
}

/** How many columns a stored peak set holds. Wide enough for a 4K canvas. */
export const PEAK_COLUMNS = 1600;

/**
 * Beyond this a recording is not decoded for the waveform.
 *
 * `decodeAudioData` expands a compressed file into raw samples — a 100 MB video
 * is several hundred MB of float data — and a practice machine should not be
 * pushed into swapping to draw a picture. The file still plays; only the drawing
 * is declined, and it says so.
 */
export const MAX_WAVEFORM_BYTES = 64 * 1024 * 1024;

/**
 * Column-wise min/max, which is what a waveform picture is.
 *
 * Channels are pooled rather than averaged: a left-hand note that only appears in
 * one channel must still show up as a peak, and averaging would shrink it.
 */
export function peaksFrom(channels: readonly Float32Array[], buckets: number): Peaks {
  const columns = Math.max(0, Math.floor(buckets));
  const low: number[] = new Array(columns).fill(0);
  const high: number[] = new Array(columns).fill(0);
  if (columns === 0) return { low, high };

  const length = channels.reduce((longest, channel) => Math.max(longest, channel.length), 0);
  if (length === 0) return { low, high };

  for (let column = 0; column < columns; column += 1) {
    // Edges by ratio so the last column ends exactly at the last sample: a
    // floor-based stride would leave the closing seconds of a recording out of
    // the picture, which is where a lot of final chords live.
    const from = Math.floor((column * length) / columns);
    const to = Math.max(from + 1, Math.floor(((column + 1) * length) / columns));
    let bottom = 0;
    let top = 0;
    for (const channel of channels) {
      const end = Math.min(to, channel.length);
      for (let index = from; index < end; index += 1) {
        const value = channel[index];
        if (!Number.isFinite(value)) continue;
        if (value < bottom) bottom = value;
        if (value > top) top = value;
      }
    }
    low[column] = bottom;
    high[column] = top;
  }
  return { low, high };
}

/** Where a time sits in the recording, as 0..1. */
export function timeToRatio(seconds: number, duration: number): number {
  if (!(duration > 0)) return 0;
  return clamp01(seconds / duration);
}

/** The time at a 0..1 position, for a click on the waveform. */
export function ratioToTime(ratio: number, duration: number): number {
  return clamp01(ratio) * Math.max(0, duration);
}

/**
 * Where playback should be, given the loop.
 *
 * One function for both halves of the behaviour: pressing play outside the loop
 * starts at A, and a playhead that has reached B goes back to A. Returning the
 * time unchanged is how "there is no loop" is expressed, so the caller has no
 * branch of its own.
 *
 * A one-sided or inverted pair is treated as no loop rather than as an error:
 * the player may set B before A, and the database refuses an unusable pair
 * anyway — this must not depend on that having happened.
 */
export function clampToLoop(
  currentTime: number,
  start: number | null,
  end: number | null,
): number {
  if (start === null || end === null || !(end > start)) return currentTime;
  return currentTime < start || currentTime >= end ? start : currentTime;
}

export interface Loop {
  start: number | null;
  end: number | null;
}

/**
 * Shortest loop the server will accept, mirrored here so the player cannot build
 * a pair that is going to be refused. Duplicating a boundary number is a smell;
 * the alternative is a control that fails on submit with a message the player
 * cannot act on.
 */
export const MIN_LOOP_S = 0.2;

/**
 * The loop after dropping a marker at `time`.
 *
 * Placing a marker on the wrong side of the other one clears that other marker
 * rather than refusing the press. The player is marking a passage by ear; being
 * told "no" mid-phrase is worse than losing a marker they can see has gone, and
 * the visible state says so immediately.
 */
export function placeMarker(time: number, loop: Loop, which: 'start' | 'end'): Loop {
  if (which === 'start') {
    const usable = loop.end !== null && loop.end - time >= MIN_LOOP_S;
    return { start: time, end: usable ? loop.end : null };
  }
  const usable = loop.start !== null && time - loop.start >= MIN_LOOP_S;
  return { start: usable ? loop.start : null, end: time };
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}
