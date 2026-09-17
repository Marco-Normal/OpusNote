<script lang="ts">
  /**
   * The stretches of a piece worth returning to.
   *
   * The app cannot see a score — there is no alignment, by decision 20-D7 — so the bar
   * numbers are the player's own and *nothing here is inferred*. "Worked on it" is a button,
   * not a detection, and a passage seeded from a recording's A/B loop records which loop it
   * came from while the bars are still typed.
   */
  import type { Passage, Recording } from '../lib/types';

  interface Props {
    passages: Passage[];
    recordings: Recording[];
    busy: boolean;
    oncreate: (body: {
      start_bar: number;
      end_bar: number;
      label: string | null;
      source: 'manual' | 'loop';
      media_id: number | null;
    }) => void;
    onworked: (passageId: number) => void;
    ondelete: (passageId: number) => void;
  }

  let { passages, recordings, busy, oncreate, onworked, ondelete }: Props = $props();

  let startBar = $state(1);
  let endBar = $state(4);
  let label = $state('');
  /** Which recording's loop seeded this, or none. */
  let mediaId = $state<number | null>(null);
  let confirmingId = $state<number | null>(null);

  const looped = $derived(recordings.filter((row) => row.loop_start_s !== null));

  function submit(): void {
    if (endBar < startBar) return;
    oncreate({
      start_bar: startBar,
      end_bar: endBar,
      label: label.trim() || null,
      // The provenance is recorded, never guessed: an empty choice means the player typed
      // the bars themselves.
      source: mediaId === null ? 'manual' : 'loop',
      media_id: mediaId,
    });
    label = '';
    mediaId = null;
  }

  function staleness(passage: Passage): string {
    if (passage.last_worked_on === null) return 'not worked on yet';
    return `last worked on ${passage.last_worked_on}`;
  }
</script>

<section class="card" data-passages={passages.length}>
  <h3>Passages to work on</h3>
  {#if passages.length === 0}
    <p class="muted small">
      Nothing marked. A passage is a bar range you want to come back to — the app cannot find
      them for you, because it cannot see your score.
    </p>
  {:else}
    <ul class="passages">
      {#each passages as passage (passage.id)}
        <li data-passage={passage.id}>
          <span class="mono">bars {passage.start_bar}–{passage.end_bar}</span>
          {#if passage.label}<span>{passage.label}</span>{/if}
          <span class="muted small">{staleness(passage)}</span>
          {#if passage.source === 'loop'}
            <span class="pill" title="Seeded from a recording's A/B markers" data-passage-source="loop">
              from a loop
            </span>
          {/if}
          <button class="ghost tiny" disabled={busy} onclick={() => onworked(passage.id)}>
            Worked on it
          </button>
          {#if confirmingId === passage.id}
            <button class="danger tiny" disabled={busy} onclick={() => ondelete(passage.id)}>
              Confirm delete
            </button>
            <button class="ghost tiny" onclick={() => (confirmingId = null)}>Cancel</button>
          {:else}
            <button class="ghost tiny" onclick={() => (confirmingId = passage.id)}>Delete</button>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}

  <div class="row wrap">
    <label class="muted small" for="passage-start">Bars</label>
    <input id="passage-start" type="number" min="1" bind:value={startBar} aria-label="First bar" />
    <span class="muted small">to</span>
    <input type="number" min="1" bind:value={endBar} aria-label="Last bar" />
    <input type="text" bind:value={label} placeholder="what is hard about it" aria-label="Note" />
    {#if looped.length > 0}
      <select bind:value={mediaId} aria-label="Seeded from a recording">
        <option value={null}>not from a recording</option>
        {#each looped as recording (recording.id)}
          <option value={recording.id}>
            {recording.title ?? recording.original_name ?? `recording ${recording.id}`} · loop
          </option>
        {/each}
      </select>
    {/if}
    <button class="primary" disabled={busy || endBar < startBar} onclick={submit}>
      Add passage
    </button>
  </div>
</section>

<style>
  .passages {
    list-style: none;
    margin: 0 0 0.6rem;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }

  .passages li {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
</style>
