<script lang="ts">
  /**
   * A GitHub-style practice calendar: one column per week, one cell per day.
   *
   * Cells are drawn for every day in the window, including empty ones, because a
   * heatmap of only the busy days is a solid strip that hides the gaps.
   */
  import type { CalendarDay } from '../lib/types';

  interface Props {
    days: CalendarDay[];
  }

  let { days }: Props = $props();

  /** Minutes per level, so "a lot" is relative to a normal day's practice. */
  function level(minutes: number): number {
    if (minutes <= 0) return 0;
    if (minutes < 10) return 1;
    if (minutes < 25) return 2;
    if (minutes < 50) return 3;
    return 4;
  }

  const weeks = $derived.by(() => {
    const columns: (CalendarDay | null)[][] = [];
    let current: (CalendarDay | null)[] = [];
    for (const day of days) {
      // Monday-first, so the weekend sits together at the bottom.
      const weekday = (new Date(`${day.date}T00:00:00`).getDay() + 6) % 7;
      if (current.length === 0 && weekday > 0) {
        current = Array.from({ length: weekday }, () => null);
      }
      current.push(day);
      if (current.length === 7) {
        columns.push(current);
        current = [];
      }
    }
    if (current.length) {
      while (current.length < 7) current.push(null);
      columns.push(current);
    }
    return columns;
  });

  const busiest = $derived(
    days.reduce((best, day) => (day.minutes > best.minutes ? day : best), {
      date: '—',
      minutes: 0,
      notes: 0,
      sittings: 0,
    } as CalendarDay),
  );
</script>

<div class="heat" role="img" aria-label="Practice minutes per day">
  <div class="grid">
    {#each weeks as week, index (index)}
      <div class="week">
        <!-- The key must be unique per *cell*: every padding cell in a week
             shares the same week index, and keying on that alone makes Svelte
             throw each_key_duplicate and abort the render. -->
        {#each week as day, position (day?.date ?? `blank-${index}-${position}`)}
          {#if day}
            <span
              class="cell l{level(day.minutes)}"
              data-date={day.date}
              data-level={level(day.minutes)}
              title="{day.date} · {day.minutes} min · {day.notes} notes · {day.sittings} sittings"
            ></span>
          {:else}
            <span class="cell blank"></span>
          {/if}
        {/each}
      </div>
    {/each}
  </div>

  <div class="spread footnote">
    <span class="muted small">
      {days.length} days · busiest {busiest.date} at {busiest.minutes} min
    </span>
    <span class="row legend">
      <span class="muted small">less</span>
      {#each [0, 1, 2, 3, 4] as step (step)}
        <span class="cell l{step}"></span>
      {/each}
      <span class="muted small">more</span>
    </span>
  </div>
</div>

<style>
  .heat {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .grid {
    display: flex;
    gap: 3px;
    overflow-x: auto;
    padding-bottom: 2px;
  }

  .week {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .cell {
    width: 12px;
    height: 12px;
    border-radius: 3px;
    background: var(--track);
    border: 1px solid transparent;
  }

  .cell.blank {
    background: transparent;
  }

  .l1 {
    background: var(--accent);
    opacity: 0.25;
  }

  .l2 {
    background: var(--accent);
    opacity: 0.45;
  }

  .l3 {
    background: var(--accent);
    opacity: 0.7;
  }

  .l4 {
    background: var(--accent);
    opacity: 1;
  }

  .footnote {
    align-items: center;
  }

  .legend {
    gap: 3px;
  }

  .small {
    font-size: 0.78rem;
  }
</style>
