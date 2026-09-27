import { defineChannel, defineTopic } from '@chanx-js/client';
import { beforeEach, describe, expect, it } from 'vitest';

import type { ContractToClient as AgUiToClient, ContractToServer as AgUiToServer } from '../../ag-ui/contract';
import { toBase64, toPcm16 } from '../../audio/core';
import type { ContractToClient as SpeakToClient, ContractToServer as SpeakToServer } from '../../player/contract';
import type { SpeakerFactory } from '../../player/speaker';
import { FakeSocket, makeClient, open, reset } from '../../tests/harness';
import type { ContractToClient as EarsToClient, ContractToServer as EarsToServer } from '../../transcriber/contract';
import type { MicrophoneFactory } from '../../transcriber/microphone';
import { connectVoiceAgent, voiceStatus } from '../core';

const transcriberTopic = defineTopic<EarsToServer, EarsToClient>()({ name: 't', pattern: 'transcribe:{session}' });
const synthesizerTopic = defineTopic<SpeakToServer, SpeakToClient>()({ name: 's', pattern: 'speak:{session}' });
const threadTopic = defineTopic<AgUiToServer, AgUiToClient>()({ name: 'a', pattern: 'agui:thread:{thread_id}' });
const voice = defineChannel<never, never>()({
  name: 'voice',
  address: '/ws/voice',
  topics: { transcriberTopic, synthesizerTopic, threadTopic },
});

beforeEach(reset);

const mic: MicrophoneFactory = async () => ({ stop() {} });
const cleared = { count: 0 };
const speaker: SpeakerFactory = async () => ({
  sampleRate: 24000,
  write() {},
  drain() {},
  clear() {
    cleared.count++;
  },
  onPlayed() {},
  suspended: false,
  resume: async () => {},
  close() {},
});
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function connect() {
  cleared.count = 0;
  const agent = connectVoiceAgent(
    makeClient(),
    voice,
    {
      transcriber: transcriberTopic.with({ session: 's1' }),
      synthesizer: synthesizerTopic.with({ session: 's1' }),
      thread: threadTopic.with({ thread_id: 's1' }),
    },
    { microphone: mic, speaker },
  );
  agent.start();
  return { agent, socket: open() };
}

describe('voiceStatus', () => {
  it('speaking wins over thinking, which wins over listening', () => {
    expect(voiceStatus({ recording: true, running: true, playing: true })).toBe('speaking');
    expect(voiceStatus({ recording: true, running: true, playing: false })).toBe('thinking');
    expect(voiceStatus({ recording: true, running: false, playing: false })).toBe('listening');
    expect(voiceStatus({ recording: false, running: false, playing: false })).toBe('idle');
  });
});

describe('connectVoiceAgent', () => {
  it('shares one socket for the three topics', () => {
    connect();
    expect(FakeSocket.instances).toHaveLength(1);
    const topics = FakeSocket.last.sent.filter((f) => f.action === 'subscribe').map((f) => f.topic);
    expect(topics.sort()).toEqual(['agui:thread:s1', 'speak:s1', 'transcribe:s1']);
  });

  it('goes quiet as soon as the user speaks over the reply', async () => {
    const { agent, socket } = connect();
    await agent.talk();
    socket.receive({
      topic: 'speak:s1',
      action: 'audio_start',
      payload: { utterance_id: 'r', text: 'A long answer', encoding: 'pcm16', sample_rate: 24000, channels: 1 },
    });
    socket.receive({
      topic: 'speak:s1',
      action: 'audio_chunk',
      payload: { utterance_id: 'r', index: 0, data: toBase64(toPcm16(new Float32Array(4800))) },
    });
    await flush();
    expect(agent.status()).toBe('speaking');

    socket.receive({ topic: 'transcribe:s1', action: 'speech_started', payload: { at_ms: 0 } });

    expect(cleared.count).toBe(1);
    expect(agent.status()).toBe('listening');
  });

  it('interrupt stops the speech and cancels the run', async () => {
    const { agent, socket } = connect();
    socket.receive({ topic: 'agui:thread:s1', action: 'ag_ui_event', seq: 1, payload: { type: 'RUN_STARTED', threadId: 's1', runId: 'r1' } });
    expect(agent.status()).toBe('thinking');
    agent.interrupt();
    const sent = socket.sent.filter((f) => f.action === 'speak_clear' || f.action === 'ag_ui_cancel');
    expect(sent.map((f) => [f.topic, f.action, f.payload])).toEqual([
      ['speak:s1', 'speak_clear', null],
      ['agui:thread:s1', 'ag_ui_cancel', { runId: 'r1' }],
    ]);
  });
});
