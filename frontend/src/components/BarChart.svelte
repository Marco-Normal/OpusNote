<script lang="ts">
  /**
   * Horizontal bars for "where did the time go" — time per piece, in minutes.
   *
   * Scaled to the largest value rather than to the total, so a piece that
   * dominates does not flatten every other bar into an invisible sliver.
   */
  interface Item {
    label: string;
    sublabel?: string;
    value: number;
    hint?: string;
  }

  interface Props {
    items: Item[];
    unit?: string;
    empty?: string;
  }

  let { items, unit = 'min', empty = 'Nothing logged yet.' }: Props = $props();

  const peak = $derived(items.reduce((best, item) => Math.max(best, item.value), 0));
</script>

{#if items.length === 0}
  <p class="muted empty">{empty}</p>
{:else}
  <ul class="bars">
    <!-- Two pieces can share a title, so the label is not a key on its own. -->
    {#each items as item, index (`${item.label}-${index}`)}
      <li>
        <div class="head">
          <span class="label">
            {item.label}
            {#if item.sublabel}<span class="muted small">{item.sublabel}</span>{/if}
          </span>
          <span class="mono value">{item.value}{unit}</span>
        </div>
        <div class="track">
          <span style="width: {peak > 0 ? Math.max(2, (item.value / peak) * 100) : 0}%"></span>
        </div>
        {#if item.hint}
          <span class="muted small">{item.hint}</span>
        {/if}
      </li>
    {/each}
  </ul>
{/if}

<style>
  .bars {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  li {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }

  .head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
    font-size: 0.86rem;
  }

  .label {
    display: inline-flex;
    gap: 0.4rem;
    align-items: baseline;
  }

  .value {
    font-size: 0.8rem;
    color: var(--muted);
  }

  .track {
    height: 7px;
    border-radius: 999px;
    background: var(--track);
    overflow: hidden;
  }

  .track span {
    display: block;
    height: 100%;
    background: var(--accent);
    border-radius: 999px;
  }

  .empty {
    margin: 0;
    font-size: 0.85rem;
  }

  .small {
    font-size: 0.78rem;
  }
</style>
