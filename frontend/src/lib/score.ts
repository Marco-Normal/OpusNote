/**
 * Sheet-music rendering and note-level feedback colouring.
 *
 * OSMD is driven from the MusicXML the API returns, so nothing about the
 * notation lives in the browser. Each rendered note is correlated back to an
 * entry in the exercise's expected-note timeline, which is what makes
 * "highlight the wrong note in red" possible.
 */

import type { GraphicalNote, OpenSheetMusicDisplay } from 'opensheetmusicdisplay';
import type { ExpectedNote, NoteStatus } from './types';

export const STATUS_COLORS: Record<NoteStatus, string> = {
  pending: '#1f2937',
  correct: '#15803d',
  wrong_pitch: '#b91c1c',
  missed: '#b45309',
  extra: '#7c3aed',
};

interface RenderedNote {
  graphicalNote: GraphicalNote;
  expectedIndex: number | null;
}

function keyFor(measure: number, hand: string, pitch: number): string {
  return `${measure}|${hand}|${pitch}`;
}

export class ScoreRenderer {
  private osmd: OpenSheetMusicDisplay | null = null;
  private rendered: RenderedNote[] = [];
  /** Guard so a failed colouring pass never breaks the practice loop. */
  private colorSupported = true;

  constructor(private readonly container: HTMLElement) {}

  async render(musicxml: string, expected: ExpectedNote[]): Promise<void> {
    this.container.innerHTML = '';
    // Loaded on demand: OSMD is by far the largest dependency and nothing on the
    // first paint needs it.
    const { OpenSheetMusicDisplay: OSMD } = await import('opensheetmusicdisplay');
    const osmd = new OSMD(this.container, {
      autoResize: true,
      backend: 'svg',
      drawTitle: false,
      drawComposer: false,
      drawCredits: false,
      drawPartNames: false,
      drawMeasureNumbers: true,
      drawTimeSignatures: true,
      followCursor: false,
      disableCursor: true,
      // The exercises are deliberately compact; keep them on one system.
      newSystemFromXML: false,
      newPageFromXML: false,
    });
    this.osmd = osmd;
    await osmd.load(musicxml);
    osmd.render();
    this.rendered = this.correlate(expected);
  }

  /**
   * Walk OSMD's graphical measures in order and match each note to the expected
   * timeline by (measure, hand, pitch).
   *
   * Order alone is not enough: within one bar OSMD yields every right-hand note
   * before the left hand, while the expected timeline is sorted by onset. The
   * keyed queues below make the correlation order-independent.
   */
  private correlate(expected: ExpectedNote[]): RenderedNote[] {
    const queues = new Map<string, number[]>();
    for (const note of expected) {
      const key = keyFor(note.measure, note.hand, note.pitch);
      const queue = queues.get(key);
      if (queue) queue.push(note.index);
      else queues.set(key, [note.index]);
    }

    const result: RenderedNote[] = [];
    const sheet = this.osmd?.GraphicSheet;
    if (!sheet) return result;

    try {
      for (let measureIndex = 0; measureIndex < sheet.MeasureList.length; measureIndex += 1) {
        const row = sheet.MeasureList[measureIndex];
        if (!row) continue;
        for (let staffIndex = 0; staffIndex < row.length; staffIndex += 1) {
          const measure = row[staffIndex];
          if (!measure) continue;
          const measureNumber = measure.MeasureNumber;
          if (!measureNumber || measureNumber < 1) continue;
          const hand = staffIndex === 0 ? 'RH' : 'LH';

          for (const staffEntry of measure.staffEntries ?? []) {
            for (const voiceEntry of staffEntry.graphicalVoiceEntries ?? []) {
              for (const graphicalNote of voiceEntry.notes ?? []) {
                const pitch = graphicalNote.sourceNote?.Pitch?.getHalfTone?.();
                if (typeof pitch !== 'number') continue;
                const queue = queues.get(keyFor(measureNumber, hand, pitch));
                const expectedIndex = queue && queue.length > 0 ? (queue.shift() as number) : null;
                result.push({ graphicalNote, expectedIndex });
              }
            }
          }
        }
      }
    } catch (error) {
      // Correlating is a nicety; the note strip below the score still gives
      // full feedback if OSMD's internals ever change shape.
      console.warn('Could not correlate rendered notes with the expected timeline', error);
    }
    return result;
  }

  /** Reset every rendered note to the default ink colour. */
  resetColors(): void {
    this.applyColors(new Map());
  }

  /**
   * Colour notes by expected-note index. Indices missing from the map are left
   * at the default colour.
   */
  colorByExpectedIndex(statuses: Map<number, NoteStatus>): void {
    this.applyColors(statuses);
  }

  private applyColors(statuses: Map<number, NoteStatus>): void {
    if (!this.colorSupported) return;
    try {
      for (const entry of this.rendered) {
        if (entry.expectedIndex === null) continue;
        const status = statuses.get(entry.expectedIndex) ?? 'pending';
        entry.graphicalNote.setColor(STATUS_COLORS[status], {
          applyToNoteheads: true,
          applyToStem: true,
          applyToBeams: true,
          applyToFlag: true,
          applyToLedgerLines: true,
          applyToTies: true,
          applyToSlurs: false,
        });
      }
    } catch (error) {
      this.colorSupported = false;
      console.warn('Note colouring is unavailable in this OSMD build', error);
    }
  }

  get noteCount(): number {
    return this.rendered.length;
  }

  get matchedCount(): number {
    return this.rendered.filter((entry) => entry.expectedIndex !== null).length;
  }

  dispose(): void {
    this.container.innerHTML = '';
    this.osmd = null;
    this.rendered = [];
  }
}
