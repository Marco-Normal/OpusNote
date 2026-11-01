/**
 * Local storage preferences for app-level settings.
 *
 * Owned by this pure module so defaults, constraints, and serialization
 * are isolated and unit-testable without mounting the entire state singleton.
 */

import type { HandChoice } from './types.ts';

export const LATENCY_STORAGE_KEY = 'srt.latencyMs';
export const BARS_STORAGE_KEY = 'srt.bars';
export const FOCUS_STORAGE_KEY = 'srt.focusMode';
export const CAPTURE_STORAGE_KEY = 'srt.capture';
export const MIDI_PIN_STORAGE_KEY = 'srt.midi.pin';
export const COUNT_IN_BARS_STORAGE_KEY = 'srt.countInBars';
export const CLICK_VOLUME_STORAGE_KEY = 'srt.clickVolume';
export const WEEKLY_TARGET_STORAGE_KEY = 'srt.weeklyTargetDays';
export const PINNED_LEVEL_STORAGE_KEY = 'srt.pinnedLevel';
export const PINNED_HAND_STORAGE_KEY = 'srt.pinnedHand';

/** Exercise lengths offered in the UI. Length is a preference, not difficulty. */
export const BAR_CHOICES = [4, 8, 12, 16] as const;

export function readBars(): number {
  try {
    const raw = localStorage.getItem(BARS_STORAGE_KEY);
    if (raw === null) return 4;
    const value = Number(raw);
    return (BAR_CHOICES as readonly number[]).includes(value) ? value : 4;
  } catch {
    return 4;
  }
}

export function writeBars(value: number): void {
  try {
    localStorage.setItem(BARS_STORAGE_KEY, String(value));
  } catch {
    // Ignore storage write failures (e.g. storage disabled).
  }
}

/**
 * The pinned difficulty, or null for the adaptive choice.
 */
export function readPinnedLevel(): number | null {
  try {
    const raw = localStorage.getItem(PINNED_LEVEL_STORAGE_KEY);
    if (raw === null) return null;
    const value = Number(raw);
    return Number.isInteger(value) && value >= 1 && value <= 10 ? value : null;
  } catch {
    return null;
  }
}

export function writePinnedLevel(value: number | null): void {
  try {
    if (value === null) {
      localStorage.removeItem(PINNED_LEVEL_STORAGE_KEY);
    } else {
      localStorage.setItem(PINNED_LEVEL_STORAGE_KEY, String(value));
    }
  } catch {
    // Ignore storage failure
  }
}

/** The pinned hand, or null to let the difficulty decide. */
export function readPinnedHand(): HandChoice | null {
  try {
    const value = localStorage.getItem(PINNED_HAND_STORAGE_KEY);
    return value === 'RH' || value === 'LH' || value === 'both' ? value : null;
  } catch {
    return null;
  }
}

export function writePinnedHand(value: HandChoice | null): void {
  try {
    if (value === null) {
      localStorage.removeItem(PINNED_HAND_STORAGE_KEY);
    } else {
      localStorage.setItem(PINNED_HAND_STORAGE_KEY, value);
    }
  } catch {
    // Ignore storage failure
  }
}

export function readFocus(): boolean {
  try {
    return localStorage.getItem(FOCUS_STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

export function writeFocus(value: boolean): void {
  try {
    localStorage.setItem(FOCUS_STORAGE_KEY, String(value));
  } catch {
    // Ignore storage failure
  }
}

export function readCountInBars(): number {
  try {
    const raw = localStorage.getItem(COUNT_IN_BARS_STORAGE_KEY);
    if (raw === null) return 1;
    const value = Number(raw);
    return value === 0 || value === 1 || value === 2 ? value : 1;
  } catch {
    return 1;
  }
}

export function writeCountInBars(value: number): void {
  try {
    localStorage.setItem(COUNT_IN_BARS_STORAGE_KEY, String(value));
  } catch {
    // Ignore storage failure
  }
}

export function readWeeklyTarget(): number {
  try {
    const raw = localStorage.getItem(WEEKLY_TARGET_STORAGE_KEY);
    if (raw === null) return 4;
    const value = Number(raw);
    return Number.isInteger(value) && value >= 1 && value <= 7 ? value : 4;
  } catch {
    return 4;
  }
}

export function writeWeeklyTarget(value: number): void {
  try {
    localStorage.setItem(WEEKLY_TARGET_STORAGE_KEY, String(value));
  } catch {
    // Ignore storage failure
  }
}

/** Click volume as a MIDI-style controller value, 0..127, so the app has one scale. */
export function readClickVolume(): number {
  try {
    const raw = localStorage.getItem(CLICK_VOLUME_STORAGE_KEY);
    if (raw === null) return 96;
    const value = Number(raw);
    return Number.isFinite(value) && value >= 0 && value <= 127 ? value : 96;
  } catch {
    return 96;
  }
}

export function writeClickVolume(value: number): void {
  try {
    localStorage.setItem(CLICK_VOLUME_STORAGE_KEY, String(value));
  } catch {
    // Ignore storage failure
  }
}

export function readCapture(): boolean {
  try {
    // Default on: the whole point of the log is that it happens without asking.
    return localStorage.getItem(CAPTURE_STORAGE_KEY) !== 'false';
  } catch {
    return true;
  }
}

export function writeCapture(value: boolean): void {
  try {
    localStorage.setItem(CAPTURE_STORAGE_KEY, String(value));
  } catch {
    // Ignore storage failure
  }
}

export function readPinnedFingerprint(): string | null {
  try {
    return localStorage.getItem(MIDI_PIN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function writePinnedFingerprint(value: string | null): void {
  try {
    if (value === null) {
      localStorage.removeItem(MIDI_PIN_STORAGE_KEY);
    } else {
      localStorage.setItem(MIDI_PIN_STORAGE_KEY, value);
    }
  } catch {
    // Ignore storage failure
  }
}

export function readStoredLatency(): number {
  try {
    const raw = localStorage.getItem(LATENCY_STORAGE_KEY);
    const value = raw === null ? 0 : Number(raw);
    return Number.isFinite(value) ? Math.max(0, Math.min(500, value)) : 0;
  } catch {
    return 0;
  }
}

export function writeStoredLatency(value: number): void {
  try {
    localStorage.setItem(LATENCY_STORAGE_KEY, String(value));
  } catch {
    // Ignore storage failure
  }
}
