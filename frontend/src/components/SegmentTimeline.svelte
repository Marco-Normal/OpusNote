<script lang="ts">
  /**
   * One sitting, broken into the pieces (or the workout) it contained.
   *
   * The boundaries are stored, never recomputed on read, so everything here is a
   * deliberate edit: tag a segment, split a boundary the silence detector got
   * wrong, merge two it split, or throw the boundaries away and start again.
   */
  import { api } from '../lib/api';
  import { app } from '../lib/state.svelte';
  import PianoRoll from './PianoRoll.svelte';
  import {
    loggedEvents,
    sustained,
    within,
    type SynthNote,
  } from '../lib/playback';
  import { formatClock, parseClock } from '../lib/clock';
  import { PRACTICE_KINDS, kindCounts, practiceKindLabel } from '../lib/kinds';
  import {
    type PieceSummary,
    type PracticeKind,
    type SegmentMetrics,
    type SegmentSummary,
    type SittingDetail,
  } from '../lib/types';

  interface Props {
    detail: SittingDetail;
    pieces: PieceSummary[];
    busy: boolean;
    onassign: (segmentId: number, pieceId: number | null) => void;
    onkinds: (
      segmentId: number,
      body: { action: 'set' | 'accept' | 'decline'; kind?: PracticeKind | null },
    ) => void;
    onsplit: (segmentId: number, atMs: number) => void;
    onmerge: (segmentId: number, otherId: number) => void;
    onresegment: (confirm: boolean) => void;
    /** Answer the matcher: it was right, it was wrong, or stop asking. */
    onidentify: (segmentId: number, action: 'accept' | 'reject' | 'dismiss') => void;
  }

  let {
    detail,
    pieces,
    busy,
    onassign,
    onkinds,
    onsplit,
    onmerge,
    onresegment,
    onidentify,
  }: Props = $props();

  /** A segment the matcher wrote, rather than one you did. */
  const inferred = (segment: SegmentSummary): boolean => segment.identified_by === 'similarity';

  /**
   * A suggestion is only worth showing when the matcher is actually putting a
   * name forward. A "none" band means it looked and found nothing close, and
   * listing the least-bad three anyway would be inviting a guess it has just
   * declined to make.
   */
  const suggested = (segment: SegmentSummary): boolean =>
    segment.piece_id === null && segment.candidates.length > 0 && segment.candidates[0].band === 'suggest';

  const percent = (value: number): string => `${Math.round(value * 100)}%`;

  /**
   * The arithmetic for a journal draft, in one line.
   *
   * The prose box stays empty when the entry opens: the app has no language model and
   * will not put words in the player's mouth. What a draft carries is the numbers
   * that are already stored and are tedious to recall a day later.
   */
  function measuredSummary(segment: SegmentSummary): string {
    const parts: string[] = [];
    const minutes = (segment.end_ms - segment.start_ms) / 60_000;
    if (minutes > 0) parts.push(`${minutes.toFixed(1)} min`);
    if (segment.metrics?.median_tempo) {
      parts.push(`${Math.round(segment.metrics.median_tempo)} BPM note rate`);
    }
    if (segment.metrics?.restarts) parts.push(`${segment.metrics.restarts} restarts`);
    return parts.join(' · ') || `${segment.note_count} notes`;
  }

  /**
   * Which half of the keyboard was played more firmly.
   *
   * Worded as registers, not as hands, because that is what it measures: the piano
   * sends both hands on a single MIDI channel, so a passive log cannot separate them,
   * and in crossed or single-hand writing the register does not follow the hand at
   * all. It reports; it does not judge.
   */
  function balanceLabel(metrics: SegmentMetrics): string | null {
    const low = metrics.mean_velocity_low;
    const high = metrics.mean_velocity_high;
    if (!low || !high) return null;
    const gap = Math.round(((low - high) / Math.max(low, high)) * 100);
    if (Math.abs(gap) < 8) return 'registers even';
    return gap > 0 ? `lower half +${gap}%` : `upper half ${gap}%`;
  }

  /** Split points, in seconds from the sitting start, keyed by segment. */
  let splitAt = $state<Record<number, string>>({});

  const total = $derived(Math.max(detail.duration_s * 1000, 1));

  /**
   * The one shared player, so a Stop here also stops whatever else was sounding and
   * nothing can play over the top of anything else.
   */
  const player = app.player;
  /** Which range is sounding, in sitting-relative milliseconds, or null. */
  let playing = $state<{ fromMs: number; toMs: number; segmentId: number | null } | null>(null);
  /** Where the playhead is, in milliseconds, whether or not anything is playing. */
  let position = $state(0);
  let playError = $state<string | null>(null);
  let showRoll = $state(false);
  // Notes are fetched on the first play rather than with the detail: a long sitting is
  // thousands of notes, and every segment edit re-reads the detail without needing one.
  /**
   * The sitting's notes, tagged with the sitting they came from.
   *
   * `$state` because the falling-notes view reads it from the template. Tagged with
   * the id because this component is reused when you pick another sitting: a cache
   * that was not keyed on it played the *previous* sitting's notes — a real bug, and
   * one that only shows up on the second sitting you listen to.
   */
  let notes = $state<{ sittingId: number; list: SynthNote[] } | null>(null);

  /**
   * Where the playhead sits, as a fraction of the sitting.
   *
   * From the *reported position* rather than from the range being played, so seeking
   * into the middle of a two-hour sitting draws the line where you actually are.
   */
  const playhead = $derived({
    at: Math.min(100, (position / total) * 100),
    span: playing
      ? Math.max(0, ((playing.toMs - playing.fromMs) / total) * 100)
      : 0,
  });

  /** What is sounding, as a range of the sitting, for highlighting the strip. */
  const soundingRange = $derived(
    playing
      ? {
          left: (playing.fromMs / total) * 100,
          width: Math.max(0.6, ((playing.toMs - playing.fromMs) / total) * 100),
        }
      : null,
  );

  async function loadNotes(): Promise<SynthNote[]> {
    if (notes !== null && notes.sittingId === detail.id) return notes.list;
    const body = await api.practice.sittingNotes(detail.id);
    // The pedal is applied to the whole sitting before any range is taken: a note
    // released under the pedal at the end of one segment must still be sounding
    // where the next one begins, and slicing first would cut that off.
    const list = sustained(loggedEvents(body.notes), body.pedals ?? []);
    notes = { sittingId: detail.id, list };
    return list;
  }

  /** The loaded notes for the sitting on screen, or none if they are not loaded. */
  const loadedNotes = $derived(notes !== null && notes.sittingId === detail.id ? notes.list : []);

  /**
   * Play a range, optionally from a point inside it.
   *
   * `startAtMs` is what makes a two-hour sitting usable: the playhead starts where
   * you clicked, and the player skips everything before it. Without a start, the
   * playback begins at the first note *in the range* rather than at the range's
   * boundary — a segment's leading silence can be twenty seconds long, and waiting
   * it out is not what "play this segment" means.
   */
  async function play(
    fromMs: number,
    toMs: number,
    segmentId: number | null,
    startAtMs?: number,
  ): Promise<void> {
    playError = null;
    try {
      const all = await loadNotes();
      const slice = segmentId === null ? all : within(all, fromMs, toMs);
      if (slice.length === 0) {
        playError = 'Nothing was played in this range.';
        return;
      }
      const firstNoteMs = Math.min(...slice.map((note) => note.onset * 1000));
      const start = Math.min(
        Math.max(startAtMs ?? Math.max(fromMs, firstNoteMs), fromMs),
        Math.max(fromMs, toMs - 1),
      );
      playing = { fromMs, toMs, segmentId };
      position = start;
      await player.play(all, {
        from: start / 1000,
        until: toMs / 1000,
        onProgress: (handle) => {
          position = handle.elapsed * 1000;
        },
        onError: (message) => {
          playError = message;
        },
        onDone: () => {
          playing = null;
        },
      });
    } catch (cause) {
      playing = null;
      playError = cause instanceof Error ? cause.message : String(cause);
    }
  }

  /** Start playing from a click anywhere on the strip. */
  function seekTo(event: MouseEvent): void {
    const strip = event.currentTarget as HTMLElement;
    const bounds = strip.getBoundingClientRect();
    if (bounds.width <= 0) return;
    const ratio = Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width));
    void play(0, total, null, ratio * total);
  }

  /** Move the playhead by a fixed step, keeping whatever range was being played. */
  function jump(bySeconds: number): void {
    const target = Math.min(total, Math.max(0, position + bySeconds * 1000));
    void play(playing?.fromMs ?? 0, playing?.toMs ?? total, playing?.segmentId ?? null, target);
  }

  function stop(): void {
    player.stop();
    playing = null;
  }

  // The shared player outlives this component, so nothing is disposed here: only
  // the sound it is making is stopped, or a tab change would leave notes ringing.
  $effect(() => () => player.stop());

  function offset(ms: number): string {
    return formatClock(ms / 1000);
  }

  /**
   * The split point, shown as a clock rather than as a number of seconds.
   *
   * A two-hour sitting is 7200 seconds, and "5412.5" is not a position anybody can
   * picture. The field accepts either ("5412.5" or "1:30:12"), so a value that came
   * from here round-trips through `parseClock`.
   */
  function midpoint(segmentId: number, startMs: number, endMs: number): string {
    return splitAt[segmentId] ?? formatClock((startMs + endMs) / 2000);
  }

  function splitPointMs(segmentId: number, startMs: number, endMs: number): number | null {
    const raw = splitAt[segmentId] ?? formatClock((startMs + endMs) / 2000);
    const seconds = parseClock(raw);
    return seconds === null ? null : Math.round(seconds * 1000);
  }

  function submitSplit(segmentId: number, startMs: number, endMs: number): void {
    const at = splitPointMs(segmentId, startMs, endMs);
    if (at === null) {
      playError = 'That is not a time. Use seconds (5412) or a clock (1:30:12).';
      return;
    }
    onsplit(segmentId, at);
  }

  const labelled = $derived(detail.segments.filter((segment) => segment.piece_id !== null).length);
