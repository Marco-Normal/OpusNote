<script lang="ts">
  /**
   * One segment row in the timeline's attempt list.
   *
   * Displays playback controls, piece identification guesses, metrics, and splitting/merging.
   */
  import { app } from '../lib/state.svelte';
  import { formatClock } from '../lib/clock';
  import { pieceLabel, uniquePieceLabels } from '../lib/pieceLabel';
  import {
    PRACTICE_KINDS,
    practiceKindLabel,
    kindCounts,
  } from '../lib/kinds';
  import type { PieceSummary, PracticeKind, SegmentCandidate, SegmentMetrics, SegmentSummary } from '../lib/types';

  interface Props {
    segment: SegmentSummary;
    index: number;
    chosenSegment: number | null;
    tint: string | null;
    busy: boolean;
    pieces: PieceSummary[];
    pieceNames: Map<number, string>;
    splitValue: string;
    previousSegmentId: number | null;
    detailId: number;
    onassign: (segmentId: number, pieceId: number | null) => void;
    onkinds: (
      segmentId: number,
      body: { action: 'set' | 'accept' | 'decline'; kind?: PracticeKind | null },
    ) => void;
    onidentify: (segmentId: number, action: 'accept' | 'reject' | 'dismiss') => void;
    onSplitInput: (value: string) => void;
    onSubmitSplit: () => void;
    onMergePrevious: () => void;
    onPlaySegment: () => void;
  }

  let {
    segment,
    index,
    chosenSegment,
    tint,
    busy,
    pieces,
    pieceNames,
    splitValue,
    previousSegmentId,
    detailId,
    onassign,
    onkinds,
    onidentify,
    onSplitInput,
    onSubmitSplit,
    onMergePrevious,
    onPlaySegment,
  }: Props = $props();

  const inferred = (seg: SegmentSummary): boolean => seg.identified_by === 'similarity';
  const suggested = (seg: SegmentSummary): boolean =>
    seg.piece_id === null && seg.candidates.length > 0 && seg.candidates[0].band === 'suggest';
  const percent = (value: number): string => `${Math.round(value * 100)}%`;

  function balanceLabel(metrics: SegmentMetrics): string | null {
    const low = metrics.mean_velocity_low;
    const high = metrics.mean_velocity_high;
    if (!low || !high) return null;
    const gap = Math.round(((low - high) / Math.max(low, high)) * 100);
    if (Math.abs(gap) < 8) return 'registers even';
    return gap > 0 ? `lower half +${gap}%` : `upper half ${gap}%`;
  }

  function measuredSummary(seg: SegmentSummary): string {
    const parts: string[] = [];
    const minutes = (seg.end_ms - seg.start_ms) / 60_000;
    if (minutes > 0) parts.push(`${minutes.toFixed(1)} min`);
    if (seg.metrics?.median_tempo) {
      parts.push(`${Math.round(seg.metrics.median_tempo)} BPM note rate`);
    }
    if (seg.metrics?.restarts) parts.push(`${seg.metrics.restarts} restarts`);
    return parts.join(' · ') || `${seg.note_count} notes`;
  }
</script>

<li
  class="segment"
  class:selected={chosenSegment === segment.id}
  data-segment={segment.id}
