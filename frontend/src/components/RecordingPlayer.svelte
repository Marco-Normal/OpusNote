<script lang="ts">
  /**
   * One recording: the player, and the waveform with its A/B loop.
   *
   * The element lives here rather than in the library view because the loop has
   * to seek it on every frame while it plays, and a picture in one component
   * driving an element in another is how "the loop" ends up silently doing
   * nothing. The markers themselves belong to the database — this asks the parent
   * to save them, and draws whatever the parent's refreshed row says.
   */
  import { api } from '../lib/api';
  import type { Recording } from '../lib/types';
  import { formatSize } from '../lib/types';
  import {
    MAX_WAVEFORM_BYTES,
    PEAK_COLUMNS,
    clampToLoop,
    peaksFrom,
    placeMarker,
    type Loop,
    type Peaks,
  } from '../lib/waveform';
  import Waveform from './Waveform.svelte';
  import { formatClock } from '../lib/clock';

  interface Props {
    recording: Recording;
    /** Persist a new loop. The parent owns the request, the error banner and the refresh. */
    onLoop: (loop: Loop) => void;
  }

  let { recording, onLoop }: Props = $props();

  const source = $derived(api.repertoire.mediaUrl(recording.id));
  const loop = $derived<Loop>({
    start: recording.loop_start_s,
    end: recording.loop_end_s,
  });

  let element = $state<HTMLMediaElement | undefined>(undefined);
  let open = $state(false);
  let decoding = $state(false);
  let problem = $state<string | null>(null);
  let peaks = $state<Peaks | null>(null);
  let position = $state(0);
  /** From the element's metadata: more trustworthy than the stored estimate. */
  let measured = $state(0);
  let playing = $state(false);
  let rate = $state(1);
  /** Whether the browser is preserving pitch, which is what makes a slow take useful. */
  let preservesPitch = $state(true);

  /**
   * Slow the take down without changing the file.
   *
   * `preservesPitch` is the browser's own time-stretch: at 0.5× the passage is lower *and* slower
   * without it, which is not what a player wants to hear. The readout says which one this browser
   * is doing rather than assuming.
   */
  function setRate(value: number): void {
    rate = value;
    if (!element) return;
    const media = element as HTMLMediaElement & {
      preservesPitch?: boolean;
      webkitPreservesPitch?: boolean;
    };
    // Both spellings: `preservesPitch` is the standard and `webkitPreservesPitch` is what older
    // Chromium builds honour, and a kiosk is exactly the kind of machine that runs an older one.
    // Support is the honest answer: assigning true and reading the property back cannot tell a
    // browser that ignores the write from one that honours it, so the property's existence is the
    // capability, and its absence is the only case the readout has to warn about.
    const supported = 'preservesPitch' in media || 'webkitPreservesPitch' in media;
    media.preservesPitch = true;
    media.webkitPreservesPitch = true;
    media.playbackRate = value;
    preservesPitch = supported;
  }

  const duration = $derived(measured || recording.duration_secs || 0);
  const looping = $derived(loop.start !== null && loop.end !== null && loop.end > loop.start);

  $effect(() => {
    if (!playing || !element) return;
    const media = element;
    let frame = requestAnimationFrame(function tick() {
      const target = clampToLoop(media.currentTime, loop.start, loop.end);
      if (target !== media.currentTime) media.currentTime = target;
      position = media.currentTime;
      frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  });

  async function decode(): Promise<void> {
    if (peaks || decoding) return;
    const size = recording.size_bytes ?? 0;
    if (size > MAX_WAVEFORM_BYTES) {
      problem =
        `This recording is ${formatSize(size)}, too large to decode for a picture. ` +
        'It still plays.';
      return;
    }
    decoding = true;
    problem = null;
    try {
      const response = await fetch(source);
      if (!response.ok) throw new Error(`the recording could not be read (${response.status})`);
      const bytes = await response.arrayBuffer();
      // Offline rather than a live AudioContext: decoding needs no output device
      // and no user gesture, and this one is closed again immediately.
      const context = new OfflineAudioContext(1, 1, 44_100);
      const decoded = await context.decodeAudioData(bytes);
      const channels = Array.from({ length: decoded.numberOfChannels }, (_, index) =>
        decoded.getChannelData(index),
      );
      peaks = peaksFrom(channels, PEAK_COLUMNS);
      // The decoded buffer is deliberately not kept: the columns are all the
      // picture needs, and holding the samples would cost hundreds of megabytes
      // on a long recording.
      if (!measured && decoded.duration > 0) measured = decoded.duration;
    } catch (cause) {
      problem = cause instanceof Error ? cause.message : String(cause);
    } finally {
      decoding = false;
    }
  }

  function toggle(): void {
    open = !open;
    if (open) void decode();
  }

  function seek(seconds: number): void {
    if (!element) return;
    element.currentTime = seconds;
    position = seconds;
  }

  /**
   * Mark A or B at the playhead.
   *
   * From `position` rather than `element.currentTime`: the element may not have
   * loaded its metadata yet (it is `preload="none"`), and a seek issued before
   * that is queued rather than applied, so reading it back would mark the start of
   * the file. `position` is the playhead the player can see.
   */
  function mark(which: 'start' | 'end'): void {
    onLoop(placeMarker(position, loop, which));
  }
</script>

<div class="player" data-recording={recording.id}>
  {#if recording.kind === 'video'}
    <!-- svelte-ignore a11y_media_has_caption — these are the player's own
         recordings; no caption track exists. -->
    <video
      controls
      preload="none"
      src={source}
      bind:this={element}
      onloadedmetadata={() => (measured = element?.duration ?? 0)}
      ontimeupdate={() => (position = element?.currentTime ?? position)}
      onseeked={() => (position = element?.currentTime ?? position)}
      onplay={() => (playing = true)}
      onpause={() => (playing = false)}
      onended={() => (playing = false)}
    ></video>
  {:else}
    <!-- svelte-ignore a11y_media_has_caption — as above. -->
    <audio
      controls
      preload="none"
      src={source}
      bind:this={element}
      onloadedmetadata={() => (measured = element?.duration ?? 0)}
      ontimeupdate={() => (position = element?.currentTime ?? position)}
      onseeked={() => (position = element?.currentTime ?? position)}
      onplay={() => (playing = true)}
      onpause={() => (playing = false)}
      onended={() => (playing = false)}
    ></audio>
  {/if}

  <div class="row wrap tools">
    <button class="ghost tiny" data-waveform-toggle onclick={toggle}>
      {open ? 'Hide waveform' : 'Waveform'}
    </button>
    {#if open}
      <span class="mono small" data-loop-readout>
        A {loop.start === null ? '—' : formatClock(loop.start)}
        · B {loop.end === null ? '—' : formatClock(loop.end)}
      </span>
      <button class="ghost tiny" data-set-a onclick={() => mark('start')}>Set A</button>
      <button class="ghost tiny" data-set-b onclick={() => mark('end')}>Set B</button>
      <!--
        Both of these stay in the layout, disabled while they do not apply.
        Hiding and revealing them reflowed the toolbar, and that reflow moved the
        waveform *while the cursor was over it* — the next click landed on a
        button instead of on the picture. A control that moves under the pointer
        is worse than one that is greyed out.
      -->
      <button
        class="ghost tiny"
        data-play-loop
        disabled={!looping}
        onclick={() => {
          seek(loop.start as number);
          void element?.play();
        }}>Loop A–B</button
      >
      <button
        class="ghost tiny"
        data-clear-loop
        disabled={loop.start === null && loop.end === null}
        onclick={() => onLoop({ start: null, end: null })}>Clear</button
      >
      <label class="row toggle">
        <span class="muted small">Speed</span>
        <select
          aria-label="Playback speed"
          value={rate}
          onchange={(event) => setRate(Number((event.currentTarget as HTMLSelectElement).value))}
        >
          {#each [1, 0.85, 0.7, 0.5] as option (option)}
            <option value={option}>{option === 1 ? 'normal' : `${option}×`}</option>
          {/each}
        </select>
      </label>
    {/if}
  </div>

  {#if open && rate !== 1}
    <span class="muted small" data-rate-note={preservesPitch ? 'same-pitch' : 'lower-pitch'}>
      {preservesPitch ? 'slower, same pitch' : 'slower and lower — this browser cannot hold pitch'}
    </span>
  {/if}

  {#if open}
    {#if decoding}
      <p class="muted small">Reading the recording…</p>
    {:else if problem}
      <p class="muted small">{problem}</p>
    {:else if peaks}
      <Waveform
        {peaks}
        {loop}
        {position}
        {duration}
        onSeek={seek}
      />
      <p class="muted small">
        Click the picture to move the playhead, then Set A and Set B. With both
        markers set, playback stays inside them — saved with the recording, so the
        same passage is there from the other machine.
      </p>
    {/if}
  {/if}
</div>

<style>
  .player {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .player audio {
    width: 100%;
    height: 2.1rem;
  }

  .player video {
    width: 100%;
    max-height: 14rem;
    background: #000;
    border-radius: 6px;
  }

  .tools {
    align-items: center;
    gap: 0.4rem;
  }

  /* A waveform that decays into a picture on a phone-sized screen is useless
     for setting markers, so the readout wraps rather than the controls shrinking. */
  .tools .mono {
    font-variant-numeric: tabular-nums;
  }
</style>
