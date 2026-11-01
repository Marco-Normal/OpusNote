<script lang="ts">
  /**
   * The library filter bar, sorting, bulk actions, and scrollable piece list.
   *
   * Extracted from RepertoireView so view state and piece list virtualization
   * are self-contained and don't inflate the library view.
   */
  import type { Composer, PiecePractice, PieceSummary } from '../lib/types';

  type Grouping = 'none' | 'composer' | 'difficulty';
  const VIEW_STORAGE_KEY = 'srt.repertoire.view';
  const SORT_KEYS = ['title', 'composer', 'last_played', 'least_time', 'most_time'] as const;
  type SortKey = (typeof SORT_KEYS)[number];
  const GROUPINGS = ['none', 'composer', 'difficulty'] as const;

  function readView(): { status: string; composer: string; grouping: Grouping; sort: SortKey } {
    const fallback = {
      status: '',
      composer: '',
      grouping: 'composer' as Grouping,
      sort: 'title' as SortKey,
    };
    try {
      const raw = localStorage.getItem(VIEW_STORAGE_KEY);
      if (!raw) return fallback;
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      return {
        status: typeof parsed.status === 'string' ? parsed.status : '',
        composer: typeof parsed.composer === 'string' ? parsed.composer : '',
        grouping: (GROUPINGS as readonly string[]).includes(parsed.grouping as string)
          ? (parsed.grouping as Grouping)
          : 'composer',
        sort: (SORT_KEYS as readonly string[]).includes(parsed.sort as string)
          ? (parsed.sort as SortKey)
          : 'title',
      };
    } catch {
      return fallback;
    }
  }

  interface Props {
    pieces: PieceSummary[];
    composers: Composer[];
    practiceByPiece: PiecePractice[];
    selectedPieceId: number | null;
    busy: boolean;
    onSelectPiece: (id: number) => void;
    onNewPiece: () => void;
    onBulkUpdate: (selectedIds: number[], status: 'active' | 'paused' | 'completed') => Promise<void>;
  }

  let {
    pieces,
    composers,
    practiceByPiece,
    selectedPieceId,
    busy,
    onSelectPiece,
    onNewPiece,
    onBulkUpdate,
  }: Props = $props();

  const savedView = readView();
  let search = $state('');
  let statusFilter = $state(savedView.status);
  let composerFilter = $state(savedView.composer);
  let grouping = $state<Grouping>(savedView.grouping);
  let sort = $state<SortKey>(savedView.sort);

  let selected = $state<Set<number>>(new Set());
  let bulkStatus = $state<'active' | 'paused' | 'completed'>('active');

  const practiceIndex = $derived(new Map(practiceByPiece.map((row) => [row.piece_id, row])));

  function sorted(rows: PieceSummary[]): PieceSummary[] {
    const copy = [...rows];
    if (sort === 'title') return copy.sort((a, b) => a.title.localeCompare(b.title));
    if (sort === 'composer') {
      return copy.sort((a, b) => (a.composer_name ?? '').localeCompare(b.composer_name ?? ''));
    }
    if (sort === 'last_played') {
      return copy.sort((a, b) => {
        const left = practiceIndex.get(a.id)?.last_played ?? '';
        const right = practiceIndex.get(b.id)?.last_played ?? '';
        return left === right ? a.title.localeCompare(b.title) : left.localeCompare(right);
      });
    }
    const minutes = (id: number) => practiceIndex.get(id)?.minutes ?? 0;
    return copy.sort((a, b) =>
      sort === 'least_time'
        ? minutes(a.id) - minutes(b.id) || a.title.localeCompare(b.title)
        : minutes(b.id) - minutes(a.id) || a.title.localeCompare(b.title),
    );
  }

  const visible = $derived(
    pieces.filter((piece) => {
      if (statusFilter && piece.status !== statusFilter) return false;
      if (composerFilter && String(piece.composer_id ?? '') !== composerFilter) return false;
      if (search) {
        const needle = search.trim().toLowerCase();
        const haystack = `${piece.title} ${piece.composer_name ?? ''} ${piece.opus ?? ''}`.toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    }),
  );

  const groups = $derived.by(() => {
    if (grouping === 'none') return [{ label: '', rows: sorted(visible) }];
    const buckets = new Map<string, PieceSummary[]>();
    for (const piece of visible) {
      const label =
        grouping === 'composer'
          ? (piece.composer_name ?? 'Unknown composer')
          : (piece.difficulty ?? 'Unclassified');
      const bucket = buckets.get(label);
      if (bucket) bucket.push(piece);
      else buckets.set(label, [piece]);
    }
    return [...buckets.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([label, rows]) => ({ label, rows: sorted(rows) }));
  });

  $effect(() => {
    try {
      localStorage.setItem(
        VIEW_STORAGE_KEY,
        JSON.stringify({ status: statusFilter, composer: composerFilter, grouping, sort }),
      );
    } catch {
      // Storage unavailable
    }
  });

  async function handleApplyBulk(): Promise<void> {
    const ids = Array.from(selected);
    await onBulkUpdate(ids, bulkStatus);
    selected = new Set();
  }
</script>

<div class="filters">
  <input
    type="search"
    placeholder="Search title, composer or opus…"
    bind:value={search}
    aria-label="Search the library"
  />
  <select bind:value={statusFilter} aria-label="Filter by status">
    <option value="">Any status</option>
    <option value="active">Active</option>
    <option value="completed">Completed</option>
    <option value="paused">Paused</option>
  </select>
  <select bind:value={composerFilter} aria-label="Filter by composer">
    <option value="">Any composer</option>
    {#each composers as composer (composer.id)}
      <option value={String(composer.id)}>{composer.name}</option>
    {/each}
  </select>
  <select bind:value={grouping} aria-label="Group by">
    <option value="composer">Group by composer</option>
    <option value="difficulty">Group by difficulty</option>
    <option value="none">No grouping</option>
  </select>
  <select bind:value={sort} aria-label="Sort the library">
    <option value="title">Title</option>
    <option value="composer">Composer</option>
    <option value="last_played">Last played</option>
    <option value="least_time">Least time invested</option>
    <option value="most_time">Most time invested</option>
  </select>
  <span class="muted small">{visible.length} shown</span>
  <button class="primary" onclick={onNewPiece}>New piece</button>
</div>

{#if selected.size > 0}
  <div class="row wrap" data-bulk={selected.size}>
    <span class="muted small">{selected.size} selected</span>
    <select bind:value={bulkStatus} aria-label="Status for the selected pieces">
      <option value="active">Active</option>
      <option value="paused">Paused</option>
      <option value="completed">Completed</option>
    </select>
    <button class="primary" disabled={busy} onclick={() => void handleApplyBulk()}>Set status</button>
    <button class="ghost" onclick={() => (selected = new Set())}>Clear</button>
  </div>
{/if}

<div class="list">
  {#each groups as group (group.label)}
    {#if group.label}
      <h4 class="group">{group.label}</h4>
    {/if}
    {#each group.rows as piece (piece.id)}
      <div class="piece-line">
        <input
          type="checkbox"
          checked={selected.has(piece.id)}
          aria-label={`Select ${piece.title}`}
          onclick={() => {
            const next = new Set(selected);
            if (next.has(piece.id)) next.delete(piece.id);
            else next.add(piece.id);
            selected = next;
          }}
        />
        <button
          class="row-piece"
          class:selected={selectedPieceId === piece.id}
          aria-expanded={selectedPieceId === piece.id}
          onclick={() => onSelectPiece(piece.id)}
        >
          <span class="title">
            {piece.title}
            {#if piece.opus}<span class="muted opus">{piece.opus}</span>{/if}
          </span>
          <span class="meta">
            {#if piece.key}<span class="tag">{piece.key}</span>{/if}
            {#if piece.difficulty}<span class="tag">{piece.difficulty}</span>{/if}
            <span class="tag" class:done={piece.status === 'completed'}>{piece.status}</span>
          </span>
          <span class="counts muted mono">
            {#if piece.journal_entries}✎ {piece.journal_entries}{/if}
            {#if piece.recording_count}♪ {piece.recording_count}{/if}
            {#if piece.score_count}𝄞 {piece.score_count}{/if}
          </span>
        </button>
      </div>
    {/each}
  {/each}

  {#if visible.length === 0}
    <p class="muted small">Nothing matches those filters.</p>
  {/if}
</div>

<style>
  .filters {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    align-items: center;
    border: 1px solid var(--line);
    background: var(--surface-2);
    border-radius: var(--radius);
    padding: 0.5rem 0.6rem;
  }

  .filters input[type='search'] {
    font: inherit;
    flex: 1 1 14rem;
    min-width: 10rem;
    padding: 0.4rem 0.55rem;
    border-radius: 8px;
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--ink);
  }

  .list {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    max-height: 34rem;
    overflow-y: auto;
  }

  .group {
    margin: 0.6rem 0 0.2rem;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
  }

  .piece-line {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .piece-line .row-piece {
    flex: 1;
    min-width: 0;
  }

  .row-piece {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto;
    gap: 0.5rem;
    align-items: center;
    text-align: left;
    padding: 0.45rem 0.55rem;
    border-radius: 8px;
    border: 1px solid transparent;
    background: var(--surface-2);
  }

  .row-piece:hover {
    border-color: var(--line);
  }

  .row-piece.selected {
    background: var(--accent-soft);
    border-color: var(--accent-line);
  }

  .title {
    font-weight: 600;
    font-size: 0.9rem;
  }

  .opus {
    font-weight: 400;
    font-size: 0.82rem;
    margin-left: 0.3rem;
  }

  .meta {
    display: flex;
    gap: 0.25rem;
    align-items: center;
  }

  .tag {
    font-size: 0.75rem;
    padding: 0.15rem 0.4rem;
    border-radius: 999px;
    background: var(--surface);
    border: 1px solid var(--line);
    color: var(--muted);
  }

  .tag.done {
    color: var(--good);
    border-color: var(--good-line);
  }

  .counts {
    font-size: 0.78rem;
    display: flex;
    gap: 0.4rem;
  }
</style>
