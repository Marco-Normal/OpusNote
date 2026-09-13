<script lang="ts">
  /**
   * One sitting, broken into the pieces (or the workout) it contained.
   *
   * The boundaries are stored, never recomputed on read, so everything here is a
   * deliberate edit: tag a segment, split a boundary the silence detector got
   * wrong, merge two it split, or throw the boundaries away and start again.
   */
  import { onDestroy } from 'svelte';
  import { api } from '../lib/api';
  import { PianoPlayer } from '../lib/pianoPlayer';
  import { loggedEvents, sounding, within, type SynthNote } from '../lib/playback';
  import { formatClock, type PieceSummary, type SittingDetail } from '../lib/types';

  interface Props {
    detail: SittingDetail;
    pieces: PieceSummary[];
    busy: boolean;
    onassign: (segmentId: number, pieceId: number | null) => void;
    onsplit: (segmentId: number, atMs: number) => void;
    onmerge: (segmentId: number, otherId: number) => void;
    onresegment: (confirm: boolean) => void;
  }

  let { detail, pieces, busy, onassign, onsplit, onmerge, onresegment }: Props = $props();

  /** Split points, in seconds from the sitting start, keyed by segment. */
  let splitAt = $state<Record<number, string>>({});

  const total = $derived(Math.max(detail.duration_s * 1000, 1));

  const player = new PianoPlayer();
  /** Which range is sounding, in sitting-relative milliseconds, or null. */
  let playing = $state<{ fromMs: number; toMs: number; segmentId: number | null } | null>(null);
  let playError = $state<string | null>(null);
  // Notes are fetched on the first play rather than with the detail: a long sitting is
  // thousands of notes, and every segment edit re-reads the detail without needing one.
  let notes: SynthNote[] | null = null;

  // A segment's playhead is positioned from the segment's own offset while it plays,
  // so it tracks the block it started in rather than jumping to the sitting's start.
  const playhead = $derived.by(() => {
    const current = playing;
    if (!current) return { start: 0, width: 0 };
    const span = Math.max(current.toMs - current.fromMs, 1);
    return {
      start: (current.fromMs / total) * 100,
      width: (span / total) * 100,
    };
  });

  async function loadNotes(): Promise<SynthNote[]> {
    if (notes) return notes;
    const body = await api.practice.sittingNotes(detail.id);
    notes = loggedEvents(body.notes);
    return notes;
  }

  async function play(fromMs: number, toMs: number, segmentId: number | null): Promise<void> {
    playError = null;
    try {
      const all = await loadNotes();
      const slice = segmentId === null ? all : within(all, fromMs, toMs);
      if (slice.length === 0) {
        playError = 'Nothing was played in this range.';
        return;
      }
      playing = { fromMs, toMs, segmentId };
      // `sounding` drops the silence before the first note, so playing a segment that
      // begins after a pause starts immediately rather than waiting it out.
      await player.play(sounding(slice), {
        onDone: () => (playing = null),
      });
    } catch (cause) {
      playing = null;
      playError = cause instanceof Error ? cause.message : String(cause);
    }
  }

  function stop(): void {
    player.stop();
    playing = null;
  }

  onDestroy(() => player.dispose());

  function offset(ms: number): string {
    return formatClock(ms / 1000);
  }

  function midpoint(segmentId: number, startMs: number, endMs: number): string {
    return splitAt[segmentId] ?? ((startMs + endMs) / 2000).toFixed(1);
  }

  function submitSplit(segmentId: number, startMs: number, endMs: number): void {
    const raw = splitAt[segmentId] ?? ((startMs + endMs) / 2000).toFixed(1);
    const seconds = Number(raw);
    if (!Number.isFinite(seconds)) return;
    onsplit(segmentId, Math.round(seconds * 1000));
  }

  const labelled = $derived(detail.segments.filter((segment) => segment.piece_id !== null).length);
</script>

