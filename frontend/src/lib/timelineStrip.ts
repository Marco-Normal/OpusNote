/**
 * How the sitting strip decides what to draw and where a click lands.
 *
 * Two decisions live here rather than in the component, because both are easy to get
 * subtly wrong and neither needs the DOM: which colour a piece owns, and which segment
 * an instant belongs to. The component keeps the painting and the scrolling, which are
 * the parts that cannot be tested without a browser.
 */

/** The span of a segment, which is all either function below needs to know about one. */
export interface StripSpan {
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
