<script lang="ts">
  import { formatClock } from '../lib/clock';
  import type { StripRange } from '../lib/timelineStrip';
  import type { SegmentSummary } from '../lib/types';

  interface Props {
    segments: SegmentSummary[];
    reviewMarksMs: number[];
    durationS: number;
    total: number;
    position: number;
    playing: { fromMs: number; toMs: number; segmentId: number | null } | null;
    scrubbing: boolean;
    soundingRange: { left: number; width: number } | null;
    playheadAt: number;
    ticks: number[];
    pieceColor: (pieceId: number | null) => string | null;
    segmentName: (segment: SegmentSummary) => string;
    onScrubChange: (active: boolean) => void;
    onMoveTo: (atMs: number) => void;
    onApplySeek: (atMs: number, fallback: StripRange | null) => void;
    onSeekBy: (seconds: number) => void;
  }

  let {
    segments,
    reviewMarksMs,
    durationS,
    total,
    position,
    playing,
    scrubbing,
    soundingRange,
    playheadAt,
    ticks,
    pieceColor,
    segmentName,
    onScrubChange,
    onMoveTo,
    onApplySeek,
    onSeekBy,
  }: Props = $props();

  /** Where the press landed, as a fraction of the strip. */
  function ratioAt(event: { clientX: number; currentTarget: EventTarget | null }): number {
    const strip = event.currentTarget as HTMLElement | null;
    if (strip === null) return 0;
    const bounds = strip.getBoundingClientRect();
    if (bounds.width <= 0) return 0;
    return Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width));
  }

  /**
   * A press begins a scrub: the playhead follows the pointer, and the sound waits.
   *
   * Dragging is the gesture a two-hour sitting needs, because at that length a click is only
   * good to about nine seconds. Scrubbing silently and resuming on release keeps it one
   * gesture instead of one restart per pixel — the player would otherwise be torn down and
   * rebuilt sixty times a second.
   */
  function onStripPointerDown(event: PointerEvent): void {
    if (event.button !== 0) return;
    const strip = event.currentTarget as HTMLElement;
    strip.setPointerCapture(event.pointerId);
    onScrubChange(true);
    onMoveTo(ratioAt(event) * total);
  }

  function onStripPointerMove(event: PointerEvent): void {
    if (!scrubbing) return;
    onMoveTo(ratioAt(event) * total);
  }

  /**
   * The release ends the scrub, and the `click` that follows it commits the seek.
   *
   * Committing here rather than in the click handler would fire twice for a plain press, since
   * a browser always follows a press and release with a click; committing *only* in `click`
   * keeps one owner for the gesture. Pointer capture is what makes that safe for a drag: the
   * pointer events stay on the strip wherever the pointer goes, so the click lands on the strip
   * too, and a drag off the bottom of the strip still commits where it was released.
   */
  function onStripPointerUp(event: PointerEvent): void {
    if (!scrubbing) return;
    onScrubChange(false);
    const strip = event.currentTarget as HTMLElement;
    if (strip.hasPointerCapture(event.pointerId)) strip.releasePointerCapture(event.pointerId);
  }
</script>

<!-- A slider, not a picture: the strip sets the position, so it takes focus and the arrow
     keys move the playhead the way the pointer does. What the position costs is decided by
     whether anything is playing: silent when nothing is, a seek when something is. -->
<div
  class="strip"
  role="slider"
  tabindex="0"
  aria-label="Sitting timeline — press or drag, or use the arrow keys, Page Up/Down and Home/End, to move to a point; the segment list below follows"
  aria-valuemin="0"
  aria-valuemax={Math.round(durationS)}
  aria-valuenow={Math.round(position / 1000)}
  data-strip
  onpointerdown={onStripPointerDown}
  onpointermove={onStripPointerMove}
  onpointerup={onStripPointerUp}
  onpointercancel={onStripPointerUp}
  onclick={(event) => onApplySeek(ratioAt(event) * total, null)}
  onkeydown={(event) => {
    if (event.key === 'ArrowRight') onSeekBy(5);
    else if (event.key === 'ArrowLeft') onSeekBy(-5);
    // Five minutes a press, because the arrows are for the passage and this is for the
    // sitting: crossing two hours at five seconds a press is not navigation.
    else if (event.key === 'PageUp') onSeekBy(300);
    else if (event.key === 'PageDown') onSeekBy(-300);
    else if (event.key === 'Home') onApplySeek(0, null);
    else if (event.key === 'End') onApplySeek(total, null);
    else return;
    // The slider consumes the key it handles. Without this, Home and End would also scroll
    // the document out from under the strip the player is aiming at.
    event.preventDefault();
  }}
