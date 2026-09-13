/**
 * Times, written and read.
 *
 * One owner for both directions, because the interface shows a time in the waveform
 * markers, the playhead, the sitting list, the split field and the workout bar — and
 * that was three implementations before this module existed, two of which disagreed
 * about whether to show tenths.
 */

/**
 * Seconds as `m:ss`, or `h:mm:ss` past an hour.
 *
 * `tenths` is for a position you are *reading* — a marker or a playhead, where the
 * difference between 0:04.2 and 0:04.7 is the point. Durations and clocks are shown
 * whole, because nobody needs to know a sitting lasted 1:03:20.4.
 */
export function formatClock(seconds: number, tenths = false): string {
  const total = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total - hours * 3600) / 60);
  const rest = total - hours * 3600 - minutes * 60;
  const tail = tenths
    ? rest.toFixed(1).padStart(4, '0')
    : String(Math.floor(rest)).padStart(2, '0');
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, '0')}:${tail}`;
  return `${minutes}:${tail}`;
}

/**
 * A time typed by hand, in seconds — or `null` if it is not a time at all.
 *
 * Accepts `90`, `1:30` and `1:01:01`, because all three are things a person types
 * when asked where in a two-hour sitting they want to be. A bare number is
 * *seconds*: it is a position, and reading `45` as minutes would send you most of an
 * hour away from where you meant.
 */
export function parseClock(text: string): number | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const parts = trimmed.split(':');
  if (parts.length > 3) return null;
  let total = 0;
  for (const part of parts) {
    const piece = part.trim();
    // A dangling colon ("1:") is a half-typed time, not one minute. Refusing it
    // keeps a typo visible instead of seeking somewhere plausible but wrong.
    if (piece === '') return null;
    const value = Number(piece);
    if (!Number.isFinite(value) || value < 0) return null;
    total = total * 60 + value;
  }
  return total;
}
