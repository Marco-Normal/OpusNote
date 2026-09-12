<script lang="ts">
  /**
   * Create or edit a piece.
   *
   * One component for both, because the fields are identical; the difference is
   * only whether `piece` is null. It emits the fields that actually changed on
   * edit, so the PATCH stays a genuine partial update.
   */
  import { api } from '../lib/api';
  import type { Composer, PieceDetail, PieceInput } from '../lib/types';

  interface Props {
    piece?: PieceDetail | null;
    composers: Composer[];
    onSaved: (piece: PieceDetail) => void;
    onCancel: () => void;
  }

  let { piece = null, composers, onSaved, onCancel }: Props = $props();

  const NEW_COMPOSER = '__new__';

  // Seeded once from the piece being edited. The parent mounts a fresh editor
  // for each piece (and keys on it), so this is deliberately a snapshot rather
  // than a live binding — hence the suppression.
  // svelte-ignore state_referenced_locally
  let form = $state({
    title: piece?.title ?? '',
    composerChoice: piece?.composer_id ? String(piece.composer_id) : '',
    newComposerName: '',
    opus: piece?.opus ?? '',
    key: piece?.key ?? '',
    difficulty: piece?.difficulty ?? '',
    startedOn: piece?.started_on ?? '',
    status: (piece?.status as 'active' | 'completed' | 'paused') ?? 'active',
    description: piece?.description ?? '',
  });

  let saving = $state(false);
  let error = $state<string | null>(null);

  // Free text with suggestions rather than a closed list: the legacy library has
  // values this app never invented, and refusing them would lose information.
  const DIFFICULTIES = [
    'Beginner',
    'Early Intermediate',
    'Intermediate',
    'Late Intermediate',
    'Advanced',
  ];
  const KEYS = [
    'C Major', 'G Major', 'D Major', 'A Major', 'E Major', 'B Major',
    'F Major', 'Bb Major', 'Eb Major', 'Ab Major', 'Db Major', 'Gb Major',
    'A Minor', 'E Minor', 'B Minor', 'F# Minor', 'C# Minor', 'D Minor',
    'G Minor', 'C Minor', 'F Minor', 'Bb Minor', 'Eb Minor',
  ];

  const isEdit = $derived(piece !== null);

  function buildBody(composerId: string): PieceInput {
    return {
      title: form.title.trim(),
      composer_id: !composerId || composerId === NEW_COMPOSER ? null : Number(composerId),
      opus: form.opus.trim() || null,
      key: form.key.trim() || null,
      difficulty: form.difficulty.trim() || null,
      started_on: form.startedOn || null,
      status: form.status,
      description: form.description.trim() || null,
    };
  }

  /** Fields whose value differs from the piece being edited. */
  function changedFields(body: PieceInput): Partial<PieceInput> {
    if (!piece) return body;
    const before: PieceInput = {
      title: piece.title,
      composer_id: piece.composer_id,
      opus: piece.opus,
      key: piece.key,
      difficulty: piece.difficulty,
      started_on: piece.started_on,
      status: piece.status as 'active' | 'completed' | 'paused',
      description: piece.description,
    };
    const changes: Record<string, unknown> = {};
    for (const [field, value] of Object.entries(body)) {
      if (before[field as keyof PieceInput] !== value) changes[field] = value;
    }
    return changes as Partial<PieceInput>;
  }

  async function save(): Promise<void> {
    error = null;
    if (!form.title.trim()) {
      error = 'A title is required.';
      return;
    }
    saving = true;
    try {
      let composerId = form.composerChoice;
      if (composerId === NEW_COMPOSER) {
        if (!form.newComposerName.trim()) {
          error = 'Give the new composer a name, or pick an existing one.';
          saving = false;
          return;
        }
        const created = await api.repertoire.createComposer({ name: form.newComposerName.trim() });
        composerId = String(created.id);
        // Remember it, so a failed save does not create the composer twice.
        form.composerChoice = composerId;
      }

      const body = buildBody(composerId);

      const saved = piece
        ? await api.repertoire.updatePiece(piece.id, changedFields(body))
        : await api.repertoire.createPiece(body);

      onSaved(saved);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      saving = false;
    }
  }
</script>

<form
  class="editor"
  onsubmit={(event) => {
    event.preventDefault();
    void save();
  }}
>
  <h3>{isEdit ? 'Edit piece' : 'New piece'}</h3>

  {#if error}
    <div class="error-banner">{error}</div>
  {/if}

  <div class="grid">
    <label class="wide">
      <span>Title</span>
      <input bind:value={form.title} required maxlength="200" placeholder="Intermezzo" />
    </label>

    <label>
      <span>Composer</span>
      <select bind:value={form.composerChoice}>
        <option value="">— none —</option>
        {#each composers as composer (composer.id)}
          <option value={String(composer.id)}>{composer.name}</option>
        {/each}
        <option value={NEW_COMPOSER}>+ new composer…</option>
      </select>
    </label>

    {#if form.composerChoice === NEW_COMPOSER}
      <label>
        <span>New composer name</span>
        <input bind:value={form.newComposerName} placeholder="Brahms" />
      </label>
    {/if}

    <label>
      <span>Opus</span>
      <input bind:value={form.opus} placeholder="Op. 118 No. 2" />
    </label>

    <label>
      <span>Key</span>
      <input bind:value={form.key} list="key-options" placeholder="A Major" />
      <datalist id="key-options">
        {#each KEYS as option (option)}<option value={option}></option>{/each}
      </datalist>
    </label>

    <label>
      <span>Difficulty</span>
      <input bind:value={form.difficulty} list="difficulty-options" placeholder="Late Intermediate" />
      <datalist id="difficulty-options">
        {#each DIFFICULTIES as option (option)}<option value={option}></option>{/each}
      </datalist>
    </label>

    <label>
      <span>Started on</span>
      <input type="date" bind:value={form.startedOn} />
    </label>

    <label>
      <span>Status</span>
      <select bind:value={form.status}>
        <option value="active">Active</option>
        <option value="completed">Completed</option>
        <option value="paused">Paused</option>
      </select>
    </label>

    <label class="wide">
      <span>Description</span>
      <textarea bind:value={form.description} rows="3"></textarea>
    </label>
  </div>

  <div class="row">
    <button class="primary" type="submit" disabled={saving}>
      {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Add piece'}
    </button>
    <button type="button" class="ghost" onclick={onCancel} disabled={saving}>Cancel</button>
  </div>
</form>

<style>
  .editor {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    border: 1px solid var(--accent-line);
    background: var(--accent-soft);
    border-radius: var(--radius);
    padding: 0.75rem 0.85rem;
  }

  .editor h3 {
    color: var(--accent);
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
    gap: 0.5rem;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    font-size: 0.78rem;
    color: var(--muted);
  }

  label.wide {
    grid-column: 1 / -1;
  }

  input,
  select,
  textarea {
    font: inherit;
    font-size: 0.88rem;
    padding: 0.35rem 0.45rem;
    border-radius: 7px;
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--ink);
    width: 100%;
  }

  textarea {
    resize: vertical;
  }
</style>
