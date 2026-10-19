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
    type PedalPoint,
    type SynthNote,
  } from '../lib/playback';
  import { formatClock, parseClock } from '../lib/clock';
  import { PRACTICE_KINDS, kindCounts, practiceKindLabel } from '../lib/kinds';
  import { pieceColorSlots, segmentAtMs, segmentStep, seekPlan, stripTicks } from '../lib/timelineStrip';
  import type { StripRange } from '../lib/timelineStrip';
  import { pieceLabel, uniquePieceLabels } from '../lib/pieceLabel';
  import {
    type PieceSummary,
    type PracticeKind,
    type PracticePassage,
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
    /** Label every attempt of one passage at once. */
    onlabelpassage: (attemptIds: number[], pieceId: number | null) => void;
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
    onlabelpassage,
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
   * The colour slot each piece in this sitting owns.
   *
   * Built from the whole sitting rather than per block, so a clash between two of its pieces is
   * resolved once. Two pieces wearing one colour is the ambiguity the colours exist to remove,
   * and a coincidence of ids is not something the player can see.
   */
  const pieceSlots = $derived(
    pieceColorSlots(
      detail.segments
        .map((segment) => segment.piece_id)
        .filter((id): id is number => id !== null),
    ),
  );

  /** The `--piece-N` token for a piece, or null when there is no piece to colour. */
  function pieceColor(pieceId: number | null): string | null {
    if (pieceId === null) return null;
    const slot = pieceSlots.get(pieceId);
    return slot === undefined ? null : `var(--piece-${slot + 1})`;
  }

  /**
   * What each piece in this library is called, guaranteed not to repeat.
   *
   * Built once from the whole library rather than per row: two pieces can share a title — two
   * Beethoven sonatas are both "Sonata" — and whether a label needs its catalogue number to be
   * told apart is a fact about the list, not about the row. The picker, the "Maybe" buttons and
   * the passage heading all read it, so they cannot disagree about what a piece is called.
   */
  const pieceNames = $derived(uniquePieceLabels(pieces, (piece) => piece.id));

  /**
   * The name of one piece, from the library's own label when it has one.
   *
   * The fallback composes from the row's own fields, so a label whose piece was deleted — or has
   * not arrived in the library list yet — still reads as a name instead of as "unidentified".
   */
  function nameOf(
    pieceId: number | null,
    fields: { title: string | null; composer_name?: string | null; opus?: string | null },
  ): string | null {
    if (pieceId === null) return null;
    return (
      pieceNames.get(pieceId) ??
      pieceLabel({ title: fields.title, composer_name: fields.composer_name, opus: fields.opus })
    );
  }

  /** The label for a stored segment. */
  function segmentName(segment: SegmentSummary): string {
    return (
      nameOf(segment.piece_id, {
        title: segment.piece_title,
        composer_name: segment.composer_name,
        opus: segment.piece_opus,
      }) ?? 'unidentified'
    );
  }

  /**
   * The one shared player, so a Stop here also stops whatever else was sounding and
   * nothing can play over the top of anything else.
   */
  const player = app.player;
  /** Which range is sounding, in sitting-relative milliseconds, or null. */
  let playing = $state<{ fromMs: number; toMs: number; segmentId: number | null } | null>(null);
  /** Where the playhead is, in milliseconds, whether or not anything is playing. */
  let position = $state(0);
  /**
   * Whether a drag on the strip is in progress.
   *
   * While it is, the playhead belongs to the pointer rather than to the player, so the
   * progress callback is ignored — otherwise every drag would be fought by the tick that
   * reports where the sound still is.
   */
  let scrubbing = $state(false);
  let playError = $state<string | null>(null);
  let showRoll = $state(false);
  /**
   * The segment list, so a click on the strip can bring one card into view without the page
   * moving. Bound rather than looked up from the document, so the search stays inside this list.
   */
  let listElement = $state<HTMLElement | undefined>(undefined);
  /**
   * The segment the strip last sent you to, and the sitting it was in.
   *
   * Keyed on the sitting for the same reason the note cache is: this component is reused when
   * you pick another sitting, and a bare segment id would leave the wrong card ringed — or, when
   * the id belongs only to the sitting you left, none at all.
   */
  let chosen = $state<{ sittingId: number; segmentId: number } | null>(null);
  const chosenSegment = $derived(
    chosen !== null && chosen.sittingId === detail.id ? chosen.segmentId : null,
  );
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
  let notes = $state<{
    sittingId: number;
    /** Key-held, exactly as logged — what the piano is sent, with the pedal stream. */
    raw: SynthNote[];
    /** The same notes with the pedal applied, for the instruments with no damper. */
    pedalled: SynthNote[];
    /** The pedal at full resolution, for the piano's own damper. */
    pedals: PedalPoint[];
  } | null>(null);

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
    if (notes !== null && notes.sittingId === detail.id) return notes.pedalled;
    const body = await api.practice.sittingNotes(detail.id);
    // The pedal is applied to the whole sitting before any range is taken: a note
    // released under the pedal at the end of one segment must still be sounding
    // where the next one begins, and slicing first would cut that off. The raw list
    // and the pedal stream are kept beside it, because the piano is sent those
    // instead — its own damper does the damping, exactly.
    const raw = loggedEvents(body.notes);
    const pedals = body.pedals ?? [];
    notes = { sittingId: detail.id, raw, pedalled: sustained(raw, pedals), pedals };
    return notes.pedalled;
  }

  /** The loaded notes for the sitting on screen, or none if they are not loaded. */
  const loadedNotes = $derived(notes !== null && notes.sittingId === detail.id ? notes.pedalled : []);

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
      // Both halves go to the player, which decides what each instrument gets: the
      // piano takes the key-held notes plus the CC64 stream, the sampler and synth
      // take the pedal-lengthened notes.
      const loaded = notes;
      await player.play(loaded?.sittingId === detail.id ? loaded.raw : all, {
        from: start / 1000,
        until: toMs / 1000,
        pedals: loaded?.sittingId === detail.id ? loaded.pedals : [],
        onProgress: (handle) => {
          // The pointer owns the playhead while it is down, so a drag is not undone by the
          // tick that reports where the sound still is.
          if (!scrubbing) position = handle.elapsed * 1000;
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

  /**
   * Act on a press on the strip: the playhead follows it, the list follows the playhead, and
   * whether anything is heard is decided by `seekPlan` rather than here.
   *
   * The rule is that the sound follows the sound. With silence the press only places the
   * playhead, which is how the strip is used to look around without making a noise. With
   * something playing the press moves the playback, because otherwise it would appear to do
   * nothing: the player's next progress tick puts the playhead back where the sound actually is.
   */
  function applySeek(atMs: number, fallback: StripRange | null): void {
    const plan = seekPlan(
      playing,
      total,
      atMs,
      segmentAtMs(detail.segments, atMs),
      fallback,
    );
    moveTo(plan.atMs);
    if (plan.resume === null) return;
    // The awaited fetch is deliberate: a seek is a fresh start of the transport, and the
    // player reports its own errors through `playError`.
    void play(plan.resume.fromMs, plan.resume.toMs, plan.resume.segmentId, plan.atMs);
  }

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
    scrubbing = true;
    moveTo(ratioAt(event) * total);
  }

  function onStripPointerMove(event: PointerEvent): void {
    if (!scrubbing) return;
    moveTo(ratioAt(event) * total);
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
    scrubbing = false;
    const strip = event.currentTarget as HTMLElement;
    if (strip.hasPointerCapture(event.pointerId)) strip.releasePointerCapture(event.pointerId);
  }

  /** Put the playhead at `atMs`, and bring the segment it belongs to into view. */
  function moveTo(atMs: number): void {
    position = Math.min(total, Math.max(0, atMs));
    const target = segmentAtMs(detail.segments, position);
    if (target !== null) reveal(target.id);
    // The falling notes draw a window around the playhead and the notes load on first use, so a
    // seek before any playback has to fetch them or the roll would draw an empty window.
    if (showRoll) {
      void loadNotes().catch((cause) => {
        playError = cause instanceof Error ? cause.message : String(cause);
      });
    }
  }

  /**
   * Bring a segment's card into the list's view.
   *
   * `scrollTop` on the list itself, rather than `card.scrollIntoView()`: that walks *every*
   * scrollable ancestor, so it moves the page too — which is the thing this must not do, because
   * the falling notes sit above the list and a page that jumps under the pointer takes the strip
   * away from where it was clicked.
   */
  function reveal(segmentId: number): void {
    chosen = { sittingId: detail.id, segmentId };
    const list = listElement;
    if (list === undefined) return;
    const card = list.querySelector<HTMLElement>(`[data-segment="${segmentId}"]`);
    if (card === null) return;
    const listBox = list.getBoundingClientRect();
    const cardBox = card.getBoundingClientRect();
    const centred =
      list.scrollTop + (cardBox.top - listBox.top) - (list.clientHeight - cardBox.height) / 2;
    list.scrollTop = Math.max(0, Math.min(centred, list.scrollHeight - list.clientHeight));
  }

  /**
   * Move the playhead by a fixed step.
   *
   * A keyboard step follows the same rule as a press: it seeks the playback when something is
   * playing and stays silent when nothing is. It is not a transport action of its own.
   */
  function seekBy(seconds: number): void {
    applySeek(position + seconds * 1000, null);
  }

  /** The whole sitting, which is what a transport button resumes when nothing else was playing. */
  const wholeSitting = $derived<StripRange>({ fromMs: 0, toMs: total, segmentId: null });

  /**
   * Move the playhead by a fixed step and keep listening.
   *
   * A transport button that moved the playhead and left it silent would be a dead button, and
   * the range that was playing is the one it resumes.
   */
  function jump(bySeconds: number): void {
    applySeek(position + bySeconds * 1000, wholeSitting);
  }

  /**
   * Skip a whole segment, in either direction.
   *
   * The segment is the unit this screen is drawn in, so it is the unit for skipping: the
   * 30-second buttons cannot cross a two-hour sitting at a usable speed, and they do not land
   * where the player thinks in boundaries.
   */
  function stepSegment(direction: 1 | -1): void {
    applySeek(segmentStep(detail.segments, position, direction, total), wholeSitting);
  }

  /** The clock labels under the strip, so a press is aimed rather than guessed. */
  const ticks = $derived(stripTicks(total, 4));

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

  /** Where an attempt sits in the stored order, for the "merge with previous" control. */
  const segmentIndex = $derived(
    new Map(detail.segments.map((segment, index) => [segment.id, index])),
  );

  /**
   * The rows the timeline draws: a piece-session heading, then a passage, then its attempts.
   *
   * The passage is the row the player thinks in — "six goes at this bit" — and the attempts stay
   * the `.segment` elements, because they are what every edit and every test hook acts on. A
   * segment the server did not place in any passage is still drawn: an attempt must never vanish
   * from the log because a derivation did not place it.
   */
  const rows = $derived.by(() => {
    const found = detail.passages ?? [];
    if (found.length === 0) {
      return detail.segments.map((segment) => ({
        kind: 'segment' as const,
        key: `segment-${segment.id}`,
        segment,
      }));
    }

    const byId = new Map(detail.segments.map((segment) => [segment.id, segment]));
    const drawn: Array<
      | { kind: 'session'; key: string; session: number; piece: string | null; pieceId: number | null }
      | { kind: 'passage'; key: string; passage: PracticePassage }
      | { kind: 'segment'; key: string; segment: SegmentSummary }
    > = [];
    let session = -1;
    for (const passage of found) {
      if (passage.session !== session) {
        session = passage.session;
        drawn.push({
          kind: 'session',
          key: `session-${passage.session}`,
          session: passage.session,
          piece: nameOf(passage.piece_id, {
            title: passage.piece_title,
            composer_name: passage.composer_name,
            opus: passage.piece_opus,
          }),
          pieceId: passage.piece_id,
        });
      }
      drawn.push({
        kind: 'passage',
        key: `passage-${passage.attempt_ids[0] ?? passage.start_ms}`,
        passage,
      });
      for (const id of passage.attempt_ids) {
        const segment = byId.get(id);
        if (segment) drawn.push({ kind: 'segment', key: `segment-${id}`, segment });
      }
    }

    const placed = new Set(found.flatMap((passage) => passage.attempt_ids));
    for (const segment of detail.segments) {
      if (!placed.has(segment.id)) {
        drawn.push({ kind: 'segment', key: `segment-${segment.id}`, segment });
      }
    }
    return drawn;
  });
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
      <!-- Always present, disabled until there is somewhere to start from: a button that
           appeared on the first drag would reflow the row above the strip and move the strip
           out from under the pointer mid-scrub. -->
      <button
        class="ghost tiny"
        data-play-from-here
        disabled={detail.note_count === 0 || position <= 0 || position >= total - 1}
        title="Play from where the playhead is, to the end of the sitting"
        onclick={() => applySeek(position, wholeSitting)}
      >
        ▶ From here
      </button>
    {/if}

    <span class="row jump">
      <button
        class="ghost tiny"
        data-step-segment-back
        disabled={detail.note_count === 0 || detail.segments.length === 0}
        title="Back to the start of this segment, or to the previous one"
        onclick={() => stepSegment(-1)}
      >
        « segment
      </button>
      <button
        class="ghost tiny"
        data-step-segment-forward
        disabled={detail.note_count === 0 || detail.segments.length === 0}
        title="On to the start of the next segment"
        onclick={() => stepSegment(1)}
      >
        segment »
      </button>
    </span>

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
      Press or drag the strip to move through the sitting — silent until something is playing, and
      a press while listening carries the sound with it.
      Played through
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
    <!-- A slider, not a picture: the strip sets the position, so it takes focus and the arrow
         keys move the playhead the way the pointer does. What the position costs is decided by
         whether anything is playing: silent when nothing is, a seek when something is. -->
    <div
      class="strip"
      role="slider"
      tabindex="0"
      aria-label="Sitting timeline — press or drag, or use the arrow keys, Page Up/Down and Home/End, to move to a point; the segment list below follows"
      aria-valuemin="0"
      aria-valuemax={Math.round(detail.duration_s)}
      aria-valuenow={Math.round(position / 1000)}
      data-strip
      onpointerdown={onStripPointerDown}
      onpointermove={onStripPointerMove}
      onpointerup={onStripPointerUp}
      onpointercancel={onStripPointerUp}
      onclick={(event) => applySeek(ratioAt(event) * total, null)}
      onkeydown={(event) => {
        if (event.key === 'ArrowRight') seekBy(5);
        else if (event.key === 'ArrowLeft') seekBy(-5);
        // Five minutes a press, because the arrows are for the passage and this is for the
        // sitting: crossing two hours at five seconds a press is not navigation.
        else if (event.key === 'PageUp') seekBy(300);
        else if (event.key === 'PageDown') seekBy(-300);
        else if (event.key === 'Home') applySeek(0, null);
        else if (event.key === 'End') applySeek(total, null);
        else return;
        // The slider consumes the key it handles. Without this, Home and End would also scroll
        // the document out from under the strip the player is aiming at.
        event.preventDefault();
      }}
    >
      {#each detail.segments as segment (segment.id)}
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
      {#each detail.review_marks_ms ?? [] as markMs (markMs)}
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
        <span class="playhead" data-playhead style="left: {playhead.at}%"></span>
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

    <ul class="segments" bind:this={listElement}>
      {#each rows as row (row.key)}
        {#if row.kind === 'session'}
          {@const tint = pieceColor(row.pieceId)}
          <li class="piece-session" data-piece-session={row.session}>
            <span class="muted small">about</span>
            {#if tint}
              <span class="swatch" style="background: {tint}" aria-hidden="true"></span>
            {/if}
            <strong>{row.piece ?? 'unidentified'}</strong>
          </li>
        {:else if row.kind === 'passage'}
          {@const tint = pieceColor(row.passage.piece_id)}
          <li class="passage" data-passage={row.passage.attempt_ids[0] ?? row.passage.start_ms}>
            <div class="head row wrap">
              <span class="pill mono">
                {row.passage.attempts}
                {row.passage.attempts === 1 ? 'attempt' : 'attempts'}
              </span>
              <span class="mono range">
                {offset(row.passage.start_ms)}–{offset(row.passage.end_ms)}
              </span>
              {#if tint}
                <span class="swatch" style="background: {tint}" aria-hidden="true"></span>
              {/if}
              <strong>{row.passage.piece_id === null
                ? 'unidentified'
                : nameOf(row.passage.piece_id, {
                    title: row.passage.piece_title,
                    composer_name: row.passage.composer_name,
                    opus: row.passage.piece_opus,
                  })}</strong>
            </div>
            <!-- Labelling the passage labels every member attempt: the label lives on the
                 segments, so this is the route that already exists sent once per member, and
                 there is no group to keep in step with them. -->
            <div class="row wrap controls">
              <select
                aria-label="Piece for this passage"
                disabled={busy}
                value={row.passage.piece_id ?? ''}
                onchange={(event) => {
                  const value = (event.currentTarget as HTMLSelectElement).value;
                  onlabelpassage(
                    row.passage.attempt_ids,
                    value === '' ? null : Number(value),
                  );
                }}
              >
                <option value="">— label all {row.passage.attempts} —</option>
                {#each pieces as piece (piece.id)}
                  <option value={piece.id}>{pieceNames.get(piece.id) ?? pieceLabel(piece)}</option>
                {/each}
              </select>
              <span class="muted small">
                one decision for the whole passage — it writes to each attempt below
              </span>
            </div>
          </li>
        {:else}
          {@const segment = row.segment}
          {@const index = segmentIndex.get(segment.id) ?? 0}
          {@const tint = pieceColor(segment.piece_id)}
        <li
          class="segment"
          class:selected={chosenSegment === segment.id}
          data-segment={segment.id}
        >
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
                title="Times the pedal crossed its threshold. MIDI's own rule: below 64 is up, so a part-depressed pedal is not counted as a change here"
              >
                {segment.metrics.pedal_changes} pedal
              </span>
              {#if segment.metrics.pedal_partial_ratio}
                <!-- The third state a continuous pedal has. Disjoint from the down
                     ratio, so this plus a fully-down share describes the span once,
                     not twice — and playback uses the position to ring on in
                     proportion, which is what makes it worth showing. -->
                <span
                  class="pill mono"
                  data-pedal-partial={segment.metrics.pedal_partial_ratio}
                  title="Share of this segment spent with the damper part-way down — a position an on/off pedal cannot report. Playback rings a note on in proportion to it; the sampler's version of that is an approximation, the piano's own damper is not"
                >
                  {percent(segment.metrics.pedal_partial_ratio)} half-pedalled
                </span>
              {/if}
              {#if segment.metrics.pedal_blur}
                <span
                  class="pill warn"
                  data-pedal-blur={segment.metrics.pedal_blur}
                  title="Attacks that brought new harmony over notes the pedal was already holding. Observed from the pitches, not from a score — it reports, it does not judge. At {segment.metrics.pedal_blur_ms
                    .map((ms) => formatClock(ms / 1000))
                    .join(', ')}"
                >
                  {segment.metrics.pedal_blur} pedal blur
                </span>
                <!-- The strip says where to look; this says what you are looking at. Capped at
                     four times because a segment can hold nine, and nine clock times in a row is
                     a wall of digits rather than a hint. The positions are sitting-relative, the
                     same as the strip's axis — see the marker above for why that matters. -->
                <span class="muted small" data-blur-where={segment.id}>
                  at {segment.metrics.pedal_blur_ms
                    .slice(0, 4)
                    .map((ms) => formatClock(ms / 1000))
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
            <!-- Two candidates can share a title — "Sonata" twice — so the guesses are named by
                 the same rule as the picker below, and the confidence does not have to carry the
                 whole burden of telling them apart. -->
            {@const candidateNames = uniquePieceLabels(
              segment.candidates,
              (candidate) => candidate.piece_id,
            )}
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
                  {candidateNames.get(candidate.piece_id) ?? pieceLabel(candidate)}{candidate.from_context
                    ? ' · this sitting'
                    : ''} · {percent(candidate.score)}
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
            {#if tint}
              <!-- The key to the strip: the colour this segment's block is drawn in. Beside the
                   control that names the piece, because a colour on its own is not a label. -->
              <span class="swatch" style="background: {tint}" aria-hidden="true"></span>
            {/if}
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
                <option value={piece.id}>{pieceNames.get(piece.id) ?? pieceLabel(piece)}</option>
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
        {/if}
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

  /* Where the strip last sent you. Without it, a click whose card was already on screen would
     look like it had done nothing at all. */
  .segment.selected {
    outline: 2px solid var(--accent);
    outline-offset: -1px;
  }

  /* The key to the strip: the same colour the block is drawn in, beside the name it belongs to.
     Decorative, because the name is the label — nothing here is signalled by colour alone. */
  .swatch {
    display: inline-block;
    flex: none;
    width: 0.7rem;
    height: 0.7rem;
    border-radius: 2px;
  }

  /* The heading above a run of passages about one piece: "what this sitting was about". */
  .piece-session {
    display: flex;
    align-items: baseline;
    gap: 0.4rem;
    margin-top: 0.5rem;
    padding-bottom: 0.2rem;
    border-bottom: 1px solid var(--line);
  }

  /* The row the player thinks in. The attempts it groups are the .segment cards beneath. */
  .passage {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 0.45rem 0.55rem;
    border: 1px solid var(--accent);
    border-radius: 8px;
    background: var(--surface);
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
