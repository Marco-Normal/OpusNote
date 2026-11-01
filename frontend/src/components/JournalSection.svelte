<script lang="ts">
  /**
   * The journal views:
   * 1. When a piece is open, shows its journal history and the entry composer form.
   * 2. When no piece is selected, shows the cross-library journal feed with tag filtering and search.
   */
  import { app } from '../lib/state.svelte';
  import { pieceLabel } from '../lib/pieceLabel';
  import type { JournalEntry, PieceDetail } from '../lib/types';

  interface Props {
    detail: PieceDetail | null;
    feedEntries: JournalEntry[];
    feedTag: string;
    feedSearch: string;
    savingJournal: boolean;
    journalSitting: number | null;
    journalMeasured: string | null;
    journalTake: number | null;
    onOpenPiece: (pieceId: number) => void;
    onAddJournalEntry: (entry: {
      entry_date: string;
      content: string;
      practice_minutes: number | null;
      sitting_id: number | null;
      tags: string[];
      difficulty: number | null;
      fluency: number | null;
      media_id: number | null;
    }) => Promise<void>;
    onSaveJournalEntry: (
      entry: JournalEntry,
      editData: {
        entry_date: string;
        content: string;
        practice_minutes: number | null;
        tags: string[];
        difficulty: number | null;
        fluency: number | null;
      },
    ) => Promise<void>;
    onRemoveJournalEntry: (entry: JournalEntry) => Promise<void>;
    onClearSittingDraft: () => void;
    onClearTakeDraft: () => void;
  }

  let {
    detail,
    feedEntries,
    feedTag = $bindable(''),
    feedSearch = $bindable(''),
    savingJournal,
    journalSitting,
    journalMeasured,
    journalTake,
    onOpenPiece,
    onAddJournalEntry,
    onSaveJournalEntry,
    onRemoveJournalEntry,
    onClearSittingDraft,
    onClearTakeDraft,
  }: Props = $props();

  function localDate(): string {
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
    return local.toISOString().slice(0, 10);
  }

  function parseTags(value: string): string[] {
    return value
      .split(',')
      .map((tag) => tag.trim())
      .filter((tag) => tag.length > 0);
  }

  // Add form fields
  let journalDate = $state(localDate());
  let journalContent = $state('');
  let journalMinutes = $state<number | null>(null);
  let journalTags = $state('');
  let journalDifficulty = $state<number | null>(null);
  let journalFluency = $state<number | null>(null);
  let journalForm = $state<HTMLElement | null>(null);

  // Edit fields
  let editingEntry = $state<number | null>(null);
  let editDate = $state('');
  let editMinutes = $state<number | null>(null);
  let editContent = $state('');
  let editTags = $state('');
  let editDifficulty = $state<number | null>(null);
  let editFluency = $state<number | null>(null);

  export function scrollFormIntoView(): void {
    journalDate = localDate();
    journalForm?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function startEditing(entry: JournalEntry): void {
    editingEntry = entry.id;
    editDate = entry.entry_date;
    editMinutes = entry.practice_minutes;
    editContent = entry.content;
    editTags = entry.tags.join(', ');
    editDifficulty = entry.difficulty;
    editFluency = entry.fluency;
  }

  function cancelEditing(): void {
    editingEntry = null;
    editContent = '';
  }

  async function handleAddEntry(): Promise<void> {
    if (!journalContent.trim()) return;
    await onAddJournalEntry({
      entry_date: journalDate,
      content: journalContent.trim(),
      practice_minutes: journalMinutes,
      sitting_id: journalSitting,
      tags: parseTags(journalTags),
      difficulty: journalDifficulty,
      fluency: journalFluency,
      media_id: journalTake,
    });
    journalContent = '';
    journalMinutes = null;
    journalTags = '';
    journalDifficulty = null;
    journalFluency = null;
  }

  async function handleSaveEdit(entry: JournalEntry): Promise<void> {
    if (!editContent.trim()) return;
    await onSaveJournalEntry(entry, {
      entry_date: editDate,
      content: editContent.trim(),
      practice_minutes: editMinutes,
      tags: parseTags(editTags),
      difficulty: editDifficulty,
      fluency: editFluency,
    });
    editingEntry = null;
    editContent = '';
  }
</script>

{#snippet entryMeta(entry: JournalEntry)}
  {#each entry.tags as tag (tag)}
    <button
      class="pill"
      data-tag={tag}
      title="Filter the journal by this tag"
      onclick={() => (feedTag = tag)}>{tag}</button
    >
  {/each}
  {#if entry.difficulty !== null}
    <span class="pill mono" data-difficulty={entry.difficulty}>hard {entry.difficulty}/5</span>
  {/if}
  {#if entry.fluency !== null}
    <span class="pill mono" data-fluency={entry.fluency}>went {entry.fluency}/5</span>
  {/if}
  {#if entry.media_id !== null}
    <span class="pill" data-journal-take={entry.media_id}>written about a take</span>
  {/if}
{/snippet}

{#if detail}
  <h4>Journal <span class="muted">({detail.journal.length})</span></h4>
  {#if detail.journal.length === 0}
    <p class="muted small">No entries yet.</p>
  {:else}
    <ul class="journal">
      {#each detail.journal as entry (entry.id)}
        <li data-journal-entry={entry.id}>
          <div class="entry-head">
            <span>
              <span class="date mono">{entry.entry_date}</span>
              {#if entry.practice_minutes}
                <span class="pill">{entry.practice_minutes} min</span>
              {/if}
              {#if entry.sitting_id}
                <span
                  class="muted small"
                  title="Written about the sitting you played, from the Log tab"
                  >about a logged session</span
                >
              {/if}
              {@render entryMeta(entry)}
            </span>
            <span class="row">
              {#if editingEntry === entry.id}
                <button
                  class="ghost tiny"
                  disabled={savingJournal || !editContent.trim()}
                  onclick={() => void handleSaveEdit(entry)}>Save entry</button
                >
                <button class="ghost tiny" onclick={cancelEditing}>Discard</button>
              {:else}
                <button
                  class="ghost tiny"
                  data-journal-edit={entry.id}
                  onclick={() => startEditing(entry)}>Edit entry</button
                >
                <button
                  class="ghost tiny"
                  disabled={!app.host?.loopback}
                  title={app.host?.loopback
                    ? 'Delete this entry'
                    : 'Only on the piano machine'}
                  onclick={() => void onRemoveJournalEntry(entry)}>×</button
                >
              {/if}
            </span>
          </div>
          {#if editingEntry === entry.id}
            <div class="journal-edit">
              <input type="date" bind:value={editDate} aria-label="Edit entry date" />
              <input
                type="number"
                min="0"
                max="1440"
                placeholder="min"
                bind:value={editMinutes}
                aria-label="Edit practice minutes"
              />
              <input
                type="text"
                bind:value={editTags}
                placeholder="tags, comma separated"
                aria-label="Edit tags"
              />
              <select bind:value={editDifficulty} aria-label="Edit how hard it felt">
                <option value={null}>difficulty —</option>
                {#each [1, 2, 3, 4, 5] as value (value)}
                  <option value={value}>{value}</option>
                {/each}
              </select>
              <select bind:value={editFluency} aria-label="Edit how well it went">
                <option value={null}>fluency —</option>
                {#each [1, 2, 3, 4, 5] as value (value)}
                  <option value={value}>{value}</option>
                {/each}
              </select>
              <textarea
                rows="4"
                bind:value={editContent}
                aria-label="Edit journal entry"
              ></textarea>
            </div>
          {:else}
            <p class="entry-body">{entry.content}</p>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}

  <form
    class="journal-form"
    bind:this={journalForm}
    onsubmit={(event) => {
      event.preventDefault();
      void handleAddEntry();
    }}
  >
    {#if journalSitting !== null}
      <p class="muted small measured" data-journal-sitting={journalSitting}>
        About the session you just played{#if journalMeasured}: {journalMeasured}{/if}.
        <button
          type="button"
          class="ghost tiny"
          onclick={onClearSittingDraft}>Write about the piece instead</button
        >
      </p>
    {/if}
    <div class="row">
      <input type="date" bind:value={journalDate} aria-label="Entry date" required />
      <input
        type="number"
        min="0"
        max="1440"
        placeholder="min"
        bind:value={journalMinutes}
        aria-label="Practice minutes"
      />
    </div>
    <div class="row">
      <input
        type="text"
        bind:value={journalTags}
        placeholder="tags, comma separated"
        aria-label="Tags for this entry"
      />
      <select bind:value={journalDifficulty} aria-label="How hard it felt">
        <option value={null}>difficulty —</option>
        {#each [1, 2, 3, 4, 5] as value (value)}
          <option value={value}>{value}</option>
        {/each}
      </select>
      <select bind:value={journalFluency} aria-label="How well it went">
        <option value={null}>fluency —</option>
        {#each [1, 2, 3, 4, 5] as value (value)}
          <option value={value}>{value}</option>
        {/each}
      </select>
    </div>
    {#if journalTake !== null}
      <p class="muted small" data-journal-take-draft={journalTake}>
        About take {journalTake}.
        <button type="button" class="ghost tiny" onclick={onClearTakeDraft}>
          Not about a take
        </button>
      </p>
    {/if}
    <textarea
      rows="3"
      placeholder="What happened in this session?"
      bind:value={journalContent}
      aria-label="Journal entry"
      required
    ></textarea>
    <button
      type="submit"
      data-journal-add
      disabled={savingJournal || !journalContent.trim()}
    >
      {savingJournal ? '…' : 'Add'}
    </button>
  </form>
{:else}
  <div class="detail card" data-journal-feed>
    <h3>Recent notes</h3>
    <p class="muted small">
      The newest journal entries across the library. Pick a piece to read or add its
      own.
    </p>
    <input
      type="search"
      placeholder="Search the journal…"
      bind:value={feedSearch}
      aria-label="Search the journal"
    />
    <input
      type="text"
      bind:value={feedTag}
      placeholder="tag"
      aria-label="Filter the journal by tag"
    />
    {#if feedEntries.length === 0}
      <p class="muted small">
        {feedSearch ? 'No entries mention that.' : 'Nothing written down yet.'}
      </p>
    {:else}
      <ul class="journal feed">
        {#each feedEntries as entry (entry.id)}
          <li data-feed-entry={entry.id}>
            <div class="entry-head">
              <span>
                <span class="date mono">{entry.entry_date}</span>
                <button class="ghost tiny piece-link" onclick={() => void onOpenPiece(entry.piece_id)}>
                  {entry.piece_title
                    ? pieceLabel({
                        title: entry.piece_title,
                        composer_name: entry.composer_name,
                        opus: entry.piece_opus,
                      })
                    : 'this piece'}
                </button>
              </span>
              {#if entry.practice_minutes}
                <span class="pill">{entry.practice_minutes} min</span>
              {/if}
              {@render entryMeta(entry)}
            </div>
            <p class="entry-body">{entry.content}</p>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}

<style>
  .detail {
    padding: 0.9rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
  }

  .entry-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.4rem;
  }

  .entry-body {
    white-space: pre-wrap;
    margin: 0.25rem 0 0;
  }

  .piece-link {
    padding: 0 0.2rem;
    font-size: 0.78rem;
    color: var(--accent);
  }

  .journal-form {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    align-items: stretch;
    margin-top: 0.35rem;
  }

  .journal-form .row,
  .journal-edit {
    display: flex;
    gap: 0.3rem;
    align-items: center;
  }

  .journal-edit {
    flex-wrap: wrap;
    margin-top: 0.3rem;
  }

  .journal-edit textarea {
    flex: 1 1 100%;
  }

  .measured {
    margin: 0;
  }

  .journal-form input,
  .journal-form textarea,
  .journal-edit input,
  .journal-edit textarea {
    font: inherit;
    font-size: 0.84rem;
    padding: 0.3rem 0.4rem;
    border-radius: 7px;
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--ink);
    min-width: 0;
  }

  .journal-form textarea,
  .journal-edit textarea {
    resize: vertical;
    line-height: 1.4;
  }

  .journal {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .journal li {
    border-left: 2px solid var(--line);
    padding-left: 0.6rem;
  }

  .date {
    font-size: 0.78rem;
    color: var(--muted);
    margin-right: 0.3rem;
  }

  h4 {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
    margin: 0.5rem 0 0.1rem;
  }
</style>
