<script lang="ts">
  /**
   * One attached score, drawn.
   *
   * Two formats, two renderers, and no third option: a PDF is handed to the
   * browser's own viewer (no library, no piracy of the engraving), and MusicXML
   * goes through the OSMD instance the exercise view already uses. The score is
   * only fetched here, when it is actually opened — a library with a dozen
   * scores should not download a dozen documents to draw a list.
   */
  import { onDestroy } from 'svelte';
  import { ScoreRenderer } from '../lib/score';
  import { theme } from '../lib/theme.svelte';
  import type { Recording } from '../lib/types';

  interface Props {
    score: Recording;
  }

  let { score }: Props = $props();

  const isPdf = $derived(score.codec === 'pdf');
  const url = $derived(`/api/repertoire/media/${score.id}/file`);
  const label = $derived(score.title ?? score.original_name ?? score.file_name);

  let container = $state<HTMLDivElement | undefined>(undefined);
  let loading = $state(false);
  let problem = $state<string | null>(null);
  let renderer: ScoreRenderer | null = null;

  $effect(() => {
    const target = container;
    // A PDF needs nothing from us beyond the iframe's src.
    if (isPdf || !target) return;

    let cancelled = false;
    loading = true;
    problem = null;
    const drawn = new ScoreRenderer(target);
    renderer = drawn;

    void (async () => {
      try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`the score could not be read (${response.status})`);
        const musicxml = await response.text();
        if (cancelled) return;
        // No expected-note timeline: this is somebody else's edition, not an
        // exercise, so there is nothing to colour and nothing to correlate.
        await drawn.render(musicxml, [], {
          dark: theme.scoreIsDark,
          maxHeight: Math.max(320, window.innerHeight * 0.75),
        });
      } catch (cause) {
        if (!cancelled) problem = cause instanceof Error ? cause.message : String(cause);
      } finally {
        if (!cancelled) loading = false;
      }
    })();

    return () => {
      cancelled = true;
      drawn.dispose();
      if (renderer === drawn) renderer = null;
    };
  });

  // Re-engrave on a paper change. OSMD reads its colours at load time, so this is
  // a re-render rather than a recolour — and it is why this is separate from the
  // effect above, which must not re-fetch on a theme switch.
  $effect(() => {
    const dark = theme.scoreIsDark;
    if (renderer) void renderer.setDark(dark);
  });

  onDestroy(() => renderer?.dispose());
</script>

<div class="viewer" data-score-viewer={score.codec} data-score-name={label}>
  {#if problem}
    <p class="bad-text">{problem}</p>
  {:else if isPdf}
    <!-- The browser's own viewer: it already handles scrolling, zooming and
         printing, and a PDF is a document rather than something we should
         re-typeset. -->
    <iframe class="pdf score-surface" src={url} title={label}></iframe>
  {:else}
    {#if loading}
      <p class="muted small">Loading the score…</p>
    {/if}
    <div class="engraving score-surface" bind:this={container}></div>
  {/if}
</div>

<style>
  .viewer {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .pdf {
    width: 100%;
    /* Tall enough to read a system or two without scrolling inside the frame. */
    height: 32rem;
  }

  .engraving {
    min-height: 8rem;
  }
</style>
