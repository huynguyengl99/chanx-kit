import { useState } from 'react';
import { useTopics } from '@chanx-js/client/react';

import { notifications } from '../generated';
import type { NotificationPayload } from '../generated';

/** notification kit: fan-out to a user's live connections. */
type Received = NotificationPayload & { from: string };

const everyone = notifications.topics.broadcastNotificationTopic.with();

export function NotificationPanel({ who }: { who: string }) {
  const [items, setItems] = useState<Received[]>([]);

  // Two audiences on one connection: the topic carries which, so the server refuses
  // another user's stream while everyone still receives the broadcast.
  const mine = notifications.topics.demoUserNotificationTopic.with({ user_id: who });

  const { sendTopic, status } = useTopics(notifications, {
    queryParams: { as: who },
    topics: [mine, everyone],
    buffer: 'none',
    on: {
      notification: (message, { topic }) =>
        setItems((current) =>
          [{ ...message.payload, from: topic ?? '' }, ...current].slice(0, 20),
        ),
    },
  });

  const ackAll = () => {
    if (items.length === 0) return;
    sendTopic(mine.topic, {
      action: 'notification_ack',
      payload: { ids: items.map((n) => n.id!) },
    });
    setItems([]);
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Notifications</h2>
        <span className="status" data-state={status}>
          {status}
        </span>
      </div>

      <ul className="log">
        {items.length === 0 && <li>No notifications yet.</li>}
        {items.map((item) => (
          <li key={item.id}>
            <span className="who">{item.title}</span>
            {item.body ? `: ${item.body}` : ''}
            <em>{item.from === everyone.topic ? ' (everyone)' : ' (just you)'}</em>
          </li>
        ))}
      </ul>

      <div className="row">
        <button className="ghost" onClick={ackAll} disabled={items.length === 0}>
          Acknowledge all
        </button>
      </div>
      <p className="hint">
        Nothing in the browser sends these, that is the point. Trigger one from a
        separate process (needs <code>REDIS_URL</code>, since an in-memory layer cannot
        cross processes):
        <br />
        <code>python -m sandbox.send_notification "Build finished"</code>
        <br />
        That one reaches every tab. Add <code>--user {who}</code> to address this
        connection alone, which the server authorizes per subscription.
      </p>
    </section>
  );
}
