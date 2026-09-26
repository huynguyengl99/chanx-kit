import type { SocketStatus } from '@chanx-js/client';

import type { ReceivedNotification } from './useNotifications';
import './notification.css';

export interface NotificationFeedProps {
  items: ReceivedNotification[];
  status?: SocketStatus;
  onAckAll?: () => void;
  /** Label for the topic an item came on. */
  describeTopic?: (topic: string) => string | undefined;
  title?: string;
  empty?: React.ReactNode;
}

/** Restyle via the `--chanx-*` variables in notification.css. */
export function NotificationFeed({
  items,
  status,
  onAckAll,
  describeTopic,
  title = 'Notifications',
  empty = 'No notifications yet.',
}: NotificationFeedProps) {
  return (
    <section className="chanx-notifications" data-state={status}>
      <header className="chanx-notifications__head">
        <h2>{title}</h2>
        {status && <span className="chanx-notifications__status">{status}</span>}
      </header>

      <ul className="chanx-notifications__list">
        {items.length === 0 && <li className="chanx-notifications__empty">{empty}</li>}
        {items.map((item) => (
          <li key={item.id} className="chanx-notifications__item" data-level={item.level ?? 'info'}>
            <strong>{item.title}</strong>
            {item.body && <span>{item.body}</span>}
            {describeTopic?.(item.topic) && (
              <small className="chanx-notifications__topic">{describeTopic(item.topic)}</small>
            )}
          </li>
        ))}
      </ul>

      {onAckAll && (
        <button
          type="button"
          className="chanx-notifications__ack"
          onClick={onAckAll}
          disabled={items.length === 0}
        >
          Acknowledge all
        </button>
      )}
    </section>
  );
}
