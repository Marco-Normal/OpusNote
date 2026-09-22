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
 * A length of time as a duration reads, or an em dash when there is nothing to report.
 *
 * The nullable wrapper exists because recordings carry a length that may be absent, and it lives
 * here rather than beside the types because `formatClock` is the one owner of "seconds written as
 * a clock". It used to live in `types.ts` and print `60:00` for an hour, while the playhead and
 * the markers printed `1:00:00` for the same length — two owners for one value, which this
 * project's own test-strategy appendix names as its recurring defect.
 *
 * Rounding happens first, so a fractional length reads as the nearest second rather than
 * truncating, which is what it did before the hour branch was added.
 */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '—';
  return formatClock(Math.round(seconds));
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
  for (const [index, part] of parts.entries()) {
    const piece = part.trim();
    // A dangling colon ("1:") is a half-typed time, not one minute. Refusing it
    // keeps a typo visible instead of seeking somewhere plausible but wrong.
    if (piece === '') return null;
    // Digits only. `Number()` also accepts `1e3`, `0x10` and `1.5`, so a typed clock used to
    // take all three: a mistyped seek to 16:40, a hex literal nobody meant to type, and a
    // fraction of a second this field does not offer.
    if (!/^\d+$/.test(piece)) return null;
    const value = Number(piece);
    if (!Number.isFinite(value)) return null;
    // The leading part counts minutes, or hours when there are three parts, so it may be any
    // size; every part after it is a remainder and cannot reach the unit above it. `1:99` was
    // read as 159 seconds — the plausible-but-wrong seek this rule exists to refuse.
    if (index > 0 && value >= 60) return null;
    total = total * 60 + value;
  }
  return total;
}
