import { useMemo, useSyncExternalStore } from 'react';
import type {
  AddressOf,
  ChannelDescriptor,
  ChanxMessage,
  HandlerMap,
  TopicControllerOptions,
  TopicRef,
  TopicRefOf,
} from '@chanx-js/client';
import { useTopic } from '@chanx-js/client/react';

import type { TranscriptOptions, TranscriptWatchTopic } from '../core';
import { createTranscript } from '../core';

export type UseTranscriptOptions<D extends ChannelDescriptor<any, any, any, any>> = Omit<
  TopicControllerOptions<AddressOf<D>>,
  'on' | 'buffer'
> &
  TranscriptOptions;

/** Watch someone else's transcript live: captions, another tab, a moderator. */
export function useTranscript<
  D extends ChannelDescriptor<any, any, any, any>,
  Ref extends TopicRefOf<D>,
>(channel: D, topic: Ref & TranscriptWatchTopic<Ref>, { limit, ...options }: UseTranscriptOptions<D> = {}) {
  const transcript = useMemo(() => createTranscript({ limit }), [limit]);
  const { status } = useTopic(channel as ChannelDescriptor, topic as TopicRef, {
    ...(options as TopicControllerOptions<string>),
    buffer: 'none',
    on: transcript.on as HandlerMap<ChanxMessage>,
  });
  const snapshot = useSyncExternalStore(transcript.subscribe, transcript.getSnapshot, transcript.getSnapshot);
  return { ...snapshot, status, clear: transcript.clear };
}
