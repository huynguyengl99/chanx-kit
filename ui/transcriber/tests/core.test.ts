import { defineChannel, defineTopic } from '@chanx-js/client';
import { beforeEach, describe, expect, it } from 'vitest';

import { makeClient, open, reset } from '../../tests/harness';
import { fromBase64 } from '../../audio/core';
import type { ContractToClient, ContractToServer } from '../contract';
import { connectTranscriber, createTranscript, utteranceText } from '../core';
import type { MicrophoneFactory, MicrophoneOptions } from '../microphone';

const transcribeTopic = defineTopic<ContractToServer, ContractToClient>()({
  name: 'transcriber_topic',
  pattern: 'transcribe:{session}',
});
const voice = defineChannel<never, never>()({
  name: 'voice',
  address: '/ws/voice',
  topics: { transcribeTopic },
});
const s1 = transcribeTopic.with({ session: 's1' });

beforeEach(reset);

/** A microphone the test speaks into. */
function fakeMicrophone() {
  const mic = {
    options: null as MicrophoneOptions | null,
    stopped: false,
    speak(bytes: number) {
      mic.options!.onChunk(new Uint8Array(bytes).fill(7));
    },
    factory: (async (options) => {
      mic.options = options;
      return {
        stop() {
          mic.stopped = true;
          options.onChunk(new Uint8Array(10)); // the last partial chunk
        },
      };
    }) as MicrophoneFactory,
  };
  return mic;
}

const final = (id: string, text: string, start: number, end: number) => ({
  action: 'transcript_final',
  payload: { utterance_id: id, text, start_ms: start, end_ms: end },
});

describe('createTranscript', () => {
  const apply = (transcript: ReturnType<typeof createTranscript>, message: any) =>
    (transcript.on as any)[message.action](message, {});

  it('builds an utterance from finals and the current partial', () => {
    const transcript = createTranscript();
    apply(transcript, { action: 'speech_started', payload: { at_ms: 0 } });
    apply(transcript, { action: 'transcript_partial', payload: { utterance_id: 'u', text: 'hel', start_ms: 0, end_ms: 100 } });
    apply(transcript, final('u', 'hello', 0, 400));
    apply(transcript, { action: 'transcript_partial', payload: { utterance_id: 'u', text: 'wor', start_ms: 400, end_ms: 500 } });

    const [utterance] = transcript.getSnapshot().utterances;
    expect(utteranceText(utterance!)).toBe('hello wor');
    expect(transcript.getSnapshot().speaking).toBe(true);

    apply(transcript, final('u', 'world', 400, 800));
    apply(transcript, { action: 'utterance_end', payload: { utterance_id: 'u' } });
    expect(transcript.getSnapshot().utterances).toEqual([
      { id: 'u', finals: ['hello', 'world'], partial: '', done: true, startMs: 0, endMs: 800 },
    ]);
    expect(transcript.getSnapshot().speaking).toBe(false);
  });

  it('keeps the newest utterances up to the limit', () => {
    const transcript = createTranscript({ limit: 2 });
    for (const id of ['a', 'b', 'c']) apply(transcript, final(id, id, 0, 1));
    expect(transcript.getSnapshot().utterances.map((u) => u.id)).toEqual(['b', 'c']);
  });

  it('does not add a final twice', () => {
    const transcript = createTranscript();
    apply(transcript, final('u', 'hello', 0, 400));
    apply(transcript, final('u', 'hello', 0, 400));
    expect(transcript.getSnapshot().utterances[0]!.finals).toEqual(['hello']);
  });
});

describe('connectTranscriber', () => {
  function connect() {
    const mic = fakeMicrophone();
    const connection = connectTranscriber(makeClient(), voice, s1, { microphone: mic.factory, language: 'en' });
    connection.start();
    const socket = open();
    return { connection, socket, mic };
  }

  it('records in the format the server asked for', async () => {
    const { connection, socket, mic } = connect();
    socket.receive({
      topic: s1.topic,
      action: 'audio_config',
      payload: { encoding: 'pcm16', sample_rate: 16000, channels: 1, chunk_ms: 50 },
    });

    await connection.record();

    expect(mic.options).toMatchObject({ sampleRate: 16000, chunkMs: 50 });
    expect(socket.sentOn(s1.topic)[0]).toMatchObject({
      action: 'audio_start',
      payload: { encoding: 'pcm16', sample_rate: 16000, channels: 1, language: 'en' },
    });
    expect(connection.recorder.getSnapshot().status).toBe('recording');
  });

  it('numbers chunks from 0, sends real bytes, and ends with audio_end', async () => {
    const { connection, socket, mic } = connect();
    await connection.record();
    mic.speak(4800);
    mic.speak(4800);
    connection.stop();

    const frames = socket.sentOn(s1.topic);
    expect(frames.map((frame) => frame.action)).toEqual([
      'audio_start',
      'audio_chunk',
      'audio_chunk',
      'audio_chunk',
      'audio_end',
    ]);
    const chunks = frames.filter((frame) => frame.action === 'audio_chunk');
    expect(chunks.map((frame) => frame.payload.index)).toEqual([0, 1, 2]);
    expect(Array.from(fromBase64(chunks[0]!.payload.data)).slice(0, 2)).toEqual([7, 7]);
    expect(mic.stopped).toBe(true);
    expect(connection.recorder.getSnapshot().status).toBe('idle');
  });

  it('collects the transcript the server sends', () => {
    const { connection, socket } = connect();
    socket.receive({ topic: s1.topic, ...final('u1', 'hello world', 0, 900) });
    expect(connection.transcript.getSnapshot().utterances[0]!.finals).toEqual(['hello world']);
  });

  it('stops recording when the server ends the stream', async () => {
    const { connection, socket, mic } = connect();
    await connection.record();
    socket.receive({
      topic: s1.topic,
      action: 'transcriber_error',
      payload: { code: 'limit_reached', message: 'too long' },
    });

    expect(connection.recorder.getSnapshot()).toMatchObject({
      status: 'idle',
      error: { code: 'limit_reached' },
    });
    expect(mic.stopped).toBe(true);
    // The server already closed the stream, so no audio_end follows.
    expect(socket.sentOn(s1.topic).at(-1)?.action).not.toBe('audio_end');
  });

  it('keeps recording through a gap', async () => {
    const { connection, socket } = connect();
    await connection.record();
    socket.receive({ topic: s1.topic, action: 'transcriber_error', payload: { code: 'audio_gap', message: 'lost' } });
    expect(connection.recorder.getSnapshot().status).toBe('recording');
  });

  it('reports a microphone that cannot be opened', async () => {
    const connection = connectTranscriber(makeClient(), voice, s1, {
      microphone: async () => {
        throw new Error('Permission denied');
      },
    });
    connection.start();
    open();
    await connection.record();
    expect(connection.recorder.getSnapshot()).toMatchObject({
      status: 'idle',
      error: { message: 'Microphone unavailable: Permission denied' },
    });
  });

  it('a stop before the microphone opens cancels the start', async () => {
    const { connection, socket, mic } = connect();
    const starting = connection.record();
    connection.stop();
    await starting;
    expect(mic.stopped).toBe(true);
    expect(socket.sentOn(s1.topic)).toEqual([]);
  });
});
