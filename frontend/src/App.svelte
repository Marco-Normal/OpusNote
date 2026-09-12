<script lang="ts">
  import { onMount } from 'svelte';
  import DeviceBar from './components/DeviceBar.svelte';
  import PracticeView from './components/PracticeView.svelte';
  import CalibrationView from './components/CalibrationView.svelte';
  import StatsView from './components/StatsView.svelte';
  import { app } from './lib/state.svelte';
  import type { AppView } from './lib/types';

  const tabs: { id: AppView; label: string }[] = [
    { id: 'practice', label: 'Practice' },
    { id: 'calibrate', label: 'Calibrate' },
    { id: 'stats', label: 'Progress' },
  ];

  onMount(() => {
    void app.bootstrap();
  });
</script>

<div class="shell">
  <header class="topbar">
    <div class="brand">
      <span class="mark">♪</span>
      <div>
        <h1>Sight-Reading Trainer</h1>
        <p class="muted tagline">Adaptive exercises for a real piano</p>
      </div>
    </div>

    <nav class="tabs" aria-label="Sections">
      {#each tabs as tab (tab.id)}
        <button
          class:active={app.view === tab.id}
          aria-current={app.view === tab.id ? 'page' : undefined}
          onclick={() => (app.view = tab.id)}
        >
          {tab.label}
        </button>
      {/each}
    </nav>
  </header>

  <DeviceBar />

  {#if app.apiOnline === false}
    <div class="error-banner">
      {app.errorMessage ?? 'The API is unreachable.'}
      <button class="ghost" onclick={() => app.bootstrap()}>Retry</button>
    </div>
  {/if}

  <main>
    {#if app.view === 'practice'}
      <PracticeView />
    {:else if app.view === 'calibrate'}
      <CalibrationView />
    {:else}
      <StatsView />
    {/if}
  </main>

  <footer class="muted footer">
    Web MIDI needs Chrome, Edge, or Opera on desktop. Play on an acoustic-silent
    setting or with the piano's own sound off for the cleanest MIDI timing.
  </footer>
</div>

<style>
  .shell {
    max-width: 1080px;
    margin: 0 auto;
    padding: 1rem 1.15rem 2.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
  }

  .topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 0.65rem;
  }

  .mark {
    display: grid;
    place-items: center;
    width: 2.1rem;
    height: 2.1rem;
    border-radius: 9px;
    background: var(--accent);
    color: #fff;
    font-size: 1.1rem;
  }

  .tagline {
    margin: 0.1rem 0 0;
    font-size: 0.82rem;
  }

  .tabs {
    display: flex;
    gap: 0.25rem;
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 0.2rem;
  }

  .tabs button {
    border: none;
    background: transparent;
    padding: 0.4rem 0.85rem;
    border-radius: 8px;
    color: var(--muted);
    font-size: 0.9rem;
  }

  .tabs button.active {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 600;
  }

  main {
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
  }

  .footer {
    font-size: 0.78rem;
    border-top: 1px solid var(--line);
    padding-top: 0.75rem;
    margin-top: 0.5rem;
    line-height: 1.5;
  }
</style>
