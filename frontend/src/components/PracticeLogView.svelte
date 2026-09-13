<script lang="ts">
  /**
   * The practice log: what you actually played, versus what you meant to.
   *
   * Everything here is measured from MIDI rather than claimed, which is the whole
   * reason the logger exists as a passive layer. The one thing it cannot see is
   * the intention, and that is what a workout supplies.
   */
  import { untrack } from 'svelte';
  import { api } from '../lib/api';
  import { app } from '../lib/state.svelte';
  import {
    formatClock,
    formatMinutes,
    type AnalyticsSummary,
    type RatingHistory,
    type PieceSummary,
    type SittingDetail,
    type SittingSummary,
  } from '../lib/types';
  import BackupPanel from './BackupPanel.svelte';
  import BarChart from './BarChart.svelte';
  import CalendarHeatmap from './CalendarHeatmap.svelte';
  import CaptureBar from './CaptureBar.svelte';
  import SegmentTimeline from './SegmentTimeline.svelte';
  import SittingList from './SittingList.svelte';

  let summary = $state<AnalyticsSummary | null>(null);
  let week = $state<RatingHistory | null>(null);
  let sittings = $state<SittingSummary[]>([]);
  let detail = $state<SittingDetail | null>(null);
  let pieces = $state<PieceSummary[]>([]);
  let days = $state(30);
  let selectedId = $state<number | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let importing = $state(false);
  let importNote = $state<string | null>(null);

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

  async function load(): Promise<void> {
    error = null;
    try {
      const [nextSummary, nextSittings] = await Promise.all([
        api.practice.summary(days),
        api.practice.sittings(50),
      ]);
      // The week summary mixes practice time with what the trainer thinks improved, so
      // it needs both domains; failures here must not stop the log rendering.
      week = await api.progressRatings(7).catch(() => null);
      summary = nextSummary;
      sittings = nextSittings;
      // Always re-read the open sitting. `load` runs after every edit, and the
      // timeline is drawn from this detail: skipping the refresh left a tag or a
      // split visible in the API but not on screen, which is worse than a stale
      // number because the interface looked like it had ignored the edit.
      if (selectedId !== null && nextSittings.some((row) => row.id === selectedId)) {
        await select(selectedId);
      } else if (nextSittings.length > 0 && selectedId === null) {
        await select(nextSittings[0].id);
      } else if (selectedId !== null) {
        selectedId = null;
        detail = null;
      }
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  async function select(id: number): Promise<void> {
    selectedId = id;
    try {
      detail = await api.practice.sitting(id);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  /** Every edit re-reads both the sitting and the totals: they are one dataset. */
  async function edit(action: () => Promise<unknown>): Promise<void> {
    busy = true;
    error = null;
    try {
      await action();
      await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = false;
    }
  }

  async function importHistory(): Promise<void> {
    importing = true;
    importNote = null;
    try {
      const report = await api.practice.importLegacy();
      importNote = report.available
        ? `${report.sittings} sittings, ${report.note_events} notes and ${report.segments} segments imported.`
        : (report.note ?? 'Nothing to import.');
      await load();
    } catch (cause) {
      importNote = cause instanceof Error ? cause.message : String(cause);
    } finally {
      importing = false;
    }
  }

  $effect(() => {
    // Re-read when the window changes or a performance is scored, so the log
    // does not go stale behind a workout the player just finished. `untrack`
    // keeps the fetch's own bookkeeping (which sitting is selected) out of the
    // dependency set, so selecting a sitting cannot re-trigger the fetch.
    days;
    app.revision;
    untrack(() => {
      void load();
    });
  });

  $effect(() => {
    void api.repertoire
      .pieces()
      .then((rows) => (pieces = rows))
      .catch(() => {
        // The assign dropdown is a convenience; the log works without it.
      });
  });
</script>

<section class="card head">
  <div class="spread wrap">
    <div>
      <h2>Practice log</h2>
      <p class="muted small">
        Recorded from your playing, not typed in afterwards. A sitting opens on the
        first note and closes after five minutes of silence.
      </p>
    </div>
    <div class="row wrap">
      <label class="row window">
        <span class="muted small">Window</span>
        <select bind:value={days}>
          <option value={7}>7 days</option>
          <option value={30}>30 days</option>
          <option value={90}>90 days</option>
          <option value={365}>1 year</option>
        </select>
      </label>
      <button class="ghost" disabled={busy} onclick={() => void load()}>Refresh</button>
      <button class="ghost" disabled={importing} onclick={() => void importHistory()}>
        {importing ? 'Importing…' : 'Import old history'}
      </button>
    </div>
  </div>
  {#if importNote}
    <p class="muted small">{importNote}</p>
  {/if}
</section>

<CaptureBar />

{#if error}
  <div class="error-banner">{error}</div>
{/if}

{#if summary}
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
    <div class="stat">
      <span class="muted small">Streak</span>
      <strong>{summary.streak_days} {summary.streak_days === 1 ? 'day' : 'days'}</strong>
      <span class="muted small">consecutive days played</span>
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
            sublabel: piece.composer_name ?? undefined,
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
              <span>
                {piece.title}
                {#if piece.composer_name}
                  <span class="muted small">· {piece.composer_name}</span>
                {/if}
              </span>
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
    </section>
  {/if}
{/if}

<div class="columns wide-left">
  <section class="card">
    <h3>Recent sittings</h3>
    <SittingList {sittings} {selectedId} onselect={(id) => void select(id)} />
  </section>

  {#if detail}
    <SegmentTimeline
      {detail}
      {pieces}
      {busy}
      onassign={(segmentId, pieceId) =>
        void edit(() => api.practice.assignSegment(segmentId, pieceId))}
      onsplit={(segmentId, atMs) => void edit(() => api.practice.splitSegment(segmentId, atMs))}
      onmerge={(segmentId, otherId) =>
        void edit(() => api.practice.mergeSegments(segmentId, otherId))}
      onresegment={(confirm) => void edit(() => api.practice.resegment(detail!.id, confirm))}
    />
  {:else}
    <section class="card empty">
      <p class="muted small">Select a sitting to see what it contained.</p>
    </section>
  {/if}
</div>

{#if summary}
  <section class="card review" data-week-review>
    <h3>This week</h3>
    <div class="review-grid">
      <div>
        <span class="muted small">Practised</span>
        <strong>{formatMinutes(summary.calendar.slice(-7).reduce((sum, day) => sum + day.minutes, 0))}</strong>
        <span class="muted small">
          over {summary.calendar.slice(-7).filter((day) => day.minutes > 0).length} days
        </span>
      </div>
      <div>
        <span class="muted small">Sight-reading</span>
        <strong>{summary.workouts_this_week} workouts</strong>
        <span class="muted small">{summary.streak_days}-day streak</span>
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
{/if}

<BackupPanel onrestored={() => void load()} />

<section class="card totals">
  <h3>Totals</h3>
  <ul class="muted small">
    <li>
      Longest sitting:
      {sittings.length
        ? formatClock(Math.max(...sittings.map((row) => row.duration_s)))
        : '—'}
    </li>
    <li>Sittings recorded: {sittings.length}</li>
  </ul>
</section>

<style>
  .head,
  .totals {
    padding: 0.75rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
  }

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
    grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
    gap: 0.75rem;
  }

  .columns.wide-left {
    grid-template-columns: minmax(18rem, 1fr) minmax(22rem, 1.4fr);
  }

  @media (max-width: 900px) {
    .columns.wide-left {
      grid-template-columns: 1fr;
    }
  }

  section.card:not(.stats):not(.head):not(.totals):not(.empty) {
    padding: 0.75rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .empty {
    padding: 0.9rem;
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

  .window {
    gap: 0.35rem;
  }
</style>
