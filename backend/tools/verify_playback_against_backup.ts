/**
 * Run the shipped playback code over the owner's real backup.
 *
 * Not a test — the unit tests own the contract. This is the end-to-end check that a
 * defect measured on real sessions is actually gone when the real functions, rather
 * than a reimplementation of them, see the real notes and pedal stream.
 *
 * The backup is the owner's own practice log, refreshed by hand and kept out of git
 * (`backend/data/` is ignored) because it is personal data and 24 MB of it. Having a
 * real database to hand is worth a great deal when measuring a change against actual
 * practice rather than against a fixture somebody imagined.
 *
 *   cd backend && node tools/verify_playback_against_backup.ts
 */
import { readFileSync } from 'node:fs';

import { resolveOverlaps, sustained } from '../../frontend/src/lib/playback.ts';

const backup = JSON.parse(
  readFileSync(new URL('../data/real-backup.json', import.meta.url), 'utf8'),
);
const tables = backup.tables as {
  note_events: { sitting_id: number; onset_ms: number; duration_ms: number; pitch: number; velocity: number }[];
  pedal_events: { sitting_id: number; onset_ms: number; value: number }[];
};

/** Notes that a stale same-pitch note-off would silence before their own release. */
function cutShort(notes: { pitch: number; onset: number; duration: number }[]) {
  const byPitch = new Map<number, typeof notes>();
  for (const note of notes) {
    const list = byPitch.get(note.pitch) ?? [];
    list.push(note);
    byPitch.set(note.pitch, list);
  }
  let count = 0;
  let worst = 0;
  for (const list of byPitch.values()) {
    list.sort((a, b) => a.onset - b.onset);
    for (let i = 0; i < list.length - 1; i += 1) {
      const a = list[i];
      const b = list[i + 1];
      const aEnd = a.onset + a.duration;
      const bEnd = b.onset + b.duration;
      if (aEnd > b.onset && bEnd > aEnd) {
        count += 1;
        worst = Math.max(worst, bEnd - aEnd);
      }
    }
  }
  return { count, worst };
}

const sittings = [...new Set(tables.pedal_events.map((p) => p.sitting_id))].sort();
let before = 0;
let after = 0;
let worstBefore = 0;
let worstAfter = 0;

for (const sitting of sittings) {
  const notes = tables.note_events.filter((n) => n.sitting_id === sitting);
  const pedals = tables.pedal_events.filter((p) => p.sitting_id === sitting);
  const played = notes.map((note) => ({
    pitch: note.pitch,
    onset: note.onset_ms / 1000,
    duration: note.duration_ms / 1000,
    velocity: note.velocity / 127,
    hand: null as null,
  }));
  const moves = pedals.map((pedal) => ({ onset_ms: pedal.onset_ms, value: pedal.value }));

  const sounding = sustained(played, moves);
  const b = cutShort(sounding);
  const a = cutShort(resolveOverlaps(sounding));

  before += b.count;
  after += a.count;
  worstBefore = Math.max(worstBefore, b.worst);
  worstAfter = Math.max(worstAfter, a.worst);

  console.log(
    `sitting ${sitting}: ${notes.length} notes, ${pedals.length} pedal moves -> ` +
      `cut short before ${b.count}, after ${a.count}`,
  );
}

console.log(
  `\nTOTAL across ${sittings.length} pedalled sittings: before ${before}, after ${after}` +
    `  (worst loss before ${worstBefore.toFixed(3)}s, after ${worstAfter.toFixed(3)}s)`,
);
