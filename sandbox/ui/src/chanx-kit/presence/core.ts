import type {
  AddressOf,
  ChanxClient,
  ChannelDescriptor,
  ChanxMessage,
  HandlerMap,
  TopicControllerOptions,
  TopicRef,
  TopicRefOf,
} from '@chanx-js/client';
import { createTopicController } from '@chanx-js/client';

import type { ContractToClient, ContractToServer, PresenceMember } from './contract';

/** A topic whose messages fit presence@1; extra actions are fine. */
export type PresenceTopic<Ref> =
  Ref extends TopicRef<infer ToServer, infer ToClient, any>
    ? [ContractToServer] extends [ToServer]
      ? [Extract<ToClient, { action: ContractToClient['action'] }>] extends [ContractToClient]
        ? Ref
        : never
      : never
    : never;

export interface PresenceSnapshot {
  /** In the order they arrived. */
  members: PresenceMember[];
}

export interface PresenceRoster {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => PresenceSnapshot;
  /** Handlers to pass as `on` to a topic controller or `useTopic`. */
  on: HandlerMap<ContractToClient>;
}

export function createPresenceRoster(): PresenceRoster {
  const listeners = new Set<() => void>();
  let snapshot: PresenceSnapshot = { members: [] };

  const publish = (members: PresenceMember[]) => {
    snapshot = { members };
    for (const listener of [...listeners]) listener();
  };

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => snapshot,
    on: {
      // Sent on every (re)subscribe, so it replaces rather than merges.
      presence_state: ({ payload }) => publish(payload.members),
      presence_join: ({ payload: { member } }) =>
        publish([...snapshot.members.filter((m) => m.id !== member.id), member]),
      presence_leave: ({ payload: { member } }) =>
        publish(snapshot.members.filter((m) => m.id !== member.id)),
    },
  };
}

/** The message that asks for the roster again, without reconnecting. */
export const presenceRequest: ContractToServer = { action: 'presence_request', payload: null };

export type ConnectPresenceOptions<D extends ChannelDescriptor<any, any, any, any>> = Omit<
  TopicControllerOptions<AddressOf<D>>,
  'on' | 'buffer'
>;

/** Join a presence topic without a framework. Call `start()`, then read `roster`. */
export function connectPresence<D extends ChannelDescriptor<any, any, any, any>, Ref extends TopicRefOf<D>>(
  client: ChanxClient,
  channel: D,
  topic: Ref & PresenceTopic<Ref>,
  options: ConnectPresenceOptions<D> = {},
) {
  const roster = createPresenceRoster();
  const controller = createTopicController(client, channel as ChannelDescriptor, topic as TopicRef, {
    ...(options as TopicControllerOptions<string>),
    buffer: 'none',
    on: roster.on as HandlerMap<ChanxMessage>,
  });
  return {
    roster,
    controller,
    refresh: () => controller.send(presenceRequest),
    start: () => controller.start(),
    stop: () => controller.stop(),
  };
}
