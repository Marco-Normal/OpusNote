<script lang="ts">
  import { onDestroy } from 'svelte';
  import { PianoPlayer } from '../lib/pianoPlayer';
  import { forHands, playedEvents, sounding, writtenEvents } from '../lib/playback';
  import type { Hand } from '../lib/playback';
  import type { Exercise, PlayedNote, ScoreResult } from '../lib/types';
  import { midiToName } from '../lib/types';

  interface Props {
    result: ScoreResult;
    exercise: Exercise;
    /** What was played, from the run that produced this result. */
    played: readonly PlayedNote[];
    onNext: () => void;
    onRetry: () => void;
  }

  let { result, exercise, played, onNext, onRetry }: Props = $props();

  const player = new PianoPlayer();
  let playing = $state<'mine' | 'written' | null>(null);
  let hearRight = $state(true);
  let hearLeft = $state(true);
  let progress = $state(0);

  const hands = $derived(
    [hearRight ? 'RH' : null, hearLeft ? 'LH' : null].filter(Boolean) as Hand[],
  );

  /** Played notes carrying the hand the scorer matched them to. */
  const mine = $derived(sounding(forHands(playedEvents(played, result.feedback), hands)));
  /** The same bars as notated, at the tempo that was counted in. */
  const written = $derived(sounding(forHands(writtenEvents(exercise.expected_notes, exercise.tempo_bpm), hands)));

  async function hear(source: 'mine' | 'written'): Promise<void> {
    const notes = source === 'mine' ? mine : written;
    playing = source;
    progress = 0;
    await player.play(notes, {
      onProgress: (handle) => {
        progress = handle.total > 0 ? Math.min(1, handle.elapsed / handle.total) : 0;
      },
      onDone: () => {
        playing = null;
        progress = 0;
      },
    });
  }

  function stop(): void {
    player.stop();
    playing = null;
    progress = 0;
  }

  onDestroy(() => player.dispose());

  const wrongNotes = $derived(result.feedback.filter((item) => item.status === 'wrong_pitch'));
  const missedNotes = $derived(result.feedback.filter((item) => item.status === 'missed'));

  function tone(value: number): string {
    if (value >= 85) return 'good';
    if (value >= 60) return 'warn';
    return 'bad';
  }

  const subScores = $derived([
    { label: 'Pitch', value: result.pitch_accuracy, weight: result.counts.expected ? 0.5 : 0 },
    { label: 'Rhythm', value: result.rhythm_accuracy, weight: 0.3 },
    { label: 'Continuity', value: result.continuity_accuracy, weight: 0.2 },
  ]);
</script>

