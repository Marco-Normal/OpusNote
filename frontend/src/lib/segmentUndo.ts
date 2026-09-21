/**
 * The inverse of a timeline edit.
 *
 * Merge, split and assign are exactly invertible through the routes that already exist, and
 * working out *which* inverse applies is a pure function of the segment list before and after —
 * so it lives here, where `node --test` can reach it, rather than inside the view that happens to
 * know which button was pressed.
 *
 * Two edits deliberately have no inverse and return null:
 *
 * * `resegment` throws every boundary and label away and rebuilds them, so the rows that were
 *   destroyed are not recoverable from the rows that exist;
 * * answering the matcher (`identify`) writes an `identification_outcomes` row, which the segments
 *   do not carry. The rows may look invertible — the label did change — but the record of the guess
 *   would not come back, so the view does not offer undo for it.
 *
 * **The one thing this cannot restore.** A merge sets the absorbed segment's
 * `identification_outcomes.segment_id` to NULL (`ON DELETE SET NULL`), so undoing a merge restores
 * the segments and their labels but not the matcher's record of one of them. The control says
 * "Undo merge" and claims nothing more.
 */
import type { SegmentSummary } from './types';

export type UndoAction =
  | { kind: 'assign'; segmentId: number; pieceId: number | null; label: string }
  | { kind: 'merge'; segmentId: number; otherId: number; label: string }
  | { kind: 'split'; segmentId: number; atMs: number; label: string };

export function inverseOf(before: SegmentSummary[], after: SegmentSummary[]): UndoAction | null {
  if (before.length === 0) return null;

  const beforeIds = new Set(before.map((segment) => segment.id));
  const afterIds = new Set(after.map((segment) => segment.id));
  const added = after.filter((segment) => !beforeIds.has(segment.id));
  const removed = before.filter((segment) => !afterIds.has(segment.id));

  // A split: one new row appeared and none went away. The original row kept the left half,
  // so merging the two adjacent halves restores both boundaries exactly.
  if (added.length === 1 && removed.length === 0) {
    const [left, right] = [before[0], added[0]].sort((a, b) => a.start_ms - b.start_ms);
    if (left === undefined || right === undefined) return null;
    return { kind: 'merge', segmentId: left.id, otherId: right.id, label: 'Undo split' };
  }

  // A merge: one row went away and none appeared. The survivor is the row whose id is in
  // both lists; the absorbed row's start was the boundary the split has to cut at.
  if (removed.length === 1 && added.length === 0) {
    const absorbed = removed[0];
    const survivor = after.find((segment) => beforeIds.has(segment.id));
    if (absorbed === undefined || survivor === undefined) return null;
    return {
      kind: 'split',
      segmentId: survivor.id,
      atMs: absorbed.start_ms,
      label: 'Undo merge',
    };
  }

  // Neither: the id set is unchanged, so this was a label edit. Whoever moved, moves back.
  if (added.length === 0 && removed.length === 0) {
    const changed = before.find((segment) => {
      const now = after.find((candidate) => candidate.id === segment.id);
      return now !== undefined && now.piece_id !== segment.piece_id;
    });
    if (changed === undefined) return null;
    return {
      kind: 'assign',
      segmentId: changed.id,
      pieceId: changed.piece_id,
      label: 'Undo label',
    };
  }

  return null;
}
