<script lang="ts">
  import { theme, type ScorePaper, type ThemePreference } from '../lib/theme.svelte';

  const preferences: { id: ThemePreference; label: string; title: string }[] = [
    { id: 'system', label: 'Auto', title: 'Follow the operating system' },
    { id: 'light', label: 'Light', title: 'Always light' },
    { id: 'dark', label: 'Dark', title: 'Always dark' },
  ];

  const papers: { id: ScorePaper; label: string; title: string }[] = [
    { id: 'theme', label: 'Themed music', title: 'Invert the notation with the theme' },
    { id: 'light', label: 'Paper music', title: 'Keep the notation black on white' },
  ];

  let open = $state(false);
</script>

<div class="theme">
  <button
    class="ghost trigger"
    aria-expanded={open}
    aria-label="Appearance settings"
    onclick={() => (open = !open)}
  >
    {theme.resolved === 'dark' ? '🌙' : '☀️'}
    <span class="label">Appearance</span>
  </button>

  {#if open}
    <div class="popover card">
      <div class="group">
        <span class="heading">Interface</span>
        <div class="segmented" role="group" aria-label="Theme">
          {#each preferences as option (option.id)}
            <button
              class:active={theme.preference === option.id}
              title={option.title}
              aria-pressed={theme.preference === option.id}
              onclick={() => theme.setPreference(option.id)}
            >
              {option.label}
            </button>
          {/each}
        </div>
      </div>

      <div class="group">
        <span class="heading">Sheet music</span>
        <div class="segmented" role="group" aria-label="Score paper">
          {#each papers as option (option.id)}
            <button
              class:active={theme.scorePaper === option.id}
              title={option.title}
              aria-pressed={theme.scorePaper === option.id}
              onclick={() => theme.setScorePaper(option.id)}
            >
              {option.label}
            </button>
          {/each}
        </div>
        <p class="muted note">
          Inverted notation divides readers, so it is a choice rather than a rule.
        </p>
      </div>

      <button class="ghost close" onclick={() => (open = false)}>Close</button>
    </div>
  {/if}
</div>

<style>
  .theme {
    position: relative;
  }

  .trigger {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.4rem 0.7rem;
  }

  .popover {
    position: absolute;
    right: 0;
    top: calc(100% + 0.4rem);
    z-index: 20;
    width: 17.5rem;
    padding: 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
  }

  .group {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .heading {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
    font-weight: 600;
  }

  .segmented {
    display: flex;
    background: var(--surface-2);
    border: 1px solid var(--line);
    border-radius: 9px;
    padding: 0.15rem;
    gap: 0.15rem;
  }

  .segmented button {
    flex: 1;
    border: none;
    background: transparent;
    padding: 0.3rem 0.35rem;
    border-radius: 7px;
    font-size: 0.8rem;
    color: var(--muted);
    white-space: nowrap;
  }

  .segmented button.active {
    background: var(--surface);
    color: var(--ink);
    font-weight: 600;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.12);
  }

  .note {
    margin: 0;
    font-size: 0.72rem;
    line-height: 1.45;
  }

  .close {
    align-self: flex-end;
    font-size: 0.78rem;
    padding: 0.25rem 0.5rem;
  }

  @media (max-width: 560px) {
    .label {
      display: none;
    }
  }
</style>
