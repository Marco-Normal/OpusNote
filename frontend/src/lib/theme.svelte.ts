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

function chartPalette(theme: ResolvedTheme): ChartPalette {
  return theme === 'dark'
    ? {
        overall: '#8b93ff',
        pitch: '#4ade80',
        rhythm: '#fbbf24',
        radarFill: 'rgba(139, 147, 255, 0.22)',
        radarStroke: '#8b93ff',
      }
    : {
        overall: '#4338ca',
        pitch: '#15803d',
        rhythm: '#b45309',
        radarFill: 'rgba(67, 56, 202, 0.16)',
        radarStroke: '#4338ca',
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

  charts = $derived(chartPalette(this.resolved as ResolvedTheme));

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
