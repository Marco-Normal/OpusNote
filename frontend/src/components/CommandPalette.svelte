<script lang="ts">
  /**
   * One box over the whole app.
   *
   * It composes searches that already exist — the library (which also matches journal
   * prose) and the journal feed — plus the recent sittings list, which has no search
   * endpoint and is therefore filtered here over the most recent fifty. That is stated
   * rather than hidden: a palette that silently searched only part of the app would be a
   * worse answer than one that says what it searched.
   *
   * It is also the first overlay in the app, so it owns the three things an overlay owes:
   * Escape closes it, a backdrop click closes it, and focus starts in the box. It does not
   * trap focus: the app has no other overlay and a partial trap is worse than none.
   */
  import { api } from '../lib/api';
  import type { JournalEntry, PieceSummary, SittingSummary } from '../lib/types';
  import type { Route } from '../lib/route';

  interface Props {
    onclose: () => void;
    onnavigate: (route: Route) => void;
  }

  let { onclose, onnavigate }: Props = $props();

  let query = $state('');
  let pieces = $state<PieceSummary[]>([]);
  let entries = $state<JournalEntry[]>([]);
  let sittings = $state<SittingSummary[]>([]);
  let input = $state<HTMLInputElement | null>(null);
  let searching = $state(false);

  $effect(() => {
    input?.focus();
  });

  $effect(() => {
    const text = query.trim();
    // A one-frame debounce: typing "chopin" is seven requests without it, and the two
    // searches are cheap but not free.
    const handle = setTimeout(() => void search(text), 120);
    return () => clearTimeout(handle);
  });

  async function search(text: string): Promise<void> {
    searching = true;
    try {
      if (text.length === 0) {
        pieces = [];
        entries = [];
        sittings = [];
        return;
      }
      const [found, written, recent] = await Promise.all([
        api.repertoire.pieces({ search: text }),
        api.repertoire.journal({ search: text, limit: 10 }),
        api.practice.sittings(50),
      ]);
      pieces = found.slice(0, 8);
      entries = written.slice(0, 5);
      sittings = recent.filter((sitting) => sitting.local_date.includes(text)).slice(0, 5);
    } finally {
      searching = false;
    }
  }

  function onkeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      onclose();
    }
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="backdrop"
  role="presentation"
  onclick={(event) => {
    // Only the backdrop itself closes: a click inside the panel bubbles here, and
    // comparing the target avoids needing a second handler on the panel.
    if (event.target === event.currentTarget) onclose();
  }}
>
  <div
    class="card palette"
    data-palette
    role="dialog"
    aria-modal="true"
    aria-label="Search the library and the log"
  >
    <input
      bind:this={input}
      bind:value={query}
      class="query"
      type="search"
      placeholder="Piece, journal word, or a date in a sitting…"
      aria-label="Search"
      onkeydown={onkeydown}
    />

    {#if searching}
      <p class="muted small">Searching…</p>
    {/if}

    {#if pieces.length > 0}
      <h4>Library</h4>
      <ul>
        {#each pieces as piece (piece.id)}
          <li>
            <button
              onclick={() =>
                onnavigate({ name: 'repertoire', entity: { kind: 'piece', id: piece.id } })}
            >
              {piece.title}{piece.composer_name ? ` · ${piece.composer_name}` : ''}
            </button>
          </li>
        {/each}
      </ul>
    {/if}

    {#if entries.length > 0}
      <h4>Journal</h4>
      <ul>
        {#each entries as entry (entry.id)}
          <li>
            <button
              onclick={() =>
                onnavigate({
                  name: 'repertoire',
                  entity: { kind: 'piece', id: entry.piece_id },
                })}
            >
              {entry.entry_date} · {entry.content.slice(0, 60)}
            </button>
          </li>
        {/each}
      </ul>
    {/if}

    {#if sittings.length > 0}
      <h4>Sittings</h4>
      <ul>
        {#each sittings as sitting (sitting.id)}
          <li>
            <button
              onclick={() => onnavigate({ name: 'log', entity: { kind: 'sitting', id: sitting.id } })}
            >
              {sitting.local_date} · {Math.round(sitting.duration_s / 60)} min · {sitting.note_count} notes
            </button>
          </li>
        {/each}
      </ul>
    {/if}

    {#if query.trim().length > 0 && !searching && pieces.length + entries.length + sittings.length === 0}
      <p class="muted small">Nothing found. Sittings are searched by date over the most recent fifty.</p>
    {/if}
  </div>
</div>
