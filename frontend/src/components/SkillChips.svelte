<script lang="ts">
  import { app } from '../lib/state.svelte';

  interface Props {
    levels: Record<string, number>;
    target: string | null;
  }

  let { levels, target }: Props = $props();

  // Ordered by the taxonomy's sort order, which the profile already carries.
  const ordered = $derived.by(() => {
    const order = app.profile ? Object.keys(app.profile.ratings) : Object.keys(levels);
    const slugs = order.filter((slug) => slug in levels);
    for (const slug of Object.keys(levels)) if (!slugs.includes(slug)) slugs.push(slug);
    return slugs.map((slug) => ({ slug, level: levels[slug], isTarget: slug === target }));
  });
</script>

<div class="chips">
  {#each ordered as item (item.slug)}
    <span class="chip" class:target={item.isTarget}>
      <span class="label">{item.slug.replace(/_/g, ' ')}</span>
      <span class="mono value">{item.level}</span>
    </span>
  {/each}
</div>

<style>
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: var(--surface-2);
    font-size: 0.75rem;
    color: var(--muted);
  }

  .chip.target {
    background: var(--accent-soft);
    border-color: #cdd2ff;
    color: var(--accent);
    font-weight: 600;
  }

  .value {
    background: rgba(0, 0, 0, 0.05);
    border-radius: 999px;
    padding: 0 0.3rem;
    font-size: 0.7rem;
  }
</style>
