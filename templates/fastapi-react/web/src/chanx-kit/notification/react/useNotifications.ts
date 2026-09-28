import { useCallback, useMemo, useSyncExternalStore } from 'react';
import type {
  AddressOf,
  ChannelDescriptor,
  ChanxMessage,
  HandlerMap,
  TopicRef,
  TopicRefOf,
  TopicsControllerOptions,
} from '@chanx-js/client';
import { useTopics } from '@chanx-js/client/react';

import type { NotificationFeedOptions, NotificationTopic } from '../core';
import { createNotificationFeed } from '../core';

export interface UseNotificationsOptions<D extends ChannelDescriptor<any, any, any, any>, Refs>
  extends Omit<TopicsControllerOptions<AddressOf<D>>, 'topics' | 'on' | 'buffer'>,
    NotificationFeedOptions {
  topics: Refs & { readonly [K in keyof Refs]: NotificationTopic<Refs[K]> };
}

/** Join notification topics and collect what arrives. */
export function useNotifications<
  D extends ChannelDescriptor<any, any, any, any>,
  const Refs extends readonly TopicRefOf<D>[],
>(channel: D, { topics, limit, ...options }: UseNotificationsOptions<D, Refs>) {
  const feed = useMemo(() => createNotificationFeed({ limit }), [limit]);

  const { status, sendTopic } = useTopics(channel as ChannelDescriptor, {
    ...(options as TopicsControllerOptions<string>),
    topics: topics as readonly TopicRef[],
    buffer: 'none',
    on: feed.on as HandlerMap<ChanxMessage>,
  });

  const { items } = useSyncExternalStore(feed.subscribe, feed.getSnapshot, feed.getSnapshot);
  const ackAll = useCallback(() => feed.ackAll(sendTopic), [feed, sendTopic]);

  return { items, status, ackAll, dismiss: feed.dismiss };
}
