<script lang="ts">
  import { onDestroy, onMount, tick } from 'svelte';
  import { api } from '../lib/api';
  import { LiveMatcher } from '../lib/liveMatch';
  import { Metronome, type BeatInfo } from '../lib/metronome';
  import { ScoreRenderer } from '../lib/score';
  import { app } from '../lib/state.svelte';
  import type { Exercise, NoteStatus, PlayedNote, PracticeMode, ScoreResult } from '../lib/types';
  import ResultsPanel from './ResultsPanel.svelte';
  import SkillChips from './SkillChips.svelte';
  import NoteStrip from './NoteStrip.svelte';

  type Phase = 'empty' | 'loading' | 'ready' | 'countin' | 'playing' | 'submitting' | 'result';

  // svelte-ignore non_reactive_update — used imperatively as an OSMD mount point.
  let scoreContainer: HTMLDivElement;
  let renderer: ScoreRenderer | null = null;
  const metronome = new Metronome();

  let phase = $state<Phase>('empty');
  let exercise = $state<Exercise | null>(null);
  let result = $state<ScoreResult | null>(null);
  let error = $state<string | null>(null);

  let mode = $state<PracticeMode>('practice');
  let forcedSkill = $state<string>('');
  let beatInfo = $state<BeatInfo | null>(null);
  let liveStatuses = $state<Map<number, NoteStatus>>(new Map());
  let progress = $state({ done: 0, total: 0, correct: 0, wrong: 0, extra: 0 });

  let played: PlayedNote[] = [];
  let matcher: LiveMatcher | null = null;
  let endTimer: ReturnType<typeof setTimeout> | null = null;
  let offBeat: (() => void) | null = null;
  let finishing = false;
  let durations = new Map<number, number>();

  const busy = $derived(phase === 'loading' || phase === 'submitting');

  onMount(() => {
    const offNote = app.midi.onNote((event) => {
      if (phase !== 'playing' && phase !== 'countin') return;
      played.push({
        pitch: event.pitch,
        onset: event.onset,
        duration: 0,
        velocity: event.velocity,
        channel: event.channel,
      });
      durations.set(event.pitch, played.length - 1);

      if (!matcher) return;
      const match = matcher.register(event.pitch, event.onset);
      // Live colouring is a practice-mode affordance; performance mode stays
      // silent until the final report, as specified.
      if (mode === 'practice') {
        liveStatuses = matcher.snapshot;
        progress = matcher.progress;
        renderer?.colorByExpectedIndex(liveStatuses);
      }
      if (match.index !== null && matcher.isComplete && !finishing) {
        setTimeout(() => void finish(), 450);
      }
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

  async function loadExercise(): Promise<void> {
    reset(false);
    phase = 'loading';
    try {
      exercise = await api.nextExercise({ skill: forcedSkill || undefined });
      await tick();
      renderer = new ScoreRenderer(scoreContainer);
      await renderer.render(exercise.musicxml, exercise.expected_notes);
      phase = 'ready';
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
      phase = 'empty';
    }
  }

  function reset(clearScore = true) {
    if (endTimer) clearTimeout(endTimer);
    endTimer = null;
    offBeat?.();
    offBeat = null;
    finishing = false;
    metronome.stop();
    app.midi.stopRecording();
    played = [];
    durations = new Map();
    matcher = null;
    result = null;
    beatInfo = null;
    liveStatuses = new Map();
    progress = { done: 0, total: 0, correct: 0, wrong: 0, extra: 0 };
    error = null;
    if (clearScore) renderer?.resetColors();
  }

  async function start(): Promise<void> {
    if (!exercise) return;
    reset();
    try {
      await metronome.unlock();
    } catch (cause) {
      error = `Could not start audio: ${cause instanceof Error ? cause.message : String(cause)}`;
      return;
    }

    matcher = new LiveMatcher(exercise.expected_notes);
    progress = matcher.progress;

    const barsBeats = exercise.measures.map((measure) => measure.beats);
    const secondsPerBeat = 60 / exercise.tempo_bpm;
    const countInBeats = barsBeats[0] ?? 4;

    phase = 'countin';
    renderer?.resetColors();

    offBeat?.();
    offBeat = metronome.onBeat((info) => {
      beatInfo = info;
      if (!info.inCountIn && phase === 'countin') phase = 'playing';
    });

    metronome.start({ barsBeats, secondsPerBeat, countInBeats });
    // Everything is measured from beat 1, not from the first count-in click.
    app.midi.startRecording(metronome.downbeatMs);

    const totalMs = metronome.totalBeats * secondsPerBeat * 1000;
    endTimer = setTimeout(() => void finish(), totalMs + 1500);
  }

  async function finish(): Promise<void> {
    if (finishing || !exercise) return;
    if (phase !== 'playing' && phase !== 'countin') return;
    finishing = true;

    if (endTimer) clearTimeout(endTimer);
    endTimer = null;
    metronome.stop();
    app.midi.stopRecording();
    beatInfo = null;

    phase = 'submitting';
    const notes = played.map((note) => ({ ...note }));

    try {
      const scored = await api.score({
        exercise_id: exercise.exercise_id,
        notes,
        mode,
        latency_ms: app.latencyMs,
      });
      result = scored;
      liveStatuses = new Map(scored.feedback.map((item) => [item.index, item.status]));
      renderer?.colorByExpectedIndex(liveStatuses);
      phase = 'result';
      app.revision += 1;
      await app.refreshProfile();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
      phase = 'ready';
    } finally {
      finishing = false;
    }
  }

  function stopEarly() {
    void finish();
  }
</script>

<section class="card panel" data-phase={phase}>
  <div class="spread wrap">
    <div class="row wrap">
      <div class="modes" role="group" aria-label="Feedback mode">
        <button class:active={mode === 'practice'} onclick={() => (mode = 'practice')}>Practice</button>
        <button class:active={mode === 'performance'} onclick={() => (mode = 'performance')}>
          Performance
        </button>
      </div>
      <span class="muted small">
        {mode === 'practice'
          ? 'Notes are marked as you play.'
          : 'No feedback until the end.'}
      </span>
    </div>

    <div class="row wrap">
      <select bind:value={forcedSkill} disabled={phase === 'playing' || phase === 'countin'}>
        <option value="">Auto (weakest skill)</option>
        {#each app.profile ? Object.keys(app.profile.ratings) : [] as slug (slug)}
          <option value={slug}>{slug.replace(/_/g, ' ')}</option>
        {/each}
      </select>
      <button onclick={() => void loadExercise()} disabled={busy || phase === 'playing' || phase === 'countin'}>
        {exercise ? 'New exercise' : 'Get exercise'}
      </button>
    </div>
  </div>
</section>

{#if error}
  <div class="error-banner">{error}</div>
{/if}

{#if phase === 'empty' && !exercise}
  <section class="card empty">
    <h2>Ready when you are</h2>
    <p class="muted">
      Each exercise is generated for your current level across nine skills — keys, meter, rhythm,
      intervals, hand position, texture, accidentals, tempo, and articulation — and the next one
      adapts to how this one went.
    </p>
    <button class="primary" onclick={() => void loadExercise()} disabled={busy}>
      {busy ? 'Preparing…' : 'Get my first exercise'}
    </button>
  </section>
{:else if exercise}
  <section class="card panel">
    <div class="spread wrap">
      <div class="row wrap">
        <span class="pill accent">
          {exercise.target_skill?.replace(/_/g, ' ') ?? 'exercise'} · level
          {exercise.levels[exercise.target_skill ?? ''] ?? '—'}
        </span>
        <span class="pill mono">{Math.round(exercise.tempo_bpm)} BPM</span>
        <span class="pill">{exercise.meter}</span>
        <span class="pill">key {exercise.key_name}</span>
        <span class="pill mono">Elo {Math.round(exercise.difficulty_elo)}</span>
      </div>

      <div class="row">
        {#if phase === 'playing' || phase === 'countin'}
          <button onclick={stopEarly}>Stop &amp; score</button>
        {:else}
          <button class="primary" onclick={() => void start()} disabled={phase === 'loading' || phase === 'submitting'}>
            {phase === 'result' ? 'Play again' : 'Start'}
          </button>
        {/if}
        <button class="ghost" onclick={() => void loadExercise()} disabled={busy}>Next</button>
      </div>
    </div>

    {#if exercise.rationale}
      <p class="muted small rationale">{exercise.rationale}</p>
    {/if}

    {#if phase === 'countin' || phase === 'playing'}
      <div class="transport">
        <div class="beats" aria-label="Metronome">
          {#each Array(exercise.measures[beatInfo?.bar ? beatInfo.bar - 1 : 0]?.beats ?? 4) as _, index}
            <span
              class="beat"
              class:on={beatInfo?.beat === index + 1}
              class:accent={beatInfo?.beat === index + 1 && beatInfo?.accent}
            ></span>
          {/each}
        </div>
        <span class="pill" class:warn={phase === 'countin'} class:good={phase === 'playing'}>
          {phase === 'countin' ? `Count-in · ${beatInfo?.beat ?? 1}` : `Bar ${beatInfo?.bar ?? 1}`}
        </span>
        <span class="pill mono">
          {mode === 'practice' ? `${progress.correct}/${progress.total} notes` : 'listening…'}
        </span>
      </div>
    {/if}

    <div class="score-surface" bind:this={scoreContainer}></div>

    {#if phase === 'result' && result}
      <ResultsPanel {result} {exercise} onNext={() => void loadExercise()} onRetry={() => void start()} />
    {:else if phase !== 'result'}
      <NoteStrip notes={exercise.expected_notes} statuses={liveStatuses} />
    {/if}

    <SkillChips levels={exercise.levels} target={exercise.target_skill} />
  </section>
{/if}

<style>
  .panel {
    padding: 0.85rem 0.95rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .empty {
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    align-items: flex-start;
  }

  .empty p {
    margin: 0;
    max-width: 60ch;
    line-height: 1.55;
  }

  .modes {
    display: flex;
    background: var(--surface-2);
    border: 1px solid var(--line);
    border-radius: 9px;
    padding: 0.15rem;
  }

  .modes button {
    border: none;
    background: transparent;
    padding: 0.3rem 0.7rem;
    border-radius: 7px;
    font-size: 0.85rem;
    color: var(--muted);
  }

  .modes button.active {
    background: var(--surface);
    color: var(--ink);
    font-weight: 600;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
  }

  .transport {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
    background: var(--surface-2);
    border: 1px solid var(--line);
    border-radius: var(--radius);
    padding: 0.5rem 0.7rem;
  }

  .beats {
    display: flex;
    gap: 0.3rem;
  }

  .beat {
    width: 0.7rem;
    height: 0.7rem;
    border-radius: 50%;
    background: #d8d8d2;
    transition: transform 0.08s ease, background 0.08s ease;
  }

  .beat.on {
    background: var(--accent);
    transform: scale(1.35);
  }

  .beat.on.accent {
    background: var(--warn);
  }

  .small {
    font-size: 0.82rem;
  }

  .rationale {
    margin: 0;
  }
</style>
