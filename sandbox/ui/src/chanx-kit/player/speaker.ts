
export interface SpeakerOptions {
  /** Audio held before playback starts, and again after running dry. */
  prebufferMs?: number;
  /** Serve the worklet from a URL, when a Content-Security-Policy forbids `blob:`. */
  workletUrl?: string;
}

export interface Speaker {
  /** The device's sample rate; write samples at this rate. */
  readonly sampleRate: number;
  /** Queue mono samples. */
  write: (samples: Float32Array) => void;
  /** Play out what is queued even if it is shorter than the prebuffer. */
  drain: () => void;
  /** Drop everything queued, now. */
  clear: () => void;
  /** Called with the total samples played so far, a few dozen times a second. */
  onPlayed: (listener: (total: number) => void) => void;
  /** Browsers suspend audio until a user gesture. */
  readonly suspended: boolean;
  resume: () => Promise<void>;
  close: () => void;
}

export type SpeakerFactory = (options: SpeakerOptions) => Promise<Speaker>;

// Plain JS from a Blob, like the capture worklet.
export const PLAYBACK_WORKLET = `
class ChanxPlayback extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.prebuffer = options.processorOptions.prebuffer;
    this.blocks = [];
    this.offset = 0;
    this.queued = 0;
    this.waiting = true;
    this.draining = false;
    this.played = 0;
    this.sinceReport = 0;
    this.port.onmessage = (event) => {
      const message = event.data;
      if (message.type === 'write') {
        this.blocks.push(message.samples);
        this.queued += message.samples.length;
      } else if (message.type === 'drain') {
        this.draining = true;
      } else if (message.type === 'clear') {
        this.blocks = [];
        this.offset = 0;
        this.queued = 0;
        this.waiting = true;
        this.draining = false;
      }
    };
  }
  process(inputs, outputs) {
    const out = outputs[0][0];
    if (this.waiting && (this.queued >= this.prebuffer || (this.draining && this.queued > 0))) {
      this.waiting = false;
    }
    let written = 0;
    while (!this.waiting && written < out.length && this.blocks.length > 0) {
      const block = this.blocks[0];
      const count = Math.min(out.length - written, block.length - this.offset);
      out.set(block.subarray(this.offset, this.offset + count), written);
      written += count;
      this.offset += count;
      this.queued -= count;
      if (this.offset === block.length) {
        this.blocks.shift();
        this.offset = 0;
      }
    }
    if (this.blocks.length === 0 && !this.waiting) {
      // Ran dry: wait for a prebuffer again, unless the utterance was ending anyway.
      this.waiting = true;
      this.draining = false;
    }
    for (let c = 1; c < outputs[0].length; c++) outputs[0][c].set(out);
    this.played += written;
    this.sinceReport += out.length;
    if (this.sinceReport >= 1024) {
      this.sinceReport = 0;
      this.port.postMessage(this.played);
    }
    return true;
  }
}
registerProcessor('chanx-playback', ChanxPlayback);
`;

export const openSpeaker: SpeakerFactory = async ({ prebufferMs = 150, workletUrl }) => {
  const context = new AudioContext();
  let url = workletUrl;
  let owned: string | null = null;
  if (!url) {
    owned = URL.createObjectURL(new Blob([PLAYBACK_WORKLET], { type: 'text/javascript' }));
    url = owned;
  }
  try {
    await context.audioWorklet.addModule(url);
  } catch (error) {
    void context.close();
    throw error;
  } finally {
    if (owned) URL.revokeObjectURL(owned);
  }
  const node = new AudioWorkletNode(context, 'chanx-playback', {
    numberOfInputs: 0,
    outputChannelCount: [context.destination.channelCount >= 2 ? 2 : 1],
    processorOptions: { prebuffer: Math.round((context.sampleRate * prebufferMs) / 1000) },
  });
  node.connect(context.destination);
  const listeners = new Set<(total: number) => void>();
  node.port.onmessage = (event: MessageEvent<number>) => {
    for (const listener of listeners) listener(event.data);
  };

  return {
    sampleRate: context.sampleRate,
    write: (samples) => node.port.postMessage({ type: 'write', samples }, [samples.buffer]),
    drain: () => node.port.postMessage({ type: 'drain' }),
    clear: () => node.port.postMessage({ type: 'clear' }),
    onPlayed: (listener) => listeners.add(listener),
    get suspended() {
      return context.state === 'suspended';
    },
    resume: () => context.resume(),
    close: () => {
      node.disconnect();
      void context.close();
    },
  };
};
