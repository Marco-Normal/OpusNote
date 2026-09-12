<script lang="ts">
  import { api } from '../lib/api';
  import { app } from '../lib/state.svelte';
  import type { Stats } from '../lib/types';
  import RadarChart from './RadarChart.svelte';
  import LineChart from './LineChart.svelte';

  let stats = $state<Stats | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let confirmingReset = $state(false);

  async function load(): Promise<void> {
    loading = true;
    error = null;
    try {
      stats = await api.stats();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading = false;
    }
  }

  // Refetch whenever a performance is recorded elsewhere in the app.
  $effect(() => {
    app.revision;
    void load();
  });

  async function reset(): Promise<void> {
    try {
      await api.resetProfile();
      confirmingReset = false;
      app.revision += 1;
      await app.refreshProfile();
      await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  const scoreSeries = $derived.by(() => {
    if (!stats) return [];
    const at = (item: { performed_at: string }) => new Date(`${item.performed_at.replace(' ', 'T')}Z`).getTime();
    return [
      {
        label: 'Overall',
        color: '#4338ca',
        points: stats.history.map((item) => ({ x: at(item), y: item.score })),
      },
      {
        label: 'Pitch',
        color: '#15803d',
        points: stats.history.map((item) => ({ x: at(item), y: item.pitch_accuracy })),
      },
      {
        label: 'Rhythm',
        color: '#b45309',
        points: stats.history.map((item) => ({ x: at(item), y: item.rhythm_accuracy })),
      },
    ];
  });

  const tempoSeries = $derived.by(() => {
    if (!stats) return [];
    return [
      {
        label: 'Best passing tempo',
        color: '#4338ca',
        points: stats.tempo_progress.map((item) => ({ x: new Date(item.date).getTime(), y: item.tempo_bpm })),
      },
    ];
  });

  const tempoMax = $derived(
    stats && stats.tempo_progress.length
      ? Math.max(60, ...stats.tempo_progress.map((item) => item.tempo_bpm)) * 1.1
      : 200,
  );
</script>

<section class="card panel">
  <div class="spread wrap">
    <h2>Progress</h2>
    <div class="row">
      <button onclick={() => void load()} disabled={loading}>{loading ? 'Loading…' : 'Refresh'}</button>
      {#if confirmingReset}
        <button class="danger" onclick={() => void reset()}>Confirm reset</button>
        <button class="ghost" onclick={() => (confirmingReset = false)}>Cancel</button>
      {:else}
        <button class="ghost" onclick={() => (confirmingReset = true)}>Reset profile</button>
      {/if}
    </div>
  </div>

  {#if error}
    <div class="error-banner">{error}</div>
  {/if}

  {#if stats}
    <div class="tiles">
      <div class="tile">
        <span class="k">Streak</span>
        <span class="v mono">{stats.summary.streak_days}<small> days</small></span>
      </div>
      <div class="tile">
        <span class="k">Average score</span>
        <span class="v mono">{stats.summary.average_score.toFixed(0)}<small> / 100</small></span>
      </div>
      <div class="tile">
        <span class="k">Best</span>
        <span class="v mono">{stats.summary.best_score.toFixed(0)}<small> / 100</small></span>
      </div>
      <div class="tile">
        <span class="k">Pass rate</span>
        <span class="v mono">{stats.summary.pass_rate.toFixed(0)}<small> %</small></span>
      </div>
      <div class="tile">
        <span class="k">Exercises played</span>
        <span class="v mono">{stats.summary.performances}</span>
      </div>
      <div class="tile">
        <span class="k">Calibration</span>
        <span class="v mono">
          {stats.summary.calibration_complete ? 'done' : `${stats.summary.calibration_step}/${stats.summary.calibration_total}`}
        </span>
      </div>
    </div>

    {#if !stats.summary.calibration_complete}
      <div class="row">
        <span class="pill warn">Calibration incomplete — ratings are still rough</span>
        <button onclick={() => (app.view = 'calibrate')}>Calibrate</button>
      </div>
    {/if}
  {/if}
</section>

{#if stats}
  <div class="grid">
    <section class="card panel">
      <h3>Skill radar</h3>
      <RadarChart axes={stats.radar.map((item) => ({ slug: item.slug, name: item.name, level: item.level }))} />
      <p class="muted small">
        Estimated level per skill, 1-10. The trainer aims each exercise just below your current
        rating so you succeed roughly 78% of the time.
      </p>
    </section>

    <section class="card panel">
      <h3>Accuracy over time</h3>
      <LineChart series={scoreSeries} yMin={0} yMax={100} yLabel="Accuracy over time" />
    </section>

    <section class="card panel">
      <h3>Tempo progress</h3>
      <LineChart
        series={tempoSeries}
        yMin={40}
        yMax={tempoMax}
        yLabel="Tempo of exercises passed at 80% pitch accuracy"
      />
      <p class="muted small">Fastest tempo per day at which you still read 80% of the notes.</p>
    </section>

    <section class="card panel">
      <h3>Most common mistakes</h3>
      {#if stats.common_mistakes.length === 0}
        <p class="muted small">No recurring mistakes yet — play a few exercises.</p>
      {:else}
        <table>
          <thead>
            <tr><th>Mistake</th><th>Count</th></tr>
          </thead>
          <tbody>
            {#each stats.common_mistakes as mistake (mistake.kind + mistake.label)}
              <tr>
                <td>{mistake.label}</td>
                <td class="mono">{mistake.count}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>
  </div>

  <section class="card panel">
    <h3>Recent exercises</h3>
    {#if stats.history.length === 0}
      <p class="muted small">Nothing played yet.</p>
    {:else}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>Focus</th>
              <th>Key</th>
              <th>Tempo</th>
              <th>Score</th>
              <th>Pitch</th>
              <th>Rhythm</th>
              <th>Continuity</th>
              <th>Elo</th>
            </tr>
          </thead>
          <tbody>
            {#each [...stats.history].reverse() as item (item.id)}
              <tr>
                <td class="muted">{item.performed_at.slice(5, 16)}</td>
                <td>{item.target_skill?.replace(/_/g, ' ') ?? '—'}</td>
                <td>{item.key_name ?? '—'}</td>
                <td class="mono">{Math.round(item.tempo_bpm)}</td>
                <td class="mono strong" class:good={item.score >= 80}>{item.score.toFixed(0)}</td>
                <td class="mono">{item.pitch_accuracy.toFixed(0)}</td>
                <td class="mono">{item.rhythm_accuracy.toFixed(0)}</td>
                <td class="mono">{item.continuity_accuracy.toFixed(0)}</td>
                <td class="mono muted">{Math.round(item.difficulty_elo)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
{/if}

<style>
  .panel {
    padding: 0.9rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(19rem, 1fr));
    gap: 0.9rem;
  }

  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr));
    gap: 0.5rem;
  }

  .tile {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    padding: 0.5rem 0.65rem;
    border-radius: var(--radius);
    border: 1px solid var(--line);
    background: var(--surface-2);
  }

  .tile .k {
    font-size: 0.75rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .tile .v {
    font-size: 1.3rem;
    font-weight: 600;
  }

  .tile .v small {
    font-size: 0.72rem;
    color: var(--muted);
    font-weight: 400;
  }

  .table-wrap {
    overflow-x: auto;
  }

  .small {
    font-size: 0.8rem;
    margin: 0;
    line-height: 1.5;
  }

  .strong {
    font-weight: 700;
  }

  .strong.good {
    color: var(--good);
  }

  button.danger {
    background: var(--bad);
    border-color: var(--bad);
    color: #fff;
  }
</style>
