/**
 * The sampled piano's file names, and the names the sampler needs.
 *
 * Two different naming schemes meet here, and they are not interchangeable:
 *
 * - **Files** are spelled with an `s` — `Ds4.mp3` — because a `#` in a URL starts a
 *   fragment, so `D#4.mp3` would request `D` and get a 404 that a loader happily hands
 *   to the audio decoder.
 * - **Note names** are spelled with a `#` — `D#4` — because that is what a music
 *   library parses. Tone's own pattern is
 *   `/^([a-g]{1}(?:b|#|##|x|bb|###|#x|x#|bbb)?)(-?[0-9]+)/i`: it accepts `#`, `b` and
 *   `x`, and **not `s`**.
 *
 * So the sampler's `urls` map has to have a Tone note name as the key and the file
 * name as the value. Feeding it the file stems directly throws for every sharp note
 * and leaves the instrument silent — which is exactly what happened, and why this is a
 * separate, tested module rather than one line inside the player.
 *
 * Pure and free of any import, so it can be tested without a browser or Tone.
 */

/** `Ds4` → `D#4`. A name with no accidental is unchanged (`A0`). */
export function toneNoteName(stem: string): string {
  const match = /^([A-Ga-g])(s?)(-?\d+)$/.exec(stem.trim());
  if (!match) return stem;
  const [, letter, sharp, octave] = match;
  return `${letter.toUpperCase()}${sharp ? '#' : ''}${octave}`;
}

/** `Ds4` → `Ds4.mp3`: what the file is called on disk and over HTTP. */
export function sampleFile(stem: string): string {
  return `${stem}.mp3`;
}

/**
 * The `urls` map for a Tone `Sampler`: note name to file name.
 *
 * A stem that is already a Tone name — no `s` to translate — works either way, which
 * is why the map is built from the *same* list the backend serves rather than from a
 * second list kept here.
 */
export function sampleUrls(stems: readonly string[]): Record<string, string> {
  const urls: Record<string, string> = {};
  for (const stem of stems) urls[toneNoteName(stem)] = sampleFile(stem);
  return urls;
}

/** The pitches the sampler can play without transposing further than a minor third. */
export function samplePitches(stems: readonly string[]): number[] {
  return stems.map(midiOfNote).filter((pitch): pitch is number => pitch !== null);
}

/** `D#4` → 63, or null if it is not a note name this module understands. */
export function midiOfNote(name: string): number | null {
  const match = /^([A-Ga-g])(#?)(-?\d+)$/.exec(toneNoteName(name));
  if (!match) return null;
  const [, letter, sharp, octave] = match;
  const steps: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
  const base = steps[letter.toUpperCase()];
  if (base === undefined) return null;
  return base + (sharp ? 1 : 0) + (Number(octave) + 1) * 12;
}
