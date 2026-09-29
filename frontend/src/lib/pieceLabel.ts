/**
 * What a piece is called, in one place.
 *
 * A library can hold two pieces with the same title: Beethoven's Op. 27 No. 2 and Op. 13 are both
 * "Sonata", and a picker that shows the title alone offers two identical-looking rows with no way
 * to tell which is which. Every place that names a piece uses this module, so the picker, the
 * matcher's "Maybe" row and the passage heading cannot disagree about it.
 *
 * The one fact this module owns beyond composition is that **a list of labels may not repeat**.
 * Composing a name is not enough on its own: two rows that agree on title, composer *and* opus are
 * still two rows, and the label is the only thing a `<select>` shows. `uniquePieceLabels` closes
 * that, decorating only the labels that would otherwise collide.
 */

/**
 * The parts of a piece that name it.
 *
 * Structural on purpose — not a `PieceSummary`. A segment, a passage and a matcher candidate each
 * arrive with the same three fields under different names, and this way all of them can be named
 * without a conversion step that a caller can forget.
 */
export interface PieceName {
  title: string | null;
  composer_name?: string | null;
  opus?: string | null;
  /** Used only to break a tie, never as part of the name itself. */
  key?: string | null;
  /** Used only to break a tie, after the key. */
  difficulty?: string | null;
}

/** A title is required in the database, so this is for the row that has none anyway. */
const UNTITLED = 'Untitled';

function present(value: string | null | undefined): string | null {
  const text = (value ?? '').trim();
  return text === '' ? null : text;
}

/**
 * ``Beethoven · Op. 27 No. 2`` — who wrote it and which one it is, without the title.
 *
 * For a line that already shows the title, so the two halves cannot drift apart the way a
 * hand-written `composer ?? ''` next to a title does.
 */
export function pieceCredits(piece: PieceName): string {
  const parts: string[] = [];
  const composer = present(piece.composer_name);
  const opus = present(piece.opus);
  if (composer !== null) parts.push(composer);
  if (opus !== null) parts.push(opus);
  return parts.join(' · ');
}

/**
 * ``Sonata · Beethoven · Op. 27 No. 2`` — every part the piece has, and no empty separator.
 *
 * The separator is a middle dot rather than a hyphen because a title can contain a hyphen
 * ("Sonata-Fantasy") and none of these names can contain a dot.
 */
export function pieceLabel(piece: PieceName): string {
  const title = present(piece.title) ?? UNTITLED;
  const credits = pieceCredits(piece);
  return credits === '' ? title : `${title} · ${credits}`;
}

/**
 * One label per piece, guaranteed not to repeat.
 *
 * ``idOf`` is passed rather than assumed because a piece arrives as a `PieceSummary` with an `id`
 * in the library and as a candidate with a `piece_id` in the matcher's answer, and a helper that
 * only accepted one of them would be re-implemented for the other.
 *
 * A label is decorated only when it would otherwise repeat, and then with the next fact that
 * distinguishes it: the key, then the difficulty, then the library id — which is always unique, so
 * the invariant holds even for two rows that agree on everything a musician would say.
 */
export function uniquePieceLabels<T extends PieceName>(
  pieces: readonly T[],
  idOf: (piece: T) => number,
): Map<number, string> {
  const bases = new Map<number, string>();
  const repeats = new Map<string, number>();
  for (const piece of pieces) {
    const base = pieceLabel(piece);
    bases.set(idOf(piece), base);
    repeats.set(base, (repeats.get(base) ?? 0) + 1);
  }

  const used = new Set<string>();
  const labels = new Map<number, string>();
  for (const piece of pieces) {
    const base = bases.get(idOf(piece)) as string;
    let label = base;
    if ((repeats.get(base) ?? 0) > 1) {
      for (const extra of [present(piece.key), present(piece.difficulty), `#${idOf(piece)}`]) {
        if (extra === null) continue;
        label = `${label} · ${extra}`;
        if (!used.has(label)) break;
      }
    }
    used.add(label);
    labels.set(idOf(piece), label);
  }
  return labels;
}
