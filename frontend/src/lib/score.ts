/**
 * Sheet-music rendering and note-level feedback colouring.
 *
 * OSMD is driven from the MusicXML the API returns, so nothing about the
 * notation lives in the browser. Each rendered note is correlated back to an
 * entry in the exercise's expected-note timeline, which is what makes
 * "highlight the wrong note in red" possible.
 *
 * The renderer is theme-aware: notation colours and the page background both
 * follow the resolved "score paper", and the music is re-rendered when that
 * changes, because OSMD only honours its colour options at load time.
 */

import type { GraphicalNote, OpenSheetMusicDisplay } from 'opensheetmusicdisplay';
import type { ExpectedNote, NoteStatus } from './types';

/**
 * Default ink per paper theme — the colour of notation that carries no feedback.
 *
 * This is passed to OSMD as well as used for the `pending` status, because OSMD
 * tracks noteheads separately from everything else: its `darkMode` option
 * lightens the music but leaves `defaultColorNotehead` at black, which produced
 * invisible black noteheads on a black page.
 */
const INK: Record<'light' | 'dark', string> = {
  light: '#000000',
  dark: '#e7e8ea',
};

/**
 * Feedback colours per paper theme. The light palette is tuned for black ink on
 * white; the dark palette is much lighter because the same green or red on a
 * near-black page fails contrast badly.
 */
const STATUS_COLORS: Record<'light' | 'dark', Record<NoteStatus, string>> = {
  light: {
    pending: INK.light,
    correct: '#15803d',
    wrong_pitch: '#b91c1c',
    missed: '#b45309',
    extra: '#7c3aed',
  },
  dark: {
    pending: INK.dark,
    correct: '#4ade80',
    wrong_pitch: '#f87171',
    missed: '#fbbf24',
    extra: '#c4b5fd',
  },
};

/**
 * Never shrink below this. Past roughly here the notation stops being readable,
 * and an unreadable exercise is worse than one that needs a shorter length — so
 * the UI refuses the length instead of scaling further.
 */
export const MIN_ZOOM = 0.55;

/** Must match `--score-bg` in app.css so the paper and its padding agree. */
const PAGE_BACKGROUND: Record<'light' | 'dark', string> = {
  light: '#ffffff',
  dark: '#0b0c0e',
};

export function statusColors(dark: boolean): Record<NoteStatus, string> {
  return STATUS_COLORS[dark ? 'dark' : 'light'];
}

export function pageBackground(dark: boolean): string {
  return PAGE_BACKGROUND[dark ? 'dark' : 'light'];
}

export function inkColor(dark: boolean): string {
  return INK[dark ? 'dark' : 'light'];
}

interface RenderedNote {
  graphicalNote: GraphicalNote;
  expectedIndex: number | null;
}

function keyFor(measure: number, hand: string, pitch: number): string {
  return `${measure}|${hand}|${pitch}`;
}

/**
 * Which hand a rendered part belongs to.
 *
 * The authority is the API, not the staff's position: `music/expected.py` labels
 * every expected note from the part's own id and name, falling back to order only
 * when neither says anything. This mirrors that rule exactly, so the two sides
 * cannot disagree about a note.
 *
 * Reading position instead happens to be right in two of the three configurations
 * the generator emits — a two-hand exercise puts "Right Hand" on staff 0 and
 * "Left Hand" on staff 1, and a right-hand-alone exercise is a single part that
 * really is the right hand — and wrong in the third: texture level 2 is one part
 * named "Left Hand" on staff 0, which a positional rule calls "RH". Every lookup
 * then missed, every note stayed black, and because the browser suite played
 * two-hand material the score could be silently uncoloured at exactly that level
 * with nothing failing. Measured: 0 of 19 noteheads painted, score 99/100.
 */
export function handForPart(
  id: string | null | undefined,
  partName: string | null | undefined,
  index: number,
): 'RH' | 'LH' {
  const identifier = String(id ?? '').toUpperCase();
  const name = String(partName ?? '').toLowerCase();
  if (identifier.startsWith('RH') || name.includes('right')) return 'RH';
  if (identifier.startsWith('LH') || name.includes('left')) return 'LH';
  return index === 0 ? 'RH' : 'LH';
}

/**
 * OSMD's `Pitch.getHalfTone()` is **not** a MIDI number.
 *
 * It returns `12 * (MusicXML octave) + fundamental`, while MIDI is
 * `12 * (octave + 1) + fundamental` — so it reads exactly one octave low. A
 * written C4 comes back as 48 instead of 60. Verified by measurement, not
 * assumption; without this correction no rendered note ever matched the
 * expected timeline and score colouring silently did nothing.
 */
function osmdPitchToMidi(pitch: { getHalfTone(): number }): number {
  return pitch.getHalfTone() + 12;
}

export class ScoreRenderer {
  private osmd: OpenSheetMusicDisplay | null = null;
  private rendered: RenderedNote[] = [];
  /** Guard so a failed colouring pass never breaks the practice loop. */
  private colorSupported = true;

