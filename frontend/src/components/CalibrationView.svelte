<script lang="ts">
  import { onDestroy, onMount, tick } from 'svelte';
  import { api } from '../lib/api';
  import { LiveMatcher } from '../lib/liveMatch';
  import { Metronome, type BeatInfo } from '../lib/metronome';
  import { ScoreRenderer } from '../lib/score';
  import { app } from '../lib/state.svelte';
  import { theme } from '../lib/theme.svelte';
  import type { Exercise, NoteStatus, PlayedNote, ScoreResult } from '../lib/types';
  import ResultsPanel from './ResultsPanel.svelte';
  import LatencyCalibrator from './LatencyCalibrator.svelte';

  type Phase = 'intro' | 'loading' | 'ready' | 'countin' | 'playing' | 'submitting' | 'result' | 'done';

  // svelte-ignore non_reactive_update — used imperatively as an OSMD mount point.
  let scoreContainer: HTMLDivElement;
  let renderer: ScoreRenderer | null = null;
  const metronome = new Metronome();

  let phase = $state<Phase>('intro');
  let exercise = $state<Exercise | null>(null);
  let result = $state<ScoreResult | null>(null);
  let error = $state<string | null>(null);
  let beatInfo = $state<BeatInfo | null>(null);
  let liveStatuses = $state<Map<number, NoteStatus>>(new Map());
  let step = $state(0);
  let total = $state(8);

  let played: PlayedNote[] = [];
  let matcher: LiveMatcher | null = null;
  let endTimer: ReturnType<typeof setTimeout> | null = null;
  let offBeat: (() => void) | null = null;
  let finishing = false;
  let durations = new Map<number, number>();

  onMount(() => {
    if (app.profile) {
      step = app.profile.calibration_step;
      total = app.profile.calibration_total;
    }
    const offNote = app.midi.onNote((event) => {
      if (phase !== 'playing' && phase !== 'countin') return;
      played.push({ pitch: event.pitch, onset: event.onset, duration: 0, velocity: event.velocity, channel: event.channel });
      durations.set(event.pitch, played.length - 1);
      if (!matcher) return;
      matcher.register(event.pitch, event.onset);
      liveStatuses = matcher.snapshot;
      renderer?.colorByExpectedIndex(liveStatuses);
      if (matcher.isComplete && !finishing) setTimeout(() => void finish(), 450);
    });
    const offRelease = app.midi.onNoteRelease((pitch, durationS) => {
      const index = durations.get(pitch);
      if (index === undefined) return;
      const note = played[index];
      if (note) note.duration = durationS;
    });
    return () => {
      offNote();
      offRelease();
    };
  });

  onDestroy(() => {
    if (endTimer) clearTimeout(endTimer);
    offBeat?.();
    metronome.stop();
    app.midi.stopRecording();
    renderer?.dispose();
  });

  // OSMD reads its colour options at load time, so a paper change means
  // re-rendering. Skipped while a run is in progress: redrawing the notation
  // mid-performance would be worse than a stale theme for a few seconds.
  $effect(() => {
    const dark = theme.scoreIsDark;
    if (!exercise || !renderer) return;
    if (phase === 'playing' || phase === 'countin' || phase === 'submitting') return;
    void renderer.setDark(dark).then(() => renderer?.colorByExpectedIndex(liveStatuses));
  });

  async function load(): Promise<void> {
    error = null;
    result = null;
    phase = 'loading';
    try {
      const next = await api.calibrationExercise();
      if (next.complete) {
        phase = 'done';
        await app.refreshProfile();
        if (app.profile) {
          step = app.profile.calibration_step;
          total = app.profile.calibration_total;
        }
        return;
      }
      exercise = next;
      step = next.step ?? step;
      total = next.total ?? total;
      await tick();
      renderer = new ScoreRenderer(scoreContainer);
      await renderer.render(exercise.musicxml, exercise.expected_notes, {
        dark: theme.scoreIsDark,
      });
      phase = 'ready';
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
      phase = 'intro';
    }
  }

  async function start(): Promise<void> {
    if (!exercise) return;
    try {
      await metronome.unlock();
    } catch (cause) {
      error = `Could not start audio: ${cause instanceof Error ? cause.message : String(cause)}`;
      return;
    }

    played = [];
    durations = new Map();
    matcher = new LiveMatcher(exercise.expected_notes);
    liveStatuses = new Map();
    renderer?.resetColors();

    const barsBeats = exercise.measures.map((measure) => measure.beats);
    // A tempo marking is quarter notes per minute; a *beat* is whatever the
    // meter says it is, which is a dotted quarter in 6/8 and a half note in cut
    // time. Passing seconds-per-quarter as seconds-per-beat made the metronome
    // and the count-in wrong in every compound meter.
    const secondsPerQuarter = 60 / exercise.tempo_bpm;
    const barBeatUnits = exercise.measures.map((measure) => measure.beat_unit_q);
    const countInBeats = barsBeats[0] ?? 4;

    phase = 'countin';
    offBeat?.();
    offBeat = metronome.onBeat((info) => {
      beatInfo = info;
      if (!info.inCountIn && phase === 'countin') phase = 'playing';
    });
    metronome.start({ barsBeats, barBeatUnits, secondsPerQuarter, countInBeats });
    app.midi.startRecording(metronome.downbeatMs);
    endTimer = setTimeout(() => void finish(), metronome.durationSeconds * 1000 + 1500);
  }

  async function finish(): Promise<void> {
    if (finishing || !exercise || (phase !== 'playing' && phase !== 'countin')) return;
    finishing = true;
    if (endTimer) clearTimeout(endTimer);
    endTimer = null;
    metronome.stop();
    app.midi.stopRecording();
    beatInfo = null;
    phase = 'submitting';

    try {
      const scored = await api.score({
        exercise_id: exercise.exercise_id,
        notes: played.map((note) => ({ ...note })),
        mode: 'performance',
        latency_ms: app.latencyMs,
        calibration: true,
      });
      result = scored;
      liveStatuses = new Map(scored.feedback.map((item) => [item.index, item.status]));
      renderer?.colorByExpectedIndex(liveStatuses);
      phase = 'result';
      app.revision += 1;
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
      phase = 'ready';
    } finally {
      finishing = false;
    }
  }

  function reset(): void {
    if (endTimer) clearTimeout(endTimer);
    endTimer = null;
    finishing = false;
    metronome.stop();
    app.midi.stopRecording();
    exercise = null;
    result = null;
    phase = 'intro';
    if (app.profile) {
      step = app.profile.calibration_step;
      total = app.profile.calibration_total;
    }
  }

  const progressPercent = $derived(total > 0 ? Math.min(100, (step / total) * 100) : 0);
