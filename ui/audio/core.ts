
/** Linear-interpolation resampler that keeps its position across blocks. */
export class Resampler {
  private readonly step: number;
  private position = 0;
  private last = 0;

  constructor(
    readonly from: number,
    readonly to: number,
  ) {
    this.step = from / to;
  }

  process(input: Float32Array): Float32Array {
    if (this.from === this.to) return input.slice();
    const out: number[] = [];
    let position = this.position;
    // Index -1 is the previous block's last sample, so blocks join seamlessly.
    const sample = (index: number) => (index < 0 ? this.last : (input[index] ?? 0));
    while (position < input.length - 1) {
      const index = Math.floor(position);
      const a = sample(index);
      out.push(a + (sample(index + 1) - a) * (position - index));
      position += this.step;
    }
    this.position = position - input.length;
    if (input.length > 0) this.last = input[input.length - 1] ?? 0;
    return Float32Array.from(out);
  }
}

/** Float samples in [-1, 1] to little-endian PCM16 bytes. */
export function toPcm16(samples: Float32Array): Uint8Array {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i] ?? 0));
    view.setInt16(i * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }
  return bytes;
}

/** Root mean square of a block, 0 to 1: a level meter's input. */
export function level(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (const value of samples) sum += value * value;
  return Math.min(1, Math.sqrt(sum / samples.length));
}

type NativeBase64 = { toBase64?: () => string };

/** Standard base64, the encoding the contract's byte fields use. */
export function toBase64(bytes: Uint8Array): string {
  // Native in current browsers and Node, and ~200x faster than the fallback.
  const native = (bytes as Uint8Array & NativeBase64).toBase64;
  if (native) return native.call(bytes);
  let binary = '';
  // In slices: String.fromCharCode with a whole second of audio overflows the stack.
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

export function fromBase64(text: string): Uint8Array {
  const native = (Uint8Array as unknown as { fromBase64?: (text: string) => Uint8Array }).fromBase64;
  if (native) return native(text);
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/** Collects PCM16 bytes and emits them in chunks of a fixed duration. */
export class Chunker {
  private readonly size: number;
  private buffered = new Uint8Array(0);

  constructor(sampleRate: number, chunkMs: number, channels = 1) {
    this.size = Math.max(2, Math.round((sampleRate * chunkMs) / 1000) * 2 * channels);
  }

  push(bytes: Uint8Array): Uint8Array[] {
    const joined = new Uint8Array(this.buffered.length + bytes.length);
    joined.set(this.buffered);
    joined.set(bytes, this.buffered.length);
    const chunks: Uint8Array[] = [];
    let offset = 0;
    while (joined.length - offset >= this.size) {
      chunks.push(joined.slice(offset, offset + this.size));
      offset += this.size;
    }
    this.buffered = joined.slice(offset);
    return chunks;
  }

  /** Whatever is left, at the end of a recording. */
  flush(): Uint8Array | null {
    const rest = this.buffered;
    this.buffered = new Uint8Array(0);
    return rest.length > 0 ? rest : null;
  }
}

/** Little-endian PCM16 bytes to float samples in [-1, 1]. */
export function fromPcm16(bytes: Uint8Array, channels = 1): Float32Array {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const frames = Math.floor(bytes.byteLength / 2 / channels);
  const out = new Float32Array(frames);
  for (let frame = 0; frame < frames; frame++) {
    let sum = 0;
    for (let channel = 0; channel < channels; channel++) {
      sum += view.getInt16((frame * channels + channel) * 2, true) / 0x8000;
    }
    out[frame] = sum / channels;
  }
  return out;
}
