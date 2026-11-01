<script lang="ts">
  /**
   * The falling-notes view: the shape of what you played, not just the sound of it.
   *
   * Drawn on a canvas because it changes every frame — sixty rectangles a second is
   * exactly what a canvas is for, and exactly what the DOM is not. All the geometry
   * lives in `pianoRoll.ts`; this file only paints what those functions return, and
   * that split is what makes the direction notes fall testable at all.
   *
   * Optimized with offscreen static canvas layering: the static keyboard columns
   * and bottom keybeds are pre-rendered once per resize/theme change and blitted
   * directly to the display context, and CSS theme colors are cached rather than
   * queried repeatedly via getComputedStyle on every animation frame.
   */
  import { onMount } from 'svelte';
  import { formatClock } from '../lib/clock';
  import {
    keyLayout,
    pitchRange,
    visibleNotes,
    type RollNote,
    type KeySlot,
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

  interface ThemeInks {
    white: string;
    line: string;
    accent: string;
    muted: string;
    ink: string;
  }

  let cachedInks: ThemeInks = {
    white: '#fff',
    line: '#d5d5d0',
    accent: '#6b7cff',
    muted: '#8a8a86',
    ink: '#111',
  };

  function readInks(): ThemeInks {
    if (typeof document === 'undefined') return cachedInks;
    const style = getComputedStyle(document.documentElement);
    return {
      white: style.getPropertyValue('--surface').trim() || '#fff',
      line: style.getPropertyValue('--line').trim() || '#d5d5d0',
      accent: style.getPropertyValue('--accent').trim() || '#6b7cff',
      muted: style.getPropertyValue('--muted').trim() || '#8a8a86',
      ink: style.getPropertyValue('--ink').trim() || '#111',
    };
  }

  onMount(() => {
    cachedInks = readInks();
    const observer = new MutationObserver(() => {
      cachedInks = readInks();
      lastBackdropKey = '';
      draw();
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme', 'class', 'style'],
    });
    return () => observer.disconnect();
  });

  let offscreenCanvas: HTMLCanvasElement | null = null;
  let lastBackdropKey = '';

  function renderStaticLayers(
    width: number,
    height: number,
    slotsList: readonly KeySlot[],
    inks: ThemeInks,
  ): HTMLCanvasElement {
    const rollHeight = height - KEYBOARD_H;
    if (!offscreenCanvas) {
      offscreenCanvas = document.createElement('canvas');
    }
    if (offscreenCanvas.width !== width || offscreenCanvas.height !== height) {
      offscreenCanvas.width = width;
      offscreenCanvas.height = height;
    }
    const ctx = offscreenCanvas.getContext('2d');
    if (!ctx) return offscreenCanvas;
    ctx.clearRect(0, 0, width, height);

    // 1. White keys as backdrop across the roll
    ctx.fillStyle = inks.white;
    for (const slot of slotsList) {
      if (slot.black) continue;
      ctx.fillRect(slot.left * width, 0, slot.width * width, rollHeight);
    }
    ctx.strokeStyle = inks.line;
    ctx.lineWidth = 1;
    for (const slot of slotsList) {
      if (slot.black) continue;
      ctx.strokeRect(slot.left * width + 0.5, -1, slot.width * width, rollHeight + 1);
    }

    // 2. The keyboard background & white keys
    ctx.fillStyle = inks.white;
    ctx.fillRect(0, rollHeight, width, KEYBOARD_H);
    ctx.strokeStyle = inks.line;
    ctx.beginPath();
    ctx.moveTo(0, rollHeight + 0.5);
    ctx.lineTo(width, rollHeight + 0.5);
    ctx.stroke();
    for (const slot of slotsList) {
      if (slot.black) continue;
      ctx.strokeRect(slot.left * width + 0.5, rollHeight, slot.width * width, KEYBOARD_H);
    }

    // 3. Black keys
    ctx.fillStyle = inks.ink;
    for (const slot of slotsList) {
      if (!slot.black) continue;
      ctx.fillRect(
        slot.left * width,
        rollHeight,
        slot.width * width,
        KEYBOARD_H * 0.62,
      );
    }

    // 4. The key line
    ctx.fillStyle = inks.accent;
    ctx.fillRect(0, rollHeight - 1, width, 2);

    return offscreenCanvas;
  }

  function draw(): void {
    const element = canvas;
    if (!element) return;
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, element.clientWidth);
    const height = Math.max(1, element.clientHeight);
    const targetW = Math.round(width * ratio);
    const targetH = Math.round(height * ratio);

    if (element.width !== targetW || element.height !== targetH) {
      element.width = targetW;
      element.height = targetH;
      lastBackdropKey = '';
    }

    const context = element.getContext('2d');
    if (!context) return;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);

    const rollHeight = height - KEYBOARD_H;
    const inks = cachedInks;

    const backdropKey = `${width}x${height}@${slots.length}@${inks.white}@${inks.ink}@${inks.line}@${inks.accent}`;
    if (backdropKey !== lastBackdropKey) {
      renderStaticLayers(width, height, slots, inks);
      lastBackdropKey = backdropKey;
    }

    // 1. Draw static backdrop (roll white key columns)
    if (offscreenCanvas) {
      context.drawImage(offscreenCanvas, 0, 0, width, rollHeight, 0, 0, width, rollHeight);
    }

    // 2. The falling notes, held notes louder
    for (const placed of visibleNotes(nearby, slots, position, lookAhead)) {
      const sounding = placed.note.onset <= position;
      context.fillStyle = inks.accent;
      context.globalAlpha = sounding ? 0.95 : 0.62;
      const x = placed.slot.left * width + 1;
      const w = Math.max(1, placed.slot.width * width - 2);
      context.fillRect(x, placed.top * rollHeight, w, placed.height * rollHeight);
    }
    context.globalAlpha = 1;

    // 3. Draw static keyboard on top of falling notes
    if (offscreenCanvas) {
      context.drawImage(
        offscreenCanvas,
        0,
        rollHeight - 1,
        width,
        KEYBOARD_H + 1,
        0,
        rollHeight - 1,
        width,
        KEYBOARD_H + 1,
      );
    }

    // 4. Timestamp clock text
    context.fillStyle = inks.muted;
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