  private musicxml = '';
  private expected: ExpectedNote[] = [];
  private dark = false;
  private statuses = new Map<number, NoteStatus>();

  /**
   * OSMD's own `autoResize` re-renders whenever the container resizes, and a
   * re-render rebuilds the SVG from scratch — silently discarding every
   * per-note colour we applied. That happens on ordinary layout shifts, such as
   * the results panel appearing, which is why feedback colours vanished the
   * moment they mattered.
   *
   * So layout is ours: `autoResize` is off, and we re-render only when the
   * *width* changes (height follows content, and reacting to it would loop).
   */
  /**
   * Renders are serialized. Overlapping calls each create their own OSMD instance
   * pointing at the same container, and since OSMD appends rather than replaces,
   * the scores stack on top of one another.
   */
  private renderChain: Promise<void> = Promise.resolve();
  private generation = 0;

  private observer: ResizeObserver | null = null;
  private lastWidth = 0;
  private relayoutTimer: ReturnType<typeof setTimeout> | null = null;

  /**
   * Notified after every internal render, including ones this component did not
   * initiate (a resize, for instance). Without it the UI's zoom and "too long"
   * readouts go stale, because those renders bypass the caller.
   */
  onStateChange: ((state: { zoom: number; fits: boolean }) => void) | null = null;

  /** Height budget in pixels; 0 means "do not scale to fit". */
  private maxHeight = 0;
  private appliedZoom = 1;
  private fitsInBudget = true;

  /** The zoom actually applied, for display and for assertions. */
  get zoom(): number {
    return this.appliedZoom;
  }

  /**
   * False when the exercise still overflows at `MIN_ZOOM`. The caller should
   * offer a shorter length rather than let the player scroll mid-performance.
   */
  get fits(): boolean {
    return this.fitsInBudget;
  }

  /**
   * A plain field rather than a constructor parameter property: `node --test`
   * strips types without transforming them, and a parameter property is a
   * transform Node refuses (`ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX`). It is what kept
   * this module — the one with the most recorded bug history in the client —
   * unloadable by the test runner.
   */
  private readonly container: HTMLElement;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  async render(
    musicxml: string,
    expected: ExpectedNote[],
    options: { dark: boolean; maxHeight?: number },
  ): Promise<void> {
    this.musicxml = musicxml;
    this.expected = expected;
    this.dark = options.dark;
    if (options.maxHeight !== undefined) this.maxHeight = options.maxHeight;
    await this.enqueueRender();
    this.observeLayout();
  }

  /**
   * Change the height budget (focus mode, window resize) and re-fit if needed.
   */
  async setMaxHeight(maxHeight: number): Promise<void> {
    if (Math.abs(maxHeight - this.maxHeight) < 8 || !this.musicxml) return;
    this.maxHeight = maxHeight;
    await this.enqueueRender();
  }

  private enqueueRender(): Promise<void> {
    const generation = ++this.generation;
    this.renderChain = this.renderChain.then(() => {
      // A newer render has superseded this one while it waited in the queue.
      if (generation !== this.generation) return undefined;
      return this.renderInternal();
    });
    return this.renderChain;
  }

  private async renderInternal(): Promise<void> {
    const musicxml = this.musicxml;
    const expected = this.expected;
    this.container.innerHTML = '';

    // Loaded on demand: OSMD is by far the largest dependency and nothing on the
    // first paint needs it.
    const { OpenSheetMusicDisplay: OSMD } = await import('opensheetmusicdisplay');
    const osmd = new OSMD(this.container, {
      autoResize: false,
      backend: 'svg',
      drawTitle: false,
      drawComposer: false,
      drawCredits: false,
      drawPartNames: false,
      drawMeasureNumbers: true,
      drawTimeSignatures: true,
      followCursor: false,
      disableCursor: true,
      // Systems stack vertically and never paginate. Sight-reading must not
      // involve a page turn, so this is pinned explicitly rather than inherited.
      pageFormat: 'Endless',
      newSystemFromXML: false,
      newPageFromXML: false,
      newSystemFromNewPageInXML: false,
      // Notation follows the paper choice, not the browser chrome. The explicit
      // colour options are required: `darkMode` alone leaves noteheads black.
      darkMode: this.dark,
      pageBackgroundColor: pageBackground(this.dark),
      defaultColorMusic: inkColor(this.dark),
      defaultColorNotehead: inkColor(this.dark),
      defaultColorStem: inkColor(this.dark),
      defaultColorRest: inkColor(this.dark),
    });
    this.osmd = osmd;
    await osmd.load(musicxml);
    osmd.render();
    this.fitToBudget(osmd);
    this.lastWidth = this.container.clientWidth;
    this.rendered = this.correlate(expected);
    this.notifyState();
    if (expected.length > 0 && this.matchedCount < expected.length) {
      // A silent correlation failure makes score feedback vanish without any
      // other symptom, which is exactly how it went unnoticed once already.
      console.warn(
        `Score feedback: correlated ${this.matchedCount}/${expected.length} notes; ` +
          'unmatched notes will not be highlighted.',
      );
    }
    this.applyColors();
  }

