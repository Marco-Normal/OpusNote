<script lang="ts">
  /**
   * What this app recorded, newest first, and any two of them side by side.
   *
   * Only `source === 'captured'` rows appear: a take is audio the app heard, which is a different
   * question from "what is in my library" — that is the recordings list below it, and mixing them
   * would make both harder to read.
   *
   * Comparing two is two independent players, not a mixer. There is no attempt to align them: the
   * app has no score to align against, and pretending to would be the same claim 20-D7 refuses.
   */
  import type { Recording, SegmentSummary } from '../lib/types';
  import { formatClock } from '../lib/clock';
  import { app } from '../lib/state.svelte';
  import RecordingPlayer from './RecordingPlayer.svelte';

  interface Props {
    takes: Recording[];
    /** Segments of the open piece's sittings, so a take can say which passage it was. */
    segments: Map<number, SegmentSummary>;
    onloop: (mediaId: number, loop: { start: number | null; end: number | null }) => void;
    ondelete: (mediaId: number) => void;
  }

  let { takes, segments, onloop, ondelete }: Props = $props();

  const loopback = $derived(app.host?.loopback ?? false);

  let compare = $state<number[]>([]);

  function toggleCompare(id: number): void {
    if (compare.includes(id)) {
      compare = compare.filter((value) => value !== id);
      return;
    }
    // Two at a time, and the older one drops out: a third player makes the page unusable and
    // nothing is gained by hearing three at once.
    compare = [...compare, id].slice(-2);
  }

  function passageOf(take: Recording): string {
    if (take.segment_id === null) return 'not tied to a segment';
    const segment = segments.get(take.segment_id);
    if (segment === undefined) return 'segment no longer exists';
    return `bars from ${formatClock(segment.start_ms / 1000)} to ${formatClock(segment.end_ms / 1000)}`;
  }
</script>

<section class="card" data-takes={takes.length}>
  <h3>Takes this app recorded</h3>
  {#if takes.length === 0}
    <p class="muted small">
      Nothing recorded here yet. Press <em>Record takes</em> in the device bar and play: a take
      starts on the first note and ends when you stop for as long as the server treats as a segment
      boundary.
    </p>
  {:else}
    <ul class="takes">
      {#each takes as take (take.id)}
        <li data-take={take.id}>
          <div class="row wrap">
            <span class="mono small">{take.taken_on ?? 'undated'}</span>
            <span class="muted small">{formatClock(take.duration_secs ?? 0)}</span>
            <span class="muted small">{passageOf(take)}</span>
            <button class="ghost tiny" onclick={() => toggleCompare(take.id)}>
              {compare.includes(take.id) ? 'Remove from compare' : 'Compare'}
            </button>
            <button
              class="ghost tiny"
              disabled={!loopback}
              title={loopback ? 'Delete this take' : 'Only on the piano machine'}
              onclick={() => ondelete(take.id)}>×</button
            >
          </div>
          {#if compare.length < 2 || compare.includes(take.id)}
            <RecordingPlayer recording={take} onLoop={(loop) => onloop(take.id, loop)} />
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .takes {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 0;
    margin: 0.5rem 0 0;
  }

  .takes li {
    border-top: 1px solid var(--line, #2a2a2a);
    padding-top: 0.6rem;
  }

  .takes li:first-child {
    border-top: none;
  }

  .small {
    font-size: 0.82rem;
  }
</style>
