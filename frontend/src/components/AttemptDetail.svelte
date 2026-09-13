<script lang="ts">
  /**
   * One past attempt, opened from the history.
   *
   * Everything here was stored when the attempt happened — the played notes, the
   * analysis, and the exercise itself — so this is a read, not a reconstruction. It
   * exists so a row in the history can be *heard* rather than only counted.
   */
  import { playedEvents, sounding, writtenEvents } from '../lib/playback';
  import type { PerformanceDetail } from '../lib/types';
  import { formatClock } from '../lib/clock';
  import HearIt from './HearIt.svelte';

  interface Props {
    detail: PerformanceDetail;
    onclose: () => void;
  }

  let { detail, onclose }: Props = $props();

  const attempt = $derived(sounding(playedEvents(detail.played_notes, detail.feedback)));
  const written = $derived(
    sounding(writtenEvents(detail.expected_notes, detail.tempo_bpm ?? 90)),
  );

  const bars = $derived([
    { label: 'Pitch', value: detail.pitch_accuracy ?? 0 },
    { label: 'Rhythm', value: detail.rhythm_accuracy ?? 0 },
    { label: 'Continuity', value: detail.continuity_accuracy ?? 0 },
  ]);

  const wrong = $derived(detail.feedback.filter((item) => item.status === 'wrong_pitch').length);
  const missed = $derived(detail.feedback.filter((item) => item.status === 'missed').length);
</script>

<section class="card attempt" data-attempt={detail.performance_id}>
  <header class="spread wrap">
    <div class="row wrap">
      <h3>Attempt {detail.performance_id}</h3>
      <span class="pill mono">{detail.score?.toFixed(0) ?? '—'}/100</span>
      <span class="pill">{detail.target_skill?.replace(/_/g, ' ') ?? 'exercise'}</span>
      {#if detail.key_name}<span class="pill">{detail.key_name}</span>{/if}
      {#if detail.meter}<span class="pill">{detail.meter}</span>{/if}
      <span class="pill mono">{Math.round(detail.tempo_bpm ?? 0)} BPM</span>
      {#if detail.performed_at}
        <span class="muted small">{detail.performed_at.slice(0, 16)}</span>
      {/if}
    </div>
    <button class="ghost tiny" onclick={onclose}>Close</button>
  </header>

  <ul class="bars">
    {#each bars as bar (bar.label)}
      <li>
        <span class="label">{bar.label}</span>
        <span class="track"><span style="width: {Math.max(2, bar.value)}%"></span></span>
        <span class="mono value">{bar.value.toFixed(0)}%</span>
      </li>
    {/each}
  </ul>

  <div class="row wrap counts">
    <span class="pill">{detail.played_notes.length} played</span>
    <span class="pill">{detail.expected_notes.length} written</span>
    {#if wrong}<span class="pill bad">{wrong} wrong pitch</span>{/if}
    {#if missed}<span class="pill warn">{missed} missed</span>{/if}
    <span class="muted small">
      {formatClock((detail.tempo_bpm ?? 90) / 60)} per beat · Elo
      {Math.round(detail.difficulty_elo ?? 0)}
    </span>
  </div>

  <HearIt {attempt} {written} />
</section>

<style>
  .attempt {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    padding: 0.75rem 0.9rem;
  }

  h3 {
    font-size: 0.95rem;
  }

  .bars {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .bars li {
    display: grid;
    grid-template-columns: 5rem 1fr 3rem;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.84rem;
  }

  .track {
    height: 7px;
    border-radius: 999px;
    background: var(--track);
    overflow: hidden;
  }

  .track span {
    display: block;
    height: 100%;
    background: var(--accent);
  }

  .value {
    text-align: right;
    color: var(--muted);
    font-size: 0.8rem;
  }

  .counts {
    gap: 0.4rem;
  }

  .small {
    font-size: 0.8rem;
  }
</style>