</script>

<section class="card timeline" data-segments={detail.segments.length}>
  <header class="spread wrap">
    <div class="row wrap">
      <h3>Sitting {detail.local_date}</h3>
      <span class="pill mono">{formatClock(detail.duration_s)}</span>
      <span class="pill">{detail.note_count} notes</span>
      {#if detail.source === 'sight_reading'}
        <span class="pill accent">sight-reading</span>
      {/if}
      {#if !detail.closed}
        <span class="pill warn">still open</span>
      {/if}
    </div>
    <button
      class="ghost tiny"
      disabled={busy}
      title="Recompute the boundaries from the notes, discarding them. Re-segmenting cannot be undone: the boundaries and labels it replaces are rebuilt from the notes."
      onclick={() => onresegment(labelled > 0)}
    >
      Re-segment{labelled > 0 ? ' (discards labels)' : ''}
    </button>
  </header>

  <div class="row wrap transport" data-playing={playing ? 'true' : 'false'}>
    {#if playing}
      <button class="ghost tiny" data-stop onclick={stop}>Stop</button>
      <span class="muted small">
        Playing {playing.segmentId === null ? 'the sitting' : 'this segment'}
      </span>
    {:else}
      <button
        class="ghost tiny"
        disabled={detail.note_count === 0}
        onclick={() => void play(0, total, null)}
      >
        Play the sitting
      </button>
    {/if}

    <span class="row jump">
      <button class="ghost tiny" disabled={detail.note_count === 0} onclick={() => jump(-30)}>
        « 30 s
      </button>
      <button class="ghost tiny" disabled={detail.note_count === 0} onclick={() => jump(30)}>
        30 s »
      </button>
    </span>

    <span class="pill mono" data-position>{formatClock(position / 1000)} / {formatClock(detail.duration_s)}</span>

    <label class="row toggle">
      <input type="checkbox" bind:checked={showRoll} data-roll-toggle />
      Falling notes
    </label>

    <span class="muted small">
      Click anywhere on the strip to start from there. Played through
      {app.instrument === 'midi'
        ? 'the piano itself'
        : app.instrument === 'piano'
          ? 'the sampled piano'
          : 'the synthesiser'}
      — timing and touch are yours.
    </span>
  </div>

  {#if showRoll}
    <PianoRoll notes={loadedNotes} position={position / 1000} />
    {#if loadedNotes.length === 0}
      <p class="muted small">The notes load with the first playback.</p>
    {/if}
  {/if}

  {#if playError}
    <p class="error-banner small">{playError}</p>
  {/if}

  {#if detail.segments.length === 0}
    <p class="muted small">
      {detail.closed
        ? 'No segments — nothing to split.'
        : 'Boundaries appear once this sitting has been quiet for five minutes.'}
    </p>
  {:else}
    <!-- A slider, not a picture: the strip is the sitting's transport, so it takes
         focus and the arrow keys move the playhead the way the pointer does. -->
    <div
      class="strip"
      role="slider"
      tabindex="0"
      aria-label="Sitting timeline — click or press the arrow keys to play from a point"
      aria-valuemin="0"
      aria-valuemax={Math.round(detail.duration_s)}
      aria-valuenow={Math.round(position / 1000)}
      data-strip
      onclick={seekTo}
      onkeydown={(event) => {
        if (event.key === 'ArrowRight') jump(5);
        if (event.key === 'ArrowLeft') jump(-5);
      }}
    >
      {#each detail.segments as segment (segment.id)}
        <span
          class="block"
          class:labelled={segment.piece_id !== null}
          class:sight={segment.source === 'sight_reading'}
          style="left: {(segment.start_ms / total) * 100}%; width: {Math.max(
            0.6,
            ((segment.end_ms - segment.start_ms) / total) * 100,
          )}%"
          title="{segment.piece_title ?? 'unidentified'} · {formatClock(
            (segment.end_ms - segment.start_ms) / 1000,
          )} · click to play from here"
        ></span>
        {#each segment.metrics?.pedal_blur_ms ?? [] as blurMs (blurMs)}
          <!-- A hairline per blur, so a long sitting can be searched by eye. The count
               says whether to look; these say where. -->
          <span
            class="blur"
            data-blur={blurMs}
            style="left: {((segment.start_ms + blurMs) / total) * 100}%"
            title="Pedal blur at {formatClock(
              (segment.start_ms + blurMs) / 1000,
            )} — new harmony arrived while the pedal was holding notes from before"
          ></span>
        {/each}
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
        <span class="playhead" data-playhead style="left: {playhead.at}%"></span>
      {/if}
    </div>

    <ul class="segments">
      {#each detail.segments as segment, index (segment.id)}
        <li class="segment">
          <div class="head row wrap">
            <span class="mono range">{offset(segment.start_ms)}–{offset(segment.end_ms)}</span>
            <span class="muted small">{segment.note_count} notes</span>
            {#if segment.metrics?.median_tempo}
              <span class="pill mono">{Math.round(segment.metrics.median_tempo)} BPM</span>
            {/if}
            {#if segment.metrics?.restarts}
              <span class="pill warn" title="Silences long enough to read as starting again">
                {segment.metrics.restarts} restarts
              </span>
            {/if}
            {#if segment.metrics?.pedal_basis}
              <span
                class="pill mono"
                data-pedal-changes={segment.metrics.pedal_changes}
                title="Times the pedal crossed its threshold. MIDI's own rule: below 64 is up, so a half-depressed pedal reads as released"
              >
                {segment.metrics.pedal_changes} pedal
              </span>
              {#if segment.metrics.pedal_blur}
                <span
                  class="pill warn"
                  data-pedal-blur={segment.metrics.pedal_blur}
                  title="Attacks that brought new harmony over notes the pedal was already holding. Observed from the pitches, not from a score — it reports, it does not judge. At {segment.metrics.pedal_blur_ms
                    .map((ms) => formatClock((segment.start_ms + ms) / 1000))
                    .join(', ')}"
                >
                  {segment.metrics.pedal_blur} pedal blur
                </span>
                <!-- The strip says where to look; this says what you are looking at. Capped at
                     four times because a segment can hold nine, and nine clock times in a row is
                     a wall of digits rather than a hint. -->
                <span class="muted small" data-blur-where={segment.id}>
                  at {segment.metrics.pedal_blur_ms
                    .slice(0, 4)
                    .map((ms) => formatClock((segment.start_ms + ms) / 1000))
                    .join(', ')}{segment.metrics.pedal_blur_ms.length > 4 ? ' …' : ''}
                </span>
              {/if}
            {:else if segment.metrics}
              <span
                class="muted small"
                data-pedal-unrecorded
                title="This sitting has no pedal events at all — imported history. Not the same as a pedal that was never pressed"
              >
                pedal not recorded
              </span>
            {/if}
            {#if segment.metrics?.median_velocity != null}
              <span
                class="pill mono"
                title="Middle velocity, at MIDI controller resolution — comparable with itself over weeks, not a measure of loudness"
              >
                {Math.round(segment.metrics.median_velocity)} vel
              </span>
            {/if}
            {#if segment.metrics && balanceLabel(segment.metrics)}
              <span
                class="pill"
                title="Mean velocity below and above middle C. A proxy for the hands, not a measurement of them — the piano sends both hands on one channel"
              >
                {balanceLabel(segment.metrics)}
              </span>
            {/if}
            {#if segment.source === 'sight_reading'}
              <span class="pill accent">
                {segment.workout_id ? `workout ${segment.workout_id}` : 'sight-reading'}
              </span>
            {/if}
            {#if segment.practice_kind && kindCounts(segment.practice_kind_basis)}
              <span
                class="pill"
                data-kind={segment.practice_kind}
                title="How this segment was practised — said by you, not inferred"
              >
                {practiceKindLabel(segment.practice_kind)}
              </span>
            {/if}
            {#if segment.piece_id}
              <button
                class="ghost tiny"
                data-write-about={segment.id}
                title="Write a journal entry about this piece and this session"
                onclick={() =>
                  app.writeAboutSitting(
                    segment.piece_id as number,
                    detail.id,
                    measuredSummary(segment),
                  )}
              >
                Write about this
              </button>
            {/if}
          </div>

          {#if inferred(segment)}
            <div class="row wrap inferred" data-inferred={segment.id}>
              <span
                class="pill accent"
                title="Written by the matcher from your own tagged practice — not by you"
              >
                guessed{segment.confidence !== null ? ` · ${percent(segment.confidence)}` : ''}
              </span>
              <button class="ghost tiny" disabled={busy} onclick={() => onidentify(segment.id, 'accept')}>
                It's right
              </button>
              <button class="ghost tiny" disabled={busy} onclick={() => onidentify(segment.id, 'reject')}>
                Not this
              </button>
              <span class="muted small">
                or correct it below — either way the answer improves the next guess
              </span>
            </div>
          {:else if suggested(segment)}
            <div class="row wrap suggest" data-suggest={segment.id}>
              <span class="muted small">Maybe</span>
              {#each segment.candidates as candidate (candidate.piece_id)}
                <button
                  class="ghost tiny"
                  disabled={busy}
                  data-candidate={candidate.piece_id}
                  title="notes {percent(candidate.pitch_class)} · tempo {percent(
                    candidate.tempo,
                  )} · register {percent(candidate.register_overlap)}"
                  onclick={() => onassign(segment.id, candidate.piece_id)}
                >
                  {candidate.title}{candidate.from_context ? ' · this sitting' : ''} · {percent(
                    candidate.score,
                  )}
                </button>
              {/each}
              <button class="ghost tiny" disabled={busy} onclick={() => onidentify(segment.id, 'dismiss')}>
                Neither
              </button>
              {#if segment.candidates[0].reason}
                <span class="muted small">{segment.candidates[0].reason}</span>
              {/if}
            </div>
          {/if}

          {#if segment.practice_kind_basis === 'offered' && segment.practice_kind}
            <div class="row wrap suggest" data-kind-offer={segment.id}>
              <span class="muted small">{practiceKindLabel(segment.practice_kind)} practice?</span>
              <button
                class="ghost tiny"
                disabled={busy}
                onclick={() => onkinds(segment.id, { action: 'accept' })}
              >
                Yes
              </button>
              <button
                class="ghost tiny"
                disabled={busy}
                onclick={() => onkinds(segment.id, { action: 'decline' })}
              >
                No
              </button>
              <span class="muted small">
                from the tempo and the restarts — not from a score, and it counts for nothing
                until you say so
              </span>
            </div>
          {/if}

          <div class="row wrap controls">
            <select
              aria-label="Piece for this segment"
              disabled={busy}
              value={segment.piece_id ?? ''}
              onchange={(event) => {
                const value = (event.currentTarget as HTMLSelectElement).value;
                onassign(segment.id, value === '' ? null : Number(value));
              }}
            >
              <option value="">— unidentified —</option>
              {#each pieces as piece (piece.id)}
                <option value={piece.id}>
                  {piece.title}{piece.composer_name ? ` · ${piece.composer_name}` : ''}
                </option>
              {/each}
            </select>

            <select
              aria-label="How this segment was practised"
              disabled={busy}
              value={segment.practice_kind && kindCounts(segment.practice_kind_basis)
                ? segment.practice_kind
                : ''}
              onchange={(event) => {
                const value = (event.currentTarget as HTMLSelectElement).value;
                onkinds(segment.id, {
                  action: 'set',
                  kind: value === '' ? null : (value as PracticeKind),
                });
              }}
            >
              <option value="">— how practised? —</option>
              {#each PRACTICE_KINDS as entry (entry.id)}
                <option value={entry.id}>{entry.label}</option>
              {/each}
            </select>

            <span class="row split">
              <label class="muted small" for="split-{segment.id}">Split at</label>
              <input
                id="split-{segment.id}"
                type="text"
                inputmode="numeric"
                class="mono at"
                aria-label="Split point as seconds or m:ss"
                title="Where to cut this segment in two — seconds from the start of the sitting, or m:ss"
                value={midpoint(segment.id, segment.start_ms, segment.end_ms)}
                oninput={(event) => {
                  splitAt[segment.id] = (event.currentTarget as HTMLInputElement).value;
                }}
              />
              <button
                class="ghost tiny"
                disabled={busy}
                onclick={() => submitSplit(segment.id, segment.start_ms, segment.end_ms)}
              >
                Split here
              </button>
            </span>

            {#if index > 0}
              <button
                class="ghost tiny"
                disabled={busy}
                onclick={() => onmerge(segment.id, detail.segments[index - 1].id)}
              >
                Merge with previous
              </button>
            {/if}

            <button
              class="ghost tiny"
              disabled={busy || segment.note_count === 0}
              title="Hear this segment"
              onclick={() =>
                void play(
                  segment.start_ms,
                  segment.end_ms,
                  segment.id,
                )}
            >
              ▶ {segment.note_count} notes
            </button>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .timeline {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    padding: 0.75rem 0.85rem;
  }

  h3 {
    font-size: 0.95rem;
  }

  .strip {
    position: relative;
    height: 18px;
    border-radius: 6px;
    background: var(--track);
    overflow: hidden;
  }

  .block {
    position: absolute;
    top: 0;
    bottom: 0;
    background: var(--muted);
    opacity: 0.55;
    border-right: 1px solid var(--surface);
  }

  .block.labelled {
    background: var(--good);
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

  .playhead {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--ink);
    box-shadow: 0 0 0 1px var(--surface);
  }

  .transport {
    gap: 0.45rem;
  }

  .block.sight {
    background: var(--accent);
    opacity: 0.85;
  }

  .segments {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    max-height: 26rem;
    overflow-y: auto;
  }

  .segment {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 0.45rem 0.55rem;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: var(--surface-2);
  }

  .range {
    font-size: 0.84rem;
  }

  .controls {
    gap: 0.45rem;
  }

  select {
    max-width: 16rem;
  }

  .split {
    gap: 0.3rem;
  }

  .at {
    width: 5.2rem;
  }

  .small {
    font-size: 0.78rem;
  }
</style>
