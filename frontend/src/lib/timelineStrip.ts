/**
 * How the sitting strip decides what to draw and where a click lands.
 *
 * Two decisions live here rather than in the component, because both are easy to get
 * subtly wrong and neither needs the DOM: which colour a piece owns, and which segment
 * an instant belongs to. The component keeps the painting and the scrolling, which are
 * the parts that cannot be tested without a browser.
 */

/** The span of a segment, which is all either function below needs to know about one. */
interface StripSpan {
  start_ms: number;
  end_ms: number;
}

/**
 * How many piece colours `app.css` defines, as `--piece-1` … `--piece-N`.
 *
 * Seven, and each one is a hue the app does not otherwise use on the strip. A palette is
 * only worth having if the hues can be told apart at a glance: a twelfth colour would need
 * a colour picker to distinguish from its neighbour, which answers "is this a different
 * piece" no faster than a smaller palette whose clashes are rare. A sitting with more than
 * seven labelled pieces repeats colours, and the swatch beside the name is the tie-break.
 */
export const PIECE_COLOR_COUNT = 7;

/**
 * The colour slot a piece owns, from its id alone.
 *
 * Derived from the id because that is how a piece is identified everywhere else, and a
 * colour that follows the piece rather than the sitting is the whole point: the Ballade is
 * the same colour in March and in June, so a glance at an old sitting is read at a glance.
 *
 * `id % count` would walk the palette in order as the library grows, because a library is
 * built in id order — the first seven pieces would take all seven hues in sequence and
 * adjacent ids would always be adjacent colours. So the id is mixed first: `Math.imul`
 * keeps the arithmetic in 32 bits, and the shifts fold the high bits down into the low
 * ones the modulo reads.
 */
export function pieceColorIndex(pieceId: number): number {
  let mixed = pieceId | 0;
  mixed = Math.imul(mixed ^ (mixed >>> 16), 0x45d9f3b);
  mixed = Math.imul(mixed ^ (mixed >>> 16), 0x45d9f3b);
  mixed = (mixed ^ (mixed >>> 16)) >>> 0;
  return mixed % PIECE_COLOR_COUNT;
}

/**
 * A colour slot per piece, with no two of them sharing one.
 *
 * `pieceColorIndex` alone occasionally gives two pieces of one sitting the same hue, and a
 * coincidence of ids is not something the player can see — two pieces in one sitting wearing
 * one colour is exactly the ambiguity this exists to remove. So a piece whose own slot is
 * already spoken for moves on to the next free one.
 *
 * Walked in id order rather than in the order the sitting lists them, so the answer depends
 * on *which* pieces are present and not on the arrangement a split or a re-segment happened
 * to leave behind: a piece must not change colour because the timeline was edited around it.
 *
 * Past `PIECE_COLOR_COUNT` pieces the palette is exhausted and slots repeat; the low ids keep
 * their own and the swatch beside the name says which piece a colour is.
 */
export function pieceColorSlots(pieceIds: readonly number[]): Map<number, number> {
  const ordered = [...new Set(pieceIds)].sort((left, right) => left - right);
  const taken = new Set<number>();
  const slots = new Map<number, number>();
  for (const pieceId of ordered) {
    const base = pieceColorIndex(pieceId);
    // `slot` starts at the piece's own colour, so an exhausted palette leaves it there rather
    // than inventing an eighth hue that the stylesheet does not define.
    let slot = base;
    for (let step = 0; step < PIECE_COLOR_COUNT; step += 1) {
      const candidate = (base + step) % PIECE_COLOR_COUNT;
      if (!taken.has(candidate)) {
        slot = candidate;
        break;
      }
    }
    taken.add(slot);
    slots.set(pieceId, slot);
  }
  return slots;
}

/**
 * The segment an instant belongs to, or the nearest one when it falls in a silence.
 *
 * A click that lands between two segments still means one of them: the strip is a way of
 * pointing at what you played, and a gap is silence you cannot point at. So a gap resolves
 * to the closer boundary, and a tie to the earlier segment. `null` only when there are no
 * segments at all — a case the strip does not draw, and one the caller must not read as
 * "the first segment".
 */
export function segmentAtMs<T extends StripSpan>(
  segments: readonly T[],
  atMs: number,
): T | null {
  if (segments.length === 0) return null;
  let nearest = segments[0];
  let nearestDistance = Number.POSITIVE_INFINITY;
  for (const segment of segments) {
    if (atMs >= segment.start_ms && atMs <= segment.end_ms) return segment;
    const distance =
      atMs < segment.start_ms ? segment.start_ms - atMs : atMs - segment.end_ms;
    // Strictly closer, so a tie stays with the earlier segment and the answer does not
    // depend on which side of the gap the loop happened to visit first.
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearest = segment;
    }
  }
  return nearest;
}

/**
 * A range that can be sounding: part of the sitting, and the segment it belongs to.
 *
 * `segmentId === null` means the whole sitting. The two are kept together because a range
 * without its owner cannot be restored: resuming "20 s to 40 s" as if it were a sitting-wide
 * play would silent-skip the very passage the player had asked to hear.
 */
