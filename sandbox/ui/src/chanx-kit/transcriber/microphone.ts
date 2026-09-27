import { Chunker, level, Resampler, toPcm16 } from '../audio/core';

export interface MicrophoneOptions {
  sampleRate: number;
  chunkMs: number;
  /** One chunk of `chunkMs` of PCM16 mono at `sampleRate`. */
  onChunk: (chunk: Uint8Array) => void;
  /** Input level, 0 to 1, a few dozen times a second. */
  onLevel?: (value: number) => void;
  /** Passed to getUserMedia. */
  constraints?: MediaTrackConstraints;
  /** Serve the worklet from a URL, when a Content-Security-Policy forbids `blob:`. */
  workletUrl?: string;
}

export interface Microphone {
  /** Stop capturing and release the device. Emits the last partial chunk first. */
  stop: () => void;
}

export type MicrophoneFactory = (options: MicrophoneOptions) => Promise<Microphone>;

// Plain JS from a Blob: bundlers copy a sibling .ts file raw, which browsers cannot run.
export const CAPTURE_WORKLET = `
class ChanxCapture extends AudioWorkletProcessor {
  constructor() { super(); this.buffer = new Float32Array(2048); this.filled = 0; }
  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channels = input.length;
    const frames = input[0].length;
    for (let i = 0; i < frames; i++) {
      let sum = 0;
      for (let c = 0; c < channels; c++) sum += input[c][i];
      this.buffer[this.filled++] = sum / channels;
      if (this.filled === this.buffer.length) {
        this.port.postMessage(this.buffer);
        this.buffer = new Float32Array(2048);
        this.filled = 0;
      }
    }
    return true;
  }
}
registerProcessor('chanx-capture', ChanxCapture);
`;

export const openMicrophone: MicrophoneFactory = async ({
  sampleRate,
  chunkMs,
  onChunk,
  onLevel,
  constraints,
  workletUrl,
}) => {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      ...constraints,
    },
  });
  // The device's rate: asking AudioContext for one is unevenly supported (older Safari).
  const context = new AudioContext();
  let url = workletUrl;
  let owned: string | null = null;
  if (!url) {
    owned = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: 'text/javascript' }));
    url = owned;
  }
  try {
    await context.audioWorklet.addModule(url);
    // Autoplay rules may suspend it; recording starts from a click, so resume.
    if (context.state === 'suspended') await context.resume();
  } catch (error) {
    // Otherwise the browser keeps showing the microphone as in use.
    for (const track of stream.getTracks()) track.stop();
    void context.close();
    throw error;
  } finally {
    if (owned) URL.revokeObjectURL(owned);
  }

  const source = context.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(context, 'chanx-capture');
  // Silent sink: some browsers only pull a graph that reaches the destination.
  const mute = context.createGain();
  mute.gain.value = 0;
  source.connect(node).connect(mute).connect(context.destination);

  const resampler = new Resampler(context.sampleRate, sampleRate);
  const chunker = new Chunker(sampleRate, chunkMs);
  node.port.onmessage = (event: MessageEvent<Float32Array>) => {
    onLevel?.(level(event.data));
    for (const chunk of chunker.push(toPcm16(resampler.process(event.data)))) onChunk(chunk);
  };

  return {
    stop() {
      node.port.onmessage = null;
      const rest = chunker.flush();
      if (rest) onChunk(rest);
      source.disconnect();
      node.disconnect();
      for (const track of stream.getTracks()) track.stop();
      void context.close();
    },
  };
};
