import type {
  AddressOf,
  ChanxClient,
  ChannelDescriptor,
  ChanxMessage,
  HandlerMap,
  TopicRef,
  TopicRefOf,
  TopicsControllerOptions,
} from '@chanx-js/client';
import { createTopicsController } from '@chanx-js/client';

import type {
  ContractToClient,
  ContractToServer,
  NotificationAckMessage,
  NotificationPayload,
} from './contract';

/** A topic whose messages fit notification@1; extra actions are fine. */
export type NotificationTopic<Ref> =
  Ref extends TopicRef<infer ToServer, infer ToClient, any>
    ? [ContractToServer] extends [ToServer]
      ? [Extract<ToClient, { action: ContractToClient['action'] }>] extends [ContractToClient]
        ? Ref
        : never
      : never
    : never;

export interface ReceivedNotification extends NotificationPayload {
  id: string;
  /** The resolved topic it arrived on, such as `notification:all`. */
  topic: string;
}

export interface NotificationFeedSnapshot {
  /** Newest first. */
  items: ReceivedNotification[];
}

export interface NotificationFeedOptions {
  /** Max kept. Defaults to 50. */
  limit?: number;
}

export interface NotificationFeed {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => NotificationFeedSnapshot;
  /** Handlers to pass as `on` to a topics controller or `useTopics`. */
  on: HandlerMap<ContractToClient>;
  /** Acknowledge every shown item, one ack per topic, then clear. */
  ackAll: (sendTopic: (topic: string, message: NotificationAckMessage) => void) => void;
  /** Drop one item locally, without acknowledging it. */
  dismiss: (id: string) => void;
}

export function createNotificationFeed({ limit = 50 }: NotificationFeedOptions = {}): NotificationFeed {
  const listeners = new Set<() => void>();
  let snapshot: NotificationFeedSnapshot = { items: [] };

  const publish = (items: ReceivedNotification[]) => {
    snapshot = { items };
    for (const listener of [...listeners]) listener();
  };

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => snapshot,
    on: {
      notification: ({ payload }, { topic }) => {
        const item = { ...payload, id: payload.id ?? crypto.randomUUID(), topic: topic ?? '' };
        // A notification sent to two joined topics arrives twice with one id.
        const rest = snapshot.items.filter((existing) => existing.id !== item.id);
        publish([item, ...rest].slice(0, limit));
      },
    },
    ackAll(sendTopic) {
      const byTopic = new Map<string, string[]>();
      for (const item of snapshot.items) {
        byTopic.set(item.topic, [...(byTopic.get(item.topic) ?? []), item.id]);
      }
      for (const [topic, ids] of byTopic) {
        sendTopic(topic, { action: 'notification_ack', payload: { ids } });
      }
      publish([]);
    },
    dismiss(id) {
      publish(snapshot.items.filter((item) => item.id !== id));
    },
  };
}

export interface ConnectNotificationsOptions<D extends ChannelDescriptor<any, any, any, any>, Refs>
  extends Omit<TopicsControllerOptions<AddressOf<D>>, 'topics' | 'on' | 'buffer'>,
    NotificationFeedOptions {
  topics: Refs & { readonly [K in keyof Refs]: NotificationTopic<Refs[K]> };
}

/** Join notification topics without a framework. Call `start()`, then read `feed`. */
export function connectNotifications<
  D extends ChannelDescriptor<any, any, any, any>,
  const Refs extends readonly TopicRefOf<D>[],
>(client: ChanxClient, channel: D, { topics, limit, ...options }: ConnectNotificationsOptions<D, Refs>) {
  const feed = createNotificationFeed({ limit });
  const controller = createTopicsController(client, channel as ChannelDescriptor, {
    ...(options as TopicsControllerOptions<string>),
    topics: topics as readonly TopicRef[],
    buffer: 'none',
    on: feed.on as HandlerMap<ChanxMessage>,
  });
  return {
    feed,
    controller,
    ackAll: () => feed.ackAll(controller.sendTopic),
    start: () => controller.start(),
    stop: () => controller.stop(),
  };
}
