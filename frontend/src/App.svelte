<script lang="ts">
  import { onMount } from 'svelte';
  import DeviceBar from './components/DeviceBar.svelte';
  import PracticeView from './components/PracticeView.svelte';
  import CalibrationView from './components/CalibrationView.svelte';
  import StatsView from './components/StatsView.svelte';
  import HostBanner from './components/HostBanner.svelte';
  import PracticeLogView from './components/PracticeLogView.svelte';
  import RepertoireView from './components/RepertoireView.svelte';
  import ThemeControls from './components/ThemeControls.svelte';
  import WorkoutBar from './components/WorkoutBar.svelte';
  import { app } from './lib/state.svelte';
  import CommandPalette from './components/CommandPalette.svelte';
  import type { AppView } from './lib/types';
  import type { Route } from './lib/route';

  const tabs: { id: AppView; label: string }[] = [
    { id: 'practice', label: 'Practice' },
    { id: 'calibrate', label: 'Calibrate' },
    { id: 'stats', label: 'Progress' },
    { id: 'log', label: 'Log' },
    { id: 'repertoire', label: 'Repertoire' },
  ];

  let paletteOpen = $state(false);

  function go(route: Route): void {
    app.navigate(route);
    paletteOpen = false;
  }

  /**
   * Global shortcuts.
   *
   * Three rules, all of which exist because a piano app gets typed into almost never and
   * played into constantly:
   *
   * * a shortcut never fires while a field has focus, so the palette's own box and the
   *   split-position input keep working;
   * * Escape always closes, whatever has focus;
   * * space is a *request* to the view, and is inert during a scored attempt, because the
   *   one thing a stray key must not do is disturb a run.
   */
  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape' && paletteOpen) {
      event.preventDefault();
      paletteOpen = false;
      return;
    }

    const target = event.target as HTMLElement | null;
    const typing =
      target !== null &&
      (target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.tagName === 'SELECT' ||
        target.isContentEditable);
    if (typing) return;

    if (event.key === '/') {
      event.preventDefault();
      paletteOpen = true;
      return;
    }
    if (event.key === 'k' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      paletteOpen = true;
      return;
    }

    const index = Number(event.key);
    if (Number.isInteger(index) && index >= 1 && index <= tabs.length) {
      event.preventDefault();
      go({ name: tabs[index - 1].id });
      return;
    }

    if (event.key === ' ' && app.view === 'practice' && !app.exerciseActive) {
      event.preventDefault();
      app.requestShortcut('start');
    }
  }

  onMount(() => {
    // A pasted link has to be honoured before the first paint of a view, so this runs
    // with the other boot work rather than in an effect that may fire twice.
    app.syncFromHash();
    void app.bootstrap().then(() => app.startMidi());
  });

  // Drives the focus-mode layout in app.css. Set on <html> so the rules can
  // reach the header and footer.
  $effect(() => {
    document.documentElement.dataset.focus = String(app.focusMode);
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

    <div class="row">
      <nav class="tabs" aria-label="Sections">
        {#each tabs as tab (tab.id)}
          <button
            class:active={app.view === tab.id}
            aria-current={app.view === tab.id ? 'page' : undefined}
            onclick={() => go({ name: tab.id })}
          >
            {tab.label}
          </button>
        {/each}
        <button
          class="ghost tiny"
          aria-keyshortcuts="/"
          data-palette-trigger
          onclick={() => (paletteOpen = true)}>Search</button
        >
      </nav>
      <ThemeControls />
    </div>
  </header>

  <DeviceBar />

  <WorkoutBar />

  <HostBanner />

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
    {:else if app.view === 'stats'}
      <StatsView />
    {:else if app.view === 'log'}
      <PracticeLogView />
    {:else}
      <RepertoireView />
    {/if}
  </main>

  <footer class="muted footer">
    Web MIDI needs Chrome, Edge, or Opera on desktop. Play on an acoustic-silent
    setting or with the piano's own sound off for the cleanest MIDI timing.
  </footer>
</div>

<svelte:window onhashchange={() => app.syncFromHash()} onkeydown={onKeydown} />

{#if paletteOpen}
  <CommandPalette onclose={() => (paletteOpen = false)} onnavigate={go} />
{/if}

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
    color: var(--accent-ink);
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
