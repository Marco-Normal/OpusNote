import type { PracticePassage, SegmentSummary, SittingDetail } from './types.ts';

export type TimelineRow =
  | { kind: 'session'; key: string; session: number; piece: string | null; pieceId: number | null }
  | { kind: 'passage'; key: string; passage: PracticePassage }
  | { kind: 'segment'; key: string; segment: SegmentSummary };

type NameResolver = (
  pieceId: number | null,
  fields: { title: string | null; composer_name?: string | null; opus?: string | null },
) => string | null;

/**
 * The rows the timeline draws: a piece-session heading, then a passage, then its attempts.
 *
 * The passage is the row the player thinks in — "six goes at this bit" — and the attempts stay
 * the `.segment` elements, because they are what every edit and every test hook acts on. A
 * segment the server did not place in any passage is still drawn: an attempt must never vanish
 * from the log because a derivation did not place it.
 */
export function buildTimelineRows(detail: SittingDetail, nameOf: NameResolver): TimelineRow[] {
  const found = detail.passages ?? [];
  if (found.length === 0) {
    return detail.segments.map((segment) => ({
      kind: 'segment' as const,
      key: `segment-${segment.id}`,
      segment,
    }));
  }

  const byId = new Map(detail.segments.map((segment) => [segment.id, segment]));
  const drawn: TimelineRow[] = [];
  let session = -1;
  for (const passage of found) {
    if (passage.session !== session) {
      session = passage.session;
      drawn.push({
        kind: 'session',
        key: `session-${passage.session}`,
        session: passage.session,
        piece: nameOf(passage.piece_id, {
          title: passage.piece_title,
          composer_name: passage.composer_name,
          opus: passage.piece_opus,
        }),
        pieceId: passage.piece_id,
      });
    }
    drawn.push({
      kind: 'passage',
      key: `passage-${passage.attempt_ids[0] ?? passage.start_ms}`,
      passage,
    });
    for (const id of passage.attempt_ids) {
      const segment = byId.get(id);
      if (segment) drawn.push({ kind: 'segment', key: `segment-${id}`, segment });
    }
  }

  const placed = new Set(found.flatMap((passage) => passage.attempt_ids));
  for (const segment of detail.segments) {
    if (!placed.has(segment.id)) {
      drawn.push({ kind: 'segment', key: `segment-${segment.id}`, segment });
    }
  }
  return drawn;
}