<section class="card timeline" data-segments={detail.segments.length}>
  <header class="spread wrap">
    <div class="row wrap">
      <h3>Sitting {detail.local_date}</h3>
      <span class="pill mono">{formatClock(detail.duration_s)}</span>
      <span class="pill">{detail.note_count} notes</span>
      {#if detail.source === 'sight_reading'}
        <span class="pill accent">sight-reading</span>
      {/if}
      {#if !detail.closed}
        <span class="pill warn">still open</span>
      {/if}
    </div>
    <button
      class="ghost tiny"
      disabled={busy}
      title="Recompute the boundaries from the notes, discarding them"
      onclick={() => onresegment(labelled > 0)}
    >
      Re-segment{labelled > 0 ? ' (discards labels)' : ''}
    </button>
  </header>

  <div class="row wrap transport" data-playing={playing ? 'true' : 'false'}>
    {#if playing}
      <button class="ghost tiny" onclick={stop}>Stop</button>
      <span class="muted small">
        Playing {playing.segmentId === null ? 'the whole sitting' : 'this segment'}
      </span>
    {:else}
      <button
        class="ghost tiny"
        disabled={detail.note_count === 0}
        onclick={() => void play(0, total, null)}
      >
        Play the sitting
      </button>
      <span class="muted small">
        Synthesised from the logged notes — timing and touch are yours, the instrument
        is not.
      </span>
    {/if}
  </div>

  {#if playError}
    <p class="error-banner small">{playError}</p>
  {/if}

  {#if detail.segments.length === 0}
    <p class="muted small">
      {detail.closed
        ? 'No segments — nothing to split.'
        : 'Boundaries appear once this sitting has been quiet for five minutes.'}
    </p>
  {:else}
    <div class="strip" role="img" aria-label="Segment timeline">
      {#each detail.segments as segment (segment.id)}
        <span
          class="block"
          class:labelled={segment.piece_id !== null}
          class:sight={segment.source === 'sight_reading'}
          style="left: {(segment.start_ms / total) * 100}%; width: {Math.max(
            0.6,
            ((segment.end_ms - segment.start_ms) / total) * 100,
          )}%"
          title="{segment.piece_title ?? 'unidentified'} · {formatClock(
            (segment.end_ms - segment.start_ms) / 1000,
          )}"
        ></span>
      {/each}
      {#if playing}
        <!-- The playhead is positioned from the *segment's* offset while a segment
             plays, so it tracks the block it started in rather than the sitting. -->
        <span
          class="playhead"
          data-playhead
          style="left: {playhead.start}%; max-width: {playhead.width}%"
        ></span>
      {/if}
    </div>

    <ul class="segments">
      {#each detail.segments as segment, index (segment.id)}
        <li class="segment">
          <div class="head row wrap">
            <span class="mono range">{offset(segment.start_ms)}–{offset(segment.end_ms)}</span>
            <span class="muted small">{segment.note_count} notes</span>
            {#if segment.metrics?.median_tempo}
              <span class="pill mono">{Math.round(segment.metrics.median_tempo)} BPM</span>
            {/if}
            {#if segment.metrics?.restarts}
              <span class="pill warn" title="Silences long enough to read as starting again">
                {segment.metrics.restarts} restarts
              </span>
            {/if}
            {#if segment.source === 'sight_reading'}
              <span class="pill accent">
                {segment.workout_id ? `workout ${segment.workout_id}` : 'sight-reading'}
              </span>
            {/if}
          </div>

          <div class="row wrap controls">
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
                <option value={piece.id}>
                  {piece.title}{piece.composer_name ? ` · ${piece.composer_name}` : ''}
                </option>
              {/each}
            </select>

            <span class="row split">
              <input
                type="number"
                min="0"
                step="0.1"
                class="mono at"
                aria-label="Split point in seconds"
                value={midpoint(segment.id, segment.start_ms, segment.end_ms)}
                oninput={(event) => {
                  splitAt[segment.id] = (event.currentTarget as HTMLInputElement).value;
                }}
              />
              <button
                class="ghost tiny"
                disabled={busy}
                onclick={() => submitSplit(segment.id, segment.start_ms, segment.end_ms)}
              >
                Split here
              </button>
            </span>

            {#if index > 0}
              <button
                class="ghost tiny"
                disabled={busy}
                onclick={() => onmerge(segment.id, detail.segments[index - 1].id)}
              >
                Merge with previous
              </button>
            {/if}

            <button
              class="ghost tiny"
              disabled={busy || segment.note_count === 0}
              title="Hear this segment"
              onclick={() =>
                void play(
                  segment.start_ms,
                  segment.end_ms,
                  segment.id,
                )}
            >
              ▶ {segment.note_count} notes
            </button>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .timeline {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    padding: 0.75rem 0.85rem;
  }

  h3 {
    font-size: 0.95rem;
  }

  .strip {
    position: relative;
    height: 18px;
    border-radius: 6px;
    background: var(--track);
    overflow: hidden;
  }

  .block {
    position: absolute;
    top: 0;
    bottom: 0;
    background: var(--muted);
    opacity: 0.55;
    border-right: 1px solid var(--surface);
  }

  .block.labelled {
    background: var(--good);
    opacity: 0.8;
  }

  .playhead {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--ink);
    box-shadow: 0 0 0 1px var(--surface);
  }

  .transport {
    gap: 0.45rem;
  }

  .block.sight {
    background: var(--accent);
    opacity: 0.85;
  }

  .segments {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    max-height: 26rem;
    overflow-y: auto;
  }

  .segment {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 0.45rem 0.55rem;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: var(--surface-2);
  }

  .range {
    font-size: 0.84rem;
  }

  .controls {
    gap: 0.45rem;
  }

  select {
    max-width: 16rem;
  }

  .split {
    gap: 0.3rem;
  }

  .at {
    width: 5.2rem;
  }

  .small {
    font-size: 0.78rem;
  }
</style>
