/**
 * The two rules that keep a background refresh from becoming its own outage.
 *
 * The Log view polls so a sitting appears without pressing F5. That is worth a cheap read every
 * twenty seconds, but two things make it expensive on the machine that actually runs this — a
 * notebook on a slow disk, which is also capturing the piano:
 *
 * 1. **The poll must never overlap itself.** The refresh reads the summary, the sitting list and
 *    the open sitting's detail. On the owner's library the detail is 30 000 notes' worth of
 *    derived work, and after a restart — cold page cache, the job runner draining its backlog —
 *    the first read of a large sitting was measured at **70 s** instead of 2.6 s. A twenty-second
 *    interval against a seventy-second read does not just waste one request: the polls stack, the
 *    queued reads fight for the same disk, and one slow read becomes the several-minute stall
 *    that was reported. The gate below is the whole fix, and it is one flag.
 * 2. **An unchanged sitting does not need re-reading.** The detail is what materialises paragraphs
 *    of server-side work, and the poll cannot learn anything new from it unless the sitting
 *    actually changed. The list row already carries the three facts that move when it does —
 *    `note_count`, `duration_s`, `segment_count` — so the refresh compares them and skips the
 *    expensive read when they agree.
 *
 * Deliberately *not* claimed: that a change made on another machine is invisible here. A label
 * edited elsewhere moves none of the three numbers, so this poll will not notice it. Explicit
 * actions re-read what they touched, and the poll is a convenience for "did a sitting finish?",
 * which is exactly what the three numbers answer. Erring towards one stale poll beats re-reading
 * 30 000 notes every twenty seconds.
 */

/** A refresh that refuses to run twice at once. */
export interface PollRunner {
  /** Run now, or do nothing if the previous run has not finished. */
  fire(): Promise<void>;
  /** Whether a run is in flight. For tests and for a caller that wants to show it. */
  readonly running: boolean;
}

/**
 * Wrap `run` so overlapping calls collapse into one.
 *
 * The ignored call resolves immediately rather than queueing: the point is to *not* touch the
 * server, and the next interval will pick up whatever the skipped call would have fetched. A
 * failed run still releases the gate, because a request that threw must not wedge the poll for
 * the life of the tab — which is the failure mode this whole module exists to prevent.
 */
export function createPollRunner(run: () => Promise<void>): PollRunner {
  let running = false;
  return {
    async fire(): Promise<void> {
      if (running) return;
      running = true;
      try {
        await run();
      } finally {
        running = false;
      }
    },
    get running(): boolean {
      return running;
    },
  };
}

/** The three facts a sitting's list row carries that move when the sitting itself changes. */
export interface RefreshableRow {
  note_count: number;
  duration_s: number;
  segment_count: number;
}

/** What the view already holds for a sitting. Structural on purpose: `segments` is only counted. */
export interface RefreshableDetail {
  note_count: number;
  duration_s: number;
  segments: unknown[];
  preparing?: boolean;
}

/**
 * Whether the loaded detail is worth re-reading.
 *
 * `preparing` is always stale: the server said the segmentation is on its way, and the retry loop
 * may have given up (bounded on purpose), so the poll is the backstop that notices when it lands.
 */
export function detailIsStale(
  row: RefreshableRow,
  detail: RefreshableDetail | null,
): boolean {
  if (detail === null) return true;
  if (detail.preparing) return true;
  return (
    row.note_count !== detail.note_count ||
    row.duration_s !== detail.duration_s ||
    row.segment_count !== detail.segments.length
  );
}
