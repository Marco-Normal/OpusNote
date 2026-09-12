<script lang="ts">
  /**
   * The workout banner.
   *
   * A workout is declared, not inferred: the player starts it and finishes it.
   * It lives in the app shell rather than in a view because the point of
   * declaring one is that everything played until Finish counts as sight-reading
   * — including the wandering between exercises.
   */
  import { app } from '../lib/state.svelte';
  import { formatClock } from '../lib/types';

  let elapsed = $state(0);

  $effect(() => {
    const running = app.workout?.running ?? false;
    const startedMs = app.workout?.started_ms ?? 0;
    if (!running) {
      elapsed = 0;
      return;
    }
    const tick = () => {
      elapsed = Math.max(0, Math.floor((Date.now() - startedMs) / 1000));
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  });

  const done = $derived(app.workout?.exercises_done ?? 0);
  const planned = $derived(app.workout?.planned ?? 0);
  const progress = $derived(planned > 0 ? Math.min(100, (done / planned) * 100) : 0);
  const running = $derived(app.workout?.running ?? false);
</script>

<section class="card bar" data-workout={running ? 'running' : 'idle'}>
  <div class="row wrap">
    <span class="pill" class:accent={running}>
      {running ? 'Workout in progress' : 'No workout running'}
    </span>
    {#if running && app.workout}
      <span class="mono muted">{formatClock(elapsed)}</span>
      <span class="muted small">
        {done} of {planned || '—'} exercises
      </span>
      {#if app.workout.target_skill}
        <span class="pill">{app.workout.target_skill.replace(/_/g, ' ')}</span>
      {/if}
    {:else if app.workout}
      <span class="muted small">
        Last workout {app.workout.local_date} · {done}
        {done === 1 ? 'exercise' : 'exercises'} · {app.workout.minutes} min
      </span>
    {:else}
      <span class="muted small">
        Start one to mark this stretch as deliberate sight-reading. Everything you
        play is logged either way.
      </span>
    {/if}
  </div>

  {#if running}
    <div class="progress" role="progressbar" aria-valuenow={done} aria-valuemin={0} aria-valuemax={planned}>
      <span style="width: {progress}%"></span>
    </div>
  {/if}

  <div class="row">
    {#if running}
      <button class="primary" onclick={() => void app.finishWorkout()}>Finish workout</button>
    {:else}
      <button onclick={() => void app.startWorkout()}>Start workout</button>
    {/if}
    {#if app.workoutError}
      <span class="pill bad">{app.workoutError}</span>
    {/if}
  </div>
</section>

<style>
  .bar {
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    padding: 0.6rem 0.8rem;
  }

  .small {
    font-size: 0.82rem;
  }

  .progress {
    height: 4px;
    border-radius: 999px;
    background: var(--track);
    overflow: hidden;
  }

  .progress span {
    display: block;
    height: 100%;
    background: var(--accent);
    transition: width 240ms ease;
  }
</style>
