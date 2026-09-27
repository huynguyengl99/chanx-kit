import { describe, expect, it } from 'vitest';

import { Chunker, fromBase64, fromPcm16, level, Resampler, toBase64, toPcm16 } from '../core';

describe('Resampler', () => {
  it('passes audio through when the rates match', () => {
    const input = Float32Array.from([0.1, 0.2, 0.3]);
    expect(Array.from(new Resampler(24000, 24000).process(input))).toEqual(Array.from(input));
  });

  it('halves the samples from 48 kHz to 24 kHz, across blocks, without drift', () => {
    const resampler = new Resampler(48000, 24000);
    let total = 0;
    // One second in 128-frame blocks, the size an AudioWorklet delivers.
    for (let block = 0; block < 375; block++) total += resampler.process(new Float32Array(128)).length;
    expect(Math.abs(total - 24000)).toBeLessThanOrEqual(1);
  });

  it('keeps a 44.1 kHz ramp continuous where blocks join', () => {
    const resampler = new Resampler(44100, 24000);
    const ramp = (start: number) => Float32Array.from({ length: 441 }, (_, i) => (start + i) / 44100);
    const out = [...resampler.process(ramp(0)), ...resampler.process(ramp(441))];
    const steps = out.slice(1).map((value, i) => value - out[i]!);
    for (const step of steps) expect(step).toBeCloseTo(1 / 24000, 6);
  });
});

describe('toPcm16', () => {
  it('writes little-endian samples and clamps', () => {
    const bytes = toPcm16(Float32Array.from([0, 1, -1, 2]));
    const view = new DataView(bytes.buffer);
    expect([0, 1, 2, 3].map((i) => view.getInt16(i * 2, true))).toEqual([0, 32767, -32768, 32767]);
  });
});

describe('base64', () => {
  it('round-trips every byte value, as the server decodes it', () => {
    const bytes = Uint8Array.from({ length: 256 }, (_, i) => i);
    expect(Array.from(fromBase64(toBase64(bytes)))).toEqual(Array.from(bytes));
    expect(toBase64(Uint8Array.from([0, 1, 2, 255]))).toBe('AAEC/w==');
  });

  it('gives the same result without the native encoder', () => {
    const bytes = Uint8Array.from({ length: 300 }, (_, i) => (i * 7) % 256);
    const plain = Object.assign(bytes.slice(), { toBase64: undefined });
    expect(toBase64(plain)).toBe(toBase64(bytes));
  });

  it('encodes a second of audio without overflowing the stack', () => {
    expect(toBase64(new Uint8Array(48000)).length).toBe(64000);
  });
});

describe('Chunker', () => {
  it('emits fixed 100 ms chunks and flushes the rest', () => {
    const chunker = new Chunker(24000, 100);
    expect(chunker.push(new Uint8Array(3000))).toEqual([]);
    const chunks = chunker.push(new Uint8Array(7000));
    expect(chunks.map((chunk) => chunk.length)).toEqual([4800, 4800]);
    expect(chunker.flush()?.length).toBe(400);
    expect(chunker.flush()).toBeNull();
  });
});

describe('level', () => {
  it('is the RMS of the block', () => {
    expect(level(new Float32Array(10))).toBe(0);
    expect(level(Float32Array.from([0.5, -0.5]))).toBeCloseTo(0.5);
  });
});

describe('fromPcm16', () => {
  it('reads little-endian samples back and downmixes', () => {
    const mono = fromPcm16(toPcm16(Float32Array.from([0, 0.5, -0.5])));
    expect(Array.from(mono).map((v) => Math.round(v * 100) / 100)).toEqual([0, 0.5, -0.5]);
    const stereo = fromPcm16(toPcm16(Float32Array.from([1, 0, -1, 0])), 2);
    expect(Array.from(stereo).map((v) => Math.round(v * 100) / 100)).toEqual([0.5, -0.5]);
  });
});
