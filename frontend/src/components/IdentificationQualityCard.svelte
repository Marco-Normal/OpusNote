<script lang="ts">
  import type { IdentificationQuality } from '../lib/types';

  interface Props {
    quality: IdentificationQuality;
    matching: boolean;
    matchNote: string | null;
    onLookForMatches: () => void;
  }

  let { quality, matching, matchNote, onLookForMatches }: Props = $props();

  /** A rate with its counts, and an em dash when there is nothing to divide. */
  function rate(label: string, value: number | null, correct: number, attempts: number): string {
    return value === null ? `${label} —` : `${label} ${Math.round(value * 100)}% (${correct}/${attempts})`;
  }
</script>

<section class="card identify" data-identification>
  <div class="row wrap spread">
    <h3>Recognising what you played</h3>
    <button class="ghost tiny" disabled={matching} onclick={onLookForMatches}>
      {matching ? 'Looking…' : 'Look for matches'}
    </button>
  </div>

  {#if quality.evaluated === 0}
    <p class="muted small">
      Nothing to measure yet. The matcher learns from the segments you have tagged
      by hand: {quality.labelled}
      {quality.labelled === 1 ? 'segment is' : 'segments are'} labelled, and
      {quality.labelled < 2
        ? 'two are the minimum, because the first one has nothing to be compared against.'
        : 'a measurement needs at least two.'}
    </p>
  {:else}
    <div class="health-grid">
      <div>
        <span class="muted small">Right first time</span>
        <strong>{quality.accuracy === null ? '—' : `${Math.round(quality.accuracy * 100)}%`}</strong>
        <span class="muted small">
          {quality.correct_top}/{quality.evaluated} labels, each hidden and guessed back
        </span>
      </div>
      <div>
        <span class="muted small">In the top three</span>
        <strong>{quality.top3_accuracy === null ? '—' : `${Math.round(quality.top3_accuracy * 100)}%`}</strong>
        <span class="muted small">{quality.correct_top3}/{quality.evaluated}</span>
      </div>
      <div>
        <span class="muted small">Written without asking</span>
        <strong>{rate('', quality.auto_precision, quality.auto_correct, quality.auto_attempted).trim() || '—'}</strong>
        <span class="muted small">
          {quality.auto_attempted} of {quality.evaluated} segments
          ({quality.auto_coverage === null ? '—' : `${Math.round(quality.auto_coverage * 100)}%`})
        </span>
      </div>
      <div>
        <span class="muted small">Offered and right</span>
        <strong>{rate('', quality.offered_precision, quality.offered_correct, quality.offered_attempted).trim() || '—'}</strong>
        <span class="muted small">
          {quality.offered_attempted} offered, {quality.unresolved} it could not judge
        </span>
      </div>
    </div>

    <p class="muted small">
      Measured by hiding each of your {quality.labelled} hand-tagged segments in turn and
      seeing whether the matcher names the right piece without it. On your own library,
      including the pieces that sound like each other.
      {#if quality.skipped}
        {quality.skipped} older labels were left out to keep this quick.
      {/if}
    </p>
  {/if}

  {#if quality.inferred > 0}
    <p class="muted small" data-inferred-count>
      {quality.inferred}
      {quality.inferred === 1 ? 'segment carries' : 'segments carry'} a label the matcher
      wrote. {#if quality.settled > 0}
        Of the {quality.settled} you have since judged,
        {quality.confirmed} were right, {quality.changed} you corrected and
        {quality.rejected} you threw out
        {#if quality.live_precision !== null}
          — {Math.round(quality.live_precision * 100)}% left alone.
        {/if}
      {:else}
        None judged yet: each one is marked <em>guessed</em> in the timeline until you
        accept or correct it.
      {/if}
      {#if quality.dismissed > 0}
        You have also declined {quality.dismissed}
        {quality.dismissed === 1 ? 'suggestion' : 'suggestions'}, which is not counted
        against the matcher.
      {/if}
    </p>
  {/if}

  {#each quality.notes as note}
    <p class="muted small">{note}</p>
  {/each}
  {#if matchNote}
    <div class="notice">{matchNote}</div>
  {/if}
</section>

<style>
  .identify {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    padding: 0.75rem 0.9rem;
  }

  .identify h3 {
    margin: 0;
  }

  .health-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
    gap: 0.75rem;
  }

  .health-grid > div {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }

  .health-grid strong {
    font-size: 1.05rem;
  }

  .small {
    font-size: 0.8rem;
  }
</style>
