import { defineChannel, defineTopic } from '@chanx-js/client';
import { beforeEach, describe, expect, it } from 'vitest';

import { toBase64, toPcm16 } from '../../audio/core';
import { makeClient, open, reset } from '../../tests/harness';
import type { ContractToClient, ContractToServer } from '../contract';
import { connectPlayer } from '../core';
import type { Speaker, SpeakerFactory } from '../speaker';

const speakTopic = defineTopic<ContractToServer, ContractToClient>()({
  name: 'synthesizer_topic',
  pattern: 'speak:{session}',
});
const voice = defineChannel<never, never>()({ name: 'voice', address: '/ws/voice', topics: { speakTopic } });
const s1 = speakTopic.with({ session: 's1' });

beforeEach(reset);

/** A speaker the test plays by hand, at 24 kHz so no resampling blurs the counts. */
function fakeSpeaker(suspended = false) {
  const state = {
    written: 0,
    cleared: 0,
    drained: 0,
    suspended,
    played: (_total: number) => {},
    total: 0,
    play(samples: number) {
      state.total += samples;
      state.played(state.total);
    },
  };
  const factory: SpeakerFactory = async () =>
    ({
      sampleRate: 24000,
      write: (samples: Float32Array) => {
        state.written += samples.length;
      },
      drain: () => state.drained++,
      clear: () => {
        state.cleared++;
      },
      onPlayed: (listener: (total: number) => void) => {
        state.played = listener;
      },
      get suspended() {
        return state.suspended;
      },
      resume: async () => {
        state.suspended = false;
      },
      close: () => {},
    }) satisfies Speaker;
  return { state, factory };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function connect(suspended = false) {
  const speaker = fakeSpeaker(suspended);
  const connection = connectPlayer(makeClient(), voice, s1, { speaker: speaker.factory, markEveryMs: 0 });
  connection.start();
  return { connection, socket: open(), speaker: speaker.state };
}

const chunk = (utterance: string, index: number, samples: number) => ({
  topic: s1.topic,
  action: 'audio_chunk',
  payload: { utterance_id: utterance, index, data: toBase64(toPcm16(new Float32Array(samples).fill(0.1))) },
});
const start = (utterance: string) => ({
  topic: s1.topic,
  action: 'audio_start',
  payload: { utterance_id: utterance, text: 'hello there', encoding: 'pcm16', sample_rate: 24000, channels: 1 },
});
const end = (utterance: string, ms: number) => ({
  topic: s1.topic,
  action: 'audio_end',
  payload: { utterance_id: utterance, duration_ms: ms },
});

describe('connectPlayer', () => {
  it('writes each chunk once, in order, even when replayed', async () => {
    const { connection, socket, speaker } = connect();
    socket.receive(start('u'));
    socket.receive(chunk('u', 0, 2400));
    await flush();
    // A reconnect replays the utterance from its start.
    socket.receive(start('u'));
    socket.receive(chunk('u', 0, 2400));
    socket.receive(chunk('u', 1, 2400));
    await flush();

    expect(speaker.written).toBe(4800);
    expect(connection.player.getSnapshot()).toMatchObject({ status: 'playing', utteranceId: 'u', text: 'hello there' });
  });

  it('reports what was heard as it plays, and a final mark at the end', async () => {
    const { connection, socket, speaker } = connect();
    socket.receive(start('u'));
    socket.receive(chunk('u', 0, 4800));
    socket.receive(end('u', 200));
    await flush();
    expect(speaker.drained).toBe(1);

    speaker.play(2400);
    expect(connection.player.getSnapshot().playedMs).toBe(100);
    speaker.play(2400);

    const marks = socket.sentOn(s1.topic).filter((f) => f.action === 'playback_mark');
    expect(marks.map((m) => m.payload)).toEqual([
      { utterance_id: 'u', played_ms: 100 },
      { utterance_id: 'u', played_ms: 200 },
    ]);
    expect(connection.player.getSnapshot()).toMatchObject({ status: 'idle', playedMs: 200, durationMs: 200 });
  });

  it('accounts consecutive utterances separately', async () => {
    const { socket, speaker } = connect();
    socket.receive(start('a'));
    socket.receive(chunk('a', 0, 2400));
    socket.receive(end('a', 100));
    socket.receive(start('b'));
    socket.receive(chunk('b', 0, 2400));
    socket.receive(end('b', 100));
    await flush();

    speaker.play(3600);
    const marks = socket.sentOn(s1.topic).filter((f) => f.action === 'playback_mark').map((m) => m.payload);
    expect(marks).toContainEqual({ utterance_id: 'a', played_ms: 100 });
    expect(marks).toContainEqual({ utterance_id: 'b', played_ms: 50 });
  });

  it('a clear drops the buffered audio and marks what was heard', async () => {
    const { connection, socket, speaker } = connect();
    socket.receive(start('u'));
    socket.receive(chunk('u', 0, 24000));
    await flush();
    speaker.play(6000);
    socket.receive({ topic: s1.topic, action: 'clear', payload: { utterance_id: 'u' } });
    await flush();

    expect(speaker.cleared).toBe(1);
    const marks = socket.sentOn(s1.topic).filter((f) => f.action === 'playback_mark');
    expect(marks.at(-1)!.payload).toEqual({ utterance_id: 'u', played_ms: 250 });
    expect(connection.player.getSnapshot().status).toBe('idle');

    // The next utterance starts where the cleared one was cut, not after its tail.
    socket.receive(start('v'));
    socket.receive(chunk('v', 0, 2400));
    await flush();
    speaker.play(2400);
    expect(connection.player.getSnapshot()).toMatchObject({ utteranceId: 'v', playedMs: 100 });
  });

  it('silence stops locally at once, before any clear from the server', async () => {
    const { connection, socket, speaker } = connect();
    socket.receive(start('u'));
    socket.receive(chunk('u', 0, 24000));
    await flush();
    connection.player.silence();
    expect(speaker.cleared).toBe(1);
    expect(connection.player.getSnapshot().status).toBe('idle');
  });

  it('speak and stop ask the server', () => {
    const { connection, socket } = connect();
    connection.speak('Hi', 'v1');
    connection.stop();
    expect(socket.sentOn(s1.topic).map(({ action, payload }) => [action, payload])).toEqual([
      ['speak', { text: 'Hi', voice: 'v1' }],
      ['speak_clear', null],
    ]);
  });

  it('asks for a gesture while the browser holds audio, and resumes on unlock', async () => {
    const { connection, socket, speaker } = connect(true);
    socket.receive(start('u'));
    await flush();
    expect(connection.player.getSnapshot().needsUnlock).toBe(true);
    await connection.unlock();
    expect(speaker.suspended).toBe(false);
    expect(connection.player.getSnapshot().needsUnlock).toBe(false);
  });

  it('reports audio output that cannot open, and lets unlock try again', async () => {
    let attempts = 0;
    const failing: SpeakerFactory = async () => {
      attempts++;
      throw new Error('no audio device');
    };
    const connection = connectPlayer(makeClient(), voice, s1, { speaker: failing });
    connection.start();
    const socket = open();
    socket.receive(start('u'));
    await flush();

    expect(connection.player.getSnapshot().error).toMatchObject({
      code: 'provider_failed',
      message: 'Audio output unavailable: no audio device',
    });
    await expect(connection.unlock()).rejects.toThrow('no audio device');
    expect(attempts).toBe(2);
  });

  it('keeps provider errors', () => {
    const { connection, socket } = connect();
    socket.receive({
      topic: s1.topic,
      action: 'synthesizer_error',
      payload: { code: 'provider_unavailable', message: 'no key', utterance_id: null },
    });
    expect(connection.player.getSnapshot().error).toMatchObject({ code: 'provider_unavailable' });
  });
});
