<script lang="ts">
  import { formatSize, type SystemStatus } from '../lib/types';

  interface Props {
    system: SystemStatus;
  }

  let { system }: Props = $props();

  function backupAge(seconds: number): string {
    const hours = seconds / 3600;
    if (hours < 1) return `${Math.round(seconds / 60)} min ago`;
    if (hours < 48) return `${Math.round(hours)} h ago`;
    return `${Math.round(hours / 24)} days ago`;
  }
</script>

<section class="card health" data-system-status>
  <h3>System</h3>
  <div class="health-grid">
    <div>
      <span class="muted small">Database</span>
      <strong>{(system.database_bytes / 1024 / 1024).toFixed(1)} MB</strong>
      <span class="muted small">
        {system.wal_bytes > 0
          ? `plus ${(system.wal_bytes / 1024).toFixed(0)} KB of WAL`
          : 'checkpointed'}
      </span>
    </div>
    <div>
      <span class="muted small">Recordings</span>
      <strong>{system.media.present} present</strong>
      <span class="muted small">
        {system.media.pending} to copy{#if system.media.missing}, {system.media.missing} missing{/if}
      </span>
    </div>
    <div>
      <span class="muted small">Recorded here</span>
      <strong>{formatSize(system.captured_audio_bytes)}</strong>
      <span class="muted small">takes this app captured — delete them in Repertoire</span>
    </div>
    <div>
      <span class="muted small">Backups</span>
      <strong>{system.backup_count} kept</strong>
      <span class="muted small">
        {#if system.last_backup_seconds === null}
          none yet
        {:else}
          newest {backupAge(system.last_backup_seconds)}
        {/if}
      </span>
    </div>
    <div>
      <span class="muted small">Piano visible to ALSA</span>
      <strong>{system.alsa_clients.some((name) => /casio|piano/i.test(name)) ? 'yes' : 'no'}</strong>
      <span class="muted small">
        {#if !system.sequencer}
          sequencer not loaded
        {:else}
          {system.alsa_clients.filter((name) => !/midi through|system/i.test(name)).join(', ') ||
            'only virtual ports'}
        {/if}
      </span>
    </div>
  </div>
  {#if system.last_backup_seconds === null && system.backup_count === 0}
    <p class="muted small">
      No nightly backup has run yet. The installer enables a timer that writes one at
      03:10 and keeps the last 14.
    </p>
  {/if}
</section>

<style>
  .health {
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
    padding: 0.75rem 0.9rem;
  }

  .health-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
    gap: 0.75rem;
  }

  .health-grid > div {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }

  .health-grid strong {
    font-size: 1.05rem;
  }

  .small {
    font-size: 0.8rem;
  }
</style>