<div class="result">
  <div class="headline">
    <div class="score-ring" class:tone={tone(result.score)}>
      <span class="value mono">{Math.round(result.score)}</span>
      <span class="unit">/ 100</span>
    </div>

    <div class="summary">
      <div class="row wrap">
        <span class="pill" class:good={result.passed} class:bad={!result.passed}>
          {result.passed ? 'Passed' : 'Keep working'}
        </span>
        {#if result.rating_change?.delta !== null && result.rating_change?.delta !== undefined}
          <span class="pill" class:good={result.rating_change.delta > 0} class:bad={result.rating_change.delta < 0}>
            {result.rating_change.skill?.replace(/_/g, ' ')}
            {result.rating_change.delta > 0 ? '+' : ''}{result.rating_change.delta}
            <span class="muted">({Math.round(result.rating_change.before ?? 0)} → {Math.round(result.rating_change.after ?? 0)})</span>
          </span>
        {/if}
        <span class="pill">{result.mode === 'practice' ? 'practice' : 'performance'}</span>
      </div>
      <p class="hint muted">{result.next_hint}</p>
    </div>
  </div>

  <div class="bars">
    {#each subScores as item (item.label)}
      <div class="bar-row">
        <span class="bar-label">{item.label}</span>
        <div class="track">
          <div class="fill {tone(item.value)}" style="width: {Math.max(2, item.value)}%"></div>
        </div>
        <span class="mono bar-value">{Math.round(item.value)}%</span>
      </div>
    {/each}
  </div>

  <div class="stats">
    <div class="stat"><span class="k">Notes right</span><span class="v mono">{result.counts.matched}/{result.counts.expected}</span></div>
    <div class="stat"><span class="k">Wrong pitch</span><span class="v mono">{result.counts.wrong_pitch}</span></div>
    <div class="stat"><span class="k">Missed</span><span class="v mono">{result.counts.missed}</span></div>
    <div class="stat"><span class="k">Extra notes</span><span class="v mono">{result.counts.extra}</span></div>
    <div class="stat"><span class="k">Hesitations</span><span class="v mono">{result.counts.hesitations}</span></div>
    <div class="stat">
      <span class="k">Timing bias</span>
      <span class="v mono">{result.timing.mean_onset_error_beats.toFixed(2)} beats</span>
    </div>
    <div class="stat">
      <span class="k">Timing spread</span>
      <span class="v mono">±{result.timing.onset_error_std_beats.toFixed(2)} beats</span>
    </div>
  </div>

  {#if Object.keys(result.by_hand).length > 1}
    <div class="row wrap">
      {#each Object.entries(result.by_hand) as [hand, data] (hand)}
        <span class="pill" class:good={data.accuracy >= 85} class:warn={data.accuracy < 85 && data.accuracy >= 60} class:bad={data.accuracy < 60}>
          {hand} {Math.round(data.accuracy)}%
        </span>
      {/each}
    </div>
  {/if}

  {#if wrongNotes.length > 0 || missedNotes.length > 0}
    <div class="problems">
      {#if wrongNotes.length > 0}
        <div>
          <h3>Wrong notes</h3>
          <ul>
            {#each wrongNotes.slice(0, 8) as item (item.index)}
              <li>
                bar {item.measure} beat {item.beat.toFixed(1)} — expected
                <b class="mono">{midiToName(item.pitch)}</b>, played
                <b class="mono bad-text">{item.played_pitch === null ? '—' : midiToName(item.played_pitch)}</b>
              </li>
            {/each}
          </ul>
          {#if wrongNotes.length > 8}
            <p class="muted small">…and {wrongNotes.length - 8} more.</p>
          {/if}
        </div>
      {/if}

      {#if missedNotes.length > 0}
        <div>
          <h3>Missed</h3>
          <ul>
            {#each missedNotes.slice(0, 8) as item (item.index)}
              <li>bar {item.measure} beat {item.beat.toFixed(1)} — <b class="mono">{midiToName(item.pitch)}</b></li>
            {/each}
          </ul>
          {#if missedNotes.length > 8}
            <p class="muted small">…and {missedNotes.length - 8} more.</p>
          {/if}
        </div>
      {/if}
    </div>
  {/if}

  <div class="row wrap hearing" data-playing={playing ?? 'false'}>
    <span class="muted small">Hear it</span>
    <button class="ghost" onclick={() => void hear('mine')} disabled={mine.length === 0}>
      Play yours
    </button>
    <button class="ghost" onclick={() => void hear('written')}>Play as written</button>
    {#if playing}
      <button class="ghost" onclick={stop}>Stop</button>
    {/if}
    <label class="hand">
      <input type="checkbox" bind:checked={hearRight} /> RH
    </label>
    <label class="hand">
      <input type="checkbox" bind:checked={hearLeft} /> LH
    </label>
    {#if playing}
      <span class="meter" aria-hidden="true"><span style="width: {progress * 100}%"></span></span>
    {/if}
    <span class="muted small">
      Synthesised, not the piano — but the timing and touch are yours.
    </span>
  </div>

  <div class="row">
    <button class="primary" onclick={onNext}>Next exercise</button>
    <button onclick={onRetry}>Play again</button>
    <span class="muted small">Exercise #{exercise.exercise_id} · Elo {Math.round(exercise.difficulty_elo)}</span>
  </div>
</div>

<style>
  .hearing {
    border-top: 1px solid var(--line);
    padding-top: 0.6rem;
    align-items: center;
  }

  .hand {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.82rem;
    color: var(--muted);
  }

  .meter {
    flex: 0 0 6rem;
    height: 3px;
    border-radius: 999px;
    background: var(--track);
    overflow: hidden;
  }

  .meter span {
    display: block;
    height: 100%;
    background: var(--accent);
  }
  .result {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    border-top: 1px solid var(--line);
    padding-top: 0.75rem;
  }

  .headline {
    display: flex;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .score-ring {
    display: flex;
    align-items: baseline;
    gap: 0.15rem;
    padding: 0.5rem 0.9rem;
    border-radius: var(--radius);
    border: 2px solid var(--line);
    background: var(--surface-2);
  }

  .score-ring .value {
    font-size: 2rem;
    font-weight: 700;
    line-height: 1;
  }

  .score-ring .unit {
    font-size: 0.8rem;
    color: var(--muted);
  }

  .score-ring.tone.good {
    border-color: var(--good-line);
    background: var(--good-soft);
    color: var(--good);
  }

  .score-ring.tone.warn {
    border-color: var(--warn-line);
    background: var(--warn-soft);
    color: var(--warn);
  }

  .score-ring.tone.bad {
    border-color: var(--bad-line);
    background: var(--bad-soft);
    color: var(--bad);
  }

  .summary {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .hint {
    margin: 0;
    font-size: 0.85rem;
  }

  .bars {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    max-width: 34rem;
  }

  .bar-row {
    display: grid;
    grid-template-columns: 5rem 1fr 3.2rem;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.85rem;
  }

  .track {
    height: 0.5rem;
    background: var(--track);
    border-radius: 999px;
    overflow: hidden;
  }

  .fill {
    height: 100%;
    border-radius: 999px;
  }

  .fill.good {
    background: var(--good);
  }

  .fill.warn {
    background: var(--warn);
  }

  .fill.bad {
    background: var(--bad);
  }

  .bar-value {
    text-align: right;
    color: var(--muted);
  }

  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr));
    gap: 0.4rem;
  }

  .stat {
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
    padding: 0.35rem 0.5rem;
    border-radius: 8px;
    background: var(--surface-2);
    border: 1px solid var(--line);
    font-size: 0.82rem;
  }

  .stat .k {
    color: var(--muted);
  }

  .problems {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
    gap: 0.75rem;
  }

  .problems ul {
    margin: 0.3rem 0 0;
    padding-left: 1.05rem;
    font-size: 0.83rem;
    line-height: 1.6;
  }

  .bad-text {
    color: var(--bad);
  }

  .small {
    font-size: 0.8rem;
  }
</style>
