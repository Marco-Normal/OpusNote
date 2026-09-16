/**
 * The deliberate-practice taxonomy, as the player sees it.
 *
 * Values are the wire format the API validates; labels are presentation. Both live here
 * rather than in a component because the timeline (where a kind is set) and the Log
 * dashboard (where the split is drawn) must agree on the words.
 */
import type { PracticeKind } from './types';

export const PRACTICE_KINDS: { id: PracticeKind; label: string }[] = [
  { id: 'run_through', label: 'Run-through' },
  { id: 'slow', label: 'Slow' },
  { id: 'section', label: 'Section' },
  { id: 'hands_separate', label: 'Hands separate' },
  { id: 'memory', label: 'From memory' },
  { id: 'warm_up', label: 'Warm-up / technique' },
  { id: 'other', label: 'Other' },
];

/** An unknown value reads as itself; a null reads as the honest "nobody has said". */
export function practiceKindLabel(kind: string | null): string {
  if (kind === null) return 'Not characterised';
  return PRACTICE_KINDS.find((entry) => entry.id === kind)?.label ?? kind;
}

/** Does a stored kind count as a label, or is it still the app's question? */
export function kindCounts(basis: string | null): boolean {
  return basis === 'manual' || basis === 'accepted';
}
