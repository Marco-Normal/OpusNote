<script lang="ts">
  import BarChart from './BarChart.svelte';
  import CalendarHeatmap from './CalendarHeatmap.svelte';
  import { practiceKindLabel } from '../lib/kinds';
  import { pieceCredits, pieceLabel } from '../lib/pieceLabel';
  import { formatMinutes, type AnalyticsSummary } from '../lib/types';

  interface Props {
    summary: AnalyticsSummary;
  }

  let { summary }: Props = $props();

  /** "localhost:8000" when a client has checked in, "not reporting" when none has. */
  function captureHeadline(data: AnalyticsSummary): string {
    if (!data.capture) return 'not reporting';
    return data.capture.enabled ? data.capture.origin : 'paused';
  }

  function lastNoteLabel(data: AnalyticsSummary): string {
    if (data.last_note_ms === null) return 'no notes recorded yet';
    const seconds = Math.max(0, Math.round((Date.now() - data.last_note_ms) / 1000));
    if (seconds < 90) return `last note ${seconds} s ago`;
    return `last note ${Math.round(seconds / 60)} min ago`;
  }
</script>

<section class="card stats">
  <div class="stat">
    <span class="muted small">Logged practice</span>
    <strong>{formatMinutes(summary.total_minutes)}</strong>
    <span class="muted small">{summary.total_notes} notes all time</span>
  </div>
  <div class="stat">
    <span class="muted small">Today</span>
    <strong>{formatMinutes(summary.today_minutes)}</strong>
    <span class="muted small">{summary.calendar.at(-1)?.notes ?? 0} notes</span>
  </div>
  <div class="stat" data-streak={summary.streak_days}>
    <span class="muted small">Streak</span>
    <strong>{summary.streak_days} {summary.streak_days === 1 ? 'day' : 'days'}</strong>
    <span class="muted small">
      {summary.streak_grace_used > 0
        ? 'counting 1 rest day'
        : 'consecutive days played'}
    </span>
  </div>
  <div class="stat">
    <span class="muted small">Workouts</span>
    <strong>{summary.workouts_this_week} this week</strong>
    <span class="muted small">{summary.workouts_completed} completed all time</span>
  </div>
  <div class="stat" data-capture-stat={summary.capture ? 'reporting' : 'silent'}>
    <span class="muted small">Capture</span>
    <strong>{captureHeadline(summary)}</strong>
    <span class="muted small">{lastNoteLabel(summary)}</span>
  </div>
</section>

<section class="card">
  <h3>Practice calendar</h3>
  <CalendarHeatmap days={summary.calendar} />
</section>

<div class="columns">
  <section class="card">
    <h3>Time per piece</h3>
    {#if summary.by_piece.length === 0}
      <p class="muted small">
        Nothing attributed yet. Tag a segment below and its time lands here.
      </p>
    {:else}
      <BarChart
        items={summary.by_piece.slice(0, 8).map((piece) => ({
          label: piece.title,
          sublabel: pieceCredits(piece) || undefined,
          value: piece.minutes,
          hint: `${piece.segments} segment${piece.segments === 1 ? '' : 's'} · last played ${piece.last_played ?? '—'}`,
        }))}
      />
    {/if}
  </section>

  <section class="card">
    <h3>Neglected</h3>
    {#if summary.neglected.length === 0}
      <p class="muted small">No active pieces in the library yet.</p>
    {:else}
      <ul class="neglected">
        {#each summary.neglected as piece (piece.piece_id)}
          <li>
            <span>{pieceLabel(piece)}</span>
            <span class="pill" class:warn={(piece.days_since ?? 999) > 14}>
              {piece.days_since === null ? 'never logged' : `${piece.days_since} d ago`}
            </span>
          </li>
        {/each}
      </ul>
    {/if}
  </section>
</div>

{#if summary.sources.length > 0}
  <section class="card">
    <h3>How the time was spent</h3>
    <div class="row wrap">
      {#each summary.sources as source (source.source)}
        <span class="pill" class:accent={source.source === 'sight_reading'}>
          {source.source === 'sight_reading' ? 'sight-reading' : 'piano'} ·
          {formatMinutes(source.minutes)} · {source.notes} notes
        </span>
      {/each}
    </div>
    {#if summary.kinds.length > 0}
      <div class="row wrap" data-kind-split>
        {#each summary.kinds as entry (entry.kind ?? 'untagged')}
          <span class="pill" class:accent={entry.kind === 'slow'}>
            {practiceKindLabel(entry.kind)} · {formatMinutes(entry.minutes)} ·
            {entry.segments}
            {entry.segments === 1 ? 'segment' : 'segments'}
          </span>
        {/each}
      </div>
    {/if}
  </section>
{/if}

<style>
  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
    gap: 0.75rem;
    padding: 0.85rem 0.9rem;
  }

  .stat {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }

  .stat strong {
    font-size: 1.25rem;
    letter-spacing: -0.01em;
  }

  .columns {
    display: grid;
    align-items: start;
    grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
    gap: 0.75rem;
  }

  section.card:not(.stats) {
    padding: 0.75rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .neglected {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    font-size: 0.86rem;
  }

  .neglected li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
  }

  .small {
    font-size: 0.8rem;
  }
</style>
