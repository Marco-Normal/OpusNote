/**
 * When a take ends.
 *
 * The rule is the server's segment rule, fetched from the practice status rather than repeated
 * here: audio cut somewhere else than the notes would disagree with them about where a passage
 * ended, and the disagreement would be invisible until somebody compared a take with its segment.
 *
 * Pure, and in its own module, because a decision about time is the part of recording that breaks
 * quietly. There is no DOM here and no `MediaRecorder`, so `node --test` can reach it.
 */

export interface CutInput {
  /** Now, ms since the Unix epoch. */
  nowMs: number;
  /** When the current take began recording, ms since the Unix epoch. */
  chunkStartedMs: number;
  /** The last note heard, ms since the Unix epoch, or null if none has been. */
  lastNoteMs: number | null;
  /** Silence the server treats as a segment boundary, in ms. */
  segmentGapMs: number;
  /** A hard ceiling, so one long unbroken passage still produces playable files. */
  maxChunkMs: number;
}

/**
 * Whether to end the current take now.
 *
 * Cutting only ever happens *after* the gap has elapsed, never before, so the take contains the
 * whole of the playing it belongs to. The maximum length is a separate reason to cut, and it is the
 * only case where a take ends while notes are still arriving.
 */
export function shouldCut(input: CutInput): boolean {
  const silence = input.lastNoteMs === null || input.nowMs - input.lastNoteMs >= input.segmentGapMs;
  const tooLong = input.nowMs - input.chunkStartedMs >= input.maxChunkMs;
  return silence || tooLong;
}

/**
 * Whether to open a take.
 *
 * A take begins on a note: recording silence is recording nothing. "A note" means one *newer*
 * than the newest note already inside a take, because `lastNoteMs` is the newest note any port
 * has ever heard and never clears — a take that opened on "some note has been heard" would
 * re-open the moment it closed and record the silence it exists to skip.
 */
export function shouldStart(input: {
  lastNoteMs: number | null;
  recording: boolean;
  /** The newest note a take has already captured, or null if none has. */
  takenThroughMs: number | null;
}): boolean {
  if (input.recording || input.lastNoteMs === null) return false;
  return input.takenThroughMs === null || input.lastNoteMs > input.takenThroughMs;
}
