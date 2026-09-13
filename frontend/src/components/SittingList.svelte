<script lang="ts">
  /**
   * Recent sittings.
   *
   * A sitting is an emergent stretch at the piano, so the list leads with when it
   * started and how long it lasted — the two things you cannot get from a note
   * count.
   */
  import { type SittingSummary } from '../lib/types';
  import { formatClock } from '../lib/clock';

  interface Props {
    sittings: SittingSummary[];
    selectedId: number | null;
    onselect: (id: number) => void;
  }

  let { sittings, selectedId, onselect }: Props = $props();

  function when(value: string): string {
    // Stored as UTC text; the browser turns it into the player's wall clock.
    const parsed = new Date(`${value.replace(' ', 'T')}Z`);
    return Number.isNaN(parsed.getTime())
      ? value
      : parsed.toLocaleString(undefined, {
          weekday: 'short',
          day: 'numeric',
          month: 'short',
          hour: '2-digit',
          minute: '2-digit',
        });
  }

  function sourceLabel(source: string): string {
    return source === 'sight_reading' ? 'sight-reading' : 'piano';
  }
</script>

{#if sittings.length === 0}
  <p class="muted empty">
    Nothing logged yet. Play something — capture files it automatically.
  </p>
{:else}
  <ul class="list" data-sittings={sittings.length}>
    {#each sittings as sitting (sitting.id)}
      <li>
        <button
          class="row-button"
          data-sitting={sitting.id}
          class:active={sitting.id === selectedId}
          aria-pressed={sitting.id === selectedId}
          onclick={() => onselect(sitting.id)}
        >
          <span class="when">{when(sitting.started_at)}</span>
          <span class="row wrap">
            <span class="pill mono">{formatClock(sitting.duration_s)}</span>
            <span class="muted small">{sitting.note_count} notes</span>
            {#if sitting.segment_count > 0}
              <span class="muted small">{sitting.segment_count} segments</span>
            {/if}
            <span class="pill" class:accent={sitting.source === 'sight_reading'}>
              {sourceLabel(sitting.source)}
            </span>
          </span>
        </button>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    max-height: 22rem;
    overflow-y: auto;
  }

  .row-button {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.25rem;
    width: 100%;
    text-align: left;
    padding: 0.45rem 0.6rem;
    border-radius: 8px;
    border: 1px solid transparent;
    background: transparent;
    color: inherit;
    cursor: pointer;
  }

  .row-button:hover {
    background: var(--scrim);
  }

  .row-button.active {
    background: var(--accent-soft);
    border-color: var(--accent-line);
  }

  .when {
    font-size: 0.88rem;
  }

  .small {
    font-size: 0.78rem;
  }

  .empty {
    margin: 0;
    font-size: 0.85rem;
  }
</style>
