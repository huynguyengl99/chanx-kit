import { useCallback, useState } from 'react';
import type {
  AddressOf,
  ChannelDescriptor,
  HandlerMap,
  TopicRef,
  TopicRefOf,
  TopicsControllerOptions,
} from '@chanx-js/client';
import { useTopics } from '@chanx-js/client/react';

import type {
  NotificationAckMessage,
  NotificationAckedMessage,
  NotificationMessage,
  NotificationPayload,
} from '@/generated';

/** A topic from the notification kit. */
export type NotificationTopicRef = TopicRef<
  NotificationAckMessage,
  NotificationAckedMessage | NotificationMessage
>;

export interface ReceivedNotification extends NotificationPayload {
  id: string;
  topic: string;
}

export interface UseNotificationsOptions<D extends ChannelDescriptor<any, any, any, any>>
  extends Omit<TopicsControllerOptions<AddressOf<D>>, 'topics' | 'on' | 'buffer'> {
  topics: ReadonlyArray<TopicRefOf<D> & NotificationTopicRef>;
  /** Max kept, newest first. */
  limit?: number;
}

/** Join notification topics and collect what arrives. The channel is passed in because
 * its name belongs to the app, not the kit. */
export function useNotifications<D extends ChannelDescriptor<any, any, any, any>>(
  channel: D,
  { topics, limit = 50, ...options }: UseNotificationsOptions<D>,
) {
  const [items, setItems] = useState<ReceivedNotification[]>([]);

  const on: HandlerMap<NotificationMessage> = {
    notification: (message, { topic }) =>
      setItems((current) =>
        [
          {
            ...message.payload,
            id: message.payload.id ?? crypto.randomUUID(),
            topic: topic ?? '',
          },
          ...current,
        ].slice(0, limit),
      ),
  };

  // `topics` is constrained to kit topics, so type the call by the kit's messages only.
  const kitChannel: ChannelDescriptor = channel;
  const kitTopics: readonly NotificationTopicRef[] = topics;
  const { status, sendTopic } = useTopics(kitChannel, {
    ...options,
    topics: kitTopics,
    buffer: 'none',
    on,
  });

  /** Ack all shown, per topic, and clear. */
  const ackAll = useCallback(() => {
    const byTopic = new Map<string, string[]>();
    for (const item of items) {
      byTopic.set(item.topic, [...(byTopic.get(item.topic) ?? []), item.id]);
    }
    for (const [topic, ids] of byTopic) {
      sendTopic(topic, { action: 'notification_ack', payload: { ids } });
    }
    setItems([]);
  }, [items, sendTopic]);

  return { items, status, ackAll };
}
