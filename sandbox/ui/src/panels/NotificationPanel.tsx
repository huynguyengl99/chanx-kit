import { useState } from 'react';

import type {
  NotificationDemoUserNotificationTopicToClient,
  NotificationDemoUserNotificationTopicToServer,
  NotificationPayload,
} from '../generated';
import { useTopics } from '../lib/socket';

/** notification kit: fan-out to a user's live connections. */
type Received = NotificationPayload & { from: string };

export function NotificationPanel({ who }: { who: string }) {
  const [items, setItems] = useState<Received[]>([]);

  // Two audiences on one connection: the topic carries which, so the server refuses
  // another user's stream while everyone still receives the broadcast.
  const topic = `notification:user:${who}`;
  const everyone = 'notification:all';

  const { send, status } = useTopics<
    NotificationDemoUserNotificationTopicToClient,
    NotificationDemoUserNotificationTopicToServer
  >(
    `/ws/notifications?as=${encodeURIComponent(who)}`,
    [topic, everyone],
    (message, from) => {
      if (message.action === 'notification') {
        setItems((current) =>
          [{ ...message.payload, from }, ...current].slice(0, 20),
        );
      }
    },
  );

  const ackAll = () => {
    if (items.length === 0) return;
    send(topic, {
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
            <em>{item.from === everyone ? ' (everyone)' : ' (just you)'}</em>
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