export interface StripRange {
  fromMs: number;
  toMs: number;
  segmentId: number | null;
}

/** Where a seek lands, and what it does to the sound. */
export interface SeekPlan {
  /** The clamped position the playhead takes. */
  atMs: number;
  /** The range to start playing, or `null` for a silent move. */
  resume: StripRange | null;
}

/**
 * What pressing a point on the strip means.
 *
 * The strip is one surface with two meanings, and which applies is not a preference: it
 * follows whether anything is playing. With silence there is nothing to move, so the press
 * places the playhead and starts nothing — that is how the strip is used to look around
 * without making a sound. With sound, the playhead *is* the sound's position, so a press
 * has to move it; leaving it behind would make the click appear ignored, because the next
 * progress tick would put the playhead straight back.
 *
 * Leaving the sounding range is the interesting case. The range you were hearing stays as
 * long as the press lands inside it; outside, the segment under the press takes over, so
 * crossing from one passage to another listens to the passage you asked for rather than
 * sitting through the rest of the one you left. With no segment under the press — a gap, or
 * a sitting with no segments at all — the whole sitting is the only range that contains
 * where you asked to be.
 *
 * `fallback` is what a press resumes when nothing was playing, and it exists for the
 * transport buttons: a step that moved the playhead but kept the silence would be a dead
 * button, while the same function with `null` is exactly the click that must stay quiet.
 */
export function seekPlan(
  playing: StripRange | null,
  totalMs: number,
  atMs: number,
  segment: { id: number; start_ms: number; end_ms: number } | null,
  fallback: StripRange | null = null,
): SeekPlan {
  const at = Math.min(Math.max(atMs, 0), Math.max(totalMs, 0));
  if (playing === null) return { atMs: at, resume: fallback };
  if (at >= playing.fromMs && at <= playing.toMs) return { atMs: at, resume: playing };
  if (segment !== null) {
    return {
      atMs: at,
      resume: { fromMs: segment.start_ms, toMs: segment.end_ms, segmentId: segment.id },
    };
  }
  return { atMs: at, resume: { fromMs: 0, toMs: Math.max(totalMs, 0), segmentId: null } };
}

/**
 * How far into a segment a step back still means "the previous segment".
 *
 * Repeated presses have to be able to walk backwards through a sitting. If a step back
 * always returned the start of the segment you were in, the second press would return the
 * same instant for ever, so a segment you have barely entered is treated as one you have
 * not started — the rule a media player uses for its previous-track button.
 */
export const SEGMENT_RESTART_MS = 3_000;

/**
 * Where a segment-by-segment step lands.
 *
 * The segment is the unit this screen is organised in — the list below is segments, the
 * colours are segments — so it is also the unit for skipping. Thirty-second buttons cannot
 * cross a two-hour sitting at any usable speed, and they do not land on the boundaries the
 * player thinks in.
 *
 * Forward runs to the next segment's start, and past the last one to the end of the
 * sitting, so the button never does nothing. Backwards rewinds the segment you are well
 * into and otherwise steps over the boundary you just crossed, which is what makes repeated
 * presses walk the sitting instead of sticking.
 */
export function segmentStep<T extends StripSpan & { id: number }>(
  segments: readonly T[],
  atMs: number,
  direction: 1 | -1,
  totalMs: number,
): number {
  const total = Math.max(totalMs, 0);
  if (segments.length === 0) return direction === 1 ? total : 0;

  if (direction === 1) {
    for (const segment of segments) {
      if (segment.start_ms > atMs) return Math.min(segment.start_ms, total);
    }
    return total;
  }

  let containing: T | null = null;
  for (const segment of segments) {
    if (atMs >= segment.start_ms && atMs <= segment.end_ms) {
      containing = segment;
      break;
    }
  }
  if (containing !== null && atMs - containing.start_ms > SEGMENT_RESTART_MS) {
    return Math.max(containing.start_ms, 0);
  }
  // Everything before the segment being left — or before the instant, when the playhead is
  // in a silence. `Math.max` against 0 rather than a sentinel keeps the answer a position.
  const limit = containing === null ? atMs : containing.start_ms;
  let previous = 0;
  for (const segment of segments) {
    if (segment.start_ms < limit) previous = Math.max(previous, segment.start_ms);
  }
  return previous;
}

/**
 * The clock positions the ruler under the strip labels.
 *
 * The strip is a picture of time with no numbers on it, and on a two-hour sitting a pixel is
 * about nine seconds — a press is aimed, not guessed, only if the scale is visible. The ends
 * are always included so the ruler spans exactly the sitting.
 */
export function stripTicks(totalMs: number, divisions = 4): number[] {
  const count = Math.max(1, Math.floor(divisions) || 1);
  const total = Math.max(totalMs, 0);
  const ticks: number[] = [];
  for (let index = 0; index <= count; index += 1) {
    ticks.push(Math.round((total * index) / count));
  }
  return ticks;
}
