/**
 * Which action each gesture on the sostenuto carries.
 *
 * A pure module rather than three fields in the store, because it owns a rule the store cannot
 * test: **one action occupies one gesture**. Two gestures bound to the same action would be a
 * pedal that does the same thing twice, which no picker can show and no player can reason about,
 * so assigning an action clears it from wherever it was.
 *
 * The stored form is a small JSON object under one `localStorage` key. A value this build does
 * not recognise falls back **per gesture** rather than discarding the whole preference: a
 * hand-edited or forward-written key must not silently disable a pedal, because a pedal that does
 * nothing is exactly what the discovery report exists to distinguish from a feature that is
 * broken.
 */

import type { HandsfreeAction, PedalBindings, PedalGestureKind } from './pedalGesture';

/** The list, in the order the picker offers it. */
export const HANDSFREE_ACTIONS: readonly HandsfreeAction[] = [
  'mark_review',
  'toggle_workout',
  'toggle_audio_capture',
  'finish_sitting',
];

export const PEDAL_GESTURE_KINDS: readonly PedalGestureKind[] = ['single', 'double', 'hold'];

/** What each action does, in the panel's words. */
export const ACTION_LABELS: Record<HandsfreeAction, string> = {
  mark_review: 'flag this place for review',
  toggle_workout: 'start or finish a workout',
  toggle_audio_capture: 'arm or stop take recording',
  finish_sitting: 'finish the sitting',
};

/**
 * The same actions in two or three words, for the pedal pill.
 *
 * The full label is a select option, where there is room; the pill has to say what the pedal does
 * beside the discovery report without becoming the widest thing in the panel.
 */
export const ACTION_SHORT: Record<HandsfreeAction, string> = {
  mark_review: 'flag',
  toggle_workout: 'workout',
  toggle_audio_capture: 'take recording',
  finish_sitting: 'finish sitting',
};

/** What each gesture is, in the panel's words. */
export const GESTURE_LABELS: Record<PedalGestureKind, string> = {
  single: 'press',
  double: 'double press',
  hold: 'press and hold',
};

/**
 * The shipped partition: the benign action takes the gesture that is easiest to fire by
 * accident, and the one action that can destroy work takes the gesture that cannot be.
 *
 * `finish_sitting` is deliberately absent: it is the most destructive entry and the rarest, so it
 * waits to be chosen rather than arriving pre-bound.
 */
export const DEFAULT_BINDINGS: PedalBindings = {
  single: 'mark_review',
  double: 'toggle_workout',
  hold: 'toggle_audio_capture',
};

export const PEDAL_BINDINGS_STORAGE_KEY = 'srt.pedal.bindings';

/** Assign an action to a gesture, or clear one with null. One action, one gesture. */
export function assignBinding(
  bindings: PedalBindings,
  kind: PedalGestureKind,
  action: HandsfreeAction | null,
): PedalBindings {
  const next: PedalBindings = { ...bindings, [kind]: action };
  if (action !== null) {
    for (const other of PEDAL_GESTURE_KINDS) {
      if (other !== kind && next[other] === action) next[other] = null;
    }
  }
  return next;
}

/** The stored preference, or the defaults. Unrecognised values fall back per gesture. */
export function parseBindings(raw: string | null): PedalBindings {
  const next: PedalBindings = { ...DEFAULT_BINDINGS };
  if (raw === null) return next;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return next;
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return next;

  const record = parsed as Record<string, unknown>;
  for (const kind of PEDAL_GESTURE_KINDS) {
    if (!(kind in record)) continue; // absent keeps the default
    const value = record[kind];
    if (value === null) {
      next[kind] = null;
      continue;
    }
    if (typeof value === 'string' && (HANDSFREE_ACTIONS as readonly string[]).includes(value)) {
      next[kind] = value as HandsfreeAction;
    }
  }

  // A stored duplicate keeps the first gesture and clears the rest, so the partition the panel
  // shows is the partition the recogniser uses.
  const claimed = new Set<HandsfreeAction>();
  for (const kind of PEDAL_GESTURE_KINDS) {
    const value = next[kind];
    if (value === null) continue;
    if (claimed.has(value)) next[kind] = null;
    else claimed.add(value);
  }
  return next;
}

export function serialiseBindings(bindings: PedalBindings): string {
  return JSON.stringify(bindings);
}

/** The stored preference, or the defaults. Storage being unavailable is not an error. */
export function loadBindings(): PedalBindings {
  try {
    return parseBindings(localStorage.getItem(PEDAL_BINDINGS_STORAGE_KEY));
  } catch {
    return { ...DEFAULT_BINDINGS };
  }
}

export function saveBindings(bindings: PedalBindings): void {
  try {
    localStorage.setItem(PEDAL_BINDINGS_STORAGE_KEY, serialiseBindings(bindings));
  } catch {
    // A preference that cannot be written is a preference that resets on reload. Saying so
    // would be noise in a panel about pedals.
  }
}
