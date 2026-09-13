/**
 * The geometry of a falling-notes view, as arithmetic.
 *
 * A piano roll is mostly coordinate maths — which key a pitch is under, how far a
 * note has fallen, which notes are worth drawing — and that is the part that is
 * miserable to debug by staring at a canvas. The canvas in `PianoRoll.svelte` draws
 * what these functions return.
 */

export interface RollNote {
  /** MIDI pitch. */
  pitch: number;
  /** Seconds from the start of the material. */
  onset: number;
  duration: number;
}

/** A key's horizontal placement, as fractions of the roll's width. */
export interface KeySlot {
  pitch: number;
  /** Left edge and width, in 0..1 of the drawing width. */
  left: number;
  width: number;
  black: boolean;
}

const BLACK_KEYS = new Set([1, 3, 6, 8, 10]);

/** Whether a pitch is a black key. */
export function isBlackKey(pitch: number): boolean {
  return BLACK_KEYS.has(((pitch % 12) + 12) % 12);
}

/** The lowest and highest pitch in the material, padded out to whole octaves. */
export function pitchRange(notes: readonly RollNote[]): { low: number; high: number } {
  if (notes.length === 0) return { low: 48, high: 72 };
  let low = Infinity;
  let high = -Infinity;
  for (const note of notes) {
    if (note.pitch < low) low = note.pitch;
    if (note.pitch > high) high = note.pitch;
  }
  // One key of margin either side, so a note at the very top is not flush with the
  // edge, then widened to whole octaves: a keyboard that starts mid-octave looks
  // wrong even when the keys are in the right order.
  const padded = { low: Math.max(21, low - 1), high: Math.min(108, high + 1) };
  return {
    low: Math.max(21, padded.low - ((padded.low - 21) % 12)),
    high: Math.min(108, padded.high + ((108 - padded.high) % 12)),
  };
}

/**
 * Where each key sits, left to right.
 *
 * White keys share the width equally and black keys are drawn on the boundaries
 * between them, which is how a real keyboard looks — and why this cannot be a
 * simple linear scale of pitch to x.
 */
export function keyLayout(low: number, high: number): KeySlot[] {
  const whites: number[] = [];
  for (let pitch = low; pitch <= high; pitch += 1) {
    if (!isBlackKey(pitch)) whites.push(pitch);
  }
  const slots: KeySlot[] = [];
  const width = whites.length > 0 ? 1 / whites.length : 1;
  const whiteIndex = new Map(whites.map((pitch, index) => [pitch, index]));
  for (let pitch = low; pitch <= high; pitch += 1) {
    if (isBlackKey(pitch)) continue;
    const index = whiteIndex.get(pitch) ?? 0;
    slots.push({ pitch, left: index * width, width, black: false });
  }
  for (let pitch = low; pitch <= high; pitch += 1) {
    if (!isBlackKey(pitch)) continue;
    // A black key sits between the white key below it and the one above.
    const below = whiteIndex.get(pitch - 1);
    if (below === undefined) continue;
    slots.push({
      pitch,
      left: (below + 1) * width - width * 0.3,
      width: width * 0.6,
      black: true,
    });
  }
  return slots;
}

/** Where a pitch's column is, most specific key first so black keys win. */
export function slotFor(slots: readonly KeySlot[], pitch: number): KeySlot | null {
  const black = slots.find((slot) => slot.pitch === pitch && slot.black);
  if (black) return black;
  return slots.find((slot) => slot.pitch === pitch) ?? null;
}

/**
 * How far down the roll a note has fallen, in 0..1 of the drawing height.
 *
 * 1 is the keyboard line: the note is sounding. 0 is the top of the view, which is
 * `lookAhead` seconds in the future. Notes above the top or below the line are
 * outside the window and are not drawn.
 */
export function fallProgress(
  onset: number,
  position: number,
  lookAhead: number,
): number {
  if (!(lookAhead > 0)) return 1;
  return 1 - (onset - position) / lookAhead;
}

export interface PlacedNote {
  note: RollNote;
  slot: KeySlot;
  /**
   * The rectangle's top edge and height, in 0..1 of the drawing height, where 0 is
   * the top of the view and 1 is the keyboard line.
   *
   * Deliberately *not* clamped: a note that started before the window began is still
   * sounding, and its rectangle legitimately extends past the bottom of the view.
   * The canvas clips it, which is simpler and more honest than pretending the note
   * starts at the line.
   */
  top: number;
  height: number;
}

/**
 * The notes worth drawing right now, with their rectangles.
 *
 * A note is included while any part of it is on screen: a long note started before
 * the window began must still be visible, which is the whole point of a falling-note
 * view for music with held bass notes.
 */
export function visibleNotes(
  notes: readonly RollNote[],
  slots: readonly KeySlot[],
  position: number,
  lookAhead: number,
): PlacedNote[] {
  const out: PlacedNote[] = [];
  for (const note of notes) {
    const end = note.onset + Math.max(0.05, note.duration);
    if (end < position) continue; // gone
    if (note.onset > position + lookAhead) continue; // not yet
    const slot = slotFor(slots, note.pitch);
    if (!slot) continue;
    // The onset is the *lowest* edge of the rectangle (it reaches the keyboard line
    // when it sounds) and the end is the highest, because both fall towards the line
    // as time passes. Getting this subtraction the other way round produces negative
    // heights, which a `max(sliver, …)` silently turns into hairlines.
    const atOnset = fallProgress(note.onset, position, lookAhead);
    const atEnd = fallProgress(end, position, lookAhead);
    out.push({
      note,
      slot,
      top: Math.min(atOnset, atEnd),
      height: Math.max(0.004, Math.abs(atOnset - atEnd)),
    });
  }
  return out;
}

/**
 * The time at a given height in the roll, for clicking on it.
 *
 * The inverse of `fallProgress`, so a click means what it looks like.
 */
export function timeAtHeight(top: number, position: number, lookAhead: number): number {
  return position + (1 - top) * lookAhead;
}
