<script lang="ts">
  import { onDestroy, onMount, tick } from 'svelte';
  import { api } from '../lib/api';
  import { countInBeats as countInBeatsFor } from '../lib/countIn';
  import { LiveMatcher } from '../lib/liveMatch';
  import { Metronome, type BeatInfo } from '../lib/metronome';
  import { ScoredAttempt, isBeforeDownbeat } from '../lib/scoredAttempt';
  import { MIN_ZOOM, ScoreRenderer } from '../lib/score';
  import { app, BAR_CHOICES } from '../lib/state.svelte';
  import { theme } from '../lib/theme.svelte';
  import { HAND_LABELS, type Exercise, type NoteStatus, type PlayedNote, type PracticeMode, type ScoreResult } from '../lib/types';
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
  /** Set when the exercise still overflows at MIN_ZOOM. */
  let tooLong = $state(false);
  let zoom = $state(1);
  let beatInfo = $state<BeatInfo | null>(null);
  /** The count-in this run actually uses, so the screen states it rather than implying it. */
  let countInBeatsUsed = $state(0);
  let liveStatuses = $state<Map<number, NoteStatus>>(new Map());
  let progress = $state({ done: 0, total: 0, correct: 0, wrong: 0, extra: 0 });

  /**
   * The attempt being captured.
   *
   * It owns the pairing of each note-off with the note-on it finishes, which is why it is a module
   * of its own rather than a `Map` in this file: keying by pitch alone held one slot per key, so a
   * re-struck note was scored with no length at all. `scoredAttempt.ts` records what happened too.
   *
   * Not reactive. It is written from a MIDI callback and read once, at scoring time.
   */
  let attemptBuffer = new ScoredAttempt();
  /** What was played, frozen at scoring time: the results panel replays this. */
  let attempt = $state<PlayedNote[]>([]);
  let matcher: LiveMatcher | null = null;
  let endTimer: ReturnType<typeof setTimeout> | null = null;
  /**
   * The 450 ms pause that lets the last note's feedback be seen before the result replaces it.
   *
   * Held and cleared like `endTimer`, because it is the same kind of hazard: navigating to
   * another tab unmounts this view, and an unheld timer would then POST the attempt from a dead
   * component, colour a disposed renderer, and assign to state nothing is rendering.
   */
  let completeTimer: ReturnType<typeof setTimeout> | null = null;
  let offBeat: (() => void) | null = null;
  let finishing = false;

  const busy = $derived(phase === 'loading' || phase === 'submitting');
  const running = $derived(phase === 'countin' || phase === 'playing');

  /** Nonsense guard for the budget, not a target: it is also where squeezing stops being honest. */
  const MIN_BUDGET_PX = 80;
  /** Sub-pixel slack, so "fits" is never decided by half a pixel. */
  const FIT_SLACK_PX = 4;
  /**
   * How far down the score starts before a run, used only until the playing layout exists.
   *
   * Measured once at 2026-09 from the running layout; they are estimates now and the run
   * replaces them with a measurement (see `heightBudget`).
   */
  const SETUP_CHROME_PX = 290;
  const FOCUS_CHROME_PX = 150;

  /**
   * Height the score may occupy.
   *
   * Before a run this is an estimate, because the layout that has to fit is the playing
   * one and it does not exist yet — the setup chrome is taller, so measuring now would
   * fit the score to the wrong box and refuse lengths that do fit.
   *
   * During a run it is **measured from the score's own position**, because no constant
   * can know what is actually above it: a host banner, a workout banner, the transport
   * row, focus mode and the window all move it. The estimate was wrong by 45 px on a
   * 1280x600 window in focus mode — the app claimed a 16-bar score fitted while its
   * bottom sat below the fold, which is the one failure this whole mechanism exists to
   * prevent (`docs/FEATURES.md` § 4). See `refitToRunLayout` for when it is measured.
   *
   * The floor only guards against nonsense values: a high one would make the "too long"
   * refusal unreachable, squeezing the score rather than admitting it cannot fit.
   */
  function heightBudget(): number {
    if (typeof window === 'undefined') return 0;
    if (running && scoreContainer) {
      const top = scoreContainer.getBoundingClientRect().top;
      // A score already scrolled out of view measures as zero or negative, which would
      // become a nonsense budget; the estimate is a better answer than arithmetic on it.
      if (top > 0) {
        // The slack is sub-pixel rounding, so "fits" is never decided by half a pixel.
        return Math.max(MIN_BUDGET_PX, Math.round(window.innerHeight - top - FIT_SLACK_PX));
      }
    }
    const chromeAbove = app.focusMode ? FOCUS_CHROME_PX : SETUP_CHROME_PX;
    return Math.max(MIN_BUDGET_PX, window.innerHeight - chromeAbove);
  }

  /**
   * Re-fit the engraving to the room the *performance* layout actually leaves.
   *
   * Called at the start of every run, and deliberately not awaited before the metronome:
   * the fit is a visual adjustment and must not delay the count-in. Re-engraving during a
   * run normally discards the live note colours, which is why this belongs at the start —
   * `start` has just reset them, so there are none to lose, and the count-in covers the
   * redraw.
   *
   * The second pass is not belt-and-braces: the fit can itself change the chrome above the
   * score, so the room it measured is not always the room it left. The "Scaled to N%" note
   * did exactly that — it appears because the score was scaled, pushed the score 56 px
   * down, and the result overflowed the window it had just been fitted to. One bounded
   * re-check settles any such case; more than one would be the scrollbar oscillation
   * again, so it is bounded at two.
   */
  async function refitToRunLayout(): Promise<void> {
    // The run's layout has to be in the DOM before it can be measured.
    await tick();
    const measured = heightBudget();
    await applyBudget(true);
    await tick();
    if (Math.abs(heightBudget() - measured) > 8) await applyBudget(true);
  }

  async function applyBudget(force = false): Promise<void> {
    if (!renderer) return;
    await renderer.setMaxHeight(heightBudget(), force);
  }

  onMount(() => {
    const onResize = () => void applyBudget();
    window.addEventListener('resize', onResize);

    const offNote = app.midi.onNote((event) => {
      if (phase !== 'playing' && phase !== 'countin') return;
      // Playing during the count-in is warm-up, not an answer. A note struck before beat 1 arrives
      // with a negative onset; admitting it would score it as an unmatched extra, which costs pitch
      // precision for the whole exercise, and would let a stray note claim expected notes in the
      // live matcher and finish the run before the player was counted in.
      if (isBeforeDownbeat(event)) return;
      attemptBuffer.record(event);

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
        if (completeTimer) clearTimeout(completeTimer);
        completeTimer = setTimeout(() => void finish(), 450);
      }
    });

    const offRelease = app.midi.onNoteRelease((pitch, durationS) => {
      // The buffer closes the oldest unreleased note of that pitch, because a key can be struck
      // again before the first strike has been released.
      attemptBuffer.release(pitch, durationS);
    });

    // Arriving with a key pinned — the Repertoire tab's "Practise in A" sets
    // one and switches here — means the ask is already explicit, so fetch
    // rather than making the user ask a second time. Without a pin the empty
    // state stands, because there is nothing to say about length or level yet.
    if (app.pinnedKey) void loadExercise();

    return () => {
      window.removeEventListener('resize', onResize);
      offNote();
      offRelease();
    };
  });

  // Focus mode changes how much room the score has.
  $effect(() => {
    app.focusMode;
    void applyBudget();
  });

  // Drives the performance layout in app.css. Set on <html> so the rules can
  // reach the header and footer, which live outside this component.
  $effect(() => {
    document.documentElement.dataset.playing = String(running);
  });

  onDestroy(() => {
    delete document.documentElement.dataset.playing;
    if (endTimer) clearTimeout(endTimer);
    if (completeTimer) clearTimeout(completeTimer);
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

  // The hands-free switch is inert while a run is being scored, and only then. Derived from
  // the phase so every transition is covered without being poked into each one separately.
  $effect(() => {
    app.setExerciseActive(phase === 'countin' || phase === 'playing' || phase === 'submitting');
  });

  // Leaving the view mid-run must not leave the switch inert for the rest of the session.
  onDestroy(() => app.setExerciseActive(false));

  // The keyboard asks; the view answers. Space never reaches here during a run, because
  // the shell checks `app.exerciseActive` before asking.
  $effect(() => {
    const request = app.consumeShortcut();
    if (request === 'start' && phase === 'ready') void start();
    if (request === 'stop' && (phase === 'countin' || phase === 'playing')) void finish();
  });

  async function loadExercise(): Promise<void> {
    reset(false);
    phase = 'loading';
    try {
      exercise = await api.nextExercise({
        skill: forcedSkill || undefined,
        bars: app.bars,
        key: app.pinnedKey ?? undefined,
        level: app.pinnedLevel ?? undefined,
        hands: app.pinnedHand ?? undefined,
      });
      await tick();
      // Disposed before it is replaced. Its ResizeObserver is still watching the same
      // container and its render chain is still live, so an orphan re-renders on the next
      // width change and re-engraves the *previous* exercise over the new one.
      renderer?.dispose();
      renderer = new ScoreRenderer(scoreContainer);
      // The renderer reports back after every render, including its own
      // resize-driven ones, so these never go stale.
      renderer.onStateChange = (state) => {
        zoom = state.zoom;
        tooLong = !state.fits;
      };
      await renderer.render(exercise.musicxml, exercise.expected_notes, {
        dark: theme.scoreIsDark,
        maxHeight: heightBudget(),
      });
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
    attemptBuffer = new ScoredAttempt();
    attempt = [];
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
    // A tempo marking is quarter notes per minute; a *beat* is whatever the
    // meter says it is, which is a dotted quarter in 6/8 and a half note in cut
    // time. Passing seconds-per-quarter as seconds-per-beat made the metronome
    // and the count-in wrong in every compound meter.
    const secondsPerQuarter = 60 / exercise.tempo_bpm;
    const barBeatUnits = exercise.measures.map((measure) => measure.beat_unit_q);
    const countInBeats = countInBeatsFor(app.countInBars, barsBeats);
    // What this run actually derived, so the screen states it rather than implying it: the
    // count-in is inaudible to the browser tier, and a player who asked for two bars and got
    // four would otherwise have no way to notice.
    countInBeatsUsed = countInBeats;

    phase = 'countin';
    renderer?.resetColors();
    // The performance layout exists only now, so the room the score has is measured
    // rather than assumed. Not awaited: the fit must not delay the count-in.
    void refitToRunLayout();

    offBeat?.();
    offBeat = metronome.onBeat((info) => {
      beatInfo = info;
      if (!info.inCountIn && phase === 'countin') phase = 'playing';
    });

    metronome.start({
      barsBeats,
      barBeatUnits,
      secondsPerQuarter,
      countInBeats,
      clickVolume: app.clickVolume,
    });
    // Everything is measured from beat 1, not from the first count-in click.
    app.midi.startRecording(metronome.downbeatMs);

    endTimer = setTimeout(() => void finish(), metronome.durationSeconds * 1000 + 1500);
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
    const notes = attemptBuffer.notes;
    attempt = notes;

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

<section class="card panel practice-chrome" data-phase={phase}>
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
      <select bind:value={forcedSkill} disabled={running}>
        <option value="">Auto (weakest skill)</option>
        {#each app.profile ? Object.keys(app.profile.ratings) : [] as slug (slug)}
          <option value={slug}>{slug.replace(/_/g, ' ')}</option>
        {/each}
      </select>

      <div class="length" role="group" aria-label="Exercise length">
        <span class="muted small">Bars</span>
        {#each BAR_CHOICES as choice (choice)}
          <button
            class:active={app.bars === choice}
            aria-pressed={app.bars === choice}
            disabled={running}
            title="{choice} bars"
            onclick={() => {
              app.setBars(choice);
              if (exercise) void loadExercise();
            }}>{choice}</button
          >
        {/each}
      </div>

      <button
        class:active={app.focusMode}
        aria-pressed={app.focusMode}
        title="Give the score as much of the screen as possible"
        onclick={() => app.toggleFocus()}
      >
        Focus
      </button>
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
        <span class="pill accent" data-exercise-badge>
          {exercise.target_skill?.replace(/_/g, ' ') ?? 'exercise'} · level
          {exercise.levels[exercise.target_skill ?? ''] ?? '—'}
        </span>
        <span class="pill mono">{Math.round(exercise.tempo_bpm)} BPM</span>
        <span class="pill">{exercise.meter}</span>
        <span class="pill">key {exercise.key_name}</span>
        <span class="pill mono">Elo {Math.round(exercise.difficulty_elo)}</span>
        {#if app.pinnedKey}
          <span class="pill accent" title="Set from the Repertoire tab">
            key pinned{app.pinnedKeySource ? ` for ${app.pinnedKeySource}` : ''}
            <button
              class="ghost tiny"
              title="Stop pinning the key"
              onclick={() => {
                app.pinKey(null);
                void loadExercise();
              }}>×</button
            >
          </span>
        {/if}
        {#if app.pinnedLevel !== null}
          <span class="pill accent" title="You chose this difficulty; it does not change your ratings">
            level {app.pinnedLevel} pinned
            <button
              class="ghost tiny"
              title="Go back to the difficulty your ratings choose"
              onclick={() => {
                app.setPinnedLevel(null);
                void loadExercise();
              }}>×</button
            >
          </span>
        {/if}
        {#if app.pinnedHand}
          <span class="pill accent" title="You chose what to read; it does not change your ratings">
            {HAND_LABELS[app.pinnedHand].toLowerCase()} pinned
            <button
              class="ghost tiny"
              title="Let the difficulty decide which hand to read"
              onclick={() => {
                app.setPinnedHand(null);
                void loadExercise();
              }}>×</button
            >
          </span>
        {/if}
        {#if exercise.bass_pattern}
          <span class="pill" title="Left-hand figure">
            LH: {exercise.bass_pattern.replace(/_/g, ' ')}
          </span>
        {/if}
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

    {#if tooLong}
      <div class="too-long">
        <strong>{app.bars} bars is too long for this window.</strong>
        The notation would have to shrink past {Math.round(MIN_ZOOM * 100)}% to fit, which is no longer
        readable, and the music must not scroll during a performance. Pick a shorter length{app.focusMode
          ? ''
          : ', or switch on Focus to give the score more room'}.
        <div class="row wrap">
          {#each BAR_CHOICES.filter((choice) => choice < app.bars) as choice (choice)}
            <button
              onclick={() => {
                app.setBars(choice);
                void loadExercise();
              }}>{choice} bars</button
            >
          {/each}
        </div>
      </div>
    {:else if zoom < 0.999}
      <p class="muted small fit-note">Scaled to {Math.round(zoom * 100)}% so the whole exercise stays on screen.</p>
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
        <span class="pill mono" data-count-in-beats={countInBeatsUsed}>
          {countInBeatsUsed} beats of count-in
        </span>
        <span class="pill mono">
          {mode === 'practice' ? `${progress.correct}/${progress.total} notes` : 'listening…'}
        </span>
      </div>
    {/if}

    <div class="score-surface" bind:this={scoreContainer}></div>

    {#if phase === 'result' && result}
      <ResultsPanel
        {result}
        {exercise}
        played={attempt}
        onNext={() => void loadExercise()}
        onRetry={() => void start()}
      />
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
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.14);
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
    background: var(--track);
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

  .length {
    display: flex;
    align-items: center;
    gap: 0.15rem;
    background: var(--surface-2);
    border: 1px solid var(--line);
    border-radius: 9px;
    padding: 0.15rem 0.15rem 0.15rem 0.5rem;
  }

  .length button {
    border: none;
    background: transparent;
    padding: 0.25rem 0.5rem;
    border-radius: 7px;
    font-size: 0.8rem;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }

  .length button.active {
    background: var(--surface);
    color: var(--ink);
    font-weight: 600;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.14);
  }

  button.active {
    background: var(--accent-soft);
    border-color: var(--accent-line);
    color: var(--accent);
    font-weight: 600;
  }

  .too-long {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    background: var(--warn-soft);
    border: 1px solid var(--warn-line);
    color: var(--warn);
    border-radius: var(--radius);
    padding: 0.6rem 0.75rem;
    font-size: 0.85rem;
    line-height: 1.5;
  }

  .rationale {
    margin: 0;
  }
</style>
