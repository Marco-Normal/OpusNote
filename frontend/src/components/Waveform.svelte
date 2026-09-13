<script lang="ts">
  /**
   * A recording drawn as its own envelope, with the A/B loop on it.
   *
   * Two stacked canvases on purpose: the picture only changes when the peaks or
   * the markers do, while the playhead moves sixty times a second. Redrawing
   * sixteen hundred bars per frame to move one line is a waste of a practice
   * machine's battery.
   *
   * Nothing here knows what is playing. It draws what it is handed and reports a
   * click as a time — the player element lives in `RecordingPlayer`.
   */
  import { ratioToTime, timeToRatio, type Loop, type Peaks } from '../lib/waveform';

  interface Props {
    peaks: Peaks;
    loop: Loop;
    /** Playback position in seconds; drawn as a moving line. */
    position: number;
    duration: number;
    /** A click anywhere on the picture, in seconds. */
    onSeek: (seconds: number) => void;
  }

  let { peaks, loop, position, duration, onSeek }: Props = $props();

  let base = $state<HTMLCanvasElement | undefined>(undefined);
  let head = $state<HTMLCanvasElement | undefined>(undefined);
  /**
   * Bumped on a window resize so the drawing effects run again. A canvas keeps
   * the pixel size it was last given, so without this a resized window would
   * stretch the old picture instead of redrawing it.
   */
  let epoch = $state(0);

  $effect(() => {
    const bump = () => {
      epoch += 1;
    };
    window.addEventListener('resize', bump);
    return () => window.removeEventListener('resize', bump);
  });

  /** Colours follow the theme, so the picture is not a light-mode island. */
  function ink(name: string, fallback: string): string {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function prepare(canvas: HTMLCanvasElement, ratio: number): CanvasRenderingContext2D | null {
    const width = Math.max(1, canvas.clientWidth);
    const height = Math.max(1, canvas.clientHeight);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const context = canvas.getContext('2d');
    if (!context) return null;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    return context;
  }

  function xFor(seconds: number, width: number): number {
    return timeToRatio(seconds, duration) * width;
  }

  $effect(() => {
    const canvas = base;
    const columns = peaks.low.length;
    // `epoch` is a dependency only so a resize redraws; it is not read otherwise.
    void epoch;
    if (!canvas || columns === 0) return;

    const ratio = window.devicePixelRatio || 1;
    const context = prepare(canvas, ratio);
    if (!context) return;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    const middle = height / 2;

    const { start, end } = loop;
    const marked = start !== null && end !== null && end > start;
    const from = marked ? xFor(start as number, width) : 0;
    const to = marked ? xFor(end as number, width) : 0;
    if (marked) {
      context.fillStyle = ink('--accent-soft', 'rgba(120,130,255,0.15)');
      context.fillRect(from, 0, Math.max(1, to - from), height);
    }

    context.fillStyle = ink('--accent', '#6b7cff');
    const columnWidth = width / columns;
    const barWidth = Math.max(1, columnWidth * 0.8);
    for (let column = 0; column < columns; column += 1) {
      const x = column * columnWidth;
      // Audio outside the loop is dimmed rather than hidden: the passage being
      // worked on has to be findable *by its surroundings*, which is the whole
      // reason for looking at a waveform.
      context.globalAlpha = !marked || (x >= from && x <= to) ? 1 : 0.3;
      const top = middle - peaks.high[column] * middle;
      const bottom = middle - peaks.low[column] * middle;
      context.fillRect(x, top, barWidth, Math.max(1, bottom - top));
    }
    context.globalAlpha = 1;

    // The centre line, so a silent passage still reads as a recording rather
    // than as a waveform that failed to load.
    context.fillStyle = ink('--line', '#2b2f36');
    context.fillRect(0, middle, width, 1);

    const markers: [number, string][] = [];
    if (start !== null) markers.push([start, ink('--good', '#15803d')]);
    if (end !== null) markers.push([end, ink('--warn', '#b45309')]);
    for (const [seconds, colour] of markers) {
      context.fillStyle = colour;
      context.fillRect(Math.min(width - 2, Math.max(0, xFor(seconds, width) - 1)), 0, 2, height);
    }
  });

  $effect(() => {
    const canvas = head;
    void epoch;
    if (!canvas) return;
    const ratio = window.devicePixelRatio || 1;
    const context = prepare(canvas, ratio);
    if (!context) return;
    const width = canvas.clientWidth;
    if (!(duration > 0)) return;
    context.fillStyle = ink('--ink', '#111');
    context.fillRect(Math.min(width - 1, Math.max(0, xFor(position, width))), 0, 1, canvas.clientHeight);
  });

  function seek(event: MouseEvent): void {
    const canvas = base;
    if (!canvas) return;
    const bounds = canvas.getBoundingClientRect();
    if (bounds.width <= 0) return;
    onSeek(ratioToTime((event.clientX - bounds.left) / bounds.width, duration));
  }
</script>

<div
  class="wave"
  role="slider"
  tabindex="0"
  aria-label="Recording waveform"
  aria-valuemin="0"
  aria-valuemax={Math.round(duration)}
  aria-valuenow={Math.round(position)}
  data-waveform
  onclick={seek}
  onkeydown={(event) => {
    // A keyboard equivalent for the click-to-seek, in tenths of a second.
    if (event.key === 'ArrowRight') onSeek(Math.min(duration, position + 0.1));
    if (event.key === 'ArrowLeft') onSeek(Math.max(0, position - 0.1));
  }}
>
  <canvas class="base" bind:this={base}></canvas>
  <canvas class="head" bind:this={head}></canvas>
</div>

<style>
  .wave {
    position: relative;
    height: 4.5rem;
    border: 1px solid var(--line);
    border-radius: 6px;
    background: var(--surface);
    cursor: crosshair;
    overflow: hidden;
  }

  .wave:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }

  canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    display: block;
  }

  .head {
    pointer-events: none;
  }
</style>
