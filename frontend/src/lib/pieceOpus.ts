/**
 * The catalogue number, mirrored for the editor.
 *
 * The authority is `backend/app/repertoire/opus.py`; this file exists so the editor can show
 * the canonical form *before* a save, which is the whole point of a guardrail at insert. The
 * server canonicalises and validates whatever arrives, so if the two ever disagree the
 * server's answer is what is stored — a mismatch here is a cosmetic defect in this file, and
 * `pieceOpus.test.ts` pins the same table as the Python test to catch it.
 *
 * The rule: `Op` and `No` carry a period, one space follows it, and a period *after* the
 * number is not the abbreviation's period — `Op 10. No. 4` is `Op. 10 No. 4`. A leading
 * catalogue initial followed by its number is upper case (`w264` → `W264`). Anything else
 * keeps its spelling: a value the rule does not recognise must survive, because the player
 * typed it and there is no second copy.
 */

/** Verbatim the server's `OPUS_NEEDS_A_NUMBER`. One refusal, one wording. */
export const OPUS_NEEDS_A_NUMBER =
  'An opus needs a number in it: the number is what tells two pieces with the same ' +
  'title apart. Write it as `Op. 27 No. 2` or `BWV 846`, or leave the field empty and ' +
  'put the note in the description.';

const OP = /\bOp\b\s*\.?\s*/gi;
const NO = /\bNo\b\s*\.?\s*/gi;
const NUMBER_THEN_NO = /(\d)\.\s+(?=No\.)/g;
const INITIAL_THEN_NUMBER = /\b([A-Za-z])\.(?=\d)/g;
const LEADING_INITIAL = /^([a-z])(?=\d)/;

/** The canonical form of a catalogue number, or null when there is none. */
export function normaliseOpus(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  let text = value.split(/\s+/).filter(Boolean).join(' ');
  if (!text) return null;
  text = text.replace(OP, 'Op. ');
  text = text.replace(NO, 'No. ');
  text = text.replace(NUMBER_THEN_NO, '$1 ');
  text = text.replace(INITIAL_THEN_NUMBER, '$1. ');
  text = text.replace(LEADING_INITIAL, (match) => match.toUpperCase());
  return text.trim();
}

/** Why this catalogue number cannot be used, or null when it can. */
export function opusProblem(value: string | null | undefined): string | null {
  const canonical = normaliseOpus(value);
  if (canonical === null) return null;
  return /\d/.test(canonical) ? null : OPUS_NEEDS_A_NUMBER;
}
