<script lang="ts">
  import BarChart from './BarChart.svelte';
  import { formatMinutes, type AnalyticsSummary, type RatingHistory } from '../lib/types';

  interface Props {
    summary: AnalyticsSummary;
    week: RatingHistory | null;
    weeklyTargetDays: number;
  }

  let { summary, week, weeklyTargetDays }: Props = $props();
</script>

<section class="card review" data-week-review>
  <h3>This week</h3>
  <div class="review-grid">
    <div data-week-target={weeklyTargetDays}>
      <span class="muted small">Practised</span>
      <strong>{formatMinutes(summary.calendar.slice(-7).reduce((sum, day) => sum + day.minutes, 0))}</strong>
      <span class="muted small">
        on {summary.calendar.slice(-7).filter((day) => day.minutes > 0).length} of
        {weeklyTargetDays} target days
      </span>
    </div>
    <div>
      <span class="muted small">Sight-reading</span>
      <strong>{summary.workouts_this_week} workouts</strong>
      <span class="muted small">
        {summary.streak_days}-day streak{summary.streak_grace_used > 0 ? ' · 1 rest day' : ''}
      </span>
    </div>
    <div>
      <span class="muted small">Most improved</span>
      {#if week && week.biggest_gain}
        <strong>{week.biggest_gain}</strong>
        <span class="muted small">
          {week.biggest_gain_delta > 0 ? '+' : ''}{week.biggest_gain_delta} rating
        </span>
      {:else}
        <strong class="muted">—</strong>
        <span class="muted small">nothing scored yet</span>
      {/if}
    </div>
    <div>
      <span class="muted small">Neglected</span>
      {#if summary.neglected.length > 0}
        <strong>{summary.neglected[0].title}</strong>
        <span class="muted small">
          {summary.neglected[0].days_since === null
            ? 'never logged'
            : `${summary.neglected[0].days_since} days`}
        </span>
      {:else}
        <strong class="muted">—</strong>
        <span class="muted small">no active pieces</span>
      {/if}
    </div>
  </div>
  <BarChart
    items={summary.calendar.slice(-7).map((day) => ({
      label: day.date.slice(5),
      value: day.minutes,
    }))}
    unit=" min"
  />
</section>

<style>
  .review {
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
    padding: 0.75rem 0.9rem;
  }

  .review-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
    gap: 0.75rem;
  }

  .review-grid > div {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }

  .review-grid strong {
    font-size: 1.05rem;
  }

  .small {
    font-size: 0.8rem;
  }
</style>
