/**
 * Local storage preferences for app-level settings.
 *
 * Owned by this pure module so defaults, constraints, and serialization
 * are isolated and unit-testable without mounting the entire state singleton.
 */

import type { HandChoice } from './types.ts';

const LATENCY_STORAGE_KEY = 'srt.latencyMs';
const BARS_STORAGE_KEY = 'srt.bars';
const FOCUS_STORAGE_KEY = 'srt.focusMode';
const CAPTURE_STORAGE_KEY = 'srt.capture';
const MIDI_PIN_STORAGE_KEY = 'srt.midi.pin';
const COUNT_IN_BARS_STORAGE_KEY = 'srt.countInBars';
const CLICK_VOLUME_STORAGE_KEY = 'srt.clickVolume';
const WEEKLY_TARGET_STORAGE_KEY = 'srt.weeklyTargetDays';
const PINNED_LEVEL_STORAGE_KEY = 'srt.pinnedLevel';
const PINNED_HAND_STORAGE_KEY = 'srt.pinnedHand';

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // Ignore storage write failures (e.g. storage disabled).
  }
}

/** Exercise lengths offered in the UI. Length is a preference, not difficulty. */
export const BAR_CHOICES = [4, 8, 12, 16] as const;

export function readBars(): number {
  const raw = readStorage(BARS_STORAGE_KEY);
  if (raw === null) return 4;
  const value = Number(raw);
  return (BAR_CHOICES as readonly number[]).includes(value) ? value : 4;
}

export function writeBars(value: number): void {
  writeStorage(BARS_STORAGE_KEY, String(value));
}

/**
 * The pinned difficulty, or null for the adaptive choice.
 */
export function readPinnedLevel(): number | null {
  const raw = readStorage(PINNED_LEVEL_STORAGE_KEY);
  if (raw === null) return null;
  const value = Number(raw);
  return Number.isInteger(value) && value >= 1 && value <= 10 ? value : null;
}

export function writePinnedLevel(value: number | null): void {
  writeStorage(PINNED_LEVEL_STORAGE_KEY, value === null ? null : String(value));
}

/** The pinned hand, or null to let the difficulty decide. */
export function readPinnedHand(): HandChoice | null {
  const value = readStorage(PINNED_HAND_STORAGE_KEY);
  return value === 'RH' || value === 'LH' || value === 'both' ? value : null;
}

export function writePinnedHand(value: HandChoice | null): void {
  writeStorage(PINNED_HAND_STORAGE_KEY, value);
}

export function readFocus(): boolean {
  return readStorage(FOCUS_STORAGE_KEY) === 'true';
}

export function writeFocus(value: boolean): void {
  writeStorage(FOCUS_STORAGE_KEY, String(value));
}

export function readCountInBars(): number {
  const raw = readStorage(COUNT_IN_BARS_STORAGE_KEY);
  if (raw === null) return 1;
  const value = Number(raw);
  return value === 0 || value === 1 || value === 2 ? value : 1;
}

export function writeCountInBars(value: number): void {
  writeStorage(COUNT_IN_BARS_STORAGE_KEY, String(value));
}

export function readWeeklyTarget(): number {
  const raw = readStorage(WEEKLY_TARGET_STORAGE_KEY);
  if (raw === null) return 4;
  const value = Number(raw);
  return Number.isInteger(value) && value >= 1 && value <= 7 ? value : 4;
}

export function writeWeeklyTarget(value: number): void {
  writeStorage(WEEKLY_TARGET_STORAGE_KEY, String(value));
}

/** Click volume as a MIDI-style controller value, 0..127, so the app has one scale. */
export function readClickVolume(): number {
  const raw = readStorage(CLICK_VOLUME_STORAGE_KEY);
  if (raw === null) return 96;
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 && value <= 127 ? value : 96;
}

export function writeClickVolume(value: number): void {
  writeStorage(CLICK_VOLUME_STORAGE_KEY, String(value));
}

export function readCapture(): boolean {
  // Default on: the whole point of the log is that it happens without asking.
  return readStorage(CAPTURE_STORAGE_KEY) !== 'false';
}

export function writeCapture(value: boolean): void {
  writeStorage(CAPTURE_STORAGE_KEY, String(value));
}

export function readPinnedFingerprint(): string | null {
  return readStorage(MIDI_PIN_STORAGE_KEY);
}

export function writePinnedFingerprint(value: string | null): void {
  writeStorage(MIDI_PIN_STORAGE_KEY, value);
}

export function readStoredLatency(): number {
  const raw = readStorage(LATENCY_STORAGE_KEY);
  const value = raw === null ? 0 : Number(raw);
  return Number.isFinite(value) ? Math.max(0, Math.min(500, value)) : 0;
}

export function writeStoredLatency(value: number): void {
  writeStorage(LATENCY_STORAGE_KEY, String(value));
}
