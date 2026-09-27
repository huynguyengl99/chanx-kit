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

import type { PresenceTopic } from '../core';
import { createPresenceRoster, presenceRequest } from '../core';

export type UsePresenceOptions<D extends ChannelDescriptor<any, any, any, any>> = Omit<
  TopicControllerOptions<AddressOf<D>>,
  'on' | 'buffer'
>;

/** Who is present on a presence topic, kept current. */
export function usePresence<D extends ChannelDescriptor<any, any, any, any>, Ref extends TopicRefOf<D>>(
  channel: D,
  topic: Ref & PresenceTopic<Ref>,
  options: UsePresenceOptions<D> = {},
) {
  const roster = useMemo(() => createPresenceRoster(), []);

  const { status, send } = useTopic(channel as ChannelDescriptor, topic as TopicRef, {
    ...(options as TopicControllerOptions<string>),
    buffer: 'none',
    on: roster.on as HandlerMap<ChanxMessage>,
  });

  const { members } = useSyncExternalStore(roster.subscribe, roster.getSnapshot, roster.getSnapshot);
  const refresh = useCallback(() => send(presenceRequest), [send]);

  return { members, status, refresh };
}