>
  {#each segments as segment (segment.id)}
    <span
      class="block"
      class:labelled={segment.piece_id !== null}
      class:sight={segment.source === 'sight_reading'}
      data-segment-block={segment.id}
      style="left: {(segment.start_ms / total) * 100}%; width: {Math.max(
        0.6,
        ((segment.end_ms - segment.start_ms) / total) * 100,
      )}%; --piece: {pieceColor(segment.piece_id) ?? 'var(--good)'}"
      title="{segmentName(segment)} · {formatClock(
        (segment.end_ms - segment.start_ms) / 1000,
      )} · click to jump to this segment"
    ></span>
    {#each segment.metrics?.pedal_blur_ms ?? [] as blurMs (blurMs)}
      <!-- A hairline per blur, so a long sitting can be searched by eye. The count
           says whether to look; these say where.

           The stored position is already **sitting-relative** — the same axis `.block`
           and `.review` are laid out on, measured from the sitting's start — so it is
           divided by the sitting's length directly. Adding `segment.start_ms` here
           counted the segment's own offset a second time: a blur in the second segment
           was drawn one segment-length too late, and could land outside its segment or
           past the end of the strip altogether. -->
      <span
        class="blur"
        data-blur={blurMs}
        style="left: {(blurMs / total) * 100}%"
        title="Pedal blur at {formatClock(
          blurMs / 1000,
        )} — new harmony arrived while the pedal was holding notes from before"
      ></span>
    {/each}
  {/each}
  {#each reviewMarksMs as markMs (markMs)}
    <!-- A flag you put there yourself, as against the blur hairline the app measured: the
         same layer, a different fact, so it must not look like one. -->
    <span
      class="review"
      data-review-mark={markMs}
      style="left: {(markMs / total) * 100}%"
      title="You flagged this for review at {formatClock(markMs / 1000)}"
    ></span>
  {/each}
  {#if soundingRange}
    <span
      class="sounding"
      style="left: {soundingRange.left}%; width: {soundingRange.width}%"
    ></span>
  {/if}
  {#if playing || position > 0}
    <!-- Positioned from the reported position rather than from the range being
         played, so seeking into a two-hour sitting draws the line where you are.
         Shown while playing even at zero, because that is where a sitting whose
         first note is at the start actually begins. -->
    <span class="playhead" data-playhead style="left: {playheadAt}%"></span>
  {/if}
</div>

<!-- The scale, which the strip itself cannot show: a two-hour sitting is about nine
     seconds per pixel, so without labels a press is guessed rather than aimed. Purely a
     reading of the strip, so it is hidden from the accessibility tree — the slider above
     already reports its value. -->
<div class="ruler" data-ruler aria-hidden="true">
  {#each ticks as tick, index (index)}
    <span
      class="tick"
      class:first={index === 0}
      class:last={index === ticks.length - 1}
      style="left: {(tick / total) * 100}%"
      data-tick={tick}
    >
      {formatClock(tick / 1000)}
    </span>
  {/each}
</div>

<style>
  .strip {
    position: relative;
    height: 18px;
    border-radius: 6px;
    background: var(--track);
    overflow: hidden;
    /* A press is a seek, so the pointer says so; and a drag must scrub rather than scroll the
       page out from under the strip on a touch screen. */
    cursor: pointer;
    touch-action: none;
  }

  .strip:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }

  /* The clock under the strip. Kept out of the strip's own box so the blocks, the hairlines and
     the playhead still fill it edge to edge. */
  .ruler {
    position: relative;
    height: 1rem;
    margin-top: 0.15rem;
  }

  .ruler .tick {
    position: absolute;
    top: 0;
    transform: translateX(-50%);
    font-size: 0.7rem;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  /* The ends are pulled inside the strip rather than centred on it, so neither label is cut
     off by the panel's edge. */
  .ruler .tick.first {
    transform: none;
  }

  .ruler .tick.last {
    transform: translateX(-100%);
  }

  .block {
    position: absolute;
    top: 0;
    bottom: 0;
    background: var(--muted);
    opacity: 0.55;
    border-right: 1px solid var(--surface);
  }

  /* The piece's own colour, handed to the block as `--piece` by the script. Every piece in the
     sitting owns a different slot, so the strip answers "which piece, and when" at a glance
     rather than "labelled, somewhere". `--good` is the fallback for the impossible case of a
     labelled block whose piece has no slot, which is what this drew before the palette. */
  .block.labelled {
    background: var(--piece, var(--good));
    opacity: 0.8;
  }

  /* A blur marker is a hairline: findable on a long sitting without becoming the loudest
     thing on the strip. It takes no pointer events, so clicking it still seeks. */
  .strip .blur {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    margin-left: -1px;
    background: var(--warn);
    opacity: 0.85;
    pointer-events: none;
  }

  /* A review flag is a hairline with a pennant: findable on a long sitting, and unmistakably not
     the warn-coloured blur hairline beside it. It takes no pointer events either, so clicking it
     still seeks. */
  .strip .review {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    margin-left: -1px;
    background: var(--good);
    pointer-events: none;
  }

  .strip .review::before {
    content: '';
    position: absolute;
    top: 0;
    left: 2px;
    width: 7px;
    height: 7px;
    background: var(--good);
    clip-path: polygon(0 0, 100% 50%, 0 100%);
  }

  .playhead {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--ink);
    box-shadow: 0 0 0 1px var(--surface);
  }

  .block.sight {
    background: var(--accent);
    opacity: 0.85;
  }
</style>