</script>

<section class="card panel">
  <div class="spread wrap">
    <div>
      <h2>Calibration</h2>
      <p class="muted small">
        A short ladder of exercises, one per skill dimension, so the trainer can find your starting
        level instead of guessing.
      </p>
    </div>
    <span class="pill mono">{Math.min(step, total)} / {total}</span>
  </div>

  <div class="track"><div class="fill" style="width: {progressPercent}%"></div></div>

  <LatencyCalibrator />
</section>

{#if error}
  <div class="error-banner">{error}</div>
{/if}

{#if phase === 'intro'}
  <section class="card panel">
    {#if step >= total}
      <h2>Calibration already complete</h2>
      <p class="muted">
        Your ratings are established. Keep practising and they will keep adapting. Resetting your
        profile from the Progress tab lets you calibrate again.
      </p>
      <div class="row">
        <button class="primary" onclick={() => (app.view = 'practice')}>Go to practice</button>
        <button onclick={reset}>Run calibration again</button>
      </div>
    {:else}
      <h2>Ready to calibrate</h2>
      <p class="muted">
        {total - step} short exercises to go. Play each one through; accuracy matters less than
        showing what you can read.
      </p>
      <button class="primary" onclick={() => void load()}>Start calibration</button>
    {/if}
  </section>
{:else if phase === 'done'}
  <section class="card panel">
    <h2>Calibration complete</h2>
    <p class="muted">Your skill ratings are set. From here every exercise adapts to your results.</p>
    <div class="row">
      <button class="primary" onclick={() => (app.view = 'practice')}>Start practising</button>
      <button onclick={() => void app.refreshProfile()}>Refresh profile</button>
    </div>
  </section>
{:else if exercise}
  <section class="card panel" data-phase={phase}>
    <div class="spread wrap">
      <div class="row wrap">
        <span class="pill accent">
          {exercise.target_skill?.replace(/_/g, ' ') ?? 'calibration'} · level
          {exercise.levels[exercise.target_skill ?? ''] ?? '—'}
        </span>
        <span class="pill mono">{Math.round(exercise.tempo_bpm)} BPM</span>
        <span class="pill">{exercise.meter}</span>
        <span class="pill">key {exercise.key_name}</span>
      </div>
      <div class="row">
        {#if phase === 'playing' || phase === 'countin'}
          <button onclick={() => void finish()}>Stop &amp; score</button>
        {:else}
          <button class="primary" onclick={() => void start()} disabled={phase === 'loading' || phase === 'submitting'}>
            {phase === 'result' ? 'Play again' : 'Start'}
          </button>
        {/if}
        {#if phase !== 'result'}
          <button class="ghost" onclick={() => void load()} disabled={phase === 'loading'}>Skip</button>
        {/if}
      </div>
    </div>

    {#if phase === 'countin' || phase === 'playing'}
      <div class="transport">
        <span class="pill" class:warn={phase === 'countin'} class:good={phase === 'playing'}>
          {phase === 'countin' ? `Count-in · ${beatInfo?.beat ?? 1}` : `Bar ${beatInfo?.bar ?? 1}`}
        </span>
        <span class="muted small mono">recording</span>
      </div>
    {/if}

    <div class="score-surface" bind:this={scoreContainer}></div>

    {#if phase === 'result' && result}
      <ResultsPanel
        {result}
        {exercise}
        onNext={() => void load()}
        onRetry={() => void start()}
      />
    {/if}
  </section>
{/if}

<style>
  .panel {
    padding: 0.9rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
  }

  .panel p {
    margin: 0.25rem 0 0;
    line-height: 1.55;
    max-width: 65ch;
  }

  .track {
    height: 0.45rem;
    background: var(--track);
    border-radius: 999px;
    overflow: hidden;
  }

  .fill {
    height: 100%;
    background: var(--accent);
    border-radius: 999px;
    transition: width 0.25s ease;
  }

  .transport {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    background: var(--surface-2);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 0.45rem 0.65rem;
  }

  .small {
    font-size: 0.84rem;
  }
</style>
