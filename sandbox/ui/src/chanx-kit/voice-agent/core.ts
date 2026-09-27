import type { ChanxClient, ChannelDescriptor, TopicRef } from '@chanx-js/client';

import { connectAgentThread } from '../ag-ui/core';
import type { AgUiThreadTopic } from '../ag-ui/core';
import { connectPlayer } from '../player/core';
import type { PlayerOptions, SynthesizerTopic } from '../player/core';
import { connectTranscriber } from '../transcriber/core';
import type { RecorderOptions, TranscriberTopic } from '../transcriber/core';

export type VoiceStatus = 'idle' | 'listening' | 'thinking' | 'speaking';

/** What the agent is doing, from the three parts' own state. */
export function voiceStatus(parts: {
  recording: boolean;
  running: boolean;
  playing: boolean;
}): VoiceStatus {
  if (parts.playing) return 'speaking';
  if (parts.running) return 'thinking';
  return parts.recording ? 'listening' : 'idle';
}

export interface VoiceAgentTopics<T, S, A> {
  /** `transcribe:{session}`: the microphone goes here. */
  transcriber: T & TranscriberTopic<T>;
  /** `speak:{session}`: the reply's audio comes from here. */
  synthesizer: S & SynthesizerTopic<S>;
  /** `agui:thread:{session}`: the conversation and its runs. */
  thread: A & AgUiThreadTopic<A>;
}

export type ConnectVoiceAgentOptions = RecorderOptions &
  PlayerOptions & {
    /** Silence the reply as soon as the user starts speaking. Defaults to true. */
    bargeIn?: boolean;
    params?: Record<string, string | number>;
    queryParams?: Record<string, string | number>;
  };

/** Talk to an agent without a framework: `start()`, then `talk()` from a click. */
export function connectVoiceAgent<D extends ChannelDescriptor<any, any, any, any>, T, S, A>(
  client: ChanxClient,
  channel: D,
  topics: VoiceAgentTopics<T, S, A>,
  { bargeIn = true, params, queryParams, ...options }: ConnectVoiceAgentOptions = {},
) {
  const shared = { params, queryParams } as Record<string, unknown>;
  const ears = connectTranscriber(client, channel, topics.transcriber as never, { ...shared, ...options } as never);
  const voice = connectPlayer(client, channel, topics.synthesizer as never, { ...shared, ...options } as never);
  const thread = connectAgentThread(client, channel, topics.thread as never, shared as never);

  // Local barge-in: the server clears too, but later.
  let wasSpeaking = false;
  ears.transcript.subscribe(() => {
    const speaking = ears.transcript.getSnapshot().speaking;
    if (bargeIn && speaking && !wasSpeaking && voice.player.getSnapshot().status === 'playing') {
      voice.player.silence();
    }
    wasSpeaking = speaking;
  });

  const status = () =>
    voiceStatus({
      recording: ears.recorder.getSnapshot().status !== 'idle',
      running: thread.thread.getSnapshot().running,
      playing: voice.player.getSnapshot().status === 'playing',
    });

  return {
    transcriber: ears,
    player: voice,
    thread,
    status,
    /** Open the microphone and unlock audio. Call from a click. */
    talk: async () => {
      await voice.unlock();
      await ears.record();
    },
    /** Close the microphone. The last words are still answered. */
    mute: () => ears.stop(),
    /** Stop the agent's reply: speech and the run. */
    interrupt: () => {
      voice.player.silence();
      voice.stop();
      thread.cancel();
    },
    start: () => {
      ears.start();
      voice.start();
      thread.start();
    },
    close: () => {
      ears.close();
      voice.close();
      thread.stop();
    },
  };
}

export type { TopicRef };
