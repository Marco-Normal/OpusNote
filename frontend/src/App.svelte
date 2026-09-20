<script lang="ts">
  import { onMount } from 'svelte';
  import DeviceStatus from './components/DeviceStatus.svelte';
  import SetupPanel from './components/SetupPanel.svelte';
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

  /**
   * Three sections, which is the shape the name describes: you play, you keep pieces, you
   * look at how it is going.
   *
   * `Calibrate` is gone from here because it was never a section: it is a diagnostic you run
   * occasionally, and it was sitting as a peer of Practice. It is reached from Setup › Timing
   * instead, and its route still resolves.
   *
   * `Progress` and `Log` are one section with two views — ratings over time, and what you
   * actually played. They were two tabs answering the same question ("how is this going?")
   * with no way to tell them apart from the outside. The merge is at the *navigation* level
   * only: `stats` and `log` stay separate views and separate routes, so every pasted
   * `#/stats/attempt/56` and `#/log/sitting/34` link still opens what it names.
   */
  interface Tab {
    id: AppView;
    label: string;
    /** The views this tab is "on". More than one only for Progress. */
    owns: AppView[];
  }

  const tabs: Tab[] = [
    { id: 'practice', label: 'Practice', owns: ['practice'] },
    { id: 'repertoire', label: 'Library', owns: ['repertoire'] },
    { id: 'stats', label: 'Progress', owns: ['stats', 'log'] },
  ];

  let paletteOpen = $state(false);
  let setupOpen = $state(false);

  /**
   * Which of the two Progress views the tab opens on.
   *
   * Remembered for the session rather than reset every time: someone who lives in the Log
   * would otherwise be sent back to the ratings on every visit. Not persisted — a fresh
   * session opening on the ratings is the right default.
   */
  let lastProgressView = $state<AppView>('stats');
  $effect(() => {
    if (app.view === 'stats' || app.view === 'log') lastProgressView = app.view;
  });

  function go(route: Route): void {
    app.navigate(route);
    paletteOpen = false;
  }

  /** Clicking the section you are already in does nothing, rather than moving you between
   *  Progress' two views — which would make the tab feel like it had lost your place. */
  function goTab(tab: Tab): void {
    if (tab.owns.includes(app.view)) return;
    go({ name: tab.id === 'stats' ? lastProgressView : tab.id });
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

    // Setup is a disclosure rather than an overlay, but Escape should still close it: it is
    // the key people press to get out of a panel.
    if (event.key === 'Escape' && setupOpen) {
      setupOpen = false;
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
      goTab(tabs[index - 1]);
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

<!-- `data-app-ready` is the browser suite's readiness sentinel. It exists so the
     suite never has to wait on a display string: the product name is a brand
     decision, and renaming it must not break verification. -->
<div class="shell" data-app-ready>
  <header class="topbar">
    <div class="brand">
      <!-- `Op.` is the catalogue abbreviation — Op. 27 No. 2 — so the monogram is the
           wordmark's own shorthand rather than a decorative music glyph. Hidden from
           assistive tech, which should hear the name once, not twice. -->
      <span class="mark" aria-hidden="true">Op.</span>
      <div>
        <h1>Opus Note</h1>
        <p class="muted tagline">Notes you play. Notes you keep.</p>
      </div>
    </div>

    <div class="row">
      <nav class="tabs" aria-label="Sections">
        {#each tabs as tab (tab.id)}
          <button
            class:active={tab.owns.includes(app.view)}
            aria-current={tab.owns.includes(app.view) ? 'page' : undefined}
            onclick={() => goTab(tab)}
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

  <DeviceStatus onsetup={() => (setupOpen = true)} />

  {#if setupOpen}
    <SetupPanel onclose={() => (setupOpen = false)} />
  {/if}

  <WorkoutBar />

  <HostBanner />

  {#if app.apiOnline === false}
    <div class="error-banner">
      {app.errorMessage ?? 'The API is unreachable.'}
      <button class="ghost" onclick={() => app.bootstrap()}>Retry</button>
    </div>
  {/if}

  <!--
    The two views of Progress: ratings over time, and what you actually played. This is
    navigation chrome rather than part of either view, so it lives here and has one owner —
    a copy inside each view would drift.
  -->
  {#if app.view === 'stats' || app.view === 'log'}
    <nav class="subtabs" aria-label="Progress views">
      <button
        class:active={app.view === 'stats'}
        aria-current={app.view === 'stats' ? 'page' : undefined}
        data-subview="stats"
        onclick={() => go({ name: 'stats' })}
      >
        Ratings
      </button>
      <button
        class:active={app.view === 'log'}
        aria-current={app.view === 'log' ? 'page' : undefined}
        data-subview="log"
        onclick={() => go({ name: 'log' })}
      >
        Log
      </button>
    </nav>
  {/if}

  <main data-view={app.view}>
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
    width: 2.2rem;
    height: 2.2rem;
    border-radius: var(--radius-sm);
    background: var(--accent);
    color: var(--accent-ink);
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 0.9rem;
    letter-spacing: -0.03em;
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
    border-radius: var(--radius);
    padding: 0.2rem;
  }

  .tabs button {
    border: none;
    background: transparent;
    padding: 0.4rem 0.85rem;
    border-radius: var(--radius-sm);
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

  /* A quieter sibling of the section tabs: the same shape, no container, so it reads as
     belonging to the view rather than competing with the header. */
  .subtabs {
    display: flex;
    gap: 0.25rem;
    border-bottom: 1px solid var(--line);
  }

  .subtabs button {
    border: none;
    background: transparent;
    padding: 0.4rem 0.7rem;
    border-radius: var(--radius-sm) var(--radius-sm) 0 0;
    color: var(--muted);
    font-size: 0.9rem;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
  }

  .subtabs button.active {
    color: var(--accent);
    font-weight: 600;
    border-bottom-color: var(--accent);
  }

  .footer {
    font-size: 0.78rem;
    border-top: 1px solid var(--line);
    padding-top: 0.75rem;
    margin-top: 0.5rem;
    line-height: 1.5;
  }
</style>
