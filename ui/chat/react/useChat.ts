import { useCallback, useMemo, useSyncExternalStore } from 'react';
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

import type { ChatTopic } from '../core';
import { chatBacklogRequest, chatSend, createChatLog } from '../core';

export type UseChatOptions<D extends ChannelDescriptor<any, any, any, any>> = Omit<
  TopicControllerOptions<AddressOf<D>>,
  'on' | 'buffer'
>;

/** A chat topic's history and live messages, plus a way to post. */
export function useChat<D extends ChannelDescriptor<any, any, any, any>, Ref extends TopicRefOf<D>>(
  channel: D,
  topic: Ref & ChatTopic<Ref>,
  options: UseChatOptions<D> = {},
) {
  const log = useMemo(() => createChatLog(), []);

  const { status, send: sendRaw } = useTopic(channel as ChannelDescriptor, topic as TopicRef, {
    ...(options as TopicControllerOptions<string>),
    buffer: 'none',
    on: log.on as HandlerMap<ChanxMessage>,
  });

  const { entries } = useSyncExternalStore(log.subscribe, log.getSnapshot, log.getSnapshot);
  const send = useCallback((body: string) => sendRaw(chatSend(body)), [sendRaw]);
  const requestBacklog = useCallback((limit?: number) => sendRaw(chatBacklogRequest(limit)), [sendRaw]);

  return { entries, status, send, requestBacklog };
}