>
  <div class="head row wrap">
    <span class="mono range">{formatClock(segment.start_ms / 1000)}–{formatClock(segment.end_ms / 1000)}</span>
    <span class="muted small">{segment.note_count} notes</span>
    {#if segment.metrics?.median_tempo}
      <span class="pill mono">{Math.round(segment.metrics.median_tempo)} BPM</span>
    {/if}
    {#if segment.metrics?.restarts}
      <span class="pill warn" title="Silences long enough to read as starting again">
        {segment.metrics.restarts} restarts
      </span>
    {/if}
    {#if segment.metrics?.pedal_basis}
      <span
        class="pill mono"
        data-pedal-changes={segment.metrics.pedal_changes}
        title="Times the pedal crossed its threshold. MIDI's own rule: below 64 is up, so a part-depressed pedal is not counted as a change here"
      >
        {segment.metrics.pedal_changes} pedal
      </span>
      {#if segment.metrics?.pedal_partial_ratio}
        <span
          class="pill mono"
          data-pedal-partial={segment.metrics.pedal_partial_ratio}
          title="Share of this segment spent with the damper part-way down — a position an on/off pedal cannot report. Playback rings a note on in proportion to it; the sampler's version of that is an approximation, the piano's own damper is not"
        >
          {percent(segment.metrics.pedal_partial_ratio)} half-pedalled
        </span>
      {/if}
      {#if segment.metrics?.pedal_blur}
        <span
          class="pill warn"
          data-pedal-blur={segment.metrics.pedal_blur}
          title="Attacks that brought new harmony over notes the pedal was already holding. Observed from the pitches, not from a score — it reports, it does not judge. At {segment.metrics.pedal_blur_ms
            .map((ms) => formatClock(ms / 1000))
            .join(', ')}"
        >
          {segment.metrics.pedal_blur} pedal blur
        </span>
        <span class="muted small" data-blur-where={segment.id}>
          at {segment.metrics.pedal_blur_ms
            .slice(0, 4)
            .map((ms) => formatClock(ms / 1000))
            .join(', ')}{segment.metrics.pedal_blur_ms.length > 4 ? ' …' : ''}
        </span>
      {/if}
    {:else if segment.metrics}
      <span
        class="muted small"
        data-pedal-unrecorded
        title="This sitting has no pedal events at all — imported history. Not the same as a pedal that was never pressed"
      >
        pedal not recorded
      </span>
    {/if}
    {#if segment.metrics?.median_velocity != null}
      <span
        class="pill mono"
        title="Middle velocity, at MIDI controller resolution — comparable with itself over weeks, not a measure of loudness"
      >
        {Math.round(segment.metrics.median_velocity)} vel
      </span>
    {/if}
    {#if segment.metrics && balanceLabel(segment.metrics)}
      <span
        class="pill"
        title="Mean velocity below and above middle C. A proxy for the hands, not a measurement of them — the piano sends both hands on one channel"
      >
        {balanceLabel(segment.metrics)}
      </span>
    {/if}
    {#if segment.source === 'sight_reading'}
      <span class="pill accent">
        {segment.workout_id ? `workout ${segment.workout_id}` : 'sight-reading'}
      </span>
    {/if}
    {#if segment.practice_kind && kindCounts(segment.practice_kind_basis)}
      <span
        class="pill"
        data-kind={segment.practice_kind}
        title="How this segment was practised — said by you, not inferred"
      >
        {practiceKindLabel(segment.practice_kind)}
      </span>
    {/if}
    {#if segment.piece_id}
      <button
        class="ghost tiny"
        data-write-about={segment.id}
        title="Write a journal entry about this piece and this session"
        onclick={() =>
          app.writeAboutSitting(
            segment.piece_id as number,
            detailId,
            measuredSummary(segment),
          )}
      >
        Write about this
      </button>
    {/if}
  </div>

  {#if inferred(segment)}
    <div class="row wrap inferred" data-inferred={segment.id}>
      <span
        class="pill accent"
        title="Written by the matcher from your own tagged practice — not by you"
      >
        guessed{segment.confidence !== null ? ` · ${percent(segment.confidence)}` : ''}
      </span>
      <button class="ghost tiny" disabled={busy} onclick={() => onidentify(segment.id, 'accept')}>
        It's right
      </button>
      <button class="ghost tiny" disabled={busy} onclick={() => onidentify(segment.id, 'reject')}>
        Not this
      </button>
      <span class="muted small">
        or correct it below — either way the answer improves the next guess
      </span>
    </div>
  {:else if suggested(segment)}
    {@const candidateNames = uniquePieceLabels(
      segment.candidates,
      (candidate: SegmentCandidate) => candidate.piece_id,
    )}
    <div class="row wrap suggest" data-suggest={segment.id}>
      <span class="muted small">Maybe</span>
      {#each segment.candidates as candidate (candidate.piece_id)}
        <button
          class="ghost tiny"
          disabled={busy}
          data-candidate={candidate.piece_id}
          title="notes {percent(candidate.pitch_class)} · tempo {percent(
            candidate.tempo,
          )} · register {percent(candidate.register_overlap)} · hands {percent(
            candidate.hand,
          )} · intervals {percent(candidate.interval)}"
          onclick={() => onassign(segment.id, candidate.piece_id)}
        >
          {candidateNames.get(candidate.piece_id) ?? pieceLabel(candidate)}{candidate.from_context
            ? ' · this sitting'
            : ''} · {percent(candidate.score)}
        </button>
      {/each}
      <button class="ghost tiny" disabled={busy} onclick={() => onidentify(segment.id, 'dismiss')}>
        Neither
      </button>
      {#if segment.candidates[0].reason}
        <span class="muted small">{segment.candidates[0].reason}</span>
      {/if}
    </div>
  {/if}

  {#if segment.practice_kind_basis === 'offered' && segment.practice_kind}
    <div class="row wrap suggest" data-kind-offer={segment.id}>
      <span class="muted small">{practiceKindLabel(segment.practice_kind)} practice?</span>
      <button
        class="ghost tiny"
        disabled={busy}
        onclick={() => onkinds(segment.id, { action: 'accept' })}
      >
        Yes
      </button>
      <button
        class="ghost tiny"
        disabled={busy}
        onclick={() => onkinds(segment.id, { action: 'decline' })}
      >
        No
      </button>
      <span class="muted small">
        from the tempo and the restarts — not from a score, and it counts for nothing
        until you say so
      </span>
    </div>
  {/if}

  <div class="row wrap controls">
    {#if tint}
      <span class="swatch" style="background: {tint}" aria-hidden="true"></span>
    {/if}
    <select
      aria-label="Piece for this segment"
      disabled={busy}
      value={segment.piece_id ?? ''}
      onchange={(event) => {
        const value = (event.currentTarget as HTMLSelectElement).value;
        onassign(segment.id, value === '' ? null : Number(value));
      }}
    >
      <option value="">— unidentified —</option>
      {#each pieces as piece (piece.id)}
        <option value={piece.id}>{pieceNames.get(piece.id) ?? pieceLabel(piece)}</option>
      {/each}
    </select>

    <select
      aria-label="How this segment was practised"
      disabled={busy}
      value={segment.practice_kind && kindCounts(segment.practice_kind_basis)
        ? segment.practice_kind
        : ''}
      onchange={(event) => {
        const value = (event.currentTarget as HTMLSelectElement).value;
        onkinds(segment.id, {
          action: 'set',
          kind: value === '' ? null : (value as PracticeKind),
        });
      }}
    >
      <option value="">— how practised? —</option>
      {#each PRACTICE_KINDS as entry (entry.id)}
        <option value={entry.id}>{entry.label}</option>
      {/each}
    </select>

    <span class="row split">
      <label class="muted small" for="split-{segment.id}">Split at</label>
      <input
        id="split-{segment.id}"
        type="text"
        inputmode="numeric"
        class="mono at"
        aria-label="Split point as seconds or m:ss"
        title="Where to cut this segment in two — seconds from the start of the sitting, or m:ss"
        value={splitValue}
        oninput={(event) => onSplitInput((event.currentTarget as HTMLInputElement).value)}
      />
      <button
        class="ghost tiny"
        disabled={busy}
        onclick={onSubmitSplit}
      >
        Split here
      </button>
    </span>

    {#if index > 0 && previousSegmentId !== null}
      <button
        class="ghost tiny"
        disabled={busy}
        onclick={onMergePrevious}
      >
        Merge with previous
      </button>
    {/if}

    <button
      class="ghost tiny"
      disabled={busy || segment.note_count === 0}
      title="Hear this segment"
      onclick={onPlaySegment}
    >
      ▶ {segment.note_count} notes
    </button>
  </div>
</li>

<style>
  .segment {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 0.5rem 0.6rem;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    background: var(--surface);
  }

  .segment.selected {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
  }

  .head {
    align-items: center;
    gap: 0.45rem;
  }

  .range {
    font-size: 0.85rem;
  }

  .swatch {
    width: 0.75rem;
    height: 0.75rem;
    border-radius: 999px;
    border: 1px solid rgba(0, 0, 0, 0.15);
    display: inline-block;
    flex-shrink: 0;
  }

  .controls {
    align-items: center;
    gap: 0.45rem;
  }

  .controls select {
    font: inherit;
    font-size: 0.85rem;
    padding: 0.2rem 0.4rem;
    border-radius: var(--radius);
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--ink);
  }

  .split {
    align-items: center;
    gap: 0.3rem;
  }

  .at {
    width: 4.8rem;
    font-size: 0.82rem;
    padding: 0.2rem 0.35rem;
    border-radius: var(--radius);
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--ink);
    text-align: right;
  }

  .inferred,
  .suggest {
    align-items: center;
    gap: 0.4rem;
    padding: 0.25rem 0.45rem;
    border-radius: var(--radius);
    background: var(--surface-2);
  }
</style>
