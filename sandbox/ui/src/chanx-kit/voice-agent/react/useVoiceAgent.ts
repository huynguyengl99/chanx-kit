import { useCallback, useEffect, useRef } from 'react';
import type { ChannelDescriptor, TopicRefOf } from '@chanx-js/client';

import { useAgentThread } from '../../ag-ui/react/useAgentThread';
import { usePlayer } from '../../player/react/usePlayer';
import { useTranscriber } from '../../transcriber/react/useTranscriber';
import type { VoiceAgentTopics } from '../core';
import { voiceStatus } from '../core';

export interface UseVoiceAgentOptions {
  /** Silence the reply as soon as the user starts speaking. Defaults to true. */
  bargeIn?: boolean;
  params?: Record<string, string | number>;
  queryParams?: Record<string, string | number>;
  language?: string;
}

/** One voice session: talk, hear the reply, interrupt by speaking. */
export function useVoiceAgent<
  D extends ChannelDescriptor<any, any, any, any>,
  T extends TopicRefOf<D>,
  S extends TopicRefOf<D>,
  A extends TopicRefOf<D>,
>(
  channel: D,
  topics: VoiceAgentTopics<T, S, A>,
  { bargeIn = true, params, queryParams, language }: UseVoiceAgentOptions = {},
) {
  // The same connection options for all three, so they share one socket.
  const connection = { params, queryParams } as unknown as Record<string, never>;
  const ears = useTranscriber<D, T>(channel, topics.transcriber, { ...connection, language });
  const voice = usePlayer<D, S>(channel, topics.synthesizer, connection);
  const thread = useAgentThread<D, A>(channel, topics.thread, connection);

  // Local barge-in: the server clears too, but later.
  const wasSpeaking = useRef(false);
  useEffect(() => {
    if (bargeIn && ears.speaking && !wasSpeaking.current && voice.status === 'playing') {
      voice.silence();
    }
    wasSpeaking.current = ears.speaking;
  }, [bargeIn, ears.speaking, voice.status, voice.silence]);

  const talk = useCallback(async () => {
    await voice.unlock();
    await ears.start();
  }, [voice.unlock, ears.start]);

  const interrupt = useCallback(() => {
    voice.silence();
    voice.stop();
    thread.cancel();
  }, [voice.silence, voice.stop, thread.cancel]);

  return {
    status: voiceStatus({
      recording: ears.recording !== 'idle',
      running: thread.running,
      playing: voice.status === 'playing',
    }),
    connection: ears.status,
    /** What the user said, live. */
    utterances: ears.utterances,
    /** The conversation, as AG-UI messages. */
    messages: thread.messages,
    /** What is being spoken now. */
    speaking: voice.text,
    level: ears.level,
    recording: ears.recording,
    error: ears.error ?? voice.error ?? (thread.error ? { code: 'agent', message: thread.error } : null),
    needsUnlock: voice.needsUnlock,
    talk,
    mute: ears.stop,
    interrupt,
    unlock: voice.unlock,
  };
}
