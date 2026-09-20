/**
 * Theme state: a three-way preference (system/light/dark) plus an independent
 * "score paper" choice.
 *
 * Notation inverts badly for some readers, so the score's theme is deliberately
 * decoupled from the chrome's: you can run a dark UI with paper-white music.
 *
 * The *resolved* theme is written to `document.documentElement` as
 * `data-theme`, and the resolved paper as `data-score-paper`. CSS keys off
 * those, and `index.html` sets them before first paint so there is no flash.
 */

export type ThemePreference = 'system' | 'light' | 'dark';
export type ScorePaper = 'theme' | 'light';
export type ResolvedTheme = 'light' | 'dark';

const PREFERENCE_KEY = 'srt.theme';
const PAPER_KEY = 'srt.scorePaper';

export interface ChartPalette {
  overall: string;
  pitch: string;
  rhythm: string;
  radarFill: string;
  radarStroke: string;
}

function readStored(key: string, allowed: readonly string[], fallback: string): string {
  try {
    const raw = localStorage.getItem(key);
    return raw !== null && allowed.includes(raw) ? raw : fallback;
  } catch {
    return fallback;
  }
}

function prefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

/**
 * Placeholder until the stylesheet has been read.
 *
 * `currentColor` rather than a hex, so the worst case if a chart ever renders before the
 * effect below runs is a correctly-coloured-but-unstyled chart rather than an invisible one.
 * The effect runs after mount and before paint, so this is not expected to be seen.
 */
const UNREAD_PALETTE: ChartPalette = {
  overall: 'currentColor',
  pitch: 'currentColor',
  rhythm: 'currentColor',
  radarFill: 'transparent',
  radarStroke: 'currentColor',
};

/**
 * Read the chart colours the stylesheet declares.
 *
 * `app.css` owns them — as `--chart-*`, themselves derived from `--accent`, `--good` and
 * `--warn`. Before this, the same six colours were typed out a second time here as hex
 * literals, which meant a rebrand had two owners and the two could silently drift. Now
 * there is one.
 *
 * Browsers substitute `var()` *inside* a custom property at computed-value time, so what
 * comes back is a resolved colour rather than the string `var(--accent)` — verified against
 * Chromium, which is the only engine this app runs on.
 */
function readChartPalette(): ChartPalette {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string): string =>
    style.getPropertyValue(name).trim() || fallback;

  return {
    overall: read('--chart-overall', UNREAD_PALETTE.overall),
    pitch: read('--chart-pitch', UNREAD_PALETTE.pitch),
    rhythm: read('--chart-rhythm', UNREAD_PALETTE.rhythm),
    radarFill: read('--chart-radar-fill', UNREAD_PALETTE.radarFill),
    radarStroke: read('--chart-radar-stroke', UNREAD_PALETTE.radarStroke),
  };
}

class ThemeState {
  preference = $state<ThemePreference>(
    readStored(PREFERENCE_KEY, ['system', 'light', 'dark'], 'system') as ThemePreference,
  );
  scorePaper = $state<ScorePaper>(readStored(PAPER_KEY, ['theme', 'light'], 'theme') as ScorePaper);

  private systemDark = $state(prefersDark());

  resolved = $derived(
    this.preference === 'system' ? (this.systemDark ? 'dark' : 'light') : this.preference,
  ) as ResolvedTheme;

  /** Whether the *notation* should render light-on-dark. */
  scoreIsDark = $derived(this.scorePaper === 'theme' ? this.resolved === 'dark' : false);

  charts = $state<ChartPalette>(UNREAD_PALETTE);

  constructor() {
    if (typeof window === 'undefined') return;

    // Follow the OS live while the preference is "system".
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    query.addEventListener('change', (event) => {
      this.systemDark = event.matches;
    });

    $effect.root(() => {
      $effect(() => {
        const root = document.documentElement;
        root.dataset.theme = this.resolved;
        root.dataset.scorePaper = this.scoreIsDark ? 'dark' : 'light';
        // Keeps native scrollbars and form controls in step with the theme.
        root.style.colorScheme = this.resolved;

        // Read *after* the theme attribute is applied, so the palette reflects the theme
        // just set rather than the one being replaced. This is the only writer of `charts`.
        this.charts = readChartPalette();
      });
    });
  }

  setPreference(preference: ThemePreference): void {
    this.preference = preference;
    this.store(PREFERENCE_KEY, preference);
  }

  setScorePaper(paper: ScorePaper): void {
    this.scorePaper = paper;
    this.store(PAPER_KEY, paper);
  }

  private store(key: string, value: string): void {
    try {
      localStorage.setItem(key, value);
    } catch {
      // Private mode: the in-memory value still applies for this session.
    }
  }
}

export const theme = new ThemeState();
