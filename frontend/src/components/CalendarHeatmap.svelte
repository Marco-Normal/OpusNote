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
      written_minutes: 0,
      written_entries: 0,
    } as CalendarDay),
  );

  /**
   * What was written down, totalled separately from what was measured.
   *
   * The two are never added: a session can be both played and written about, so a
   * combined figure would count it twice. The heat itself stays measured-only for
   * the same reason — written time is an overlay on the picture, not part of its
   * scale.
   */
  const writtenTotal = $derived(
    Math.round(days.reduce((sum, day) => sum + day.written_minutes, 0) * 10) / 10,
  );
  const writtenDays = $derived(days.filter((day) => day.written_minutes > 0).length);
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
              class:written={day.written_minutes > 0}
              class:unmeasured={day.written_minutes > 0 && day.minutes <= 0}
              data-date={day.date}
              data-level={level(day.minutes)}
              data-written={day.written_minutes}
              title="{day.date} · {day.minutes} min · {day.notes} notes · {day.sittings} sittings{day.written_minutes
                ? ` · ${day.written_minutes} min written down`
                : ''}"
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
      {#if writtenDays > 0}
        · {writtenTotal} min written down over {writtenDays}
        {writtenDays === 1 ? 'day' : 'days'}
      {/if}
    </span>
    <span class="row legend">
      <span class="muted small">less</span>
      {#each [0, 1, 2, 3, 4] as step (step)}
        <span class="cell l{step}"></span>
      {/each}
      <span class="muted small">more</span>
      <span class="cell l2 written"></span>
      <span class="muted small">written down</span>
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

  /* Written time is an overlay, so it is drawn as a border rather than as another
     shade: the fill still means "minutes the piano heard" and nothing else. */
  .cell.written {
    border-color: var(--accent);
  }

  /* A day with prose and nothing measured is its own state, not a low value. */
  .cell.unmeasured {
    background: transparent;
    border-style: dashed;
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
