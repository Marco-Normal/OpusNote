<script lang="ts">
  /**
   * Skill radar: one axis per skill dimension, drawn on a 1-10 level scale.
   *
   * Hand-rolled SVG rather than a charting dependency — it is one polygon and
   * a dozen labels, and it keeps the bundle small.
   */

  import { theme } from '../lib/theme.svelte';

  interface Props {
    axes: { slug: string; name: string; level: number }[];
    max?: number;
  }

  let { axes, max = 10 }: Props = $props();

  const SIZE = 340;
  const CENTER = SIZE / 2;
  /** Leaves room for two lines of label at the horizontal extremes, where the text has to
   *  fit between the polygon and the edge of the canvas. */
  const RADIUS = SIZE / 2 - 66;
  const LINE_HEIGHT = 10;

  /**
   * Characters per label line.
   *
   * The longest axis name is "Articulation and dynamics" at 25 characters. Unwrapped it ran
   * off the left of the viewBox, and it collided with "Key signatures" on the way — which is
   * what the overlap on the Progress view was. 14 keeps "Key signatures" and "Hand position"
   * on one line while splitting the one name that needs it.
   */
  const LABEL_WRAP = 14;

  /** Word-wrap a label, keeping at most two lines so the chart stays readable. */
  function wrap(name: string): string[] {
    const lines: string[] = [];
    for (const word of name.split(/\s+/)) {
      const last = lines[lines.length - 1];
      if (last !== undefined && `${last} ${word}`.length <= LABEL_WRAP) {
        lines[lines.length - 1] = `${last} ${word}`;
      } else {
        lines.push(word);
      }
    }
    if (lines.length <= 2) return lines;
    // Never drop a word: fold the remainder onto the second line rather than truncating,
    // because a truncated axis name is a wrong axis name.
    return [lines[0], lines.slice(1).join(' ')];
  }

  const points = $derived.by(() => {
    const count = axes.length || 1;
    return axes.map((axis, index) => {
      const angle = (Math.PI * 2 * index) / count - Math.PI / 2;
      const clamped = Math.max(0, Math.min(max, axis.level));
      const ratio = clamped / max;
      const labelX = CENTER + Math.cos(angle) * (RADIUS + 20);
      const labelY = CENTER + Math.sin(angle) * (RADIUS + 20);
      const lines = wrap(axis.name);
      // The block is the label lines plus the value beneath them, centred on the anchor.
      const blockTop = labelY - ((lines.length + 1) * LINE_HEIGHT) / 2 + LINE_HEIGHT / 2;
      return {
        ...axis,
        angle,
        x: CENTER + Math.cos(angle) * RADIUS * ratio,
        y: CENTER + Math.sin(angle) * RADIUS * ratio,
        labelX,
        lines,
        blockTop,
        anchor: Math.abs(labelX - CENTER) < 12 ? 'middle' : labelX > CENTER ? 'start' : 'end',
        axisX: CENTER + Math.cos(angle) * RADIUS,
        axisY: CENTER + Math.sin(angle) * RADIUS,
      };
    });
  });

  const polygon = $derived(points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' '));

  const rings = [0.25, 0.5, 0.75, 1];
</script>

<svg
  viewBox="0 0 {SIZE} {SIZE}"
  role="img"
  aria-label="Skill levels radar chart"
  style="--radar-fill: {theme.charts.radarFill}; --radar-stroke: {theme.charts.radarStroke};"
>
  {#each rings as ring (ring)}
    <polygon
      class="ring"
      points={points
        .map((point) => {
          const x = CENTER + Math.cos(point.angle) * RADIUS * ring;
          const y = CENTER + Math.sin(point.angle) * RADIUS * ring;
          return `${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(' ')}
    />
  {/each}

  {#each points as point (point.slug)}
    <line class="spoke" x1={CENTER} y1={CENTER} x2={point.axisX} y2={point.axisY} />
  {/each}

  <polygon class="area" points={polygon} />

  {#each points as point (point.slug)}
    <circle class="dot" cx={point.x} cy={point.y} r="3" />
    {#each point.lines as line, index (index)}
      <text
        class="label"
        x={point.labelX}
        y={point.blockTop + index * LINE_HEIGHT}
        text-anchor={point.anchor}
        dominant-baseline="middle"
      >
        {line}
      </text>
    {/each}
    <text
      class="value"
      x={point.labelX}
      y={point.blockTop + point.lines.length * LINE_HEIGHT}
      text-anchor={point.anchor}
      dominant-baseline="middle"
    >
      {point.level.toFixed(1)}
    </text>
  {/each}
</svg>

<style>
  svg {
    width: 100%;
    max-width: 30rem;
    height: auto;
    /* A wrapped word can still be wider than the gap left at the horizontal extremes; letting
       it paint past the viewBox means the worst case is a label near the card's edge rather
       than a label cut in half. */
    overflow: visible;
  }

  .ring {
    fill: none;
    stroke: var(--line);
    stroke-width: 1;
  }

  .spoke {
    stroke: var(--line);
    stroke-width: 1;
  }

  .area {
    fill: var(--radar-fill);
    stroke: var(--radar-stroke);
    stroke-width: 2;
    stroke-linejoin: round;
  }

  .dot {
    fill: var(--radar-stroke);
  }

  .label {
    font-size: 9.5px;
    fill: var(--muted);
    /* No `text-transform: capitalize`: the names arrive correctly cased ("Articulation and
       dynamics") and capitalising every word turned them into "Articulation And Dynamics". */
  }

  .value {
    font-size: 9px;
    fill: var(--ink);
    font-weight: 600;
    font-family: var(--mono);
  }
</style>
