<script lang="ts">
  /**
   * Export and restore.
   *
   * One JSON file holds every table. Recordings are not inside it — 138 MB of
   * Opus has no business in a JSON document — so the panel says so rather than
   * letting someone discover it after a machine move.
   *
   * Restoring in `replace` mode discards everything here, so it takes two clicks
   * and an explicit sentence, the same shape as deleting a piece.
   */
  import { api } from '../lib/api';

  interface Props {
    onrestored: () => void;
  }

  let { onrestored }: Props = $props();

  let file = $state<File | null>(null);
  let fileInput = $state<HTMLInputElement | undefined>(undefined);
  let mode = $state<'merge' | 'replace'>('merge');
  let confirming = $state(false);
  let busy = $state(false);
  let note = $state<string | null>(null);
  let error = $state<string | null>(null);

  async function run(): Promise<void> {
    if (!file) return;
    busy = true;
    error = null;
    note = null;
    try {
      const parsed = JSON.parse(await file.text());
      const result = await api.backup.import(parsed, mode, mode === 'replace');
      note =
        mode === 'replace'
          ? `Restored ${result.total} rows.`
          : `Read ${result.total} new rows; everything already here was kept.`;
      onrestored();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = false;
      confirming = false;
      file = null;
      // Same file twice fires no change event, so the input is cleared.
      if (fileInput) fileInput.value = '';
    }
  }

  function choose(): void {
    if (mode === 'replace') confirming = true;
    else void run();
  }
</script>

<section class="card backup">
  <h3>Export &amp; backup</h3>
  <p class="muted small">
    Everything — the library, the journal, practice sittings, note events, workouts
    and ratings — in one JSON file. Recording <em>files</em> are not inside it: copy
    the media directory alongside it to keep playback.
  </p>

  <div class="row wrap">
    <a class="download" href={api.backup.exportUrl} download="piano-ecosystem-backup.json">
      Download backup
    </a>
    <span class="muted small">Restoring is safe to try: the default only adds what is missing.</span>
  </div>

  <div class="row wrap">
    <input
      type="file"
      accept="application/json,.json"
      aria-label="Backup file"
      bind:this={fileInput}
      onchange={(event) => {
        file = (event.currentTarget as HTMLInputElement).files?.[0] ?? null;
        note = null;
        error = null;
      }}
    />
    <label class="row mode">
      <span class="muted small">Restore mode</span>
      <select bind:value={mode} aria-label="Restore mode">
        <option value="merge">Add what is missing</option>
        <option value="replace">Replace everything</option>
      </select>
    </label>

    {#if confirming}
      <button class="danger" disabled={busy} onclick={() => void run()}>
        {busy ? 'Restoring…' : 'Replace everything for good'}
      </button>
      <button class="ghost" onclick={() => (confirming = false)}>Cancel</button>
    {:else}
      <button disabled={!file || busy} onclick={choose}>
        {busy ? 'Restoring…' : 'Restore backup'}
      </button>
    {/if}
  </div>

  {#if confirming}
    <div class="notice">
      Replace mode empties every table first. Anything recorded since the backup
      was taken is gone.
    </div>
  {/if}
  {#if note}
    <p class="muted small">{note}</p>
  {/if}
  {#if error}
    <div class="error-banner">{error}</div>
  {/if}
</section>

<style>
  .backup {
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    padding: 0.75rem 0.9rem;
  }

  h3 {
    font-size: 1rem;
  }

  .download {
    display: inline-flex;
    align-items: center;
    padding: 0.4rem 0.7rem;
    border-radius: 8px;
    border: 1px solid var(--accent-line);
    background: var(--accent-soft);
    color: var(--accent);
    text-decoration: none;
    font-size: 0.86rem;
    font-weight: 600;
  }

  .mode {
    gap: 0.35rem;
  }

  .notice {
    font-size: 0.84rem;
    padding: 0.5rem 0.6rem;
    border-radius: 8px;
    background: var(--warn-soft);
    border: 1px solid var(--warn-line);
    color: var(--warn);
  }

  .small {
    font-size: 0.8rem;
  }
</style>
