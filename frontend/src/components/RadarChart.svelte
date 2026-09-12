<script lang="ts">
  /**
   * Skill radar: one axis per skill dimension, drawn on a 1-10 level scale.
   *
   * Hand-rolled SVG rather than a charting dependency — it is one polygon and
   * a dozen labels, and it keeps the bundle small.
   */

  interface Props {
    axes: { slug: string; name: string; level: number }[];
    max?: number;
  }

  let { axes, max = 10 }: Props = $props();

  const SIZE = 320;
  const CENTER = SIZE / 2;
  const RADIUS = SIZE / 2 - 46;

  const points = $derived.by(() => {
    const count = axes.length || 1;
    return axes.map((axis, index) => {
      const angle = (Math.PI * 2 * index) / count - Math.PI / 2;
      const clamped = Math.max(0, Math.min(max, axis.level));
      const ratio = clamped / max;
      return {
        ...axis,
        angle,
        x: CENTER + Math.cos(angle) * RADIUS * ratio,
        y: CENTER + Math.sin(angle) * RADIUS * ratio,
        labelX: CENTER + Math.cos(angle) * (RADIUS + 20),
        labelY: CENTER + Math.sin(angle) * (RADIUS + 20),
        axisX: CENTER + Math.cos(angle) * RADIUS,
        axisY: CENTER + Math.sin(angle) * RADIUS,
      };
    });
  });

  const polygon = $derived(points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' '));

  const rings = [0.25, 0.5, 0.75, 1];
</script>

<svg viewBox="0 0 {SIZE} {SIZE}" role="img" aria-label="Skill levels radar chart">
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
    <text
      class="label"
      x={point.labelX}
      y={point.labelY}
      text-anchor={Math.abs(point.labelX - CENTER) < 12 ? 'middle' : point.labelX > CENTER ? 'start' : 'end'}
      dominant-baseline="middle"
    >
      {point.name}
    </text>
    <text
      class="value"
      x={point.labelX}
      y={point.labelY + 11}
      text-anchor={Math.abs(point.labelX - CENTER) < 12 ? 'middle' : point.labelX > CENTER ? 'start' : 'end'}
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
    fill: rgba(67, 56, 202, 0.16);
    stroke: var(--accent);
    stroke-width: 2;
    stroke-linejoin: round;
  }

  .dot {
    fill: var(--accent);
  }

  .label {
    font-size: 9.5px;
    fill: var(--muted);
    text-transform: capitalize;
  }

  .value {
    font-size: 9px;
    fill: var(--ink);
    font-weight: 600;
    font-family: var(--mono);
  }
</style>