  /**
   * Re-render on a different paper. OSMD reads its colour options at load time,
   * so this renders again rather than recolouring in place; at roughly 50 ms
   * that is imperceptible. Existing feedback colours are preserved.
   */
  async setDark(dark: boolean): Promise<void> {
    if (dark === this.dark || !this.musicxml) return;
    await this.render(this.musicxml, this.expected, { dark });
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
          // The part's own identity, once per staff rather than once per note.
          // `ParentStaff` and `ParentInstrument` are the OSMD chain that carries
          // the MusicXML part id and name; `staffIndex` is only the fallback for
          // MusicXML that names its parts nothing at all.
          const instrument = measure.ParentStaff?.ParentInstrument;
          const hand = handForPart(instrument?.IdString, instrument?.Name, staffIndex);

          for (const staffEntry of measure.staffEntries ?? []) {
            for (const voiceEntry of staffEntry.graphicalVoiceEntries ?? []) {
              for (const graphicalNote of voiceEntry.notes ?? []) {
                const sourcePitch = graphicalNote.sourceNote?.Pitch;
                if (!sourcePitch || typeof sourcePitch.getHalfTone !== 'function') continue;
                const pitch = osmdPitchToMidi(sourcePitch);
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

  /** Reset every rendered note to the paper's default ink colour. */
  resetColors(): void {
    this.statuses = new Map();
    this.applyColors();
  }

  /**
   * Colour notes by expected-note index. Indices missing from the map are left
   * at the default colour.
   */
  colorByExpectedIndex(statuses: Map<number, NoteStatus>): void {
    this.statuses = new Map(statuses);
    this.applyColors();
  }

  private applyColors(): void {
    if (!this.colorSupported) return;
    const palette = statusColors(this.dark);
    try {
      for (const entry of this.rendered) {
        if (entry.expectedIndex === null) continue;
        const status = this.statuses.get(entry.expectedIndex) ?? 'pending';
        entry.graphicalNote.setColor(palette[status], {
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

  /**
   * Height the score occupies on the page, including the paper's padding.
   *
   * Measuring the container rather than summing the SVGs keeps the fit target
   * and the budget in the same units; comparing SVG height against a budget for
   * the whole box left a padding-sized error that long exercises sat in.
   */
  private contentHeight(): number {
    return this.container.getBoundingClientRect().height;
  }

  /**
   * OSMD appends a fresh SVG on every `render()` rather than replacing the
   * previous one. Calling render twice therefore stacks two full scores and the
   * container height silently becomes their sum, which broke both the layout and
   * any measurement of it.
   */
  private clearRendered(): void {
    for (const svg of Array.from(this.container.querySelectorAll('svg'))) svg.remove();
  }

  /**
   * Scale the engraving down so the whole exercise fits the height budget.
   *
   * Iterated rather than solved in one step: shrinking changes how many bars fit
   * per system, so the resulting height is not a linear function of the zoom. A
   * single pass consistently landed above budget for long exercises.
   *
   * Safe to render repeatedly only because `clearRendered()` runs first — OSMD
   * appends rather than replaces.
   */
  private fitToBudget(osmd: OpenSheetMusicDisplay): void {
    this.appliedZoom = 1;
    this.fitsInBudget = true;
    if (!this.maxHeight) return;

    const initialHeight = this.contentHeight();
    if (initialHeight <= 0 || initialHeight <= this.maxHeight) return;

    for (let attempt = 0; attempt < 4; attempt += 1) {
      const height = this.contentHeight();
      if (height <= this.maxHeight) break;

      const zoom = Math.max(MIN_ZOOM, Math.min(1, (this.maxHeight / height) * this.appliedZoom));
      if (Math.abs(zoom - this.appliedZoom) < 0.005) {
        this.appliedZoom = zoom;
        break;
      }
      this.appliedZoom = zoom;
      osmd.Zoom = zoom;
      this.clearRendered();
      osmd.render();
    }

    this.fitsInBudget = this.contentHeight() <= this.maxHeight;
  }

  private notifyState(): void {
    this.onStateChange?.({ zoom: this.appliedZoom, fits: this.fitsInBudget });
  }

  private observeLayout(): void {
    if (this.observer || typeof ResizeObserver === 'undefined') return;
    this.observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? 0;
      // Deliberately coarse. Scrollbar appearance and sub-pixel layout jitter
      // move the width by a few pixels and must not trigger a re-wrap; only a
      // genuine resize should.
      if (!width || Math.abs(width - this.lastWidth) < 24) return;
      this.lastWidth = width;
      if (this.relayoutTimer) clearTimeout(this.relayoutTimer);
      // Debounced: a resize drag fires continuously.
      this.relayoutTimer = setTimeout(() => void this.enqueueRender(), 200);
    });
    this.observer.observe(this.container);
  }

  dispose(): void {
    this.observer?.disconnect();
    this.observer = null;
    if (this.relayoutTimer) clearTimeout(this.relayoutTimer);
    this.container.innerHTML = '';
    this.osmd = null;
    this.rendered = [];
    this.musicxml = '';
    this.statuses = new Map();
  }
}
