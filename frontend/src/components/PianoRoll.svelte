<script lang="ts">
  /**
   * The falling-notes view: the shape of what you played, not just the sound of it.
   *
   * Drawn on a canvas because it changes every frame — sixty rectangles a second is
   * exactly what a canvas is for, and exactly what the DOM is not. All the geometry
   * lives in `pianoRoll.ts`; this file only paints what those functions return, and
   * that split is what makes the direction notes fall testable at all.
   */
  import { formatClock } from '../lib/clock';
  import {
    keyLayout,
    pitchRange,
    visibleNotes,
    type RollNote,
  } from '../lib/pianoRoll';

  interface Props {
    notes: readonly RollNote[];
    /** Where playback has reached, in seconds of the same timeline as the notes. */
    position: number;
    /** How many seconds of music are on screen at once. */
    lookAhead?: number;
    /** Clipped to this many seconds, so a long sitting does not draw off-screen work. */
    until?: number;
  }

  let { notes, position, lookAhead = 4, until = Infinity }: Props = $props();

  let canvas = $state<HTMLCanvasElement | undefined>(undefined);

  /**
   * The notes this view has to bother with.
   *
   * A sitting can be two hours long; the canvas shows four seconds. Filtering to the
   * neighbourhood of the playhead keeps the per-frame work proportional to what is on
   * screen rather than to what was recorded.
   */
  const nearby = $derived(
    notes.filter(
      (note) =>
        note.onset <= position + lookAhead &&
        note.onset + Math.max(0.05, note.duration) >= position - 1 &&
        note.onset < until,
    ),
  );

  // The keyboard is laid out from the range of the *whole* piece, not of the notes
  // currently on screen: a keyboard that rescaled itself as notes came and went would
  // slide around under the player's eyes.
  const range = $derived(pitchRange(notes));
  const slots = $derived(keyLayout(range.low, range.high));

  const KEYBOARD_H = 44;

  function ink(name: string, fallback: string): string {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function draw(): void {
    const element = canvas;
    if (!element) return;
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, element.clientWidth);
    const height = Math.max(1, element.clientHeight);
    element.width = Math.round(width * ratio);
    element.height = Math.round(height * ratio);
    const context = element.getContext('2d');
    if (!context) return;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);

    const rollHeight = height - KEYBOARD_H;
    const white = ink('--surface', '#fff');
    const line = ink('--line', '#d5d5d0');
    const accent = ink('--accent', '#6b7cff');
    const text = ink('--muted', '#8a8a86');

    // White keys as a backdrop across the roll, so the eye can follow a column up.
    context.fillStyle = white;
    for (const slot of slots) {
      if (slot.black) continue;
      context.fillRect(slot.left * width, 0, slot.width * width, rollHeight);
    }
    context.strokeStyle = line;
    context.lineWidth = 1;
    for (const slot of slots) {
      if (slot.black) continue;
      context.strokeRect(slot.left * width + 0.5, -1, slot.width * width, rollHeight + 1);
    }

    // The notes, and the ones being held right now drawn louder.
    for (const placed of visibleNotes(nearby, slots, position, lookAhead)) {
      const sounding = placed.note.onset <= position;
      context.fillStyle = accent;
      context.globalAlpha = sounding ? 0.95 : 0.62;
      const x = placed.slot.left * width + 1;
      const w = Math.max(1, placed.slot.width * width - 2);
      context.fillRect(x, placed.top * rollHeight, w, placed.height * rollHeight);
    }
    context.globalAlpha = 1;

    // The keyboard, drawn last so it sits in front of the falling notes.
    context.fillStyle = white;
    context.fillRect(0, rollHeight, width, KEYBOARD_H);
    context.strokeStyle = line;
    context.beginPath();
    context.moveTo(0, rollHeight + 0.5);
    context.lineTo(width, rollHeight + 0.5);
    context.stroke();
    for (const slot of slots) {
      if (slot.black) continue;
      context.strokeRect(slot.left * width + 0.5, rollHeight, slot.width * width, KEYBOARD_H);
    }
    context.fillStyle = ink('--ink', '#111');
    for (const slot of slots) {
      if (!slot.black) continue;
      context.fillRect(
        slot.left * width,
        rollHeight,
        slot.width * width,
        KEYBOARD_H * 0.62,
      );
    }
    // The key line: where a note is the moment it sounds.
    context.fillStyle = accent;
    context.fillRect(0, rollHeight - 1, width, 2);

    context.fillStyle = text;
    context.font = '11px system-ui, sans-serif';
    context.fillText(formatClock(position), 6, rollHeight - 6);
  }

  $effect(() => {
    // Every dependency this needs, read on purpose: position changes each frame, and
    // the rest matter so a resize or a new piece repaints.
    void position;
    void nearby;
    void slots;
    void canvas;
    draw();
  });
</script>

<!-- Presentation only: everything it draws is also in the note strip and in the
     sound itself, so it is hidden from assistive technology rather than described
     twice. -->
<canvas class="roll" bind:this={canvas} data-piano-roll aria-hidden="true"></canvas>

<style>
  .roll {
    display: block;
    width: 100%;
    height: 15rem;
    border: 1px solid var(--line);
    border-radius: 6px;
    background: var(--surface-2);
  }
</style>
