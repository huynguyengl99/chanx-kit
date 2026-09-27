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

import type { ChatEntry, ContractToClient, ContractToServer } from './contract';

/** A topic whose messages fit chat@1; extra actions are fine. */
export type ChatTopic<Ref> =
  Ref extends TopicRef<infer ToServer, infer ToClient, any>
    ? [ContractToServer] extends [ToServer]
      ? [Extract<ToClient, { action: ContractToClient['action'] }>] extends [ContractToClient]
        ? Ref
        : never
      : never
    : never;

export interface ChatSnapshot {
  /** Oldest first. */
  entries: ChatEntry[];
}

export interface ChatLog {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => ChatSnapshot;
  /** Handlers to pass as `on` to a topic controller or `useTopic`. */
  on: HandlerMap<ContractToClient>;
}

export function createChatLog(): ChatLog {
  const listeners = new Set<() => void>();
  let snapshot: ChatSnapshot = { entries: [] };

  const publish = (entries: ChatEntry[]) => {
    snapshot = { entries };
    for (const listener of [...listeners]) listener();
  };

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => snapshot,
    on: {
      // Sent on every (re)subscribe; keep live messages newer than it.
      chat_backlog: ({ payload }) => {
        const known = new Set(payload.entries.map((entry) => entry.id));
        const newest = payload.entries.at(-1)?.sent_at ?? '';
        const live = snapshot.entries.filter(
          (entry) => !known.has(entry.id) && (entry.sent_at ?? '') > newest,
        );
        publish([...payload.entries, ...live]);
      },
      chat_message: ({ payload }) => {
        if (payload.id && snapshot.entries.some((entry) => entry.id === payload.id)) return;
        publish([...snapshot.entries, payload]);
      },
    },
  };
}

export const chatSend = (body: string): ContractToServer => ({ action: 'chat_send', payload: { body } });

export const chatBacklogRequest = (limit?: number): ContractToServer => ({
  action: 'chat_backlog_request',
  payload: { limit: limit ?? null },
});

export type ConnectChatOptions<D extends ChannelDescriptor<any, any, any, any>> = Omit<
  TopicControllerOptions<AddressOf<D>>,
  'on' | 'buffer'
>;

/** Join a chat topic without a framework. Call `start()`, then read `log`. */
export function connectChat<D extends ChannelDescriptor<any, any, any, any>, Ref extends TopicRefOf<D>>(
  client: ChanxClient,
  channel: D,
  topic: Ref & ChatTopic<Ref>,
  options: ConnectChatOptions<D> = {},
) {
  const log = createChatLog();
  const controller = createTopicController(client, channel as ChannelDescriptor, topic as TopicRef, {
    ...(options as TopicControllerOptions<string>),
    buffer: 'none',
    on: log.on as HandlerMap<ChanxMessage>,
  });
  return {
    log,
    controller,
    /** Post a message. It shows once the server publishes it back. */
    send: (body: string) => controller.send(chatSend(body)),
    requestBacklog: (limit?: number) => controller.send(chatBacklogRequest(limit)),
    start: () => controller.start(),
    stop: () => controller.stop(),
  };
}
