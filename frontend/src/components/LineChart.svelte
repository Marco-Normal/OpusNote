<script lang="ts">
  /**
   * A small multi-series line chart for score history and tempo progress.
   */

  interface Series {
    label: string;
    color: string;
    points: { x: number; y: number }[];
  }

  interface Props {
    series: Series[];
    yMin?: number;
    yMax?: number;
    yLabel?: string;
    height?: number;
  }

  let { series, yMin = 0, yMax = 100, yLabel = '', height = 190 }: Props = $props();

  const WIDTH = 640;
  const PAD = { top: 12, right: 14, bottom: 26, left: 38 };

  const plotWidth = WIDTH - PAD.left - PAD.right;
  const plotHeight = $derived(height - PAD.top - PAD.bottom);

  const allPoints = $derived(series.flatMap((item) => item.points));
  const xMin = $derived(allPoints.length ? Math.min(...allPoints.map((point) => point.x)) : 0);
  const xMax = $derived(allPoints.length ? Math.max(...allPoints.map((point) => point.x)) : 1);

  function scaleX(x: number): number {
    if (xMax === xMin) return PAD.left + plotWidth / 2;
    return PAD.left + ((x - xMin) / (xMax - xMin)) * plotWidth;
  }

  function scaleY(y: number): number {
    const clamped = Math.max(yMin, Math.min(yMax, y));
    return PAD.top + plotHeight - ((clamped - yMin) / (yMax - yMin)) * plotHeight;
  }

  function path(points: { x: number; y: number }[]): string {
    if (points.length === 0) return '';
    return points
      .map((point, index) => `${index === 0 ? 'M' : 'L'} ${scaleX(point.x).toFixed(1)} ${scaleY(point.y).toFixed(1)}`)
      .join(' ');
  }

  const gridValues = $derived.by(() => {
    const steps = 4;
    return Array.from({ length: steps + 1 }, (_, index) => yMin + ((yMax - yMin) * index) / steps);
  });
</script>

<div class="chart">
  {#if allPoints.length === 0}
    <p class="muted empty">No data yet.</p>
  {:else}
    <svg viewBox="0 0 {WIDTH} {height}" role="img" aria-label={yLabel || 'Chart'}>
      {#each gridValues as value (value)}
        <line class="grid" x1={PAD.left} y1={scaleY(value)} x2={WIDTH - PAD.right} y2={scaleY(value)} />
        <text class="tick" x={PAD.left - 6} y={scaleY(value)} text-anchor="end" dominant-baseline="middle">
          {Math.round(value)}
        </text>
      {/each}

      {#each series as item (item.label)}
        <path class="line" d={path(item.points)} stroke={item.color} />
        {#each item.points as point, index (index)}
          <circle cx={scaleX(point.x)} cy={scaleY(point.y)} r="2.2" fill={item.color} />
        {/each}
      {/each}

      <text class="tick" x={PAD.left} y={height - 6}>{new Date(xMin).toLocaleDateString()}</text>
      <text class="tick" x={WIDTH - PAD.right} y={height - 6} text-anchor="end">
        {new Date(xMax).toLocaleDateString()}
      </text>
    </svg>

    <div class="legend">
      {#each series as item (item.label)}
        <span class="key">
          <span class="swatch" style="background: {item.color}"></span>
          {item.label}
        </span>
      {/each}
    </div>
  {/if}
</div>

<style>
  .chart {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  svg {
    width: 100%;
    height: auto;
    overflow: visible;
  }

  .grid {
    stroke: var(--line);
    stroke-width: 1;
  }

  .line {
    fill: none;
    stroke-width: 2;
    stroke-linejoin: round;
    stroke-linecap: round;
  }

  .tick {
    font-size: 9px;
    fill: var(--muted);
    font-family: var(--mono);
  }

  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    font-size: 0.78rem;
    color: var(--muted);
  }

  .key {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
  }

  .swatch {
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 2px;
  }

  .empty {
    margin: 0;
    font-size: 0.85rem;
  }
</style>
