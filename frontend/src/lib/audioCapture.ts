/**
 * The standing audio switch.
 *
 * One `MediaRecorder` per take, rather than one long recording chopped up afterwards: each take has
 * to be a self-contained file for the probe and the transcode to read, and a WebM stream is only
 * complete when the recorder that wrote it stops.
 *
 * Quality is deliberately modest — mono Opus at 32 kbps, about 14 MB an hour. The piano's own
 * pen-drive recording is the archive; this is the layer that makes a take shareable without finding
 * a memory stick (20-D4).
 *
 * Nothing is recorded while nothing is played: a take opens on the first note and closes on the
 * server's own silence gap. Silence is not practice and is not worth storing.
 */
import { shouldCut, shouldStart } from './audioCut';

/** Mono Opus, low bitrate. Not an archive, and not pretending to be one. */
const AUDIO_BITS_PER_SECOND = 32_000;

/** One take never runs longer than this, so a continuous half-hour is three playable files. */
const MAX_TAKE_MS = 10 * 60 * 1000;

/** How often the switch considers whether to open or close a take. */
const TICK_MS = 1_000;

export type CaptureDeviceState = 'unknown' | 'ready' | 'unavailable' | 'denied';

export class AudioCaptureClient {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private startedMs = 0;
  private takenThroughMs: number | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private busy = false;
  private starting = false;

  deviceState: CaptureDeviceState = 'unknown';
  lastError: string | null = null;

  constructor(
    /** The last note any port has heard, or null. The same source the gesture reads. */
    private readonly lastNoteMs: () => number | null,
    /** The server's segment gap, in ms, from the practice status. */
    private readonly segmentGapMs: () => number,
    /** Ask the server whether there is a sitting to attach to, and how to post a take. */
    private readonly upload: (blob: Blob, startedMs: number) => Promise<void>,
    private readonly onStatus: () => void,
  ) {}

  async start(): Promise<void> {
    // `timer` is only set once the device is in hand, so without `starting` a second click while
    // the permission prompt is open would ask for a second stream, overwrite `this.stream`, and
    // leave the first microphone live with nothing holding it.
    if (this.timer !== null || this.starting) return;
    this.starting = true;
    this.lastError = null;
    // Everything heard before the switch was armed is already in the past; a take opens on the
    // next note, not on a stale one that arrived while nothing was recording.
    this.takenThroughMs = this.lastNoteMs();
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false },
      });
      this.deviceState = 'ready';
    } catch (cause) {
      // `NotAllowedError` is the permission; anything else is a machine with no input at all.
      const name = cause instanceof DOMException ? cause.name : '';
      this.deviceState = name === 'NotAllowedError' ? 'denied' : 'unavailable';
      this.lastError = cause instanceof Error ? cause.message : String(cause);
      this.onStatus();
      return;
    } finally {
      this.starting = false;
    }
    this.timer = setInterval(() => void this.tick(), TICK_MS);
    this.onStatus();
  }

  stop(): void {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    void this.close();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.deviceState = 'unknown';
    this.onStatus();
  }

  private async tick(): Promise<void> {
    if (this.busy) return;
    const now = Date.now();
    if (this.recorder === null) {
      if (
        shouldStart({
          lastNoteMs: this.lastNoteMs(),
          recording: false,
          takenThroughMs: this.takenThroughMs,
        })
      ) {
        this.open(now);
      }
      return;
    }
    if (
      shouldCut({
        nowMs: now,
        chunkStartedMs: this.startedMs,
        lastNoteMs: this.lastNoteMs(),
        segmentGapMs: this.segmentGapMs(),
        maxChunkMs: MAX_TAKE_MS,
      })
    ) {
      await this.close();
    }
  }

  private open(nowMs: number): void {
    if (this.stream === null) return;
    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(this.stream, {
        mimeType: 'audio/webm;codecs=opus',
        audioBitsPerSecond: AUDIO_BITS_PER_SECOND,
      });
      recorder.start();
    } catch (cause) {
      // A browser that cannot produce this codec is a machine that cannot record. Saying so and
      // stopping beats throwing out of an unawaited tick once a second, which looks exactly like
      // a microphone that is simply silent.
      this.deviceState = 'unavailable';
      this.lastError = cause instanceof Error ? cause.message : String(cause);
      if (this.timer !== null) clearInterval(this.timer);
      this.timer = null;
      this.onStatus();
      return;
    }
    this.chunks = [];
    // The take begins at the note that opened it, not at the tick that noticed it. The tick is
    // up to a second late, and an epoch taken from it can fall *after* the phrase it recorded —
    // which would place the take outside the segment it belongs to, or past the sitting entirely.
    // The note's own time is what the server resolves the passage from, and it is the moment the
    // playing began rather than the moment this recorder noticed.
    this.startedMs = this.lastNoteMs() ?? nowMs;
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) this.chunks.push(event.data);
    };
    this.recorder = recorder;
  }

  /**
   * Close the current take and hand it to the server.
   *
   * The blob is built from the recorder's own chunks *after* `stop()` settles, because the last
   * `dataavailable` fires as part of stopping: reading `this.chunks` before that would upload a
   * file missing its tail, which is the kind of loss nobody notices until a phrase ends early.
   */
  private async close(): Promise<void> {
    const recorder = this.recorder;
    if (recorder === null) return;
    this.busy = true;
    this.recorder = null;
    const startedMs = this.startedMs;
    // Everything heard up to this moment is inside the take being closed, so the next one opens
    // only on a note newer than this. Without it the switch re-opens on the same stale note and
    // records silence for ever — which is what the browser scenario caught.
    this.takenThroughMs = this.lastNoteMs() ?? this.takenThroughMs;

    let blob: Blob;
    try {
      // A recorder that has already stopped — the device went away, or a track ended — will never
      // fire `onstop` again, so awaiting it would strand `busy` and every later take with it.
      if (recorder.state !== 'inactive') {
        await new Promise<void>((resolve, reject) => {
          recorder.onstop = () => resolve();
          recorder.onerror = () => reject(new Error('the recorder stopped on an error'));
          recorder.stop();
        });
      }
      blob = new Blob(this.chunks, { type: 'audio/webm' });
    } catch (cause) {
      this.lastError = cause instanceof Error ? cause.message : String(cause);
      this.chunks = [];
      this.busy = false;
      this.onStatus();
      return;
    }
    this.chunks = [];

    // Recording is free to start again while the upload is in flight: the bytes are already in
    // `blob`, and a server that is slow to answer must not stop the switch hearing the next
    // phrase. The failure, if any, is surfaced below rather than swallowed.
    this.busy = false;
    try {
      if (blob.size > 0) await this.upload(blob, startedMs);
    } catch (cause) {
      this.lastError = cause instanceof Error ? cause.message : String(cause);
    } finally {
      this.onStatus();
    }
  }
}
